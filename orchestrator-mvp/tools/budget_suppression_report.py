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

from tools.execution_trace import append_trace
from tools.io_utils import atomic_write_json

INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"
GOAL_BACKLOG_STATUS_PATH = DATA / "goal_backlog_status.json"
ARTIFACT_GROWTH_STATUS_PATH = DATA / "artifact_growth_status.json"
CAPABILITY_BUILDER_STATUS_PATH = DATA / "capability_builder_status.json"
P2_SANDBOX_STATUS_PATH = DATA / "p2_sandbox_status.json"
FAILURE_BACKLOG_REPORT_PATH = DATA / "task_backlog_automation.json"
OUTPUT_PATH = DATA / "budget_suppression_report.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _iso(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    return text if text.endswith("Z") else text


def run_budget_suppression_report() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    industrial_operations = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    goal_backlog_status = _load_json(GOAL_BACKLOG_STATUS_PATH, {})
    artifact_growth_status = _load_json(ARTIFACT_GROWTH_STATUS_PATH, {})
    capability_builder_status = _load_json(CAPABILITY_BUILDER_STATUS_PATH, {})
    p2_sandbox_status = _load_json(P2_SANDBOX_STATUS_PATH, {})
    failure_backlog_report = _load_json(FAILURE_BACKLOG_REPORT_PATH, {})

    budget_control = industrial_operations.get("budget_control") if isinstance(industrial_operations, dict) else {}
    gates = (budget_control or {}).get("gates") or {}
    replenishment = (budget_control or {}).get("replenishment") or {}
    closed_pools = [pool for pool in ("P0", "P1", "P2", "P3") if gates.get(f"allow_{pool.lower()}") is False]
    suppression = {
        "goal_backlog": {
            "candidate_count": int(goal_backlog_status.get("pending_candidate_count") or 0)
            + int(goal_backlog_status.get("active_candidate_count") or 0),
            "suppressed_count": int(goal_backlog_status.get("budget_suppressed_candidate_count") or 0),
            "goal_health": str(goal_backlog_status.get("goal_health") or ""),
            "last_replenishment_result": str(goal_backlog_status.get("last_replenishment_result") or ""),
            "dispatch_now_count": int(goal_backlog_status.get("dispatch_now_count") or 0),
        },
        "artifact_growth": {
            "status": str(artifact_growth_status.get("status") or ""),
            "open_items_total": int(artifact_growth_status.get("open_items_total") or 0),
            "created_items": int(artifact_growth_status.get("created_items") or 0),
            "skipped_due_to_budget": int(artifact_growth_status.get("skipped_due_to_budget") or 0),
            "budget_closed": str(artifact_growth_status.get("status") or "") == "budget_closed",
            "next_replenishment_at": _iso(((replenishment.get("artifact_growth_daily") or {}).get("next_replenishment_at"))),
        },
        "capability_builder": {
            "status": str(capability_builder_status.get("status") or ""),
            "open_items_total": int(capability_builder_status.get("open_items_total") or 0),
            "open_items_created": int(capability_builder_status.get("open_items_created") or 0),
            "budget_closed": str(capability_builder_status.get("status") or "") == "budget_closed",
            "next_replenishment_at": _iso(((replenishment.get("capability_expansion_daily") or {}).get("next_replenishment_at"))),
        },
        "p2_sandbox": {
            "status": str(p2_sandbox_status.get("status") or ""),
            "open_items_total": int(p2_sandbox_status.get("open_items_total") or 0),
            "created_items": int(p2_sandbox_status.get("created_items") or 0),
            "budget_closed": str(p2_sandbox_status.get("status") or "") == "budget_closed",
            "next_replenishment_at": _iso(((replenishment.get("sandbox_p2_daily") or {}).get("next_replenishment_at"))),
        },
        "failure_backlog_automation": {
            "created_count": int(failure_backlog_report.get("created_count") or 0),
            "toyos_created_count": int(failure_backlog_report.get("toyos_replenishment", {}).get("active_candidate_count") or 0)
            + int(failure_backlog_report.get("toyos_replenishment", {}).get("pending_candidate_count") or 0),
            "budget_suppressed_candidate_count": int(failure_backlog_report.get("budget_suppressed_candidate_count") or 0),
            "replenishment_block_reason": str(failure_backlog_report.get("toyos_replenishment", {}).get("goal_health") or ""),
        },
    }
    suppressed_total = len(closed_pools) + sum(
        int(section.get("suppressed_count") or 0)
        if "suppressed_count" in section
        else int(section.get("skipped_due_to_budget") or 0)
        if "skipped_due_to_budget" in section
        else int(section.get("budget_suppressed_candidate_count") or 0)
        for section in suppression.values()
    )
    report = {
        "updated_at": _utc(),
        "status": "pass",
        "industrial_operations_status": str(industrial_operations.get("status") or ""),
        "task_pools": (industrial_operations.get("task_pools") or {}),
        "budget_control": {
            "gates": gates,
            "replenishment": replenishment,
        },
        "closed_pools": closed_pools,
        "closed_pool_count": len(closed_pools),
        "suppression": suppression,
        "suppressed_total": suppressed_total,
        "next_replenishment_at": {
            "artifact_growth_daily": _iso(((replenishment.get("artifact_growth_daily") or {}).get("next_replenishment_at"))),
            "capability_expansion_daily": _iso(((replenishment.get("capability_expansion_daily") or {}).get("next_replenishment_at"))),
            "sandbox_p2_daily": _iso(((replenishment.get("sandbox_p2_daily") or {}).get("next_replenishment_at"))),
            "research_daily": _iso(((replenishment.get("research_daily") or {}).get("next_replenishment_at"))),
            "self_repair_daily": _iso(((replenishment.get("self_repair_daily") or {}).get("next_replenishment_at"))),
        },
        "next_actions": [
            "Keep P0 and P1 open.",
            "Do not schedule new P2 capability growth until capability_expansion_daily headroom returns.",
            "Use the dedicated P2 sandbox lane only for low-risk tasks while allow_p2_sandbox remains true.",
            "Keep P3 closed until the system is normal and research headroom is available.",
        ],
    }
    atomic_write_json(OUTPUT_PATH, report)
    append_trace(
        "industrial-readiness",
        "build budget suppression report",
        "run budget_suppression_report.py",
        f"suppressed_total={suppressed_total} status={report['status']}",
        "refresh budget suppression views or wait for replenishment",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"output_path": str(OUTPUT_PATH), "suppressed_total": suppressed_total},
    )
    return report


def main() -> int:
    _ = argparse.ArgumentParser(description="Build a budget suppression daily report.").parse_args()
    print(json.dumps(run_budget_suppression_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
