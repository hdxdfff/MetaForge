from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.amplifier_observability import record_run
from tools.execution_trace import append_trace
from tools.io_utils import atomic_write_json

QUEUE_PATH = DATA / "p2_sandbox_queue.json"
STATUS_PATH = DATA / "p2_sandbox_status.json"
INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"

TEMPLATES = [
    ("doc-generation", "draft a control-plane doc patch", "Prepare a small documentation patch for the autonomy control plane.", "doc_patch"),
    ("test-completion", "complete a missing test case", "Add or complete a minimal test case for a small validation gap.", "unit_test_run"),
    ("build-verify", "build and verify a small bundle", "Build and verify a small low-risk technical bundle in sandbox.", "build_fix"),
    ("issue-decomposition", "decompose an issue into patch steps", "Break a small issue into concrete patch steps and validation notes.", "report_refresh"),
    ("patch-proposal", "draft a patch proposal", "Draft a bounded patch proposal with validation and rollback notes.", "manifest_patch"),
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
    queue.setdefault("version", 1)
    return queue


def _industrial_operations() -> dict[str, Any]:
    payload = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _sandbox_allowed() -> bool:
    operations = _industrial_operations()
    gates = (operations.get("budget_control") or {}).get("gates") or {}
    if isinstance(gates, dict) and gates.get("allow_p2_sandbox") is False:
        return False
    return True


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
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    for slug, title, goal, task_type in TEMPLATES[:1]:
        items.append(
            {
                "id": f"p2s_{stamp}_{slug}",
                "task_type": task_type,
                "category": "p2_sandbox_low_risk",
                "amplifier": "p2_sandbox_task_generator",
                "budget_pool": "P2",
                "sandbox_lane": "p2_low_risk",
                "admission_lane": "sandbox_low_risk",
                "growth_type": slug,
                "title": title,
                "goal": goal,
                "expected_outcome": "small low-risk sandbox task with manifest and validation evidence",
                "verification_plan": ["py_compile", "self-test", "status refresh"],
                "priority": "low",
                "status": "open",
                "created_at": _utc(),
            }
        )
    return items


def run_p2_sandbox_task_generator() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    queue = _queue_state()
    open_items = _dedupe(list(queue.get("open_items") or []))
    existing_titles = _existing_titles(queue)
    allowed = _sandbox_allowed()
    created = 0
    skipped_due_to_gate = 0
    for item in _build_items():
        if item["title"] in existing_titles:
            continue
        if not allowed:
            skipped_due_to_gate += 1
            continue
        open_items.append(item)
        existing_titles.add(item["title"])
        created += 1
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)

    record_run(
        "p2_sandbox_task_generator",
        generated_tasks=created,
        entered_execution=0,
        completed_tasks=0,
        trigger_count=1,
        metadata={"queue_path": str(QUEUE_PATH), "sandbox_gate": allowed},
    )
    report = {
        "updated_at": _utc(),
        "status": "pass" if allowed else "budget_closed",
        "created_items": created,
        "open_items_total": len(open_items),
        "skipped_due_to_gate": skipped_due_to_gate,
        "queue_path": str(QUEUE_PATH),
        "sandbox_gate": {
            "allow_p2_sandbox": allowed,
            "source": str(INDUSTRIAL_OPERATIONS_PATH),
        },
    }
    atomic_write_json(STATUS_PATH, report)
    append_trace(
        "industrial-readiness",
        "generate p2 sandbox tasks",
        "run p2_sandbox_task_generator.py",
        f"created={created}",
        "queue low-risk P2 sandbox tasks for execution",
        worker="cheap-worker",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"queue_path": str(QUEUE_PATH), "created_items": created},
    )
    return report


def main() -> int:
    _ = argparse.ArgumentParser(description="Generate a low-risk P2 sandbox task queue.").parse_args()
    print(json.dumps(run_p2_sandbox_task_generator(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
