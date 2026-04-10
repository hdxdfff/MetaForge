from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.amplifier_observability import record_run
from tools.execution_trace import append_trace

QUEUE_PATH = DATA / "artifact_growth_queue.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"

TEMPLATES = [
    ("validator-demo", "build a validator demo", "Add a runnable validator demo that can self-test and emit an artifact manifest."),
    ("report-exporter", "build a report exporter", "Add a runnable report exporter that summarizes live status into a portable report bundle."),
    ("replay-utility", "build a replay utility", "Add a runnable replay utility that can reproduce a small recent event trace."),
    ("smoke-harness", "build a smoke harness", "Add a runnable smoke harness for local validation of a small technical bundle."),
    ("scaffold-bundle", "build a scaffold bundle", "Add a runnable scaffold bundle that produces a minimal real artifact directory."),
]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _queue_state() -> dict[str, Any]:
    queue = _load_json(QUEUE_PATH, {})
    if not isinstance(queue, dict):
        queue = {}
    for key in ("open_items", "in_progress_items", "done_items", "failed_items"):
        queue.setdefault(key, [])
    return queue


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _existing_titles(queue: dict[str, Any]) -> set[str]:
    titles: set[str] = set()
    for section in ("open_items", "in_progress_items", "done_items", "failed_items"):
        for item in queue.get(section) or []:
            if isinstance(item, dict) and item.get("title"):
                titles.add(str(item["title"]))
    return titles


def _build_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for slug, title, goal in TEMPLATES:
        items.append({
            "id": f"ag_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{slug}_{uuid4().hex[:6]}",
            "task_type": "technical_artifact",
            "category": "artifact_growth",
            "amplifier": "artifact_growth_task_generator",
            "growth_type": slug,
            "title": title,
            "goal": goal,
            "expected_outcome": "new real artifact directory with manifest and validation evidence",
            "verification_plan": ["py_compile", "self-test", "artifact registry refresh"],
            "priority": "medium",
            "status": "open",
            "created_at": _utc(),
        })
    return items


def run_artifact_growth_task_generator() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    queue = _queue_state()
    open_items = _dedupe(list(queue.get("open_items") or []))
    existing_titles = _existing_titles(queue)
    created = 0
    for item in _build_items():
        if str(item.get("title") or "") in existing_titles:
            continue
        open_items.append(item)
        existing_titles.add(str(item.get("title") or ""))
        created += 1
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)
    record_run(
        "artifact_growth_task_generator",
        generated_tasks=created,
        entered_execution=0,
        completed_tasks=0,
        trigger_count=1,
        metadata={"queue_path": str(QUEUE_PATH), "registry_path": str(ARTIFACT_REGISTRY_PATH)},
    )
    append_trace(
        "industrial-readiness",
        "generate artifact growth tasks",
        "run artifact_growth_task_generator.py",
        f"created={created}",
        "queue artifact growth tasks for execution",
        worker="cheap-worker",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"queue_path": str(QUEUE_PATH), "created_items": created},
    )
    return {
        "updated_at": _utc(),
        "status": "pass",
        "created_items": created,
        "open_items_total": len(open_items),
        "queue_path": str(QUEUE_PATH),
        "registry_path": str(ARTIFACT_REGISTRY_PATH),
    }


def main() -> int:
    _ = argparse.ArgumentParser(description="Generate minimal real artifact tasks on a periodic basis.").parse_args()
    print(json.dumps(run_artifact_growth_task_generator(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
