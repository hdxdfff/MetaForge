const state = {
  snapshot: null,
  tasks: [],
  executors: null,
  incidents: [],
  risk: null,
  security: null,
  policy: null,
  trace: [],
  coreMessages: [],
  selectedTaskId: null,
  selectedTask: null,
  taskSummary: null,
  queueFilter: "all",
  queueScope: null,
  searchQuery: "",
  view: "overview",
  loaded: {
    snapshot: false,
    tasks: false,
    executors: false,
    auxiliary: false,
  },
  pagination: {
    queue: 1,
    artifacts: 1,
    events: 1,
    incidents: 1,
  },
};

const bootstrap = window.__FACTORY_BOOTSTRAP__ || {};
if (bootstrap && typeof bootstrap === "object" && Array.isArray(bootstrap.executors)) {
  state.executors = bootstrap;
}

function buildBootstrapSnapshot(source) {
  if (!source || typeof source !== "object") return null;
  const control = source.control_center || {};
  const factory = source.factory_state || {};
  const goalBacklog = source.goal_backlog || {};
  const controlLayer = factory.control_layer || {};
  const runtime = {
    health: control.paused ? "degraded" : "healthy",
    control_status: control.status || "unknown",
    autonomy_stage: factory.autonomy?.stage || "unknown",
    autonomy_score: factory.autonomy?.score ?? null,
    quality_status: controlLayer.quality_status || "unknown",
    quality_score: controlLayer.quality_score ?? null,
    daemon_status: factory.daemon?.status || "unknown",
    daemon_running: factory.daemon?.status === "running",
    goal_primary: goalBacklog.goal_primary || factory.goal_primary || "unknown",
    goal_mode: goalBacklog.goal_mode || factory.goal_mode || "unknown",
    workspace_root: "D:\\codex",
    blocked_count: factory.messages?.open_errors || 0,
  };

  return {
    ...control,
    updated_at: factory.updated_at || control.updated_at || null,
    freshness_seconds: 0,
    running: !control.paused,
    status: control.status || "live",
    paused: Boolean(control.paused),
    delivery_summary: factory.delivery_summary || {},
    release_operations: {
      status: factory.release_ops?.status || "unknown",
      release_train_status: factory.release_ops?.release_train_status || factory.release_ops?.status || "unknown",
    },
    release_ops: factory.release_ops || {},
    control_policy: {
      mode: controlLayer.status || "unknown",
      signal_dashboard: {
        Runtime: {
          status: factory.daemon?.status === "running" ? "healthy" : "blocked",
          signal_count: factory.messages?.open_errors || 0,
          signals: [],
        },
        Maturity: {
          status: factory.autonomy?.stage || "unknown",
          signal_count: 1,
          signals: [],
        },
        "Release Readiness": {
          status: factory.release_ops?.status || "unknown",
          signal_count: 0,
          signals: [],
        },
      },
    },
    signal_dashboard: {
      Runtime: {
        status: factory.daemon?.status === "running" ? "healthy" : "blocked",
        signal_count: factory.messages?.open_errors || 0,
        signals: [],
      },
      Maturity: {
        status: factory.autonomy?.stage || "unknown",
        signal_count: 1,
        signals: [],
      },
      "Release Readiness": {
        status: factory.release_ops?.status || "unknown",
        signal_count: 0,
        signals: [],
      },
    },
    quality_system: {
      status: factory.control_layer?.quality_status || "unknown",
      overall_score: factory.control_layer?.quality_score ?? null,
    },
    autonomy_score: factory.autonomy || null,
    identity_gate: {
      runtime,
      authority: {
        session_active: true,
        session_owner: "codex-control",
        session_role: "operator",
        session_scope: "global",
        control_center_status: control.status || "active",
        control_center_paused: Boolean(control.paused),
      },
    },
    identity_kernel: {
      runtime,
      authority: {
        session_active: true,
        session_owner: "codex-control",
        session_role: "operator",
        session_scope: "global",
        control_center_status: control.status || "active",
        control_center_paused: Boolean(control.paused),
      },
    },
  };
}

function bootstrapPreviewTasks(source) {
  const preview = Array.isArray(source?.goal_backlog_preview) ? source.goal_backlog_preview : [];
  return preview.map((item, index) => ({
    ...item,
    id: item.id || item.node_id || item.goal_id || `preview-${index}`,
    title: item.title || item.goal || item.prompt || item.node_title || `预览任务 ${index + 1}`,
    prompt: item.prompt || item.title || item.goal || "",
    status: item.status || item.state || item.phase || (item.dispatch_now ? "queued" : "queued"),
    updated_at: item.updated_at || source?.goal_backlog?.updated_at || null,
  }));
}

const bootstrapSnapshot = buildBootstrapSnapshot(bootstrap);
if (bootstrapSnapshot) {
  state.snapshot = bootstrapSnapshot;
  markLoaded("snapshot");
}
if (bootstrap && typeof bootstrap === "object" && bootstrap.task_summary && typeof bootstrap.task_summary === "object") {
  state.taskSummary = bootstrap.task_summary;
}
const bootstrapTasks = bootstrapPreviewTasks(bootstrap);
if (bootstrapTasks.length) {
  state.tasks = bootstrapTasks;
  state.selectedTaskId = bootstrapTasks[0].id;
  state.selectedTask = bootstrapTasks[0];
}
if (bootstrap && typeof bootstrap === "object" && Array.isArray(bootstrap.executors)) {
  markLoaded("executors");
}
const loadLocks = {};

const PAGE_SIZES = {
  queue: 8,
  artifacts: 8,
  events: 8,
  incidents: 5,
};

const FINAL_STATUSES = new Set(["completed", "released", "verification_passed", "delivery_ready"]);

const esc = (v) =>
  String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

const norm = (v) => String(v ?? "").toLowerCase().replaceAll("-", "_");
const tone = (v) => {
  const s = norm(v);
  if (!s) return "subtle-pill";
  if (s.includes("fail") || s.includes("blocked") || s.includes("paused") || s.includes("error") || s.includes("stopped")) return "danger-pill";
  if (s.includes("warn") || s.includes("attention") || s.includes("pending") || s.includes("weak") || s.includes("degraded")) return "warning-pill";
  return "pill";
};

const statusTextMap = {
  unknown: "未知",
  live: "在线",
  online: "在线",
  degraded: "降级",
  offline: "离线",
  idle: "空闲",
  running: "运行中",
  blocked: "已阻塞",
  stopped: "已停止",
  paused: "已暂停",
  healthy: "健康",
  attention: "注意",
  warning: "警告",
  error: "错误",
  pass: "通过",
  passed: "通过",
  ready: "就绪",
  observer: "观察者",
  active: "活跃",
  disabled: "已禁用",
  failed: "失败",
  cancelled: "已取消",
  timed_out: "已超时",
  pending: "待处理",
  queued: "排队中",
  completed: "已完成",
  released: "已发布",
  artifact: "产物",
  signal: "信号",
  event: "事件",
  observe: "观察",
  observed: "已观察",
  task_output: "任务产出",
  "n/a": "无",
  n_a: "无",
  na: "无",
};

const zh = (value) => {
  const raw = String(value ?? "");
  const key = norm(raw);
  if (statusTextMap[key]) return statusTextMap[key];
  if (key.includes("stage4")) return "阶段 4";
  if (key.includes("stage3")) return "阶段 3";
  if (key.includes("stage2")) return "阶段 2";
  if (key.includes("stage1")) return "阶段 1";
  if (key.includes("lean_execution")) return "轻量执行";
  if (key.includes("signal_only")) return "仅信号";
  if (key.includes("weak_control")) return "弱控制";
  if (key.includes("priority_directive_toyos")) return "ToyOS 优先模式";
  if (key.includes("toyos_priority_mode")) return "ToyOS 优先模式";
  if (key.includes("stage_gate_release_claims")) return "阶段门控";
  if (key.includes("release_train_ready")) return "发布列车就绪";
  if (key.includes("long_horizon")) return "长周期";
  if (key.includes("short")) return "短周期";
  if (key.includes("task output")) return "任务产出";
  if (key.includes("task_output")) return "任务产出";
  if (key.includes("release readiness")) return "发布就绪";
  if (key.includes("verification")) return "验证";
  if (key.includes("artifact")) return "产物";
  if (key.includes("signal")) return "信号";
  if (key.includes("event")) return "事件";
  if (key.includes("observe")) return "观察";
  if (raw === "Restore ToyOS real artifact delivery") return "恢复 ToyOS 真实产物交付";
  return raw || "-";
};

const fmt = (v) => {
  if (!v) return "-";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
};

const clampLabel = (value, max = 120) => {
  const text = String(value ?? "");
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
};

const ago = (v) => {
  if (!v) return "-";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return String(v);
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.round(s / 3600)} 小时前`;
  return `${Math.round(s / 86400)} 天前`;
};

const text = (v) => (v === null || v === undefined || v === "" ? "-" : String(v));
const arr = (v) => (Array.isArray(v) ? v : Array.isArray(v?.items) ? v.items : Array.isArray(v?.data) ? v.data : Array.isArray(v?.executors) ? v.executors : []);
const setText = (id, value) => {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
};

function totalPages(total, pageSize) {
  return Math.max(1, Math.ceil(total / pageSize));
}

function currentPage(key, total, pageSize) {
  const page = Math.max(1, Math.min(state.pagination[key] || 1, totalPages(total, pageSize)));
  state.pagination[key] = page;
  return page;
}

function paginate(items, key, pageSize) {
  const page = currentPage(key, items.length, pageSize);
  const start = (page - 1) * pageSize;
  return {
    page,
    totalPages: totalPages(items.length, pageSize),
    total: items.length,
    items: items.slice(start, start + pageSize),
  };
}

function renderPager(id, key, total, pageSize, label) {
  const el = document.getElementById(id);
  if (!el) return;
  const pages = totalPages(total, pageSize);
  const page = currentPage(key, total, pageSize);
  el.innerHTML = `
    <div class="pager-meta">${esc(label)} · 第 ${page} / ${pages} 页 · 共 ${total} 条</div>
    <div class="pager-actions">
      <button type="button" class="ghost-btn" data-page-key="${esc(key)}" data-page-step="-1" ${page <= 1 ? "disabled" : ""}>上一页</button>
      <button type="button" class="ghost-btn" data-page-key="${esc(key)}" data-page-step="1" ${page >= pages ? "disabled" : ""}>下一页</button>
    </div>`;
  el.querySelectorAll("[data-page-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const step = Number(button.dataset.pageStep || 0);
      state.pagination[key] = Math.max(1, Math.min(pages, (state.pagination[key] || 1) + step));
      renderTasks();
      renderArtifacts();
      renderTimeline();
    });
  });
}

function switchView(view) {
  state.view = view || "overview";
  renderView();
  ensureViewData(state.view).catch(logAsyncError);
}

function renderView() {
  const panes = document.querySelectorAll("main [data-view]");
  panes.forEach((pane) => {
    const active = pane.dataset.view === state.view;
    pane.classList.toggle("is-active", active);
  });
  document.querySelectorAll("button[data-view]").forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
}

async function request(url, options = {}) {
  const { timeoutMs = 2500, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, { ...fetchOptions, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  const body = await res.text();
  if (!res.ok) throw new Error(body || `请求失败：${res.status}`);
  return body ? JSON.parse(body) : null;
}

function markLoaded(key) {
  if (state.loaded && Object.prototype.hasOwnProperty.call(state.loaded, key)) {
    state.loaded[key] = true;
  }
}

function withLoadLock(key, loader) {
  if (loadLocks[key]) return loadLocks[key];
  const run = (async () => {
    try {
      return await loader();
    } finally {
      delete loadLocks[key];
    }
  })();
  loadLocks[key] = run;
  return run;
}

function logAsyncError(err) {
  if (!err) return;
  const name = err.name || "";
  const message = String(err.message || err || "");
  if (name === "AbortError" || message.includes("signal is aborted")) return;
  console.error(err);
}

function runtime() {
  const s = state.snapshot || {};
  return s.identity_gate?.runtime || s.identity_kernel?.runtime || s.runtime || {};
}

function signals() {
  const s = state.snapshot || {};
  return s.signal_dashboard || s.control_policy?.signal_dashboard || {};
}

function queueCounts(tasks) {
  const counts = { all: tasks.length, queued: 0, running: 0, done: 0, problem: 0 };
  for (const task of tasks) {
    const b = bucket(task);
    if (counts[b] !== undefined) counts[b] += 1;
  }
  return counts;
}

function bucket(status) {
  const s = norm(typeof status === "object" && status ? taskStatus(status) : status);
  if (["queued", "planning", "waiting_approval"].includes(s)) return "queued";
  if (["running", "execution_finished", "verification_pending", "verification_running"].includes(s)) return "running";
  if (["verification_passed", "delivery_ready", "released", "completed"].includes(s)) return "done";
  if (["verification_failed", "failed", "cancelled", "timed_out"].includes(s)) return "problem";
  return s;
}

function taskStatus(task, fallback = "queued") {
  if (!task || typeof task !== "object") return fallback;
  const direct = [
    task.status,
    task.state,
    task.phase,
    task.final_status,
    task.verification_status,
    task.delivery_status,
    task.queue_status,
    task.lifecycle?.status,
    task.result?.status,
  ];
  for (const value of direct) {
    const s = norm(value);
    if (!s || ["unknown", "n_a", "na"].includes(s)) continue;
    if (s === "signal_only") return "signal-only";
    return s;
  }

  if (task.completed_at || task.finished_at || task.ended_at || task.released_at) {
    return task.released_at ? "released" : "completed";
  }

  if (task.started_at || task.running_at || task.execution_started_at) return "running";
  if (Array.isArray(task.result?.artifacts) && task.result.artifacts.length) return "completed";
  if (task.result?.summary || task.result?.output || task.result?.message) return "completed";
  if (task.dispatch_now || task.scheduled_by || task.admission_mode) return "queued";
  return fallback;
}

function taskHasSignals(task) {
  const signalsList = task?.signals || task?.verification_signals || task?.signal_list || [];
  return Array.isArray(signalsList) && signalsList.length > 0;
}

function taskIsFresh(task) {
  const ts = new Date(task?.updated_at || 0).getTime();
  return Number.isFinite(ts) && Date.now() - ts < 24 * 60 * 60 * 1000;
}

function taskSearchText(task) {
  return [
    task?.id,
    task?.title,
    task?.goal,
    task?.prompt,
    task?.repo_path,
    task?.repo_id,
    task?.executor_id,
    task?.preferred_worker,
    task?.execution_lane,
    task?.status,
    task?.state,
    task?.phase,
    task?.final_status,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function scopeLabel(scope) {
  if (!scope || typeof scope !== "object") return "全部任务";
  if (scope.type === "task") return "指定任务";
  if (scope.type === "goal") return "目标任务";
  if (scope.type === "signal") return "带信号任务";
  if (scope.type === "fresh") return "24 小时内任务";
  if (scope.type === "released") return "已发布任务";
  if (scope.type === "all") return "全部任务";
  return zh(scope.type || "all");
}

function taskMatchesScope(task, scope) {
  if (!scope || !scope.type || scope.type === "all") return true;
  const status = taskStatus(task);
  const bucketStatus = bucket(task);
  if (scope.type === "running") return bucketStatus === "running";
  if (scope.type === "done") return bucketStatus === "done";
  if (scope.type === "problem") return bucketStatus === "problem";
  if (scope.type === "released") return norm(status) === "released" || bucketStatus === "done";
  if (scope.type === "fresh") return taskIsFresh(task);
  if (scope.type === "signal") return taskHasSignals(task);
  if (scope.type === "task") return norm(task.id) === norm(scope.value);
  if (scope.type === "goal") {
    const goal = String(scope.value || "").trim().toLowerCase();
    if (!goal) return true;
    const haystack = taskSearchText(task);
    return haystack.includes(goal);
  }
  if (scope.type === "search") {
    const query = String(scope.value || "").trim().toLowerCase();
    if (!query) return true;
    return taskSearchText(task).includes(query);
  }
  return true;
}

function bestTaskForScope(scope, tasks = state.tasks) {
  const list = Array.isArray(tasks) ? tasks : [];
  const scoped = list.filter((task) => taskMatchesScope(task, scope));
  if (scope?.type === "task" && scope.value) {
    return scoped.find((task) => norm(task.id) === norm(scope.value)) || null;
  }
  if (scope?.type === "goal" && scope.value) {
    const query = String(scope.value).trim().toLowerCase();
    const direct = scoped.find((task) => taskSearchText(task).includes(query));
    if (direct) return direct;
  }
  if (scope?.type === "signal") {
    return scoped[0] || null;
  }
  if (scope?.type === "problem") {
    return scoped[0] || null;
  }
  if (scope?.type === "running") {
    return scoped[0] || null;
  }
  if (scope?.type === "done" || scope?.type === "released" || scope?.type === "fresh") {
    return scoped[0] || null;
  }
  return scoped[0] || list[0] || null;
}

async function openTaskDrill(scope) {
  const normalized = scope && typeof scope === "object" ? scope : { type: "all" };
  state.queueScope = normalized;
  if (normalized.type === "all") {
    state.queueFilter = "all";
  } else if (["running", "done", "problem"].includes(normalized.type)) {
    state.queueFilter = normalized.type;
  } else if (normalized.type === "released") {
    state.queueFilter = "done";
  } else {
    state.queueFilter = "all";
  }

  if (!state.loaded.tasks) {
    await loadTasksData();
  }

  state.view = "mission";
  renderView();
  const match = bestTaskForScope(normalized);
  renderTasks();
  renderOverview();
  if (match?.id) {
    await selectTask(match.id);
  }

  setTimeout(() => {
    const target = document.getElementById("task-detail") || document.getElementById("queue");
    if (target) {
      target.classList.remove("task-focus-flash");
      void target.offsetWidth;
      target.classList.add("task-focus-flash");
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setTimeout(() => target.classList.remove("task-focus-flash"), 1200);
    }
  }, 60);
}

function activeWorkers(payload) {
  const items = arr(payload);
  return items.filter((item) => {
    const s = norm(item.status || item.health || item.state);
    return !s || ["active", "running", "online", "healthy", "ready", "available"].some((x) => s.includes(x));
  }).length;
}

function executorLoad(executorId) {
  const id = norm(executorId);
  const tasks = Array.isArray(state.tasks) ? state.tasks : [];
  const activeStates = new Set(["running", "execution_finished", "verification_pending", "verification_running"]);
  const matched = tasks.filter((task) => {
    const route = task.executor_route || {};
    const selected = route.selected || {};
    const routeCandidates = Array.isArray(route.candidates) ? route.candidates : [];
    const fields = [
      task.executor_id,
      task.preferred_worker,
      task.execution_lane,
      task.worker,
      task.assigned_executor_id,
      task.routing?.executor_id,
      task.routing?.preferred_worker,
      selected.executor_id,
      selected.id,
      selected.name,
      ...routeCandidates.map((candidate) => candidate?.executor_id || candidate?.id || candidate?.name),
    ].map(norm);
    return fields.some((field) => field && (field === id || field.includes(id) || id.includes(field)));
  });
  const summaryCount = Number(state.taskSummary?.executor_counts?.[id] || 0);
  const summaryRunning = Number(state.taskSummary?.executor_running_counts?.[id] || 0);
  const summaryBlocked = Number(state.taskSummary?.executor_blocked_counts?.[id] || 0);
  if (!matched.length && summaryCount > 0) {
    const summaryActive = summaryRunning > 0;
    return {
      total: summaryCount,
      running: summaryRunning,
      done: Math.max(0, summaryCount - summaryRunning - summaryBlocked),
      blocked: summaryBlocked,
      usageLabel: summaryBlocked > 0 ? "阻塞中" : summaryActive ? "进行中" : "已收尾",
    };
  }
  const running = matched.filter((task) => activeStates.has(norm(taskStatus(task)))).length;
  const done = matched.filter((task) => FINAL_STATUSES.has(norm(taskStatus(task)))).length;
  const blocked = matched.filter((task) => ["problem", "blocked", "failed", "cancelled", "timed_out"].includes(bucket(task))).length;
  return {
    total: matched.length,
    running,
    done,
    blocked,
    usageLabel: blocked ? "阻塞中" : running ? "进行中" : matched.length ? "已收尾" : "空闲",
  };
}

function executorHealth(item) {
  const health = item?.health || {};
  if (item?.enabled === false) return { status: "disabled", label: "已禁用" };
  const raw = health.status || item.status || item.state || item.health;
  const normalized = norm(raw);
  if (health.healthy === true) return { status: "healthy", label: "健康" };
  if (health.healthy === false) return { status: "degraded", label: "降级" };
  if (normalized && !["unknown", "n_a", "na"].includes(normalized)) {
    return { status: normalized, label: zh(normalized) };
  }
  return { status: "healthy", label: "健康" };
}

function artifactsFromTask(task) {
  const status = taskStatus(task);
  const out = [];
  const spec = task?.artifact_spec || {};
  if (spec.artifact_id || spec.type) {
    out.push({
      name: spec.artifact_id || spec.type || "artifact",
      type: spec.artifact_type || spec.type || "artifact",
      status,
      source: task.id,
      updated_at: task.updated_at,
      value: task.result?.summary || task.result?.output || task.goal || task.prompt,
    });
  }
  if (Array.isArray(task?.result?.artifacts)) {
    for (const artifact of task.result.artifacts) {
      out.push({
        name: artifact.name || artifact.artifact_id || artifact.type || "artifact",
        type: artifact.type || artifact.artifact_type || "artifact",
        status: artifact.status || status,
        source: task.id,
        updated_at: task.updated_at,
        value: artifact.value || artifact.summary || artifact.path || task.goal || task.prompt,
      });
    }
  }
  if (!out.length && FINAL_STATUSES.has(norm(status))) {
    out.push({
      name: task.title || task.goal || task.id,
      type: "task output",
      status,
      source: task.id,
      updated_at: task.updated_at,
      value: task.result?.summary || task.result?.message || task.prompt,
    });
  }
  return out;
}

function renderPill(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = value || "-";
  el.className = tone(value);
}

function snapshotRuntime() {
  const s = state.snapshot || {};
  return runtime() || s.runtime || {};
}

function controlState() {
  const s = state.snapshot || {};
  return s.authority || s.identity_gate?.authority || s.identity_kernel?.authority || {};
}

function renderOverview() {
  const s = state.snapshot || {};
  const r = snapshotRuntime();
  const sig = signals();
  const summary = state.taskSummary || s.task_summary || {};
  const q = queueCounts(state.tasks);
  const queueDepth = Number(summary.total_tasks || summary.queue_depth || q.all || 0);
  const queueRunning = Number(summary.running_count ?? q.running ?? 0);
  const queueDone = Number(summary.completed_count ?? q.done ?? 0);
  const queueProblem = Number(summary.problem_count ?? q.problem ?? 0);
  const artifactCount = Number(summary.artifact_count ?? summary.real_artifact_count ?? 0) || state.tasks.filter((task) => FINAL_STATUSES.has(norm(taskStatus(task)))).length;
  const blockerCount = (r.blocked_count || 0) + (sig.Runtime?.signal_count || 0);
  const finalCount = state.tasks.filter((t) => FINAL_STATUSES.has(norm(taskStatus(t)))).length;
  const activeTask = state.selectedTask || bestTaskForScope({ type: "running" }) || bestTaskForScope({ type: "task", value: state.selectedTaskId });
  const freshCount = state.tasks.filter((t) => {
    const ts = new Date(t.updated_at || 0).getTime();
    return Number.isFinite(ts) && Date.now() - ts < 24 * 60 * 60 * 1000 && FINAL_STATUSES.has(norm(taskStatus(t)));
  }).length || finalCount;
  const controlLayerLabel = zh(
    s.control_policy?.mode
    || r.control_status
    || s.identity_gate?.runtime?.control_status
    || "lean_execution",
  );
  const qualityGateLabel = zh(
    r.quality_status
    || s.quality_system?.status
    || s.identity_gate?.runtime?.quality_status
    || "promote",
  );
  const releaseLabel = zh(
    s.release_operations?.release_train_status
    || s.release_ops?.status
    || s.identity_gate?.runtime?.release_train_status
    || "signal-only",
  );
  const queueHealthLabel = zh(
    r.daemon_status
    || s.identity_gate?.runtime?.daemon_status
    || "running",
  );

  renderPill("factory-status", !s.running ? "已停止" : sig.Runtime?.status === "blocked" ? "已阻塞" : r.health === "healthy" ? "运行中" : "降级");
  renderPill("control-layer-status", controlLayerLabel);
  renderPill("quality-gate", qualityGateLabel);
  renderPill("connection-pill", zh(s.status || "live"));
  renderPill("session-pill", zh(controlState().session_role || "observer"));
  renderPill("mode-pill", zh(r.goal_mode || "unknown"));
  renderPill("snapshot-age", s.updated_at ? `已刷新 ${ago(s.updated_at)}` : "未知");

  setText("queue-depth", String(q.all));
  setText("current-mission", r.goal_primary || "暂无进行中的任务");
  setText("current-mission-copy", `${zh(r.goal_mode || "unknown")} 模式，${zh(r.control_status || "unknown")} 控制，${blockerCount} 个阻塞点。`);
  setText("active-runtime", `${zh(r.health || "unknown")} / ${queueHealthLabel} / ${qualityGateLabel}`);
  setText("active-runtime-copy", `${r.workspace_root || "工作区未知"} | 新鲜度 ${s.freshness_seconds ?? r.daemon_freshness_seconds ?? "无"} 秒`);
  setText("blocker-count", String(blockerCount));
  setText("blocker-copy", blockerCount ? `${zh(sig.Runtime?.status || "attention")} 运行信号与 ${sig["Release Readiness"]?.signal_count || 0} 个发布信号。` : "当前没有运行阻塞。");
  const missionMeta = document.getElementById("current-mission-meta");
  if (missionMeta) {
    missionMeta.innerHTML = [
      ["任务", activeTask?.id || "自动选择"],
      ["阶段", zh(r.goal_mode || "unknown")],
      ["控制", controlLayerLabel],
      ["真实产物", artifactCount || freshCount],
      ["推荐动作", blockerCount ? "运行验证" : "刷新队列"],
    ].map(([label, value]) => `<span class="pill subtle-pill">${esc(label)}：${esc(value)}</span>`).join("");
  }
  const missionCard = document.getElementById("current-mission-card");
  if (missionCard) {
    missionCard.dataset.drillType = activeTask?.id ? "task" : "goal";
    missionCard.dataset.drillValue = activeTask?.id || "Restore ToyOS real artifact delivery";
    missionCard.setAttribute("aria-label", activeTask?.id ? `打开任务 ${activeTask.id}` : "当前任务钻取");
  }
  const missionActions = document.getElementById("current-mission-actions");
  if (missionActions) {
    missionActions.innerHTML = [
      `<button type="button" class="primary-btn" data-action="run-verification">运行验证</button>`,
      `<button type="button" class="ghost-btn" data-action="focus-queue">查看队列</button>`,
      activeTask?.id ? `<button type="button" class="ghost-btn" data-action="open-current-task">打开任务</button>` : "",
      `<button type="button" class="ghost-btn" data-action="open-incident">打开事件</button>`,
    ].join("");
  }
  const blockerMeta = document.getElementById("blocker-meta");
  if (blockerMeta) {
    blockerMeta.innerHTML = [
      ["运行信号", sig.Runtime?.signal_count || 0],
      ["发布信号", sig["Release Readiness"]?.signal_count || 0],
      ["真实产物", artifactCount || freshCount],
      ["发布态", releaseLabel],
    ].map(([label, value]) => `<span class="pill subtle-pill">${esc(label)}：${esc(value)}</span>`).join("");
  }

  document.getElementById("global-badges").innerHTML = [
    ["工厂", document.getElementById("factory-status").textContent],
    ["控制", document.getElementById("control-layer-status").textContent],
    ["队列", document.getElementById("queue-depth").textContent],
    ["质量", document.getElementById("quality-gate").textContent],
    ["阻塞", blockerCount],
  ].map(([label, value]) => `<span class="${tone(value)}">${esc(label)}：${esc(value)}</span>`).join("");

  const kpis = [
    ["队列深度", queueDepth, "accent", "all", ""],
    ["进行中", queueRunning, "", "running", ""],
    ["完成", queueDone, "accent", "done", ""],
    ["问题", queueProblem, "danger", "problem", ""],
    ["产物", artifactCount || freshCount, "accent", "done", ""],
    ["信号", Object.values(sig).reduce((sum, x) => sum + (x?.signal_count || 0), 0), "warn", "signal", ""],
    ["发布", zh(s.release_operations?.release_train_status || s.release_operations?.status || "unknown"), "", "released", ""],
    ["新鲜度", s.freshness_seconds ?? r.daemon_freshness_seconds ?? "无", "", "fresh", ""],
  ];
  document.getElementById("kpi-strip").innerHTML = kpis.map(([label, value, cls, drillType, drillValue]) => {
    const dataAttrs = ` data-drill-type="${esc(drillType)}"${drillValue ? ` data-drill-value="${esc(drillValue)}"` : ""} tabindex="0" role="button" aria-label="${esc(label)} 任务钻取"`;
    return `<article class="kpi ${cls} drill-card"${dataAttrs}><span>${esc(label)}</span><strong>${esc(value)}</strong></article>`;
  }).join("");

  setText("queue-depth", String(queueDepth));
  setText("queue-depth-copy", `${queueRunning} 进行中 · ${queueDone} 完成 · ${queueProblem} 问题`);

  document.getElementById("operator-notes").innerHTML = [
    ["权限", zh(controlState().control_center_status || "unknown")],
    ["会话", controlState().session_owner || "未知"],
    ["降级", s.policy?.fallback_strategy?.default_runtime_when_core_unavailable || "无"],
    ["工作区", r.workspace_root || "无"],
    ["未关闭升级", s.autonomy_score?.metrics?.history?.recovery?.open_error_escalations ?? 0],
  ].map(([label, value]) => `<div class="mini-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join("");

  renderSignals();
  renderRawState();
}

function renderSignals() {
  const s = state.snapshot || {};
  const sig = signals();
  const verificationSection = document.getElementById("verification");
  const verification = document.getElementById("verification-summary");
  const incidents = document.getElementById("incident-list");
  const signalList = document.getElementById("signal-list");
  const vp = document.getElementById("verification-pill");
  if (!verification || !incidents || !signalList || !vp) return;

  const groups = Object.entries(sig);
  vp.textContent = groups.length ? "在线" : "空闲";
  vp.className = groups.length ? "pill" : "pill subtle-pill";

  let qualityStrip = document.getElementById("quality-strip");
  if (!qualityStrip && verificationSection) {
    qualityStrip = document.createElement("div");
    qualityStrip.id = "quality-strip";
    qualityStrip.className = "quality-strip";
    verificationSection.insertBefore(qualityStrip, verificationSection.querySelector(".split-grid"));
  }

  if (qualityStrip) {
    qualityStrip.innerHTML = [
      ["运行", sig.Runtime?.status || "unknown", sig.Runtime?.signal_count || 0],
      ["成熟度", sig.Maturity?.status || "unknown", sig.Maturity?.signal_count || 0],
      ["发布", sig["Release Readiness"]?.status || "unknown", sig["Release Readiness"]?.signal_count || 0],
    ].map(([label, status, value]) => `
      <article class="quality-strip-card">
        <span class="eyebrow">${esc(label)}</span>
        <strong>${esc(zh(status))}</strong>
        <span class="meta">${esc(value)} 个信号</span>
      </article>`).join("");
  }

  signalList.innerHTML = groups.length
    ? groups.map(([group, payload]) => `
        <article class="signal-card">
          <h3>${esc(zh(group))}</h3>
          <div class="meta">${esc(zh(payload?.status || "unknown"))} · ${esc(payload?.signal_count || 0)} 个信号</div>
          <div class="stack">
            ${(payload?.signals || []).slice(0, 3).map((item) => `
              <div class="mini-metric">
                <span>${esc(item.code || item.category || "signal")}</span>
                <strong>${esc(zh(item.effect || item.source || "observe"))}</strong>
              </div>`).join("")}
          </div>
        </article>`).join("")
    : '<div class="empty-state">当前还没有验证信号。</div>';

  verification.innerHTML = [
    ["运行", sig.Runtime?.status || "unknown", sig.Runtime?.signal_count || 0],
    ["成熟度", sig.Maturity?.status || "unknown", sig.Maturity?.signal_count || 0],
    ["发布", sig["Release Readiness"]?.status || "unknown", sig["Release Readiness"]?.signal_count || 0],
    ["质量", s.quality_system?.status || "unknown", s.quality_system?.overall_score || s.quality_score || 0],
    ["风险扫描", state.risk?.status || state.risk?.scan_status || "unknown", state.risk?.risk_count || 0],
    ["安全", state.security?.status || state.security?.overall_status || "unknown", state.security?.alert_count || 0],
  ].map(([label, status, value]) => `<article class="executor-card"><p class="eyebrow">${esc(label)}</p><h3>${esc(zh(status))}</h3><div class="meta">${esc(value)}</div></article>`).join("");

  const incidentsSource = Array.isArray(state.incidents) ? state.incidents.slice().sort((a, b) => new Date(b.updated_at || b.created_at || b.timestamp || 0) - new Date(a.updated_at || a.created_at || a.timestamp || 0)) : [];
  const incidentPage = paginate(incidentsSource, "incidents", PAGE_SIZES.incidents);
  incidents.innerHTML = incidentPage.items.length
    ? incidentPage.items.map((item) => `
        <article class="incident-card">
          <div class="section-head compact">
            <h3>${esc(item.title || item.message || item.code || item.summary || "事件")}</h3>
            <span class="${tone(item.status || item.severity || item.level)}">${esc(zh(item.status || item.severity || item.level || "unknown"))}</span>
          </div>
          <div class="meta">${esc(fmt(item.updated_at || item.created_at || item.timestamp))}</div>
          <div class="detail-copy">${esc(item.detail || item.reason || item.description || item.output || "暂无详情")}</div>
        </article>`).join("")
    : '<div class="empty-state">当前没有事件记录。</div>';
  renderPager("incident-pager", "incidents", incidentsSource.length, PAGE_SIZES.incidents, "事件");

  document.getElementById("artifact-summary-pill").textContent = zh(s.release_operations?.release_train_status || s.release_operations?.status || "ready");
  document.getElementById("event-summary-pill").textContent = (state.trace.length || state.coreMessages.length) ? `${state.trace.length + state.coreMessages.length} 条事件` : "空闲";
  document.getElementById("executor-summary-pill").textContent = `${arr(state.executors).length} 条通道`;
}

function renderTasks() {
  const counts = queueCounts(state.tasks);
  const filterRow = document.getElementById("queue-filter-row");
  const list = document.getElementById("queue-list");
  if (!filterRow || !list) return;

  const scopeChip = state.queueScope
    ? `<button type="button" class="filter-chip active" data-clear-scope="1">钻取：${esc(scopeLabel(state.queueScope))}</button>`
    : "";
  const filterChips = [["all", "全部"], ["queued", "排队中"], ["running", "运行中"], ["done", "已完成"], ["problem", "问题"]]
    .map(([key, label]) => `<button type="button" class="filter-chip ${state.queueFilter === key ? "active" : ""}" data-filter="${esc(key)}">${esc(label)} (${counts[key]})</button>`)
    .join("");
  filterRow.innerHTML = `${scopeChip}${filterChips}`;
  filterRow.querySelectorAll("[data-filter]").forEach((btn) => btn.addEventListener("click", () => {
    state.queueFilter = btn.dataset.filter || "all";
    state.queueScope = null;
    renderTasks();
  }));
  filterRow.querySelectorAll("[data-clear-scope]").forEach((btn) => btn.addEventListener("click", () => {
    state.queueScope = null;
    renderTasks();
  }));

  const query = state.searchQuery.trim().toLowerCase();
  const filtered = state.tasks.filter((task) => {
    const bucketMatch = state.queueFilter === "all" || bucket(task) === state.queueFilter;
    if (!bucketMatch) return false;
    if (!taskMatchesScope(task, state.queueScope)) return false;
    if (!query) return true;
    return taskSearchText(task).includes(query);
  });
  const ordered = filtered.slice().sort((a, b) => new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0));
  const paged = paginate(ordered, "queue", PAGE_SIZES.queue);
  list.innerHTML = paged.items.length
    ? paged.items.map((task) => `
        <article class="queue-row ${task.id === state.selectedTaskId ? "active" : ""}" data-task-id="${esc(task.id)}">
          <div class="queue-cell-title">
            <strong>${esc(task.title || task.goal || task.prompt || task.id)}</strong>
            <span>${esc(clampLabel(task.prompt || task.goal || "", 96))}</span>
          </div>
          <div class="queue-cell"><span class="${tone(taskStatus(task))}">${esc(zh(taskStatus(task)))}</span></div>
          <div class="queue-cell">${esc(task.repo_path || task.repo_id || "无")}</div>
          <div class="queue-cell">${esc(task.executor_id || task.preferred_worker || task.execution_lane || "无")}</div>
          <div class="queue-cell">${esc(ago(task.updated_at || task.created_at))}</div>
        </article>`).join("")
    : '<div class="empty-state">当前筛选条件下没有匹配的任务。</div>';
  renderPager("queue-pager", "queue", ordered.length, PAGE_SIZES.queue, "队列");

  list.querySelectorAll("[data-task-id]").forEach((card) => card.addEventListener("click", () => selectTask(card.dataset.taskId)));

  const selected = state.selectedTask || state.tasks.find((task) => task.id === state.selectedTaskId) || null;
  const title = document.getElementById("task-title");
  const pill = document.getElementById("task-status");
  if (selected) {
    title.textContent = selected.title || selected.goal || selected.prompt || selected.id;
    pill.textContent = zh(taskStatus(selected));
    pill.className = tone(taskStatus(selected));
    renderTaskDetail();
  } else {
    title.textContent = "未选择";
    pill.textContent = "空闲";
    pill.className = "pill subtle-pill";
    document.getElementById("task-detail").innerHTML = '<div class="empty-state">从队列中选择一个任务，可以查看详细信息。</div>';
    document.getElementById("raw-task").textContent = "";
  }
}

function renderTaskDetail() {
  const task = state.selectedTask;
  if (!task) return;
  const detail = document.getElementById("task-detail");
  const raw = document.getElementById("raw-task");
  if (!detail || !raw) return;
  const status = taskStatus(task);
  raw.textContent = JSON.stringify(task, null, 2);
  const plan = Array.isArray(task.plan) ? task.plan : [];
  const signalsList = task.signals || task.verification_signals || [];
  const artifacts = artifactsFromTask(task);
  detail.innerHTML = `
    <div class="stack">
      <article class="event-card">
        <div class="section-head compact">
          <h3>任务摘要</h3>
          <span class="${tone(status)}">${esc(zh(status))}</span>
        </div>
        <div class="meta">仓库：${esc(task.repo_path || "无")}</div>
        <div class="meta">执行器：${esc(task.executor_id || task.preferred_worker || task.execution_lane || "无")}</div>
        <div class="meta">上下文：${esc(zh(task.context_mode || task.context_envelope?.mode || "无"))}</div>
        <div class="meta">验证：${esc(task.verification_level || task.verification_contract?.verification_level || "无")}</div>
        <div class="detail-copy">${esc(task.prompt || task.goal || "暂无任务描述")}</div>
      </article>
      <article class="event-card">
        <h3>运行事实</h3>
        <div class="meta">队列：${esc(task.queue_name || "无")}</div>
        <div class="meta">通道：${esc(task.execution_lane || "无")}</div>
        <div class="meta">接纳：${esc(task.admission_lane || "无")}</div>
        <div class="meta">原因：${esc(task.admission_reason || "无")}</div>
        <div class="meta">父任务 / 根任务：${esc(task.parent_task_id || "-")} / ${esc(task.root_task_id || "-")}</div>
      </article>
      ${plan.length ? `<article class="event-card"><h3>计划</h3><div class="stack">${plan.map((step, index) => `
        <div class="mini-metric"><span>${esc(step.title || `步骤 ${index + 1}`)} · ${esc(zh(step.phase || step.status || "pending"))}</span><strong>${esc(step.worker || "执行者")}</strong></div>
        <div class="detail-copy">${esc(step.instructions || step.output || step.summary || "")}</div>`).join("")}</div></article>` : ""}
      ${signalsList.length ? `<article class="event-card"><h3>验证信号</h3><div class="stack">${signalsList.map((signal) => `<div class="mini-metric"><span>${esc(signal.code || signal.category || "signal")}</span><strong>${esc(zh(signal.status || signal.effect || "observed"))}</strong></div>`).join("")}</div></article>` : ""}
      ${artifacts.length ? `<article class="event-card"><h3>产物证据</h3><div class="stack">${artifacts.map((artifact) => `<div class="mini-metric"><span>${esc(artifact.name)}</span><strong>${esc(zh(artifact.status || "unknown"))}</strong></div><div class="detail-copy">${esc(artifact.value || "暂无产物内容")}</div>`).join("")}</div></article>` : ""}
      ${task.result && Object.keys(task.result).length ? `<article class="event-card"><h3>结果</h3><pre class="code-block">${esc(JSON.stringify(task.result, null, 2))}</pre></article>` : ""}
    </div>`;
}

function renderExecutors() {
  const list = arr(state.executors);
  const grid = document.getElementById("executor-grid");
  if (!grid) return;
  const defaultExecutor = state.executors?.routing_policy?.default_executor_id || null;
  const enhanced = list.map((item) => {
    const id = item.executor_id || item.id || item.name || "executor";
    const load = executorLoad(id);
    const health = executorHealth(item);
    return { ...item, _id: id, _load: load, _health: health };
  }).sort((a, b) => {
    const loadDelta = (b._load?.total || 0) - (a._load?.total || 0);
    if (loadDelta) return loadDelta;
    const runningDelta = (b._load?.running || 0) - (a._load?.running || 0);
    if (runningDelta) return runningDelta;
    const healthWeight = (health) => (health === "healthy" ? 2 : health === "degraded" ? 1 : 0);
    const healthDelta = healthWeight(b._health?.status) - healthWeight(a._health?.status);
    if (healthDelta) return healthDelta;
    return String(a._id || "").localeCompare(String(b._id || ""), "zh-Hans-CN");
  });
  const enabledCount = enhanced.filter((item) => item.enabled !== false).length;
  const onlineCount = enhanced.filter((item) => item._health.status === "healthy").length;
  const parallelCount = enhanced.filter((item) => item.supports_parallel || (item.health || {}).supports_parallel).length;
  const longHorizonCount = enhanced.filter((item) => item.supports_long_horizon || (item.health || {}).supports_long_horizon).length;
  const totalTaskTypes = list.reduce((sum, item) => sum + (Array.isArray(item.task_types) ? item.task_types.length : 0), 0);
  const loadedTaskExecutors = enhanced.filter((item) => (item._load?.total || 0) > 0).length;
  const totalMatchedTasks = enhanced.reduce((sum, item) => sum + (item._load?.total || 0), 0);
  const activeChannels = enhanced.filter((item) => (item._load?.running || 0) > 0).length;
  const blockedChannels = enhanced.filter((item) => (item._load?.blocked || 0) > 0).length;
  const closedChannels = enhanced.filter((item) => (item._load?.total || 0) > 0 && (item._load?.running || 0) === 0 && (item._load?.blocked || 0) === 0).length;
  const idleChannels = enhanced.filter((item) => (item._load?.total || 0) === 0).length;
  document.getElementById("executor-summary-pill").textContent = `${list.length} 条通道 · ${activeChannels} 进行中 · ${blockedChannels} 阻塞中`;
  const loadStrip = document.getElementById("executor-load-strip");
  if (loadStrip) {
    loadStrip.innerHTML = [
      ["进行中通道", activeChannels],
      ["阻塞中通道", blockedChannels],
      ["已收尾通道", closedChannels],
      ["空闲通道", idleChannels],
    ].map(([label, value]) => `
      <article class="mini-metric">
        <span>${esc(label)}</span>
        <strong>${esc(value)}</strong>
      </article>`).join("");
  }
  const executorNote = document.getElementById("executor-note");
  if (executorNote) {
    executorNote.textContent = blockedChannels
      ? `说明：阻塞中通道统计的是历史失败、超时或问题态任务，不等于当前执行器离线。`
      : `说明：当前没有历史阻塞积压，执行器通道状态较为平稳。`;
  }
  const target = grid;
  target.innerHTML = list.length
    ? enhanced.map((item) => {
        const id = item._id;
        const health = item._health;
        const load = item._load;
        const status = health.status || "healthy";
        const taskTypes = Array.isArray(item.task_types) ? item.task_types : [];
        const taskTypePreview = taskTypes.slice(0, 3).map((entry) => esc(zh(entry))).join("、");
        const supportsParallel = item.supports_parallel ?? health.supports_parallel ?? false;
        const supportsLongHorizon = item.supports_long_horizon ?? health.supports_long_horizon ?? false;
        return `
          <article class="executor-row">
            <div class="executor-cell">
              <strong class="executor-title">${esc(id)}</strong>
              <span class="executor-subtitle">${esc(zh(item.adapter || health.adapter || "无"))}</span>
            </div>
            <div class="executor-cell">
              <strong class="executor-title">${esc(zh(item.mode || "无"))}</strong>
              <span class="executor-subtitle">${esc(item.execution_lane || item.mode || "无")}</span>
            </div>
            <div class="executor-cell">
              <strong class="executor-title">${esc(zh(item.engine || "无"))}</strong>
              <span class="executor-subtitle">${esc(supportsLongHorizon ? "支持长周期" : "短周期通道")}</span>
            </div>
            <div class="executor-cell">
              <span class="${tone(status)}">${esc(zh(status))}</span>
              <span class="executor-subtitle">${esc(load.total)} 任务 · ${esc(load.running)} 进行中 · ${esc(load.blocked)} 阻塞</span>
            </div>
            <div class="executor-cell">
              <strong class="executor-title">${esc(load.usageLabel)}</strong>
              <span class="executor-subtitle">${esc(taskTypes.length)} 个类型 · ${esc(taskTypePreview || "无")}</span>
            </div>
            <div class="executor-cell">
              <strong class="executor-title">${esc(supportsParallel ? "并行" : "串行")}</strong>
              <span class="executor-subtitle">${esc(defaultExecutor === id ? "默认通道" : defaultExecutor ? `默认：${defaultExecutor}` : "默认：未配置")} · ${esc(supportsLongHorizon ? "长周期" : "短周期")}</span>
            </div>
          </article>`;
      }).join("")
    : `<div class="empty-state">当前没有执行器记录。<div class="stack"><div class="mini-metric"><span>启用</span><strong>${esc(enabledCount)}</strong></div><div class="mini-metric"><span>在线</span><strong>${esc(onlineCount)}</strong></div><div class="mini-metric"><span>并行</span><strong>${esc(parallelCount)}</strong></div><div class="mini-metric"><span>长周期</span><strong>${esc(longHorizonCount)}</strong></div><div class="mini-metric"><span>任务类型</span><strong>${esc(totalTaskTypes)}</strong></div></div></div>`;
}

function renderArtifacts() {
  const list = document.getElementById("artifact-list");
  if (!list) return;
  const artifacts = state.tasks.flatMap((task) => artifactsFromTask(task));
  const paged = paginate(artifacts, "artifacts", PAGE_SIZES.artifacts);
  document.getElementById("artifact-summary-pill").textContent = artifacts.length ? `${artifacts.length} 项` : "无";
  list.innerHTML = paged.items.length
    ? paged.items.map((artifact) => `
        <article class="artifact-card">
          <div class="section-head compact">
            <h3>${esc(artifact.name)}</h3>
            <span class="${tone(artifact.status)}">${esc(zh(artifact.status || "unknown"))}</span>
          </div>
          <div class="meta">类型：${esc(zh(artifact.type || "无"))}</div>
          <div class="meta">来源任务：${esc(artifact.source)}</div>
          <div class="meta">更新时间：${esc(ago(artifact.updated_at))}</div>
          <div class="detail-copy">${esc(artifact.value || "暂无产物正文")}</div>
        </article>`).join("")
    : '<div class="empty-state">当前还没有已验证产物。</div>';
  renderPager("artifact-pager", "artifacts", artifacts.length, PAGE_SIZES.artifacts, "产物");
}

function renderTimeline() {
  const list = document.getElementById("timeline-list");
  if (!list) return;
  const source = (state.trace.length ? state.trace : state.coreMessages).slice().reverse();
  const paged = paginate(source, "events", PAGE_SIZES.events);
  document.getElementById("event-summary-pill").textContent = source.length ? `${source.length} 条事件` : "空闲";
  list.innerHTML = paged.items.length
    ? paged.items.map((item) => `
        <article class="event-card">
          <div class="timeline-node">
            <div class="timeline-time">${esc(fmt(item.timestamp || item.created_at || item.updated_at || item.time))}</div>
            <div>
              <div class="section-head compact">
                <h3>${esc(zh(item.message || item.action || item.summary || item.title || item.reason || "更新"))}</h3>
                <span class="pill subtle-pill">${esc(zh(item.phase || item.kind || item.level || item.status || "event"))}</span>
              </div>
              <div class="detail-copy">${esc(item.result || item.next || item.detail || item.output || "")}</div>
            </div>
          </div>
        </article>`).join("")
    : '<div class="empty-state">当前还没有捕获事件。</div>';
  renderPager("event-pager", "events", source.length, PAGE_SIZES.events, "事件");
}

function renderRawState() {
  const el = document.getElementById("raw-snapshot");
  if (el) {
    el.textContent = JSON.stringify({
      runtime: runtime(),
      control_policy: state.snapshot?.control_policy,
      signal_dashboard: signals(),
      delivery_summary: state.snapshot?.delivery_summary,
      quality_system: state.snapshot?.quality_system,
      risk: state.risk,
      security: state.security,
    }, null, 2);
  }
}

let deferredLoadsScheduled = false;
let hydrationScheduled = false;

function scheduleDeferredLoads() {
  if (deferredLoadsScheduled) return;
  deferredLoadsScheduled = true;
  const run = () => {
    const work = [];
    if (!state.loaded.tasks) work.push(loadTasksData());
    if (!state.loaded.executors) work.push(loadExecutorsData());
    if (work.length) {
      Promise.allSettled(work)
        .then(() => ensureViewData(state.view))
        .catch(logAsyncError);
      return;
    }
    ensureViewData(state.view).catch(logAsyncError);
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(run, { timeout: 2500 });
  } else {
    setTimeout(run, 1200);
  }
}

function scheduleHydration() {
  if (hydrationScheduled) return;
  hydrationScheduled = true;
  const run = () => {
    loadCoreDashboard()
      .then(() => {
        scheduleDeferredLoads();
      })
      .catch((err) => {
        logAsyncError(err);
        document.getElementById("connection-pill").textContent = "离线";
        scheduleDeferredLoads();
      });
  };
  if (typeof window.requestIdleCallback === "function") {
    window.requestIdleCallback(run, { timeout: 1800 });
  } else {
    setTimeout(run, 350);
  }
}

async function ensureViewData(view) {
  const current = view || state.view || "overview";
  if (current === "mission") {
    if (!state.loaded.tasks) await loadTasksData();
    return;
  }
  if (current === "runtime") {
    const work = [];
    if (!state.loaded.tasks) work.push(loadTasksData());
    if (!state.loaded.executors) work.push(loadExecutorsData());
    if (work.length) await Promise.allSettled(work);
    return;
  }
  if (current === "quality" || current === "evidence") {
    const work = [];
    if (!state.loaded.tasks) work.push(loadTasksData());
    if (!state.loaded.executors && current === "quality") work.push(loadExecutorsData());
    if (!state.loaded.auxiliary) work.push(loadAuxiliaryPanels());
    if (work.length) await Promise.allSettled(work);
    return;
  }
  if (!state.loaded.snapshot) {
    await loadCoreDashboard();
  }
}

async function selectTask(id) {
  if (!id) return;
  state.selectedTaskId = id;
  const source = state.tasks.find((task) => task.id === id) || null;
  try {
    const [detail, tree, signalsPayload, graph] = await Promise.all([
      request(`/api/tasks/${encodeURIComponent(id)}`),
      request(`/api/tasks/${encodeURIComponent(id)}/tree`),
      request(`/api/tasks/${encodeURIComponent(id)}/verification-signals`),
      request(`/api/tasks/${encodeURIComponent(id)}/graph`),
    ]);
    state.selectedTask = { ...(source || {}), ...(detail || {}), tree, signals: signalsPayload?.signals || [], graph };
  } catch (error) {
    state.selectedTask = { ...(source || {}), error: error.message };
  }
  renderTasks();
  renderTaskDetail();
  renderRawState();
}

async function loadCoreDashboard() {
  return withLoadLock("snapshot", async () => {
    const result = await Promise.allSettled([
      request("/api/bootstrap", { timeoutMs: 1200 }),
    ]);
    const snapshotResult = result[0];
    state.snapshot = snapshotResult.status === "fulfilled"
      ? { ...(state.snapshot || {}), ...(snapshotResult.value || {}) }
      : (state.snapshot || { error: snapshotResult.reason?.message || "仪表盘不可用" });
    markLoaded("snapshot");
    renderOverview();
    document.getElementById("connection-pill").textContent = snapshotResult.status === "fulfilled" ? "在线" : "降级";
    document.getElementById("connection-pill").className = snapshotResult.status === "fulfilled" ? "pill" : "warning-pill";
    return state.snapshot;
  });
}

async function loadTasksData() {
  return withLoadLock("tasks", async () => {
    const payload = await request("/api/tasks", { timeoutMs: 12000 });
    state.tasks = arr(payload);
    if (!state.selectedTaskId && state.tasks.length) {
      const preferred = state.tasks.find((task) => norm(taskStatus(task)) === "running") || state.tasks[0];
      state.selectedTaskId = preferred.id;
      state.selectedTask = preferred;
    } else if (state.selectedTaskId) {
      state.selectedTask = state.tasks.find((task) => task.id === state.selectedTaskId) || null;
      if (!state.selectedTask && state.tasks.length) {
        const preferred = state.tasks.find((task) => norm(taskStatus(task)) === "running") || state.tasks[0];
        state.selectedTaskId = preferred.id;
        state.selectedTask = preferred;
      }
    }
    markLoaded("tasks");
    renderTasks();
    renderOverview();
    renderExecutors();
    renderArtifacts();
    renderTimeline();
    return state.tasks;
  });
}

async function loadExecutorsData() {
  return withLoadLock("executors", async () => {
    try {
      const payload = await request("/api/executors", { timeoutMs: 5000 });
      state.executors = payload;
    } catch (error) {
      if (!state.executors) {
        state.executors = { executors: [], error: error?.message || "执行器不可用" };
      }
    }
    markLoaded("executors");
    renderOverview();
    renderExecutors();
    return state.executors;
  });
}

async function loadAuxiliaryPanels() {
  return withLoadLock("auxiliary", async () => {
    const endpoints = {
      incidents: "/api/incidents",
      risk: "/api/risk/status",
      security: "/api/security/status",
      policy: "/api/policy",
      trace: "/api/execution-trace",
      coreMessages: "/api/core-messages",
    };
    const results = await Promise.allSettled(
      Object.entries(endpoints).map(([, url]) => request(url, { timeoutMs: 4500 })),
    );
    const map = Object.keys(endpoints).reduce((acc, key, index) => {
      acc[key] = results[index];
      return acc;
    }, {});
    state.incidents = map.incidents.status === "fulfilled" ? arr(map.incidents.value) : [];
    state.risk = map.risk.status === "fulfilled" ? map.risk.value : null;
    state.security = map.security.status === "fulfilled" ? map.security.value : null;
    state.policy = map.policy.status === "fulfilled" ? map.policy.value : null;
    state.trace = map.trace.status === "fulfilled" ? arr(map.trace.value) : [];
    state.coreMessages = map.coreMessages.status === "fulfilled" ? arr(map.coreMessages.value) : [];
    markLoaded("auxiliary");
    renderOverview();
    renderSignals();
    renderArtifacts();
    renderTimeline();
    return {
      incidents: state.incidents,
      trace: state.trace,
    };
  });
}

async function loadDashboard({ eagerAuxiliary = false } = {}) {
  await loadCoreDashboard();
  await ensureViewData(state.view);
  if (eagerAuxiliary) {
    await Promise.allSettled([
      loadTasksData(),
      loadExecutorsData(),
      loadAuxiliaryPanels(),
    ]);
  }
}

async function post(url, payload = null) {
  const options = { method: "POST" };
  if (payload) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(payload);
  }
  return request(url, options);
}

function missionPayload() {
  return {
    prompt: document.getElementById("command_prompt").value.trim(),
    title: document.getElementById("command_goal").value.trim() || null,
    repo_path: document.getElementById("command_repo_path").value.trim() || null,
    project_id: document.getElementById("command_project_id").value.trim() || null,
    caller: "mission-control",
    context_mode: document.getElementById("command_context_mode").value || "standard",
    allow_resource_scan: true,
    allow_repo_status: true,
    auto_approve: document.getElementById("command_auto_approve").checked,
    verification_level: document.getElementById("command_verification_level").value || null,
    scheduled_by: "mission-control",
    execution_mode: "governance",
    scheduler_hint: { source: "mission-control" },
    tool_policy: {},
    worker_vm_policy: {},
    executor_hint: {},
    goal_admission: { source: "mission-control", priority: "high" },
  };
}

async function dispatchMission() {
  const payload = missionPayload();
  if (!payload.prompt || payload.prompt.length < 8) return alert("任务描述至少需要 8 个字符。");
  await post("/api/dispatch", payload);
  await loadDashboard();
}

async function admitGoal() {
  const payload = missionPayload();
  const goal = document.getElementById("command_goal").value.trim() || payload.prompt;
  if (!goal || goal.length < 8) return alert("目标至少需要 8 个字符。");
  await post("/api/goals/admit", {
    goal,
    title: document.getElementById("command_goal").value.trim() || goal,
    prompt: payload.prompt || goal,
    project_id: payload.project_id,
    repo_path: payload.repo_path,
    goal_id: goal,
    scheduled_by: "mission-control",
    context_mode: payload.context_mode,
    max_context_chars: 1600,
    allow_resource_scan: true,
    allow_repo_status: true,
    execution_mode: "research",
    preferred_worker: null,
    execution_lane: "host-control",
    auto_approve: payload.auto_approve,
    task_type: "mission",
    queue_name: "mission-control",
    verification_level: payload.verification_level,
    scheduler_hint: payload.scheduler_hint,
    goal_admission: payload.goal_admission,
  });
  await loadDashboard();
}

async function togglePauseResume() {
  const paused = Boolean(state.snapshot?.paused);
  await post(paused ? "/api/control-center/resume" : "/api/control-center/pause", {
    reason: paused ? "已从任务指挥台恢复。" : "已从任务指挥台暂停。",
  });
  await loadDashboard();
}

async function safeMode() {
  await post("/api/control-center/pause", { reason: "已从任务指挥台进入安全模式。" });
  await loadDashboard();
}

async function runVerification() {
  await Promise.allSettled([post("/api/risk/scan"), request("/api/security/audit?limit=20")]);
  await loadDashboard();
}

async function ensureRecovery() {
  await post("/api/recovery/ensure");
  await loadDashboard();
}

async function auditGoals() {
  await request("/api/goals/audit");
  await loadDashboard();
}

function clearForm() {
  document.getElementById("command_prompt").value = "";
  document.getElementById("command_goal").value = "";
  document.getElementById("command_repo_path").value = "D:\\codex\\generated\\toy-os-demo";
  document.getElementById("command_project_id").value = "";
  document.getElementById("command_auto_approve").checked = false;
  document.getElementById("command_verification_level").value = "";
  document.getElementById("command_context_mode").value = "standard";
}

function openLatestIncident() {
  const el = document.getElementById("incident-list")?.firstElementChild;
  if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
}

function bindEvents() {
  document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
  document.querySelectorAll("button[data-view]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  const search = document.getElementById("global-search");
  if (search) {
    search.addEventListener("input", () => {
      state.searchQuery = search.value || "";
      renderTasks();
    });
  }
  document.getElementById("command-form").addEventListener("submit", (e) => {
    e.preventDefault();
    dispatchMission().catch((err) => alert(`任务派发失败：${err.message}`));
  });
  document.getElementById("admit-goal-btn").addEventListener("click", (e) => {
    e.preventDefault();
    admitGoal().catch((err) => alert(`目标接纳失败：${err.message}`));
  });
  document.getElementById("clear-command-btn").addEventListener("click", clearForm);
  document.getElementById("open-incident-btn").addEventListener("click", openLatestIncident);

  const handlers = {
    "toggle-pause": togglePauseResume,
    "safe-mode": safeMode,
    "run-verification": runVerification,
    "ensure-recovery": ensureRecovery,
    "audit-goals": auditGoals,
    "open-current-task": async () => {
      const current = state.selectedTask || bestTaskForScope({ type: "running" }) || bestTaskForScope({ type: "task", value: state.selectedTaskId });
      if (current?.id) {
        await openTaskDrill({ type: "task", value: current.id });
      }
    },
    "refresh-queue": loadDashboard,
    "focus-queue": () => {
      switchView("mission");
      setTimeout(() => {
        const pane = document.getElementById("queue");
        pane?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 80);
    },
    "open-incident": openLatestIncident,
    "drill:all": () => openTaskDrill({ type: "all" }),
    "drill:running": () => openTaskDrill({ type: "running" }),
    "drill:done": () => openTaskDrill({ type: "done" }),
    "drill:problem": () => openTaskDrill({ type: "problem" }),
    "drill:released": () => openTaskDrill({ type: "released" }),
    "drill:fresh": () => openTaskDrill({ type: "fresh" }),
    "drill:signal": () => openTaskDrill({ type: "signal" }),
    "drill:task": (value) => openTaskDrill({ type: "task", value }),
    "drill:goal": (value) => openTaskDrill({ type: "goal", value }),
  };
  document.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-action]");
    if (button) {
      const handler = handlers[button.dataset.action];
      if (handler) {
        handler().catch((err) => alert(`${button.textContent}失败：${err.message}`));
        return;
      }
    }
    const drill = event.target.closest?.("[data-drill-type]");
    if (!drill) return;
    const drillHandler = handlers[`drill:${drill.dataset.drillType}`];
    if (!drillHandler) return;
    const value = drill.dataset.drillValue || "";
    drillHandler(value).catch((err) => alert(`卡片钻取失败：${err.message}`));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const drill = event.target.closest?.("[data-drill-type]");
    if (!drill) return;
    event.preventDefault();
    const drillHandler = handlers[`drill:${drill.dataset.drillType}`];
    if (!drillHandler) return;
    const value = drill.dataset.drillValue || "";
    drillHandler(value).catch((err) => alert(`卡片钻取失败：${err.message}`));
  });
}

bindEvents();
renderView();
renderOverview();
renderTasks();
renderExecutors();
renderSignals();
renderArtifacts();
renderTimeline();
renderRawState();
scheduleHydration();
setInterval(() => loadCoreDashboard().catch(logAsyncError), 15000);
setInterval(() => {
  if (state.view === "mission" || state.view === "quality") {
    loadTasksData().catch(logAsyncError);
  }
  if (state.view === "runtime" || state.view === "quality") {
    loadExecutorsData().catch(logAsyncError);
  }
  if (state.view === "quality" || state.view === "evidence") {
    loadAuxiliaryPanels().catch(logAsyncError);
  }
}, 60000);
