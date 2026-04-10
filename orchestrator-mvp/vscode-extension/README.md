# AI Command Console Bridge

Minimal zero-dependency VS Code extension that dispatches workspace and file context to the local AI Command Console orchestrator.

## Commands

- `AI Command Console: Dispatch Workspace`
- `AI Command Console: Dispatch Current File`
- `AI Command Console: Dispatch Selection`
- `AI Command Console: Dispatch Prompt File`
- `AI Command Console: Open Prompt File`
- `AI Command Console: Pick Project Memory`
- `AI Command Console: Refresh Tasks`
- `AI Command Console: Show Task Panel`

## Sidebar

The extension now contributes an `AI Console` activity-bar icon with a `Tasks` tree view.

The tree view lets you:

- inspect the latest orchestrator tasks from `/api/tasks`
- refresh the task list from the view title
- switch the default project memory from the view title
- click any task to open a detailed webview with prompt and result JSON

## What it does

The extension sends requests to the local orchestrator at `http://127.0.0.1:8787/api/dispatch` and can also show recent task results from `/api/tasks`.

It can include:

- workspace root
- current file path
- relative path
- truncated current-file contents
- selected text from the editor
- prompt-file contents from `.orchestrator-prompt.txt`
- project memory chosen from the orchestrator's `/api/projects`

It also adds a status bar button for fast current-file dispatch.

## Development use

1. Open this `vscode-extension` folder in VS Code.
2. Press `F5` to launch an Extension Development Host.
3. In the new host window, open your target workspace.
4. Use `AI Command Console: Pick Project Memory` once if you want dispatches tied to a shared project memory.
5. Run one of the extension commands from the Command Palette.
6. Use the `AI Console` sidebar or `AI Command Console: Show Task Panel` to inspect progress.

## Notes

- The orchestrator API must be running locally.
- This extension is intentionally plain JavaScript with no build step.
- The task panel auto-refreshes on a short polling interval and can manually refresh on demand.
- `Dispatch Selection` is the fastest way to hand off a local code block without paying to send an entire repository context.
- The sidebar tree is the fastest place to inspect recent tasks without leaving VS Code.
