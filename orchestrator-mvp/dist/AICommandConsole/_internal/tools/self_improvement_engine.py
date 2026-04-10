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

QUEUE_PATH = DATA / "self_improvement_queue.json"
LEDGER_PATH = DATA / "evolution_ledger.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
AUTONOMY_PATH = DATA / "autonomy_score.json"
DAEMON_PATH = DATA / "factory_daemon_state.json"
DASHBOARD_PATH = DATA / "stage5_dashboard.json"


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


def _open_repair_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    release_ops = _load_json(RELEASE_OPS_PATH, {})
    readiness = release_ops.get("readiness_summary") or {}
    failing_checks = readiness.get("failing_checks") or []
    if isinstance(failing_checks, list) and failing_checks:
        items.append(
            {
                "id": f"sir_{datetime.now(timezone.utc).strftime('%Y%m%d')}_release_{uuid4().hex[:6]}",
                "category": "verification_gate",
                "severity": "medium",
                "trigger": {
                    "source": "release_operations_status.json",
                    "signal": "verification_gate_attention",
                },
                "goal": "Restore release readiness by refreshing stale verification evidence and clearing artifact_audit attention.",
                "proposed_action": {
                    "type": "verification_refresh",
                    "target": "tools/verification_engine.py",
                },
                "status": "open",
                "created_at": _utc(),
            }
        )

    control_layer = _load_json(CONTROL_LAYER_PATH, {})
    control_status = str(control_layer.get("status") or "").lower()
    if control_status in {"attention", "degraded"}:
        items.append(
            {
                "id": f"sir_{datetime.now(timezone.utc).strftime('%Y%m%d')}_control_{uuid4().hex[:6]}",
                "category": "control_snapshot",
                "severity": "low",
                "trigger": {
                    "source": "control_layer_status.json",
                    "signal": "cached_signal_only",
                },
                "goal": "Refresh control-layer evidence so the cached weak-control snapshot does not outlive live status.",
                "proposed_action": {
                    "type": "status_refresh",
                    "target": "tools/meta_factory_control.py",
                },
                "status": "open",
                "created_at": _utc(),
            }
        )

    daemon = _load_json(DAEMON_PATH, {})
    ai_testing = (daemon.get("last_result") or {}).get("ai_testing") or {}
    if str(ai_testing.get("status") or "").lower() == "degraded":
        items.append(
            {
                "id": f"sir_{datetime.now(timezone.utc).strftime('%Y%m%d')}_aitest_{uuid4().hex[:6]}",
                "category": "ai_testing",
                "severity": "high",
                "trigger": {
                    "source": "factory_daemon_state.json",
                    "signal": "ai_testing_degraded",
                },
                "goal": "Restore AI testing to pass and clear the degraded release signal.",
                "proposed_action": {
                    "type": "test_fix",
                    "target": "tools/ai_testing_compat.py",
                },
                "status": "open",
                "created_at": _utc(),
            }
        )
    return items


def run_self_improvement_engine() -> dict[str, Any]:
    queue = _queue_state()
    open_items = _normalize_items(list(queue.get("open_items") or []))
    created_items = _open_repair_items()
    for item in created_items:
        if not any(existing.get("id") == item["id"] for existing in open_items):
            open_items.append(item)
    queue["open_items"] = open_items
    atomic_write_json(QUEUE_PATH, queue)

    dashboard = _load_json(DASHBOARD_PATH, {})
    if isinstance(dashboard, dict):
        dashboard["last_evaluated_at"] = _utc()
        atomic_write_json(DASHBOARD_PATH, dashboard)

    return {
        "updated_at": _utc(),
        "status": "pass",
        "open_items_created": len(created_items),
        "open_items_total": len(open_items),
        "queue_path": str(QUEUE_PATH),
        "ledger_path": str(LEDGER_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the live state for self-improvement work items.")
    _ = parser.parse_args()
    payload = run_self_improvement_engine()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
