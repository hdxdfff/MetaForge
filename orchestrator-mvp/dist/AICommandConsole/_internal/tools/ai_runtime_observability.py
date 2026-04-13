from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.execution_trace import read_tail
from tools.factory_event_log import read_events
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AI_ROOT = DATA / "ai"
AI_STATE_PATH = DATA / "ai_runtime_state.json"

TASKS_PATH = DATA / "tasks.json"
FACTORY_STATE_PATH = DATA / "factory_state.json"
STATUS_CACHE_PATH = DATA / "status_cache.json"
ECONOMICS_PATH = DATA / "economics_engine_status.json"
SELF_MODEL_PATH = DATA / "self_model_runtime.json"
CONTROL_PATH = DATA / "control_layer_status.json"
AI_TEST_PATH = DATA / "ai_test_status.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            time.sleep(0.1 * (attempt + 1))
        except Exception:
            return default
    return default


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _task_progress(task: dict[str, Any]) -> int:
    plan = task.get("plan") or []
    if plan:
        completed = sum(1 for step in plan if step.get("status") in {"completed", "done", "success"})
        return int(round((completed / max(len(plan), 1)) * 100))
    status = str(task.get("status") or "")
    if status in {"completed", "success"}:
        return 100
    if status in {"running", "planning"}:
        return 50
    return 0


def _task_rows(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        rows.append(
            {
                "task_id": task.get("id"),
                "title": task.get("title") or task.get("goal") or task.get("prompt"),
                "type": task.get("goal_type") or task.get("type") or "task",
                "status": task.get("status"),
                "progress": _task_progress(task),
                "repo_path": task.get("repo_path"),
                "goal": task.get("goal"),
                "goal_id": task.get("goal_id") or ((task.get("scheduler_hint") or {}).get("goal_id")),
                "node_id": task.get("node_id") or ((task.get("scheduler_hint") or {}).get("node_id")),
                "updated_at": task.get("updated_at"),
            }
        )
    rows.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return rows


def _agent_rows(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    active_statuses = {"queued", "planning", "running", "waiting_approval"}
    for task in tasks:
        if task.get("status") not in active_statuses:
            continue
        running_steps = [step for step in (task.get("plan") or []) if step.get("status") == "running"]
        waiting_steps = [step for step in (task.get("plan") or []) if step.get("status") in {"queued", "pending", "waiting"}]
        if running_steps:
            for idx, step in enumerate(running_steps, start=1):
                rows.append(
                    {
                        "agent_id": f"{task.get('id')}:{step.get('worker') or 'worker'}:{idx}",
                        "name": step.get("worker") or "worker",
                        "status": "running",
                        "task_id": task.get("id"),
                        "phase": step.get("phase"),
                        "step_title": step.get("title"),
                        "model": (task.get("cheap_lane") or {}).get("model"),
                        "repo_path": task.get("repo_path"),
                    }
                )
        elif waiting_steps:
            step = waiting_steps[0]
            rows.append(
                {
                    "agent_id": f"{task.get('id')}:{step.get('worker') or 'worker'}",
                    "name": step.get("worker") or "worker",
                    "status": "waiting",
                    "task_id": task.get("id"),
                    "phase": step.get("phase"),
                    "step_title": step.get("title"),
                    "model": (task.get("cheap_lane") or {}).get("model"),
                    "repo_path": task.get("repo_path"),
                }
            )
        else:
            rows.append(
                {
                    "agent_id": f"{task.get('id')}:supervisor",
                    "name": "supervisor",
                    "status": task.get("status"),
                    "task_id": task.get("id"),
                    "phase": task.get("status"),
                    "step_title": task.get("goal") or task.get("title"),
                    "model": (task.get("cheap_lane") or {}).get("model"),
                    "repo_path": task.get("repo_path"),
                }
            )
    rows.sort(key=lambda item: (item.get("status") != "running", item.get("task_id") or ""))
    return rows


def _tool_rows(events: list[dict[str, Any]], traces: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        rows.append(
            {
                "id": event.get("event_id"),
                "timestamp": event.get("timestamp"),
                "source": "factory_event",
                "tool": event.get("source"),
                "action": event.get("type"),
                "status": event.get("severity"),
                "summary": event.get("summary"),
            }
        )
    for idx, trace in enumerate(traces, start=1):
        rows.append(
            {
                "id": f"trace_{idx}",
                "timestamp": trace.get("timestamp"),
                "source": "execution_trace",
                "tool": trace.get("worker"),
                "action": trace.get("action"),
                "status": trace.get("level"),
                "summary": trace.get("result"),
            }
        )
    rows.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return rows[:limit]


def _reasoning_rows(traces: list[dict[str, Any]], self_model: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if self_model:
        rows.append(
            {
                "source": "self_model",
                "timestamp": self_model.get("updated_at"),
                "decision": self_model.get("goal"),
                "reason_summary": self_model.get("reflection_summary"),
                "inputs_used": ["factory_state", "status_cache", "task_runtime"],
                "confidence": None,
                "next_action": (self_model.get("next_actions") or [None])[0],
                "mode": self_model.get("mode"),
                "blockers": self_model.get("blockers") or [],
            }
        )
    for trace in traces[-20:]:
        rows.append(
            {
                "source": trace.get("phase"),
                "timestamp": trace.get("timestamp"),
                "decision": trace.get("action"),
                "reason_summary": trace.get("reason"),
                "inputs_used": [],
                "confidence": None,
                "next_action": trace.get("next"),
                "mode": trace.get("level"),
                "blockers": [],
            }
        )
    rows.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return rows[:20]


def _recent_task_rate(events: list[dict[str, Any]], *, window_minutes: int = 15) -> float:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    task_events = 0
    for event in events:
        ts = _parse_ts(event.get("timestamp"))
        if ts and ts >= cutoff and str(event.get("type") or "").startswith("daemon.tick"):
            task_events += 1
    return round(task_events / max(window_minutes, 1), 2)


def _metrics_payload(tasks: list[dict[str, Any]], events: list[dict[str, Any]], factory_state: dict[str, Any], economics: dict[str, Any]) -> dict[str, Any]:
    total = len(tasks)
    completed = sum(1 for item in tasks if item.get("status") == "completed")
    failed = sum(1 for item in tasks if item.get("status") in {"failed", "timed_out", "cancelled"})
    active = sum(1 for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"})
    error_events = [item for item in events if item.get("severity") == "error"]
    return {
        "updated_at": _utc(),
        "task_rate_per_min": _recent_task_rate(events),
        "success_rate": round((completed / total), 4) if total else 0.0,
        "error_rate": round((len(error_events) / len(events)), 4) if events else 0.0,
        "queue_depth": active,
        "task_total": total,
        "task_completed": completed,
        "task_failed": failed,
        "cost_today": ((economics.get("currency_system") or {}).get("usage") or {}),
        "completed_value_mfc": ((economics.get("ai_gdp") or {}).get("completed_value_mfc")),
        "consistency_status": (factory_state.get("consistency") or {}).get("status"),
    }


def _system_payload(factory_state: dict[str, Any], status_cache: dict[str, Any], economics: dict[str, Any]) -> dict[str, Any]:
    control = factory_state.get("control_layer") or _load_json(CONTROL_PATH, {})
    ai_testing = factory_state.get("ai_testing") or _load_json(AI_TEST_PATH, {})
    release_ops = factory_state.get("release_ops") or _load_json(RELEASE_OPS_PATH, {})
    return {
        "updated_at": _utc(),
        "daemon": factory_state.get("daemon") or {},
        "control_layer": control,
        "engineering_os": factory_state.get("engineering_os") or ((control.get("engineering_os") or {}) if isinstance(control, dict) else {}),
        "autonomy": factory_state.get("autonomy") or {},
        "tool_health": factory_state.get("tool_health") or {},
        "ai_testing": ai_testing,
        "release_ops": release_ops,
        "self_model": status_cache.get("self_model") or {},
        "economics": {
            "status": economics.get("status"),
            "score": economics.get("score"),
            "summary": economics.get("summary") or {},
        },
    }


def _trace_payload(events: list[dict[str, Any]], traces: list[dict[str, Any]]) -> dict[str, Any]:
    recent = []
    for event in events[-40:]:
        recent.append(
            {
                "timestamp": event.get("timestamp"),
                "kind": "event",
                "source": event.get("source"),
                "action": event.get("type"),
                "summary": event.get("summary"),
                "status": event.get("severity"),
            }
        )
    for trace in traces[-40:]:
        recent.append(
            {
                "timestamp": trace.get("timestamp"),
                "kind": "trace",
                "source": trace.get("worker"),
                "action": trace.get("action"),
                "summary": trace.get("reason"),
                "status": trace.get("level"),
            }
        )
    recent.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return {
        "updated_at": _utc(),
        "recent": recent[:60],
    }


def build_ai_runtime_state() -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    factory_state = _load_json(FACTORY_STATE_PATH, {})
    status_cache = _load_json(STATUS_CACHE_PATH, {})
    economics = _load_json(ECONOMICS_PATH, {})
    self_model = _load_json(SELF_MODEL_PATH, {})
    events = read_events(limit=200)
    traces = read_tail(limit=200)

    task_rows = _task_rows(tasks)
    agent_rows = _agent_rows(tasks)
    tool_rows = _tool_rows(events, traces)
    reasoning_rows = _reasoning_rows(traces, self_model)

    return {
        "updated_at": _utc(),
        "root": "/ai",
        "paths": {
            "tasks": "/ai/tasks",
            "agents": "/ai/agents",
            "tools": "/ai/tools",
            "reasoning": "/ai/reasoning",
            "metrics": "/ai/metrics",
            "system": "/ai/system",
            "traces": "/ai/traces",
        },
        "tasks": {
            "count": len(task_rows),
            "active_count": sum(1 for item in task_rows if item.get("status") in {"queued", "planning", "running", "waiting_approval"}),
            "rows": task_rows,
        },
        "agents": {
            "count": len(agent_rows),
            "running_count": sum(1 for item in agent_rows if item.get("status") == "running"),
            "rows": agent_rows,
        },
        "tools": {
            "count": len(tool_rows),
            "rows": tool_rows,
        },
        "reasoning": {
            "count": len(reasoning_rows),
            "rows": reasoning_rows,
        },
        "metrics": _metrics_payload(tasks, events, factory_state, economics),
        "system": _system_payload(factory_state, status_cache, economics),
        "traces": _trace_payload(events, traces),
    }


def publish_ai_runtime_state() -> dict[str, Any]:
    payload = build_ai_runtime_state()
    AI_ROOT.mkdir(parents=True, exist_ok=True)
    atomic_write_json(AI_ROOT / "tasks.json", payload["tasks"])
    atomic_write_json(AI_ROOT / "agents.json", payload["agents"])
    atomic_write_json(AI_ROOT / "tools.json", payload["tools"])
    atomic_write_json(AI_ROOT / "reasoning.json", payload["reasoning"])
    atomic_write_json(AI_ROOT / "metrics.json", payload["metrics"])
    atomic_write_json(AI_ROOT / "system.json", payload["system"])
    atomic_write_json(AI_ROOT / "traces.json", payload["traces"])
    atomic_write_json(AI_STATE_PATH, payload)
    return payload


def load_ai_runtime_state(refresh: bool = False) -> dict[str, Any]:
    if refresh or not AI_STATE_PATH.exists():
        return publish_ai_runtime_state()
    return _load_json(AI_STATE_PATH, {})


def _task_by_id(payload: dict[str, Any], task_id: str) -> dict[str, Any] | None:
    for item in ((payload.get("tasks") or {}).get("rows") or []):
        if item.get("task_id") == task_id:
            return item
    return None


def resolve_ai_path(path: str, *, refresh: bool = False) -> Any:
    payload = load_ai_runtime_state(refresh=refresh)
    normalized = (path or "/ai").strip()
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized.rstrip("/") in {"", "/ai"}:
        return payload
    parts = [part for part in normalized.strip("/").split("/") if part]
    if not parts or parts[0] != "ai":
        raise KeyError(f"Unknown AI path: {path}")
    if len(parts) == 2:
        key = parts[1]
        if key not in payload:
            raise KeyError(f"Unknown AI path: {path}")
        return payload[key]
    if len(parts) == 3 and parts[1] == "tasks":
        item = _task_by_id(payload, parts[2])
        if item is None:
            raise KeyError(f"Task not found: {parts[2]}")
        return item
    raise KeyError(f"Unknown AI path: {path}")

