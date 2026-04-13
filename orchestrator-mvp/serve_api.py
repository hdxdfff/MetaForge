from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT.parent / "tools" / "python311-embed" / "python.exe"
SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"
BACKEND_PORT = 8788
FRONTDOOR_PORT = 8787
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
BACKEND_SCRIPT = ROOT / "serve_backend.py"
STATIC_DIR = ROOT / "app" / "static"
CONTROL_CENTER_STATE_PATH = ROOT / "data" / "control_center_state.json"
FACTORY_STATE_PATH = ROOT / "data" / "factory_state.json"
GOAL_BACKLOG_STATUS_PATH = ROOT / "data" / "goal_backlog_status.json"
TASKS_PATH = ROOT / "data" / "tasks.json"
TASK_SUMMARY_PATH = ROOT / "data" / "task_summary.json"
EXECUTOR_REGISTRY_PATH = ROOT / "contracts" / "executors" / "executor_registry.json"
BACKEND_LOCK = threading.Lock()

if SITE_PACKAGES.exists():
    sys.path.insert(0, str(SITE_PACKAGES))
sys.path.insert(0, str(ROOT))


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _read_control_center_state() -> dict:
    state = {
        "paused": False,
        "status": "active",
        "updated_at": None,
        "reason": "",
        "resident": True,
    }
    state.update(_read_json(CONTROL_CENTER_STATE_PATH, {}))
    return state


def _read_factory_state() -> dict:
    return _read_json(FACTORY_STATE_PATH, {})


def _read_goal_backlog_status() -> dict:
    return _read_json(GOAL_BACKLOG_STATUS_PATH, {})


def _read_tasks() -> list[dict]:
    tasks = _read_json(TASKS_PATH, [])
    return tasks if isinstance(tasks, list) else []


def _task_summary_cache_is_valid() -> bool:
    if not TASK_SUMMARY_PATH.exists() or not TASKS_PATH.exists():
        return False
    try:
        return TASK_SUMMARY_PATH.stat().st_mtime >= TASKS_PATH.stat().st_mtime
    except Exception:
        return False


def _task_summary_executor_fields(task: dict) -> list[str]:
    if not isinstance(task, dict):
        return []
    route = task.get("executor_route") or {}
    selected = route.get("selected") or {}
    candidates = route.get("candidates") if isinstance(route.get("candidates"), list) else []
    fields = [
        task.get("executor_id"),
        task.get("preferred_worker"),
        task.get("execution_lane"),
        task.get("worker"),
        task.get("assigned_executor_id"),
        (task.get("routing") or {}).get("executor_id") if isinstance(task.get("routing"), dict) else None,
        (task.get("routing") or {}).get("preferred_worker") if isinstance(task.get("routing"), dict) else None,
        selected.get("executor_id"),
        selected.get("id"),
        selected.get("name"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            fields.extend([candidate.get("executor_id"), candidate.get("id"), candidate.get("name")])
    return [str(field).strip() for field in fields if field]


def _compute_task_summary(tasks: list[dict]) -> dict:
    status_counts = Counter()
    executor_counts = Counter()
    executor_running_counts = Counter()
    executor_blocked_counts = Counter()
    completed_count = 0
    running_count = 0
    problem_count = 0
    artifact_count = 0

    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = _task_status(task)
        status_counts[status] += 1
        if status in {"running", "execution_finished", "verification_pending", "verification_running"}:
            running_count += 1
        elif status in {"verification_passed", "delivery_ready", "released", "completed"}:
            completed_count += 1
        elif status in {"verification_failed", "failed", "cancelled", "timed_out", "blocked", "problem"}:
            problem_count += 1

        if status in {"completed", "released", "verification_passed", "delivery_ready"}:
            artifact_count += 1

        fields = _task_summary_executor_fields(task)
        if fields:
            unique_fields = {field.lower() for field in fields}
            for field in unique_fields:
                executor_counts[field] += 1
                if status in {"running", "execution_finished", "verification_pending", "verification_running"}:
                    executor_running_counts[field] += 1
                if status in {"verification_failed", "failed", "cancelled", "timed_out", "blocked", "problem"}:
                    executor_blocked_counts[field] += 1

    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_tasks": len(tasks),
        "running_count": running_count,
        "completed_count": completed_count,
        "problem_count": problem_count,
        "artifact_count": artifact_count,
        "status_counts": dict(status_counts),
        "executor_counts": dict(executor_counts),
        "executor_running_counts": dict(executor_running_counts),
        "executor_blocked_counts": dict(executor_blocked_counts),
    }
    try:
        TASK_SUMMARY_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return payload


def _read_task_summary() -> dict:
    if _task_summary_cache_is_valid():
        cached = _read_json(TASK_SUMMARY_PATH, {})
        if isinstance(cached, dict) and cached:
            return cached
    return _compute_task_summary(_read_tasks())


def _task_status(task: dict, fallback: str = "queued") -> str:
    if not isinstance(task, dict):
        return fallback
    direct_values = [
        task.get("status"),
        task.get("state"),
        task.get("phase"),
        task.get("final_status"),
        task.get("verification_status"),
        task.get("delivery_status"),
        task.get("queue_status"),
        (task.get("lifecycle") or {}).get("status") if isinstance(task.get("lifecycle"), dict) else None,
        (task.get("result") or {}).get("status") if isinstance(task.get("result"), dict) else None,
    ]
    for value in direct_values:
        status = str(value or "").strip().lower().replace("-", "_")
        if not status or status in {"unknown", "n_a", "na"}:
            continue
        if status == "signal_only":
            return "signal-only"
        return status
    if task.get("completed_at") or task.get("finished_at") or task.get("ended_at") or task.get("released_at"):
        return "released" if task.get("released_at") else "completed"
    if task.get("started_at") or task.get("running_at") or task.get("execution_started_at"):
        return "running"
    result = task.get("result") or {}
    if isinstance(result, dict) and (result.get("summary") or result.get("output") or result.get("message")):
        return "completed"
    if isinstance(result, dict) and isinstance(result.get("artifacts"), list) and result.get("artifacts"):
        return "completed"
    if task.get("dispatch_now") or task.get("scheduled_by") or task.get("admission_mode"):
        return "queued"
    return fallback


def _task_by_id(task_id: str) -> dict | None:
    if not task_id:
        return None
    for task in _read_tasks():
        if isinstance(task, dict) and str(task.get("id") or "") == task_id:
            return task
    return None


def _task_signals(task: dict) -> list[dict]:
    if not isinstance(task, dict):
        return []
    signals = task.get("verification_signals")
    if isinstance(signals, list) and signals:
        return signals
    signals = task.get("signals")
    if isinstance(signals, list) and signals:
        return signals
    status = _task_status(task)
    result = task.get("result") or {}
    if status in {"failed", "cancelled", "timed_out"}:
        detail = ""
        if isinstance(result, dict):
            detail = str(result.get("checkpoint_error") or result.get("summary") or result.get("message") or "")
        return [
            {
                "code": status,
                "category": "runtime_blocker",
                "source": "task_record",
                "detail": detail or None,
                "effect": "observe_only",
                "affects_runtime": False,
                "affects_release": False,
                "affects_reporting": True,
                "whitelisted": False,
            }
        ]
    if status in {"completed", "released", "verification_passed", "delivery_ready"}:
        return [
            {
                "code": "task_completed",
                "category": "delivery",
                "source": "task_record",
                "detail": None,
                "effect": "observe_only",
                "affects_runtime": False,
                "affects_release": False,
                "affects_reporting": True,
                "whitelisted": True,
            }
        ]
    return [
        {
            "code": "task_pending",
            "category": "queue",
            "source": "task_record",
            "detail": None,
            "effect": "observe_only",
            "affects_runtime": False,
            "affects_release": False,
            "affects_reporting": True,
            "whitelisted": True,
        }
    ]


def _task_tree(task: dict) -> dict:
    plan = task.get("plan") if isinstance(task, dict) else []
    nodes = []
    edges = []
    if isinstance(plan, list) and plan:
        root_id = str(task.get("id") or "task-root")
        nodes.append({
            "id": root_id,
            "label": task.get("title") or task.get("goal") or task.get("prompt") or root_id,
            "type": "task",
            "status": _task_status(task),
        })
        for index, step in enumerate(plan):
            if not isinstance(step, dict):
                continue
            node_id = str(step.get("id") or f"step-{index}")
            nodes.append({
                "id": node_id,
                "label": step.get("title") or f"步骤 {index + 1}",
                "type": step.get("phase") or "step",
                "status": step.get("status") or "pending",
                "worker": step.get("worker"),
            })
            edges.append({"from": root_id, "to": node_id})
        return {"root": root_id, "nodes": nodes, "edges": edges}
    root_id = str(task.get("id") or "task-root")
    return {
        "root": root_id,
        "nodes": [
            {
                "id": root_id,
                "label": task.get("title") or task.get("goal") or task.get("prompt") or root_id,
                "type": "task",
                "status": _task_status(task),
            }
        ],
        "edges": [],
    }


def _task_graph(task: dict) -> dict:
    tree = _task_tree(task)
    return {
        "task_id": task.get("id"),
        "nodes": tree.get("nodes", []),
        "edges": tree.get("edges", []),
        "root": tree.get("root"),
    }


def _read_goal_backlog_preview(limit: int = 3) -> list[dict]:
    backlog = _read_goal_backlog_status()
    candidates = backlog.get("dispatch_candidates")
    if not isinstance(candidates, list):
        return []
    return [candidate for candidate in candidates[: max(0, limit)] if isinstance(candidate, dict)]


def _read_executor_registry() -> dict:
    registry = _read_json(EXECUTOR_REGISTRY_PATH, {})
    executors = registry.get("executors") if isinstance(registry, dict) else []
    if not isinstance(executors, list):
        executors = []
    default_executor_id = None
    for item in executors:
        if isinstance(item, dict) and item.get("enabled", True) is not False:
            default_executor_id = item.get("executor_id") or item.get("id") or item.get("name")
            if default_executor_id:
                break
    payload = dict(registry) if isinstance(registry, dict) else {}
    payload.setdefault("version", "v1")
    payload["executors"] = executors
    payload["routing_policy"] = {
        "default_executor_id": default_executor_id or "opencode_executor",
    }
    return payload


def _bootstrap_payload() -> dict:
    control_center = _read_control_center_state()
    factory_state = _read_factory_state()
    goal_backlog = _read_goal_backlog_status()
    executors = _read_executor_registry()
    task_summary = _read_task_summary()
    return {
        "control_center": {
            "paused": bool(control_center.get("paused")),
            "status": control_center.get("status") or "active",
            "updated_at": control_center.get("updated_at"),
            "reason": control_center.get("reason") or "",
            "resident": bool(control_center.get("resident", True)),
        },
        "factory_state": {
            "updated_at": factory_state.get("updated_at"),
            "daemon": factory_state.get("daemon") or {},
            "delivery_summary": factory_state.get("delivery_summary") or {},
            "control_layer": factory_state.get("control_layer") or {},
            "autonomy": factory_state.get("autonomy") or {},
            "release_ops": factory_state.get("release_ops") or {},
            "messages": factory_state.get("messages") or {},
            "task_runtime": factory_state.get("task_runtime") or {},
            "goal_primary": factory_state.get("goal_primary") or goal_backlog.get("goal_primary"),
            "goal_mode": factory_state.get("goal_mode") or goal_backlog.get("goal_mode"),
        },
        "goal_backlog": {
            "updated_at": goal_backlog.get("updated_at"),
            "goal_primary": goal_backlog.get("goal_primary"),
            "goal_mode": goal_backlog.get("goal_mode"),
            "goal_health": goal_backlog.get("goal_health"),
        },
        "goal_backlog_preview": _read_goal_backlog_preview(),
        "task_summary": task_summary,
        "executors": executors.get("executors") or [],
        "executor_registry": executors,
    }


def _content_type_for(path: Path) -> str:
    if path.suffix == ".js":
        return "application/javascript; charset=utf-8"
    if path.suffix == ".css":
        return "text/css; charset=utf-8"
    if path.suffix == ".svg":
        return "image/svg+xml"
    if path.suffix == ".json":
        return "application/json; charset=utf-8"
    if path.suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/api/bootstrap", timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False


def _launch_backend() -> None:
    if _backend_healthy():
        return
    with BACKEND_LOCK:
        if _backend_healthy():
            return
        env = os.environ.copy()
        env["ORCH_NETWORK_AGENT_ENABLED"] = "false"
        backend_cmd = [str(PYTHON), str(BACKEND_SCRIPT)]
        subprocess.Popen(
            backend_cmd,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        deadline = time.time() + 8
        while time.time() < deadline:
            if _backend_healthy():
                return
            time.sleep(0.2)


def _proxy_request(handler: BaseHTTPRequestHandler) -> None:
    target_url = f"{BACKEND_URL}{handler.path}"
    method = handler.command or "GET"
    headers = {
        key: value
        for key, value in handler.headers.items()
        if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
    }
    body = None
    length = int(handler.headers.get("Content-Length") or 0)
    if length > 0:
        body = handler.rfile.read(length)
    request = urllib.request.Request(target_url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = response.read()
            handler.send_response(response.status)
            content_type = response.headers.get("Content-Type")
            if content_type:
                handler.send_header("Content-Type", content_type)
            for key, value in response.headers.items():
                if key.lower() in {"content-type", "content-length", "transfer-encoding", "connection"}:
                    continue
                handler.send_header(key, value)
            handler.send_header("Content-Length", str(len(payload)))
            handler.end_headers()
            handler.wfile.write(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read() if exc.fp else b""
        handler.send_response(exc.code)
        handler.send_header("Content-Type", exc.headers.get("Content-Type", "application/json; charset=utf-8"))
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        if payload:
            handler.wfile.write(payload)
    except Exception:
        payload = json.dumps(
            {
                "detail": "后端仍在启动或暂时不可用",
                "backend": BACKEND_URL,
                "path": handler.path,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        handler.send_response(HTTPStatus.SERVICE_UNAVAILABLE)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


class FrontDoorHandler(BaseHTTPRequestHandler):
    server_version = "MetaForgeFrontDoor/1.0"

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch()

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch()

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch()

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch()

    def _dispatch(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/" or path == "":
            self._serve_index()
            return
        if path == "/api/bootstrap":
            self._serve_json(_bootstrap_payload())
            return
        if path == "/api/control-center/status":
            self._serve_json(_lightweight_control_center_status())
            return
        if path == "/api/stats":
            self._serve_json(_lightweight_stats())
            return
        if path == "/api/tasks":
            self._serve_json(_read_tasks())
            return
        if path.startswith("/api/tasks/"):
            parts = path.split("/")
            task_id = parts[3] if len(parts) >= 4 else ""
            tail = "/".join(parts[4:])
            task = _task_by_id(task_id)
            if task is None:
                self.send_response(HTTPStatus.NOT_FOUND)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                payload = json.dumps({"detail": "Task not found", "task_id": task_id}, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if tail == "" or tail == "/":
                self._serve_json(task)
                return
            if tail == "tree":
                self._serve_json(_task_tree(task))
                return
            if tail == "verification-signals":
                self._serve_json({"signals": _task_signals(task)})
                return
            if tail == "graph":
                self._serve_json(_task_graph(task))
                return
        if path == "/api/executors":
            self._serve_json(_read_executor_registry())
            return
        if path == "/api/health":
            self._serve_json(_lightweight_health())
            return
        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if path.startswith("/static/"):
            self._serve_static(path)
            return
        if path.startswith("/api/"):
            _proxy_request(self)
            return
        self.send_response(HTTPStatus.NOT_FOUND)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        payload = json.dumps({"detail": "Not Found"}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_json(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        rel_path = path.removeprefix("/static/").lstrip("/")
        file_path = (STATIC_DIR / rel_path).resolve()
        if not file_path.exists() or STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        data = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _content_type_for(file_path))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_index(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        asset_version = str(int((STATIC_DIR / "app.js").stat().st_mtime))
        html = html.replace("/static/app.js", f"/static/app.js?v={asset_version}")
        html = html.replace("/static/styles.css", f"/static/styles.css?v={asset_version}")
        injection = f"<script>window.__FACTORY_BOOTSTRAP__ = {json.dumps(_bootstrap_payload(), ensure_ascii=False)};</script>"
        if "</head>" in html:
            html = html.replace("</head>", f"{injection}\n</head>", 1)
        else:
            html = f"{injection}\n{html}"
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _lightweight_control_center_status() -> dict:
    bootstrap = _bootstrap_payload()
    control = bootstrap["control_center"]
    factory = bootstrap["factory_state"]
    return {
        **control,
        "delivery_summary": factory.get("delivery_summary") or {},
        "goal_backlog": bootstrap["goal_backlog"],
        "goal_backlog_preview": bootstrap["goal_backlog_preview"],
        "network": {"status": "disabled", "queue_size": 0},
        "stats": {
            "completed_tasks": int((factory.get("delivery_summary") or {}).get("completed_tasks") or 0),
            "delivery_ready_tasks": int((factory.get("delivery_summary") or {}).get("delivery_ready_tasks") or 0),
            "released_tasks": int((factory.get("delivery_summary") or {}).get("released_tasks") or 0),
            "verification_failed_tasks": int((factory.get("delivery_summary") or {}).get("verification_failed_tasks") or 0),
        },
        "goal_storage": {"status": "cached"},
        "integrations": {"configured": False, "complete": False, "summary": {}, "updated_at": None},
    }


def _lightweight_stats() -> dict:
    bootstrap = _bootstrap_payload()
    factory = bootstrap["factory_state"]
    delivery = factory.get("delivery_summary") or {}
    return {
        "completed_tasks": int(delivery.get("completed_tasks") or 0),
        "delivery_ready_tasks": int(delivery.get("delivery_ready_tasks") or 0),
        "released_tasks": int(delivery.get("released_tasks") or 0),
        "verification_failed_tasks": int(delivery.get("verification_failed_tasks") or 0),
        "control_center": bootstrap["control_center"],
        "goal_backlog": bootstrap["goal_backlog"],
        "task_summary": bootstrap.get("task_summary") or {},
        "executors": bootstrap["executors"],
    }


def _lightweight_health() -> dict:
    bootstrap = _bootstrap_payload()
    factory = bootstrap["factory_state"]
    executors = bootstrap["executors"]
    return {
        "status": "ok",
        "real_execution_enabled": False,
        "approval_mode": "observer",
        "shell_backend": "embedded",
        "cheap_llm_configured": False,
        "planner_configured": False,
        "llm_gateway": {
            "cheap_base_url": None,
            "planner_base_url": None,
            "planner_api_style": None,
            "shared_gateway": False,
            "cheap_local_gateway": False,
            "planner_local_gateway": False,
        },
        "resource_count": 0,
        "repo_count": 0,
        "project_count": 0,
        "capability_count": 0,
        "core_message_count": 0,
        "goal_storage": {"status": "cached"},
        "integrations": {"configured": False, "complete": False, "summary": {}, "updated_at": None},
        "policy_version": factory.get("control_layer", {}).get("policy_version", "local"),
        "cheap_max_calls_per_task": 0,
        "cheap_max_chars_per_task": 0,
        "cheap_max_output_chars": 0,
        "cheap_request_timeout_seconds": 0,
        "planner_request_timeout_seconds": 0,
        "max_escalations_per_task": 0,
        "denied_command_pattern_count": 0,
        "network_agent_enabled": False,
        "network_agent_status": "disabled",
        "external_queue_size": 0,
        "current_proxy": None,
        "provider_gateway": {"status": "disabled"},
        "executors": executors,
    }


def main() -> None:
    threading.Thread(target=_launch_backend, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", FRONTDOOR_PORT), FrontDoorHandler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
