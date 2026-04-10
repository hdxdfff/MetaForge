from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

OUT = DATA / "coordination_runtime.json"
TASKS = DATA / "cross_project_tasks.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def run_coordination(selected: list[dict[str, Any]], *, target: str | None = None, limit: int = 3) -> dict[str, Any]:
    registry = _load_json(TASKS, {"items": []})
    items = registry.get("items", [])
    created: list[str] = []
    completed: list[str] = []

    for item in selected[:limit]:
        if target and str(item.get("target") or "").strip().lower() != target.strip().lower():
            continue
        coordination_id = item.get("coordination_id")
        if not coordination_id:
            continue
        existing = next((entry for entry in items if entry.get("coordination_id") == coordination_id), None)
        if existing is None:
            existing = {
                "coordination_id": coordination_id,
                "target": item.get("target"),
                "projects": item.get("projects", []),
                "departments": item.get("departments", []),
                "work_packages": item.get("work_packages", []),
                "status": "running",
                "created_at": _utc(),
            }
            items.append(existing)
            created.append(coordination_id)
        existing["status"] = "completed"
        existing["completed_at"] = _utc()
        existing["updated_at"] = _utc()
        completed.append(coordination_id)

    registry["items"] = items
    registry["updated_at"] = _utc()
    _save_json(TASKS, registry)
    payload = {
        "updated_at": _utc(),
        "status": "completed" if completed else "idle",
        "created": created,
        "completed": completed,
        "completed_count": len(completed),
        "task_count": len(items),
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_coordination([]), ensure_ascii=False, indent=2))
