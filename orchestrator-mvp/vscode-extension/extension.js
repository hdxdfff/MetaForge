const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

let taskPanel = null;
let taskRefreshTimer = null;

function getConfig() {
  const config = vscode.workspace.getConfiguration('aiCommandConsole');
  return {
    apiBaseUrl: config.get('apiBaseUrl', 'http://127.0.0.1:8787'),
    projectId: config.get('projectId', ''),
    defaultGoal: config.get('defaultGoal', 'Keep the workspace healthy and prefer local resources first.'),
    dispatchHint: config.get('dispatchHint', 'Prefer local runtime resources and cheap workers before escalating the planner.'),
    promptFileName: config.get('promptFileName', '.orchestrator-prompt.txt'),
    contextMode: config.get('contextMode', 'lean'),
    maxContextChars: config.get('maxContextChars', 1600),
    taskPanelRefreshSeconds: config.get('taskPanelRefreshSeconds', 5),
  };
}

function workspaceFolder() {
  return vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length
    ? vscode.workspace.workspaceFolders[0].uri.fsPath
    : '';
}

function requestJson(urlString, payload, method = 'POST') {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const body = payload ? JSON.stringify(payload) : '';
    const transport = url.protocol === 'https:' ? https : http;
    const req = transport.request({
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method,
      headers: body ? {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      } : {},
    }, (res) => {
      let raw = '';
      res.on('data', (chunk) => { raw += chunk; });
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(raw || '{}'));
          } catch (error) {
            reject(error);
          }
          return;
        }
        reject(new Error(raw || `Request failed with status ${res.statusCode}`));
      });
    });
    req.on('error', reject);
    if (body) {
      req.write(body);
    }
    req.end();
  });
}

function truncate(text, limit) {
  if (!text) {
    return '';
  }
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit)}\n...[truncated]`;
}

function escapeHtml(text) {
  return String(text || '').replace(/[&<>]/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
  }[char]));
}

function getSelectionBlock(editor) {
  if (!editor || !editor.selection || editor.selection.isEmpty) {
    return '';
  }
  const selected = editor.document.getText(editor.selection).trim();
  if (!selected) {
    return '';
  }
  return `Selected text:\n${truncate(selected, 2000)}`;
}

class TaskItem extends vscode.TreeItem {
  constructor(task) {
    super(`${task.status}  ${task.id.slice(0, 8)}`, vscode.TreeItemCollapsibleState.None);
    this.task = task;
    this.tooltip = `${task.id}\n${task.repo_path || 'no repo path'}`;
    this.description = task.phase || task.updated_at;
    this.contextValue = 'taskItem';
    this.command = {
      command: 'aiCommandConsole.openTaskDetails',
      title: 'Open Task Details',
      arguments: [task],
    };
    this.iconPath = new vscode.ThemeIcon(task.status === 'completed' ? 'check' : task.status === 'failed' ? 'error' : 'sync');
  }
}

class TaskTreeProvider {
  constructor() {
    this._onDidChangeTreeData = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._onDidChangeTreeData.event;
    this.tasks = [];
  }

  getTreeItem(element) {
    return element;
  }

  getChildren() {
    return this.tasks.map((task) => new TaskItem(task));
  }

  async refresh() {
    const config = getConfig();
    try {
      const tasks = await requestJson(`${config.apiBaseUrl}/api/tasks`, null, 'GET');
      this.tasks = Array.isArray(tasks) ? tasks.slice(0, 20) : [];
      this._onDidChangeTreeData.fire();
      return this.tasks;
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to refresh AI tasks: ${error.message}`);
      return [];
    }
  }
}

async function buildPrompt(kind, editor, promptText, options = {}) {
  const root = workspaceFolder();
  const blocks = [promptText.trim()];
  if (root) {
    blocks.push(`Workspace: ${root}`);
  }
  if (editor && editor.document) {
    const filePath = editor.document.uri.fsPath;
    const relativePath = root ? path.relative(root, filePath) : path.basename(filePath);
    blocks.push(`Current file: ${filePath}`);
    blocks.push(`Relative file: ${relativePath}`);
    if (options.includeFileContents !== false) {
      blocks.push(`Attached context from ${filePath}:\n${truncate(editor.document.getText().trim(), 4000)}`);
    }
    if (options.includeSelection) {
      const selectionBlock = getSelectionBlock(editor);
      if (selectionBlock) {
        blocks.push(selectionBlock);
      }
    }
  }
  blocks.push(`Dispatch kind: ${kind}`);
  return blocks.filter(Boolean).join('\n\n');
}

async function dispatch(kind, promptSource, options = {}) {
  const config = getConfig();
  const editor = vscode.window.activeTextEditor;
  const root = workspaceFolder();
  if (!root) {
    vscode.window.showErrorMessage('No workspace folder is open.');
    return null;
  }

  const promptText = await promptSource(config, root, editor);
  if (!promptText || promptText.trim().length < 8) {
    vscode.window.showErrorMessage('Prompt is too short.');
    return null;
  }

  const payload = {
    prompt: await buildPrompt(kind, editor, `${promptText}\n\nDispatch hint: ${config.dispatchHint}`, options),
    project_id: config.projectId || null,
    repo_path: root,
    goal: config.defaultGoal,
    caller: `vscode-extension:${kind}`,
    context_mode: config.contextMode,
    max_context_chars: config.maxContextChars,
    auto_approve: false,
    allow_resource_scan: true,
    allow_repo_status: true,
  };

  try {
    const response = await requestJson(`${config.apiBaseUrl}/api/dispatch`, payload, 'POST');
    vscode.window.showInformationMessage(`Dispatched task ${response.id} (${response.status})`);
    return response;
  } catch (error) {
    vscode.window.showErrorMessage(`Dispatch failed: ${error.message}`);
    return null;
  }
}

async function promptForWorkspace() {
  return vscode.window.showInputBox({
    prompt: 'Describe the workspace-level task for AI Command Console',
    placeHolder: 'Review the current workspace and suggest the next safest engineering step.',
    ignoreFocusOut: true,
  });
}

async function promptForCurrentFile(editor) {
  if (!editor) {
    vscode.window.showErrorMessage('No active editor.');
    return '';
  }
  return vscode.window.showInputBox({
    prompt: 'Describe what to do with the current file',
    placeHolder: 'Review this file and suggest the next safest refactor.',
    ignoreFocusOut: true,
  });
}

async function promptForSelection(editor) {
  if (!editor || !editor.selection || editor.selection.isEmpty) {
    vscode.window.showErrorMessage('No text selection.');
    return '';
  }
  return vscode.window.showInputBox({
    prompt: 'Describe what to do with the selected text',
    placeHolder: 'Refactor this selected block and explain the safest patch plan.',
    ignoreFocusOut: true,
  });
}

async function readPromptFile(config, root) {
  const promptPath = path.join(root, config.promptFileName);
  if (!fs.existsSync(promptPath)) {
    fs.writeFileSync(promptPath, '# Write your orchestrator prompt here.\n', 'utf8');
  }
  const text = fs.readFileSync(promptPath, 'utf8').trim();
  if (!text) {
    vscode.window.showWarningMessage(`Prompt file is empty: ${promptPath}`);
  }
  return text;
}

function formatTasksHtml(tasks, projectLabel, autoRefreshSeconds) {
  const cards = tasks.slice(0, 16).map((task) => {
    const prompt = escapeHtml(String(task.prompt || '').slice(0, 320));
    const result = escapeHtml(JSON.stringify(task.result || {}, null, 2));
    const repoPath = escapeHtml(task.repo_path || 'no repo path');
    const phase = escapeHtml(task.phase || 'n/a');
    const model = escapeHtml(task.model_route || task.cheap_lane || 'n/a');
    return `
      <article class="task-card">
        <div class="head"><strong>${escapeHtml(task.status)}</strong><span>${escapeHtml(new Date(task.updated_at).toLocaleString())}</span></div>
        <div class="meta">${repoPath}</div>
        <div class="meta">phase: ${phase} | route: ${model}</div>
        <div class="prompt">${prompt}</div>
        <pre>${result}</pre>
      </article>
    `;
  }).join('');
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body { font-family: Segoe UI, sans-serif; padding: 12px; background: #0b1520; color: #eef6ff; }
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 12px; }
.toolbar-left { display: flex; flex-direction: column; gap: 4px; }
.toolbar-right { display: flex; gap: 8px; }
button { background: #76f5d6; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
small { color: #8ea5bb; }
.grid { display: grid; gap: 10px; }
.task-card { border: 1px solid rgba(255,255,255,0.12); background: rgba(255,255,255,0.04); border-radius: 14px; padding: 12px; }
.head { display: flex; justify-content: space-between; gap: 8px; }
.meta { color: #8ea5bb; margin-top: 4px; }
.prompt { margin-top: 8px; }
pre { white-space: pre-wrap; word-break: break-word; background: rgba(0,0,0,0.35); padding: 10px; border-radius: 10px; }
</style>
</head>
<body>
<div class="toolbar">
  <div class="toolbar-left">
    <h2>AI Command Console Tasks</h2>
    <small>project: ${escapeHtml(projectLabel)} | auto refresh: ${autoRefreshSeconds}s</small>
  </div>
  <div class="toolbar-right">
    <button onclick="pickProject()">Pick Project</button>
    <button onclick="refreshPanel()">Refresh</button>
  </div>
</div>
<div class="grid">${cards || '<div>No tasks yet.</div>'}</div>
<script>
const vscode = acquireVsCodeApi();
function refreshPanel() { vscode.postMessage({ type: 'refresh' }); }
function pickProject() { vscode.postMessage({ type: 'pick-project' }); }
</script>
</body>
</html>`;
}

function clearTaskPanelTimer() {
  if (taskRefreshTimer) {
    clearInterval(taskRefreshTimer);
    taskRefreshTimer = null;
  }
}

async function loadProjects(config) {
  return requestJson(`${config.apiBaseUrl}/api/projects`, null, 'GET');
}

async function pickProjectId() {
  const config = getConfig();
  try {
    const projects = await loadProjects(config);
    if (!Array.isArray(projects) || projects.length === 0) {
      vscode.window.showWarningMessage('No project memories are registered in the orchestrator yet.');
      return null;
    }
    const picks = projects.map((project) => ({
      label: project.name || project.project_id,
      description: project.project_id,
      detail: (project.repo_path || project.summary || '').slice(0, 120),
      projectId: project.project_id,
    }));
    const choice = await vscode.window.showQuickPick(picks, {
      title: 'Select default project memory',
      placeHolder: 'Choose the project memory used for future dispatches',
      ignoreFocusOut: true,
    });
    if (!choice) {
      return null;
    }
    await vscode.workspace.getConfiguration('aiCommandConsole').update('projectId', choice.projectId, vscode.ConfigurationTarget.Workspace);
    vscode.window.showInformationMessage(`AI Command Console project set to ${choice.projectId}`);
    return choice.projectId;
  } catch (error) {
    vscode.window.showErrorMessage(`Failed to load projects: ${error.message}`);
    return null;
  }
}

function createTaskDetailHtml(task) {
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body { font-family: Segoe UI, sans-serif; padding: 16px; background: #0d1622; color: #eef6ff; }
pre { white-space: pre-wrap; word-break: break-word; background: rgba(255,255,255,0.05); padding: 12px; border-radius: 12px; }
.section { margin-bottom: 16px; }
.label { color: #8ea5bb; margin-bottom: 6px; }
</style>
</head>
<body>
  <div class="section"><h2>${escapeHtml(task.status)} ${escapeHtml(task.id)}</h2></div>
  <div class="section"><div class="label">Repo</div><pre>${escapeHtml(task.repo_path || 'no repo path')}</pre></div>
  <div class="section"><div class="label">Prompt</div><pre>${escapeHtml(task.prompt || '')}</pre></div>
  <div class="section"><div class="label">Result</div><pre>${escapeHtml(JSON.stringify(task.result || {}, null, 2))}</pre></div>
</body>
</html>`;
}

async function openTaskDetails(task) {
  const panel = vscode.window.createWebviewPanel(
    'aiCommandConsoleTaskDetails',
    `Task ${task.id.slice(0, 8)}`,
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );
  panel.webview.html = createTaskDetailHtml(task);
}

async function renderTaskPanel(panel) {
  const config = getConfig();
  try {
    const tasks = await requestJson(`${config.apiBaseUrl}/api/tasks`, null, 'GET');
    const projectLabel = config.projectId || 'none';
    panel.webview.html = formatTasksHtml(tasks, projectLabel, config.taskPanelRefreshSeconds);
  } catch (error) {
    panel.webview.html = `<html><body><pre>Failed to load tasks: ${escapeHtml(error.message)}</pre></body></html>`;
  }
}

async function showTaskPanel(context) {
  if (taskPanel) {
    taskPanel.reveal(vscode.ViewColumn.Beside);
    await renderTaskPanel(taskPanel);
    return taskPanel;
  }

  taskPanel = vscode.window.createWebviewPanel(
    'aiCommandConsoleTasks',
    'AI Command Console Tasks',
    vscode.ViewColumn.Beside,
    { enableScripts: true }
  );

  taskPanel.onDidDispose(() => {
    clearTaskPanelTimer();
    taskPanel = null;
  }, undefined, context.subscriptions);

  taskPanel.webview.onDidReceiveMessage(async (message) => {
    if (message.type === 'refresh') {
      await renderTaskPanel(taskPanel);
      return;
    }
    if (message.type === 'pick-project') {
      const projectId = await pickProjectId();
      if (projectId) {
        await renderTaskPanel(taskPanel);
      }
    }
  }, undefined, context.subscriptions);

  await renderTaskPanel(taskPanel);
  clearTaskPanelTimer();
  const refreshSeconds = Math.max(3, Number(getConfig().taskPanelRefreshSeconds) || 5);
  taskRefreshTimer = setInterval(() => {
    if (taskPanel) {
      renderTaskPanel(taskPanel).catch(() => {});
    }
  }, refreshSeconds * 1000);
  context.subscriptions.push({ dispose: clearTaskPanelTimer });
  return taskPanel;
}

function activate(context) {
  const taskTreeProvider = new TaskTreeProvider();
  vscode.window.registerTreeDataProvider('aiCommandConsoleTasksView', taskTreeProvider);
  context.subscriptions.push({ dispose: () => clearTaskPanelTimer() });

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.text = '$(hubot) AI Dispatch';
  statusBar.command = 'aiCommandConsole.dispatchCurrentFile';
  statusBar.tooltip = 'Dispatch the current file to AI Command Console';
  statusBar.show();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.dispatchWorkspace', async () => {
    const response = await dispatch('workspace', async () => promptForWorkspace());
    if (response) {
      await taskTreeProvider.refresh();
      await showTaskPanel(context);
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.dispatchCurrentFile', async () => {
    const response = await dispatch('current-file', async (_config, _root, editor) => promptForCurrentFile(editor));
    if (response) {
      await taskTreeProvider.refresh();
      await showTaskPanel(context);
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.dispatchSelection', async () => {
    const response = await dispatch(
      'selection',
      async (_config, _root, editor) => promptForSelection(editor),
      { includeSelection: true, includeFileContents: true }
    );
    if (response) {
      await taskTreeProvider.refresh();
      await showTaskPanel(context);
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.dispatchPromptFile', async () => {
    const response = await dispatch('prompt-file', async (config, root) => readPromptFile(config, root));
    if (response) {
      await taskTreeProvider.refresh();
      await showTaskPanel(context);
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.openPromptFile', async () => {
    const root = workspaceFolder();
    if (!root) {
      vscode.window.showErrorMessage('No workspace folder is open.');
      return;
    }
    const config = getConfig();
    const promptPath = path.join(root, config.promptFileName);
    if (!fs.existsSync(promptPath)) {
      fs.writeFileSync(promptPath, '# Write your orchestrator prompt here.\n', 'utf8');
    }
    const document = await vscode.workspace.openTextDocument(promptPath);
    await vscode.window.showTextDocument(document, { preview: false });
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.pickProject', async () => {
    const projectId = await pickProjectId();
    if (projectId) {
      await taskTreeProvider.refresh();
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.showTaskPanel', async () => {
    await showTaskPanel(context);
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.refreshTasks', async () => {
    await taskTreeProvider.refresh();
  }));

  context.subscriptions.push(vscode.commands.registerCommand('aiCommandConsole.openTaskDetails', async (task) => {
    await openTaskDetails(task);
  }));

  taskTreeProvider.refresh().catch(() => {});
}

function deactivate() {
  clearTaskPanelTimer();
}

module.exports = {
  activate,
  deactivate,
};
