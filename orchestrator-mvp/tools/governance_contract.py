from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = ROOT / "data" / "orchestrator_harness_contract.json"

DEFAULT_CONTRACT: dict[str, Any] = {
    "schema_version": "1.0",
    "status": "missing",
    "contract_name": "orchestrator_harness_split",
    "incident_classification": "quality_plane_regression_without_runtime_continuity_loss",
    "orchestrator_responsibilities": [
        "goal intake",
        "task decomposition",
        "executor dispatch",
        "context reduction",
        "queue management",
    ],
    "harness_responsibilities": [
        "contract validation",
        "evidence validation",
        "risk classification",
        "release gating",
        "rollback eligibility",
        "audit ledger integrity",
    ],
    "shared_constraints": [
        "context separation",
        "evidence required for pass",
        "no pass without evaluation",
        "incident classification preserved separately from runtime continuity",
    ],
    "default_governance_states": [
        "planned",
        "dispatched",
        "generating",
        "candidate_ready",
        "evaluating",
        "pass",
        "fail",
    ],
}


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def load_governance_contract() -> dict[str, Any]:
    payload = _load_json(CONTRACT_PATH, DEFAULT_CONTRACT)
    if not isinstance(payload, dict):
        return dict(DEFAULT_CONTRACT)
    merged = dict(DEFAULT_CONTRACT)
    merged.update(payload)
    return merged


def summarize_governance_contract(contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_governance_contract()
    orchestrator_responsibilities = list(contract.get("orchestrator_responsibilities") or [])
    harness_responsibilities = list(contract.get("harness_responsibilities") or [])
    shared_constraints = list(contract.get("shared_constraints") or [])
    has_split = bool(orchestrator_responsibilities and harness_responsibilities and shared_constraints)
    return {
        "status": "pass" if contract.get("status") == "active" and has_split else "attention",
        "schema_version": contract.get("schema_version"),
        "contract_name": contract.get("contract_name"),
        "incident_classification": contract.get("incident_classification"),
        "orchestrator_responsibility_count": len(orchestrator_responsibilities),
        "harness_responsibility_count": len(harness_responsibilities),
        "shared_constraint_count": len(shared_constraints),
        "governance_state_count": len(list(contract.get("default_governance_states") or [])),
        "context_separation": has_split,
        "orchestrator_responsibilities": orchestrator_responsibilities[:8],
        "harness_responsibilities": harness_responsibilities[:8],
        "shared_constraints": shared_constraints[:8],
    }
