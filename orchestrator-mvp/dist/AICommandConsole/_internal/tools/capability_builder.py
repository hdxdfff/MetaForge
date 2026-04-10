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

QUEUE_PATH = DATA / "capability_build_queue.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
CONTINUITY_METRICS_PATH = DATA / "continuity_metrics.json"
STAGE5_HISTORY_PATH = DATA / "stage5_metrics_history.json"


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


def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _existing_open_ids(queue: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in queue.get("open_items") or []:
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids


def _artifact_registry() -> dict[str, Any]:
    registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    return registry if isinstance(registry, dict) else {}


def _open_capability_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    registry = _artifact_registry()
    if str(registry.get("status") or "").lower() == "pass" and int(registry.get("issue_count") or 0) > 0:
        items.append(
            {
                "id": f"cap_{datetime.now(timezone.utc).strftime('%Y%m%d')}_validator_{uuid4().hex[:6]}",
                "category": "artifact_regression",
                "trigger": {
                    "source": "artifact_registry.json",
                    "signal": "registry_has_issues_but_no_dedicated_regression_bundle",
                },
                "goal": "Add a dedicated regression validator for generated technical artifact bundles.",
                "proposed_action": {
                    "type": "new_validator",
                    "target": "tools/artifact_regression_validator.py",
                },
                "status": "open",
                "created_at": _utc(),
            }
        )
    items.append(
        {
            "id": f"cap_{datetime.now(timezone.utc).strftime('%Y%m%d')}_ledger_{uuid4().hex[:6]}",
            "category": "transition_ledger",
            "trigger": {
                "source": "stage5_evaluator",
                "signal": "blocked_to_done_conversion_pending_transition_ledger",
            },
            "goal": "Add a durable blocked-to-done transition ledger so productivity trend can be measured without inference.",
            "proposed_action": {
                "type": "new_ledger",
                "target": "D:\\codex\\orchestrator-mvp\\data\\blocked_to_done_transitions.json",
            },
            "status": "open",
            "created_at": _utc(),
        }
    )
    return items


def run_capability_builder() -> dict[str, Any]:
    queue = _queue_state()
    open_items = _normalize_items(list(queue.get("open_items") or []))
    open_ids = _existing_open_ids(queue)
    created_items = _open_capability_items()
    for item in created_items:
        if item["id"] not in open_ids:
            open_items.append(item)
            open_ids.add(item["id"])
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)

    return {
        "updated_at": _utc(),
        "status": "pass",
        "open_items_created": len(created_items),
        "open_items_total": len(open_items),
        "queue_path": str(QUEUE_PATH),
        "contingency_inputs": [
            str(ARTIFACT_REGISTRY_PATH),
            str(CONTINUITY_METRICS_PATH),
            str(STAGE5_HISTORY_PATH),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for missing system capabilities and queue expansion items.")
    _ = parser.parse_args()
    payload = run_capability_builder()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
