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
REPORT_PATH = DATA / "capability_builder_status.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
CONTINUITY_METRICS_PATH = DATA / "continuity_metrics.json"
STAGE5_HISTORY_PATH = DATA / "stage5_metrics_history.json"
INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"


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
    seen_ids: set[str] = set()
    seen_signatures: set[str] = set()
    result = []
    for item in items:
        item_id = str(item.get("id") or "")
        signature = _item_signature(item)
        if not item_id or item_id in seen_ids:
            continue
        if signature and signature in seen_signatures:
            continue
        seen_ids.add(item_id)
        if signature:
            seen_signatures.add(signature)
        result.append(item)
    return result


def _existing_open_ids(queue: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for item in queue.get("open_items") or []:
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids


def _item_signature(item: dict[str, Any]) -> str:
    trigger = item.get("trigger") if isinstance(item.get("trigger"), dict) else {}
    action = item.get("proposed_action") if isinstance(item.get("proposed_action"), dict) else {}
    parts = [
        str(item.get("category") or "").strip().lower(),
        str(trigger.get("source") or "").strip().lower(),
        str(trigger.get("signal") or "").strip().lower(),
        str(action.get("type") or "").strip().lower(),
        str(action.get("target") or "").strip().lower(),
    ]
    normalized = "|".join(parts).strip("|")
    return normalized


def _existing_active_signatures(queue: dict[str, Any]) -> set[str]:
    signatures: set[str] = set()
    for bucket in ("open_items", "in_progress_items"):
        for item in queue.get(bucket) or []:
            if not isinstance(item, dict):
                continue
            signature = _item_signature(item)
            if signature:
                signatures.add(signature)
    return signatures


def _artifact_registry() -> dict[str, Any]:
    registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    return registry if isinstance(registry, dict) else {}


def _industrial_operations() -> dict[str, Any]:
    payload = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _p2_allowed() -> bool:
    operations = _industrial_operations()
    gates = (operations.get("budget_control") or {}).get("gates") or {}
    if isinstance(gates, dict) and gates.get("allow_p2") is False:
        return False
    replenishment = (operations.get("budget_control") or {}).get("replenishment") or {}
    p2_replenishment = replenishment.get("capability_expansion_daily") or {}
    if isinstance(p2_replenishment, dict) and p2_replenishment.get("budget_exhausted") is True:
        return False
    return True


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
                "budget_pool": "P2",
                "admission_lane": "capability_growth",
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
            "budget_pool": "P2",
            "admission_lane": "capability_growth",
            "status": "open",
            "created_at": _utc(),
        }
    )
    return items


def run_capability_builder() -> dict[str, Any]:
    queue = _queue_state()
    open_items = _normalize_items(list(queue.get("open_items") or []))
    queue["open_items"] = open_items
    queue["in_progress_items"] = _normalize_items(list(queue.get("in_progress_items") or []))
    open_ids = _existing_open_ids(queue)
    active_signatures = _existing_active_signatures(queue)
    budget_allows = _p2_allowed()
    created_candidates = _open_capability_items() if budget_allows else []
    created_items: list[dict[str, Any]] = []
    for item in created_candidates:
        signature = _item_signature(item)
        if item["id"] in open_ids:
            continue
        if signature and signature in active_signatures:
            continue
        open_items.append(item)
        created_items.append(item)
        open_ids.add(item["id"])
        if signature:
            active_signatures.add(signature)
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)

    report = {
        "updated_at": _utc(),
        "status": "pass" if budget_allows else "budget_closed",
        "open_items_created": len(created_items),
        "open_items_total": len(open_items),
        "queue_path": str(QUEUE_PATH),
        "report_path": str(REPORT_PATH),
        "budget_gate": {
            "allow_p2": budget_allows,
            "source": str(INDUSTRIAL_OPERATIONS_PATH),
        },
        "contingency_inputs": [
            str(ARTIFACT_REGISTRY_PATH),
            str(CONTINUITY_METRICS_PATH),
            str(STAGE5_HISTORY_PATH),
        ],
    }
    atomic_write_json(REPORT_PATH, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for missing system capabilities and queue expansion items.")
    _ = parser.parse_args()
    payload = run_capability_builder()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
