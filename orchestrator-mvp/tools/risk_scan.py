from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.incident_state_machine import IncidentStateMachine
from app.risk_engine import INCIDENT_LEDGER_PATH, RISK_STATUS_PATH, RiskEngine, build_runtime_snapshot
from app.risk_policy import RiskPolicy
from app.safe_repair_executor import SafeRepairExecutor
from app.semantic_verifier import SemanticVerifier


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _summarize_risks(risks: list[dict[str, Any]]) -> dict[str, Any]:
    by_domain: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for risk in risks:
        domain = str(risk.get("domain") or "unknown")
        severity = str(risk.get("severity") or "unknown")
        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_severity[severity] = by_severity.get(severity, 0) + 1
    return {"by_domain": by_domain, "by_severity": by_severity}


def run_risk_branch(
    snapshot: dict[str, Any] | None = None,
    *,
    apply_repairs: bool = False,
    source: str = "manual",
) -> dict[str, Any]:
    engine = RiskEngine()
    policy = RiskPolicy()
    executor = SafeRepairExecutor()
    verifier = SemanticVerifier()
    incident_machine = IncidentStateMachine()

    before_snapshot = snapshot or build_runtime_snapshot()
    risks = engine.scan(before_snapshot)
    incident_records: list[dict[str, Any]] = []

    for risk in risks:
        decision = policy.decide(risk)
        incident = incident_machine.upsert_incident(risk, source=source, snapshot=before_snapshot, policy_decision=decision)
        actions = executor.execute(
            risk,
            snapshot=before_snapshot,
            dry_run=not (apply_repairs and bool(decision.get("auto_repair_allowed"))),
        )
        incident_machine.record_actions(str(incident.get("incident_id") or ""), actions)
        after_snapshot = build_runtime_snapshot() if apply_repairs and bool(decision.get("auto_repair_allowed")) else before_snapshot
        semantic = verifier.verify(snapshot_before=before_snapshot, snapshot_after=after_snapshot, risk=risk, actions=actions)
        updated = incident_machine.finalize(str(incident.get("incident_id") or ""), semantic, "recovered" if semantic.get("repair_success") else "verifying")
        if updated is not None:
            incident = updated
        for action in actions:
            if str(action.get("result") or "").lower() not in {"success", "failed", "simulated"}:
                continue
            incident_machine.record_repair_action(
                incident_id=str(incident.get("incident_id") or ""),
                risk_id=str(risk.get("risk_id") or ""),
                action=action,
                source=source,
            )
        incident["verification"] = semantic
        incident["actions"] = actions
        incident_records.append(incident)
        before_snapshot = after_snapshot

    status = {
        "updated_at": before_snapshot.get("updated_at"),
        "source": source,
        "scan_status": "pass" if not risks else "attention",
        "risk_count": len(risks),
        "open_incident_count": len([item for item in incident_records if item.get("status") != "closed"]),
        "closed_incident_count": len([item for item in incident_records if item.get("status") == "closed"]),
        "risks": risks,
        "risk_summary": _summarize_risks(risks),
        "incidents": incident_records,
    }
    semantic_health = {
        "updated_at": status["updated_at"],
        "repair_success": all(bool((item.get("verification") or {}).get("repair_success")) for item in incident_records) if incident_records else True,
        "open_incidents": [item.get("incident_id") for item in incident_records if item.get("status") != "closed"],
        "closed_incidents": [item.get("incident_id") for item in incident_records if item.get("status") == "closed"],
        "risk_count": len(risks),
    }
    incident_machine.write_status(status)
    incident_machine.write_semantic_health(semantic_health)
    return {"status": status, "semantic_health": semantic_health}


def read_risk_status() -> dict[str, Any]:
    payload = _load_json(RISK_STATUS_PATH, {})
    return payload if isinstance(payload, dict) else {}


def read_incident_ledger(limit: int | None = None) -> list[dict[str, Any]]:
    payload = _load_json(INCIDENT_LEDGER_PATH, [])
    if not isinstance(payload, list):
        return []
    if limit is None:
        return payload
    return payload[-max(1, limit):]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the risk branch scan.")
    parser.add_argument("--apply", action="store_true", help="Apply safe repairs when policy allows.")
    parser.add_argument("--source", default="cli", help="Source label for incident records.")
    parser.add_argument("--json", action="store_true", help="Print JSON only.")
    args = parser.parse_args()
    payload = run_risk_branch(apply_repairs=args.apply, source=args.source)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"risk scan status: {payload['status']['scan_status']}")
        print(f"risk count: {payload['status']['risk_count']}")
        print(f"incident ledger: {INCIDENT_LEDGER_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
