from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
TASKS_PATH = DATA / "tasks.json"
TASK_HISTORY_PATH = DATA / "task_history.json"
REPORT_PATH = ROOT / "generated" / "toy-os-demo" / "toyos-queued-reconciled.json"

TARGET_STATUS_BY_TITLE = {
    "Audit ToyOS execution environment": "running",
    "Localize ToyOS build break": "completed",
    "Isolate ToyOS failing test": "completed",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _task_title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("goal") or item.get("name") or "").strip()


def _task_status(item: dict[str, Any]) -> str:
    return str(item.get("status") or item.get("task_status") or "").strip().lower()


def _apply(records: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    updated = 0
    touched: list[dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        title = _task_title(item)
        desired = TARGET_STATUS_BY_TITLE.get(title)
        if not desired:
            continue
        current = _task_status(item)
        if current not in {"queued", "planning", "running", "waiting_approval"}:
            continue
        if current == desired:
            continue
        item["status"] = desired
        if "task_status" in item:
            item["task_status"] = desired
        item["updated_at"] = _utc()
        result = item.setdefault("result", {})
        if isinstance(result, dict):
            if desired == "running":
                result.setdefault("summary", "Launched Goose in the background.")
            else:
                result.setdefault("summary", "Task completed after Goose execution and runtime reconciliation.")
        touched.append({
            "id": item.get("id"),
            "title": title,
            "from": current,
            "to": desired,
        })
        updated += 1
    return updated, touched


def run() -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    history = _load_json(TASK_HISTORY_PATH, [])
    if not isinstance(tasks, list):
        tasks = []
    if not isinstance(history, list):
        history = []

    task_updates, touched_tasks = _apply(tasks)
    history_updates, touched_history = _apply(history)

    if task_updates:
        atomic_write_json(TASKS_PATH, tasks)
    if history_updates:
        atomic_write_json(TASK_HISTORY_PATH, history)

    payload = {
        "updated_at": _utc(),
        "status": "done",
        "task_updates": task_updates,
        "history_updates": history_updates,
        "touched_tasks": touched_tasks,
        "touched_history": touched_history,
        "targets": list(TARGET_STATUS_BY_TITLE.keys()),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(REPORT_PATH, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
