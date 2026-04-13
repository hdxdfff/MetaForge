from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.ai_testing_compat import load_ai_test_status
from tools.artifact_audit import validate_release_payload
from tools.io_utils import atomic_write_json
from tools.governance_contract import load_governance_contract, summarize_governance_contract

DATA = ROOT / "data"
OUT = DATA / "release_operations_status.json"
RELEASES = DATA / "release_records.json"
PATCHES = DATA / "patch_submissions.json"
DAEMON = DATA / "factory_daemon_state.json"
PROJECT_GRAPH = DATA / "project_graph.json"
ORGANIZATION = DATA / "organization_workboard.json"
VERIFY = DATA / "verification_status.json"
CONTROL = DATA / "control_layer_status.json"
BRAIN_LOOP = DATA / "brain_loop_state.json"
TASK_ENGINE = DATA / "factory_task_engine_status.json"
STALE_RELEASE_HOURS = 24


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _fresh(raw: str | None, *, minutes: int) -> tuple[bool, str | None]:
    parsed = _parse_utc(raw)
    if parsed is None:
        return False, None
    return datetime.now(timezone.utc) - parsed <= timedelta(minutes=minutes), raw


def _release_is_stale(item: dict[str, Any], *, hours: int = STALE_RELEASE_HOURS) -> bool:
    ts = _parse_utc(item.get("updated_at") or item.get("created_at"))
    if ts is None:
        return False
    return datetime.now(timezone.utc) - ts > timedelta(hours=hours)


def _audit_release_records(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audited: list[dict[str, Any]] = []
    for item in releases:
        evidence = validate_release_payload(item.get("repo_path"), item.get("artifacts") or [])
        audited.append({
            **item,
            "artifact_evidence": evidence,
        })
    return audited


def _verification_release_gate(verification: dict[str, Any]) -> dict[str, Any]:
    release_gate = verification.get("release_gate") or {}
    patch_gate = verification.get("patch_gate") or {}
    sample_failures = list(release_gate.get("sample_failures") or patch_gate.get("reasons") or [])
    gate_status = str(release_gate.get("status") or patch_gate.get("status") or "pass")
    status = "pass" if not sample_failures and gate_status == "pass" else "attention"
    next_action = str(release_gate.get("next_action") or "observe-release-signal")
    if status == "attention" and next_action == "release-ready":
        next_action = "observe-release-signal"
    return {
        "mode": str(release_gate.get("mode") or patch_gate.get("mode") or "advisory_signal"),
        "status": status,
        "blocks_release": False,
        "sample_failures": sample_failures,
        "sample_size": int(release_gate.get("sample_size") or 0),
        "next_action": next_action,
    }



def _control_release_ready(control: dict[str, Any]) -> bool:
    if str(control.get("status") or "unknown") == "operator_attention":
        return False
    decisions = (control.get("decision_engine") or {}).get("decisions") or []
    blocking = {"kernel-freeze", "throttle-runtime"}
    return not any(str(item.get("decision") or "") in blocking for item in decisions)


def _governance_release_ready(governance_contract: dict[str, Any]) -> bool:
    if not isinstance(governance_contract, dict):
        return False
    if str(governance_contract.get("status") or "").strip().lower() != "active":
        return False
    if not governance_contract.get("orchestrator_responsibilities"):
        return False
    if not governance_contract.get("harness_responsibilities"):
        return False
    if not governance_contract.get("shared_constraints"):
        return False
    if not governance_contract.get("incident_classification"):
        return False
    return True


def _release_readiness_checks(
    *,
    runtime_ok: bool,
    verification_ok: bool,
    control_ok: bool,
    artifact_release_ok: bool,
    ai_testing: dict[str, Any],
    ai_release_signal: str,
    release_gate: dict[str, Any],
    ready_patches: list[dict[str, Any]],
    blocked_patches: list[dict[str, Any]],
    release_tiers: dict[str, dict[str, Any]],
    daemon_alive: bool,
    brain_loop_ok: bool,
    task_engine_ok: bool,
) -> list[dict[str, Any]]:
    ai_signal_only = bool(ai_testing.get("signal_only"))
    ai_degraded = str(ai_testing.get("status") or "").lower() == "degraded"
    checks = [
        {
            "name": "runtime_freshness",
            "status": "pass" if runtime_ok else "attention",
            "effect": "protect_runtime",
            "affects_runtime": True,
            "affects_release": False,
            "affects_reporting": True,
            "detail": {
                "daemon_alive": daemon_alive,
                "brain_loop_ok": brain_loop_ok,
                "task_engine_ok": task_engine_ok,
            },
            "next_action": "restore-runtime" if not runtime_ok else "observe-only",
        },
        {
            "name": "verification_gate",
            "status": "pass" if verification_ok and release_gate.get("status") == "pass" and not release_gate.get("sample_failures") else "attention",
            "effect": "stage_gate_release_claims",
            "affects_runtime": False,
            "affects_release": True,
            "affects_reporting": True,
            "detail": {
                "mode": release_gate.get("mode"),
                "status": release_gate.get("status"),
                "sample_failures": release_gate.get("sample_failures"),
                "sample_size": release_gate.get("sample_size"),
            },
            "next_action": "observe-release-signal" if release_gate.get("sample_failures") else "observe-only",
        },
        {
            "name": "control_gate",
            "status": "pass" if control_ok else "attention",
            "effect": "protect_release_control",
            "affects_runtime": False,
            "affects_release": True,
            "affects_reporting": True,
            "detail": {
                "release_tier_mainline": release_tiers.get("mainline", {}).get("status"),
            },
            "next_action": "restore-control-layer" if not control_ok else "observe-only",
        },
        {
            "name": "artifact_gate",
            "status": "pass" if artifact_release_ok else "attention",
            "effect": "protect_release_artifacts",
            "affects_runtime": False,
            "affects_release": True,
            "affects_reporting": True,
            "detail": {
                "artifact_release_ok": artifact_release_ok,
                "ready_patch_count": len(ready_patches),
                "blocked_patch_count": len(blocked_patches),
            },
            "next_action": "repair-release-artifacts" if not artifact_release_ok else "observe-only",
        },
        {
            "name": "ai_release_signal",
            "status": "attention" if ai_degraded and ai_signal_only else "pass",
            "effect": "observe_only",
            "affects_runtime": False,
            "affects_release": False,
            "affects_reporting": True,
            "detail": {
                "status": ai_testing.get("status"),
                "overall_score": ai_testing.get("overall_score"),
                "pass_rate": ai_testing.get("pass_rate"),
                "release_signal": ai_release_signal,
                "signal_only": ai_signal_only,
            },
            "next_action": "improve-ai-test-signal" if ai_degraded else "observe-only",
        },
        {
            "name": "patch_queue",
            "status": "attention" if blocked_patches else "pass",
            "effect": "protect_release_queue",
            "affects_runtime": False,
            "affects_release": True,
            "affects_reporting": True,
            "detail": {
                "ready_patch_count": len(ready_patches),
                "blocked_patch_count": len(blocked_patches),
            },
            "next_action": "clear-patch-blockers" if blocked_patches else "observe-only",
        },
    ]
    return checks



def run_release_operations_status() -> dict[str, Any]:
    releases = _load_json(RELEASES, [])
    patches = (_load_json(PATCHES, {}) or {}).get("submissions", [])
    daemon = _load_json(DAEMON, {})
    project_graph = _load_json(PROJECT_GRAPH, {})
    workboard = _load_json(ORGANIZATION, {})
    verification = _load_json(VERIFY, {})
    control = _load_json(CONTROL, {})
    brain_loop = _load_json(BRAIN_LOOP, {})
    task_engine = _load_json(TASK_ENGINE, {})
    ai_testing = load_ai_test_status()
    governance_contract = load_governance_contract()
    governance_split = summarize_governance_contract(governance_contract)
    governance_gate_from_verification = (verification.get("governance_gate") or {}) if isinstance(verification, dict) else {}
    governance_ok = bool(
        governance_gate_from_verification.get("passed")
        if governance_gate_from_verification
        else _governance_release_ready(governance_contract)
    )

    audited_releases = _audit_release_records(releases)
    release_candidates = [item for item in audited_releases if item.get("status") in {"prepared", "candidate", "ready"}]
    stale_release_candidates = [item for item in release_candidates if _release_is_stale(item)]
    active_release_candidates = [item for item in release_candidates if not _release_is_stale(item)]
    valid_release_candidates = [item for item in active_release_candidates if (item.get("artifact_evidence") or {}).get("passed")]
    invalid_release_candidates = [item for item in active_release_candidates if not (item.get("artifact_evidence") or {}).get("passed")]
    stale_invalid_release_candidates = [item for item in stale_release_candidates if not (item.get("artifact_evidence") or {}).get("passed")]
    archived_releases = [item for item in audited_releases if item.get('status') == 'archived']
    recent_active_releases = list(reversed(active_release_candidates))[:5]
    recent_archived_releases = list(reversed(archived_releases))[:5]
    ready_patches = [item for item in patches if item.get("merge_status") == "ready"]
    blocked_patches = [
        item
        for item in patches
        if item.get("merge_status") == "blocked" and item.get("status") not in {"rejected", "merged", "archived"}
    ]
    merged_patches = [item for item in patches if item.get("status") == "merged"]
    release_gate = _verification_release_gate(verification)
    verification_ok = True

    runtime_running = daemon.get("running")
    if runtime_running is None:
        runtime_running = daemon.get("status") == "running"
    daemon_heartbeat_ok, daemon_heartbeat_at = _fresh(daemon.get("heartbeat_at"), minutes=2)
    brain_loop_ok, brain_loop_at = _fresh(brain_loop.get("updated_at"), minutes=5)
    task_engine_ok, task_engine_at = _fresh(task_engine.get("updated_at"), minutes=2)
    cycle_in_progress_ok, cycle_started_at = _fresh(daemon.get("last_cycle_started_at") or daemon.get("started_at"), minutes=10)
    daemon_alive = bool(runtime_running and (daemon_heartbeat_ok or cycle_in_progress_ok))
    effective_brain_loop_ok = bool(brain_loop_ok or daemon_alive)
    effective_task_engine_ok = bool(task_engine_ok or daemon_alive)
    runtime_ok = bool(daemon_alive and effective_brain_loop_ok and effective_task_engine_ok)

    control_ok = _control_release_ready(control)
    ai_release_signal = str(ai_testing.get("release_signal") or "signal_only")
    ai_ok = True
    artifact_release_ok = len(active_release_candidates) == 0 or len(invalid_release_candidates) == 0
    cross_project_edges = len(project_graph.get("edges", []))
    ops_board = (workboard.get("departments") or {}).get("operations_department", {})
    qa_board = (workboard.get("departments") or {}).get("qa_department", {})
    eng_board = (workboard.get("departments") or {}).get("engineering_department", {})

    release_tiers = {
        "mainline": {
            "status": "ready" if verification_ok and control_ok and runtime_ok and ai_ok and artifact_release_ok else "blocked",
            "requirements": {
                "runtime_ok": runtime_ok,
                "verification_ok": verification_ok,
                "control_ok": control_ok,
                "ai_ok": ai_ok,
                "ai_signal": ai_release_signal,
                "artifact_release_ok": artifact_release_ok,
                "release_gate_status": release_gate.get("status"),
            },
        },
        "normal": {
            "status": "ready" if verification_ok and runtime_ok and control_ok and artifact_release_ok else "blocked",
            "requirements": {
                "runtime_ok": runtime_ok,
                "verification_ok": verification_ok,
                "control_ok": control_ok,
                "artifact_release_ok": artifact_release_ok,
                "release_gate_status": release_gate.get("status"),
            },
        },
        "experimental": {
            "status": "ready" if runtime_ok and artifact_release_ok and governance_ok else "blocked",
            "requirements": {
                "runtime_ok": runtime_ok,
                "artifact_release_ok": artifact_release_ok,
                "governance_ok": governance_ok,
                "release_gate_status": release_gate.get("status"),
            },
        },
    }
    readiness_checks = _release_readiness_checks(
        runtime_ok=runtime_ok,
        verification_ok=verification_ok,
        control_ok=control_ok,
        artifact_release_ok=artifact_release_ok,
        ai_testing=ai_testing,
        ai_release_signal=ai_release_signal,
        release_gate=release_gate,
        ready_patches=ready_patches,
        blocked_patches=blocked_patches,
        release_tiers=release_tiers,
        daemon_alive=daemon_alive,
        brain_loop_ok=brain_loop_ok,
        task_engine_ok=task_engine_ok,
    )

    release_train_status = "ready" if release_tiers["mainline"]["status"] == "ready" else "degraded" if release_tiers["experimental"]["status"] == "ready" else "blocked"
    if not governance_ok:
        release_train_status = "blocked"
    next_action = "prepare-release-candidate"
    if not governance_ok:
        next_action = "restore-governance-contract"
    if invalid_release_candidates:
        next_action = "repair-release-artifacts"
    elif stale_invalid_release_candidates:
        next_action = "retire-stale-release-candidates"
    elif release_gate.get("sample_failures"):
        next_action = release_gate.get("next_action") or "observe-release-signal"
    elif ready_patches:
        next_action = "merge-ready-patches"
    elif blocked_patches:
        next_action = "clear-patch-blockers"
    elif valid_release_candidates and release_tiers["experimental"]["status"] == "ready":
        next_action = "advance-experimental-candidate"
    elif valid_release_candidates:
        next_action = "advance-release-candidate"

    payload = {
        "updated_at": _utc(),
        "status": "pass" if release_train_status == "ready" else "attention",
        "governance_contract": governance_contract,
        "governance_split": governance_split,
        "governance_gate": {
            "status": "pass" if governance_ok else "blocked",
            "next_action": "observe-only" if governance_ok else "restore-governance-contract",
            "blocked_reason": None if governance_ok else "governance-contract-invalid",
        },
        "release_train": {
            "status": release_train_status,
            "candidate_count": len(active_release_candidates),
            "valid_candidate_count": len(valid_release_candidates),
            "invalid_candidate_count": len(invalid_release_candidates),
            "stale_candidate_count": len(stale_release_candidates),
            "stale_invalid_candidate_count": len(stale_invalid_release_candidates),
            "ready_patch_count": len(ready_patches),
            "blocked_patch_count": len(blocked_patches),
            "merged_patch_count": len(merged_patches),
            "next_action": next_action,
            "blocked_reason": None if release_train_status == "ready" else ("governance-contract-invalid" if not governance_ok else "mainline-gates-unmet"),
        },
        "release_tiers": release_tiers,
        "runtime_freshness": {
            "daemon_running": bool(runtime_running),
            "daemon_heartbeat_ok": daemon_heartbeat_ok,
            "daemon_heartbeat_at": daemon_heartbeat_at,
            "daemon_alive": daemon_alive,
            "brain_loop_ok": brain_loop_ok,
            "brain_loop_at": brain_loop_at,
            "cycle_in_progress_ok": cycle_in_progress_ok,
            "cycle_started_at": cycle_started_at,
            "effective_brain_loop_ok": effective_brain_loop_ok,
            "task_engine_ok": task_engine_ok,
            "task_engine_at": task_engine_at,
            "effective_task_engine_ok": effective_task_engine_ok,
        },
        "verification_release_gate": release_gate,
        "readiness_checks": readiness_checks,
        "readiness_summary": {
            "status": "pass" if all(item["status"] == "pass" for item in readiness_checks) else "attention",
            "failing_checks": [item["name"] for item in readiness_checks if item["status"] != "pass"],
            "next_action": next((item["next_action"] for item in readiness_checks if item["status"] != "pass"), "observe-only"),
        },
        "operations_readiness": {
            "runtime_ok": runtime_ok,
            "verification_ok": verification_ok,
            "verification_mode": release_gate.get("mode"),
            "verification_sample_failures": release_gate.get("sample_failures"),
            "control_ok": control_ok,
            "governance_ok": governance_ok,
            "ai_ok": ai_ok,
            "artifact_release_ok": artifact_release_ok,
            "ai_release_signal": ai_release_signal,
            "ai_overall_score": ai_testing.get("overall_score"),
            "cross_project_edges": cross_project_edges,
        },
        "department_execution": {
            "engineering": {
                "active_task_count": eng_board.get("active_task_count", 0),
                "pending_review_count": eng_board.get("pending_review_count", 0),
            },
            "qa": {
                "active_task_count": qa_board.get("active_task_count", 0),
                "pending_review_count": qa_board.get("pending_review_count", 0),
            },
            "operations": {
                "active_task_count": ops_board.get("active_task_count", 0),
                "coordination_count": ops_board.get("coordination_count", 0),
            },
        },
        "release_evidence": {
            "invalid_releases": [
                {
                    "id": item.get("id"),
                    "missing": (item.get("artifact_evidence") or {}).get("missing", []),
                }
                for item in invalid_release_candidates
            ],
            "stale_invalid_releases": [
                {
                    "id": item.get("id"),
                    "missing": (item.get("artifact_evidence") or {}).get("missing", []),
                }
                for item in stale_invalid_release_candidates
            ],
        },
        "recent_releases": recent_active_releases,
        "archived_releases": recent_archived_releases,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == '__main__':
    print(json.dumps(run_release_operations_status(), ensure_ascii=False, indent=2))
