from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.execution_trace import append_trace
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
RUNTIME_TASKS = ROOT / "factory" / "runtime" / "tasks"
TASKS_PATH = DATA / "tasks.json"
TASK_HISTORY_PATH = DATA / "task_history.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _task_id(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("task_id") or "").strip()


def _normalize_status(context: dict[str, Any], current_status: str) -> str | None:
    raw_status = str(context.get("task_status") or context.get("status") or "").strip().lower()
    phase = str(context.get("phase") or "").strip().lower()
    error = context.get("error")
    if not raw_status:
        return None
    if raw_status == "running" and (phase.startswith("step-failed") or error):
        return "failed"
    if raw_status in {"completed", "delivery_ready", "released", "failed", "timed_out", "cancelled"}:
        return raw_status
    if raw_status == "running":
        if current_status in {"completed", "delivery_ready", "released"} and (phase.startswith("step-failed") or error):
            return "failed"
        return "running"
    return raw_status


def _context_payload(task_id: str) -> dict[str, Any] | None:
    path = RUNTIME_TASKS / task_id / "context.json"
    if not path.exists():
        return None
    payload = _load_json(path, {})
    return payload if isinstance(payload, dict) else None


def _apply_status_updates(records: list[dict[str, Any]], context_map: dict[str, dict[str, Any]]) -> tuple[int, list[str]]:
    updated = 0
    updated_ids: list[str] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        task_id = _task_id(item)
        if not task_id:
            continue
        context = context_map.get(task_id)
        if not context:
            continue
        current_status = str(item.get("status") or item.get("task_status") or "").strip().lower()
        desired = _normalize_status(context, current_status)
        if not desired or desired == current_status:
            continue
        item["status"] = desired
        if "task_status" in item:
            item["task_status"] = desired
        updated_at = str(context.get("updated_at") or context.get("heartbeat_at") or _utc())
        item["updated_at"] = updated_at
        if "heartbeat_at" in item or context.get("heartbeat_at"):
            item["heartbeat_at"] = str(context.get("heartbeat_at") or updated_at)
        if desired in {"failed", "timed_out", "cancelled"}:
            result = item.setdefault("result", {})
            if isinstance(result, dict):
                result.setdefault("summary", str(context.get("error") or context.get("title") or "Context-reconciled terminal task."))
                if context.get("error") and not result.get("error"):
                    result["error"] = context.get("error")
        elif desired == "running":
            result = item.setdefault("result", {})
            if isinstance(result, dict):
                result.setdefault("summary", str(context.get("title") or context.get("goal") or "Context-reconciled running task."))
        updated += 1
        updated_ids.append(task_id)
    return updated, updated_ids


def run_reconcile_task_status_from_context() -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    history = _load_json(TASK_HISTORY_PATH, [])
    if not isinstance(tasks, list):
        tasks = []
    if not isinstance(history, list):
        history = []

    context_map: dict[str, dict[str, Any]] = {}
    for path in RUNTIME_TASKS.iterdir() if RUNTIME_TASKS.exists() else []:
        if not path.is_dir():
            continue
        context = _context_payload(path.name)
        if context:
            context_map[path.name] = context

    task_updates, task_ids = _apply_status_updates(tasks, context_map)
    history_updates, history_ids = _apply_status_updates(history, context_map)

    if task_updates:
        atomic_write_json(TASKS_PATH, tasks)
    if history_updates:
        atomic_write_json(TASK_HISTORY_PATH, history)

    payload = {
        "updated_at": _utc(),
        "status": "done",
        "task_updates": task_updates,
        "history_updates": history_updates,
        "updated_task_ids": task_ids,
        "updated_history_ids": history_ids,
        "context_count": len(context_map),
    }
    append_trace(
        "task-reconcile",
        "reconcile task status from runtime context",
        "run reconcile_task_status_from_context.py",
        f"task_updates={task_updates} history_updates={history_updates}",
        "refresh task metrics",
        worker="maintenance",
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(run_reconcile_task_status_from_context(), ensure_ascii=False, indent=2))
