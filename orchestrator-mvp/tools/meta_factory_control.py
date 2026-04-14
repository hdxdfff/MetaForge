from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

from tools.tool_registry import list_tools
from tools.ai_guard import run_guard
from tools.autonomy_score import run_autonomy_score
from tools.knowledge_engine import rebuild_knowledge
from tools.platform_registry import platform_health_summary
from tools.quality_system import run_quality
from tools.module_ownership_graph import build_module_ownership_graph, build_review_policy_graph
from tools.dependency_impact_engine import analyze_dependency_impact
from tools.project_graph import build_project_graph
from tools.organization_model import build_organization_model
from tools.cross_project_coordination import run_cross_project_coordination
from tools.organization_workboard import build_organization_workboard
from tools.branch_workboard import build_branch_workboard
from tools.global_policy_engine import run_global_policy
from tools.code_knowledge_graph import build_code_knowledge_graph
from tools.architecture_validator import run_architecture_validation
from tools.verification_engine import run_verification
from tools.module_ownership import refresh_patch_submissions, patch_review_queue
from tools.automation_lab import run_automation_lab_status
from tools.release_operations import run_release_operations_status
from tools.tool_health_audit import run_tool_health_audit
from tools.change_attribution import run_change_attribution_status
from tools.ai_testing_compat import load_ai_test_status
from tools.self_repair_playbooks import run_self_repair_playbooks
from tools.rnd_department import build_rnd_department_status
from tools.rnd_delivery_pipeline import build_rnd_delivery_pipeline_status
from tools.rnd_asset_governance import build_rnd_asset_governance_status
from tools.economics_engine import run_economics_engine_status
from tools.kernel_mode import is_component_enabled, load_kernel_mode
from tools.identity_kernel import identity_kernel_status
from tools.governance_contract import load_governance_contract, summarize_governance_contract

DATA = ROOT / "data"
FACTORY = ROOT / "factory"
OUT = DATA / "control_layer_status.json"
AUDIT = DATA / "audit_log.json"
LOG_PATH = DATA / "factory_daemon.log"

GUARD = DATA / "health_status.json"
QUALITY = DATA / "quality_status.json"
EVOLUTION = DATA / "evolution_control.json"
USAGE = DATA / "usage_tracker.json"
TASKS = DATA / "tasks.json"
CORE_MESSAGES = DATA / "core_messages.json"
CAPABILITIES = FACTORY / "capability_registry.json"
PLATFORMS = FACTORY / "platform_registry.json"
POLICY = DATA / "approval_policy.json"
GUARD_POLICY = DATA / "guard_policy.json"
QUALITY_POLICY = DATA / "quality_policy.json"
DECISION_ENGINE = DATA / "decision_engine_status.json"
CAPABILITY_REPUTATION = DATA / "capability_reputation.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"
TASK_ENGINE = DATA / "factory_task_engine_status.json"


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


def _tail_log(limit: int = 20) -> list[str]:
    if not LOG_PATH.exists():
        return []
    return LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]


def _disabled_status(name: str, kernel_mode: dict[str, Any]) -> dict[str, Any]:
    profile = kernel_mode.get("profile") or "standard"
    return {
        "status": "disabled",
        "reason": f"{name} disabled by {profile}",
        "profile": profile,
    }


def _state_kernel(
    tasks: list[dict[str, Any]],
    platforms: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    active_tasks = [
        item
        for item in tasks
        if item.get("status") in {"queued", "planning", "running", "waiting_approval"}
    ]
    failed_tasks = [item for item in tasks if item.get("status") in {"failed", "timed_out"}]
    open_messages = [item for item in messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_messages if item.get("severity") == "error"]
    return {
        "agents_running": len(active_tasks),
        "active_tasks": len(active_tasks),
        "failed_tasks": len(failed_tasks),
        "capabilities": len(capabilities),
        "platforms": len(platforms),
        "open_escalations": len(open_messages),
        "open_error_escalations": len(open_errors),
        "task_ids": [item.get("id") for item in active_tasks[:8]],
        "platform_ids": [item.get("platform_id") for item in platforms[:8]],
    }


def _resource_governor(guard: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    tasks = guard.get("tasks", {})
    recent_window = usage.get("recent_window") or {}
    recent_total_calls = int(recent_window.get("total_calls", 0) or 0)
    min_ratio_sample_calls = int(usage.get("ratio_sample_min_calls", 5) or 5)
    use_recent_window = recent_total_calls >= min_ratio_sample_calls
    usage_source = recent_window if use_recent_window else usage
    payload = {
        "status": guard.get("status", "unknown"),
        "allow_brain_loop": bool(guard.get("allow_brain_loop", True)),
        "allow_meta": bool(guard.get("allow_meta", True)),
        "allow_evolution": bool(guard.get("allow_evolution", True)),
        "reasoning_ratio": float(usage_source.get("reasoning_ratio", 0.0) or 0.0),
        "reasoning_allowed": bool(usage.get("reasoning_allowed", True)),
        "max_reasoning_model_ratio": float(usage.get("max_reasoning_model_ratio", 0.6) or 0.6),
        "strong_ratio": float(usage_source.get("strong_ratio", 0.0) or 0.0),
        "strong_allowed": bool(usage.get("strong_allowed", True)),
        "max_strong_model_ratio": float(usage.get("max_strong_model_ratio", 0.2) or 0.2),
        "active_tasks": int(tasks.get("active", 0) or 0),
        "queued_tasks": int(tasks.get("queued", 0) or 0),
        "reasons": guard.get("reasons", []),
        "advisories": guard.get("advisories", []),
    }
    if use_recent_window:
        payload["usage_window_hours"] = int(recent_window.get("hours", 1) or 1)
    payload["ratio_source"] = "recent_window" if use_recent_window else "full_window"
    payload["ratio_sample_min_calls"] = min_ratio_sample_calls
    payload["recent_window_sample_sufficient"] = use_recent_window
    return payload


def _decision_engine(
    guard: dict[str, Any],
    quality: dict[str, Any],
    evolution: dict[str, Any],
    state_kernel: dict[str, Any],
    verification: dict[str, Any],
    ai_testing: dict[str, Any],
    kernel_mode: dict[str, Any],
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    overall_quality = float(quality.get("overall_score", 0.0) or 0.0)
    lean_execution = kernel_mode.get("profile") in {"lean_execution", "interaction_only"}

    if not guard.get("allow_brain_loop", True):
        decisions.append(
            {
                "decision": "throttle-runtime",
                "reason": ", ".join(guard.get("reasons", [])) or "guard restricted runtime loop",
                "applies_to": "orchestrator",
            }
        )

    if lean_execution:
        decisions.append(
            {
                "decision": "lean-mode-active",
                "reason": ", ".join(kernel_mode.get("reasons", []))
                or "lean execution profile active",
                "applies_to": "control-plane",
            }
        )
        if state_kernel.get("open_error_escalations", 0) > 0:
            decisions.append(
                {
                    "decision": "require-operator-review",
                    "reason": f"{state_kernel['open_error_escalations']} open error escalations",
                    "applies_to": "escalation-handler",
                }
            )
        mode = "lean_execution"
        if state_kernel.get("open_error_escalations", 0) > 0:
            mode = "operator_attention"
        elif not guard.get("allow_brain_loop", True):
            mode = "constrained"
        return {
            "mode": mode,
            "decisions": decisions,
            "decision_count": len(decisions),
        }

    if not guard.get("allow_meta", True):
        decisions.append(
            {
                "decision": "throttle-meta",
                "reason": ", ".join(guard.get("reasons", [])) or "guard restricted meta loop",
                "applies_to": "meta-factory",
            }
        )
    if not guard.get("allow_evolution", True):
        decisions.append(
            {
                "decision": "throttle-evolution",
                "reason": ", ".join(guard.get("reasons", [])) or "guard restricted evolution loop",
                "applies_to": "evolution",
            }
        )
    if overall_quality < 0.75:
        decisions.append(
            {
                "decision": "defer-promotion",
                "reason": f"quality score below threshold ({overall_quality:.4f})",
                "applies_to": "promotion",
            }
        )
    delayed_verification = verification.get("delayed_verification") or verification.get(
        "patch_gate", {}
    )
    delayed_verification_status = str(delayed_verification.get("status") or "unknown")
    if delayed_verification_status != "pass":
        pending = (
            ",".join((delayed_verification.get("pending_checks") or [])[:5])
            or delayed_verification_status
        )
        decisions.append(
            {
                "decision": "delay-verification",
                "reason": f"verification mode={delayed_verification.get('mode', 'delayed')} pending={pending}",
                "applies_to": "verification",
            }
        )
    release_gate = verification.get("release_gate", {})
    release_gate_status = str(release_gate.get("status") or "pass")
    if release_gate_status != "pass" or release_gate.get("sample_failures"):
        sampled_failures = (
            ",".join((release_gate.get("sample_failures") or [])[:5]) or release_gate_status
        )
        decisions.append(
            {
                "decision": "observe-release-signal",
                "reason": f"release gate advisory status={release_gate_status} sampled_failures={sampled_failures}",
                "applies_to": "release-train",
            }
        )
    ai_status = str(ai_testing.get("status") or "missing")
    ai_pass_rate = float(ai_testing.get("pass_rate", 0.0) or 0.0)
    ai_error_count = int(ai_testing.get("error_count", 0) or 0)
    ai_overall_score = float(ai_testing.get("overall_score", ai_pass_rate * 100.0) or 0.0)
    if ai_error_count > 0 or ai_status in {"warning", "degraded", "attention", "missing"}:
        decisions.append(
            {
                "decision": "observe-ai-testing-signal",
                "reason": f"ai quality signal-only status={ai_status} overall_score={ai_overall_score:.1f} pass_rate={ai_pass_rate:.2f} error_count={ai_error_count}",
                "applies_to": "ai-testing",
            }
        )
    if state_kernel.get("open_error_escalations", 0) > 0:
        decisions.append(
            {
                "decision": "require-operator-review",
                "reason": f"{state_kernel['open_error_escalations']} open error escalations",
                "applies_to": "escalation-handler",
            }
        )
    if kernel_mode.get("kernel_freeze"):
        decisions.append(
            {
                "decision": "kernel-freeze",
                "reason": ", ".join(kernel_mode.get("reasons", [])) or "kernel freeze active",
                "applies_to": "control-plane",
            }
        )
    elif (
        evolution.get("allowed") and overall_quality >= 0.75 and guard.get("allow_evolution", True)
    ):
        decisions.append(
            {
                "decision": "allow-evolution-candidates",
                "reason": f"{evolution.get('selected_count', 0)} promoted candidates available",
                "applies_to": "evolution",
            }
        )

    mode = "stable"
    blocking_decisions = {"throttle-runtime", "kernel-freeze"}
    if kernel_mode.get("kernel_freeze") or any(
        item["decision"] in blocking_decisions for item in decisions
    ):
        mode = "constrained"
    if state_kernel.get("open_error_escalations", 0) > 0:
        mode = "operator_attention"

    return {
        "mode": mode,
        "decisions": decisions,
        "decision_count": len(decisions),
    }


def _derive_execution_policy(
    decision: dict[str, Any],
    verification: dict[str, Any],
    ai_testing: dict[str, Any],
    kernel_mode: dict[str, Any],
    guard: dict[str, Any],
    identity_gate: dict[str, Any],
) -> str:
    delayed_verification = verification.get("delayed_verification") or verification.get(
        "patch_gate", {}
    )
    delayed_verification_status = str(delayed_verification.get("status") or "unknown")
    release_gate_status = str((verification.get("release_gate") or {}).get("status") or "unknown")
    ai_status = str(ai_testing.get("status") or "missing")
    ai_release_signal = str(ai_testing.get("release_signal") or "signal_only").strip().lower()
    ai_error_count = int(ai_testing.get("error_count", 0) or 0)
    ai_blocks_execution = bool(ai_testing.get("blocks_execution"))
    ai_blocking_release_failures = [
        str(item)
        for item in (ai_testing.get("failed_release_blocker_case_ids") or [])
        if str(item).strip()
    ]
    decision_mode = str(decision.get("mode") or "unknown")
    identity_status = str(identity_gate.get("status") or "unknown")

    if kernel_mode.get("kernel_freeze"):
        return "signal_only"
    if identity_status != "stable":
        return "signal_only"
    if decision_mode in {"constrained", "operator_attention", "attention", "lean_execution"}:
        return "signal_only"
    if not guard.get("allow_brain_loop", True):
        return "signal_only"
    if delayed_verification_status != "pass":
        return "signal_only"
    if release_gate_status != "pass":
        return "signal_only"
    if ai_blocks_execution or ai_blocking_release_failures:
        return "signal_only"
    if ai_error_count > 0 and ai_release_signal not in {"signal_only", "sampled_async"}:
        return "signal_only"
    if (
        ai_status in {"warning", "degraded", "attention", "missing"}
        and ai_release_signal not in {"signal_only", "sampled_async", "ready"}
    ):
        return "signal_only"
    return "active"


def _audit_system(messages: list[dict[str, Any]]) -> dict[str, Any]:
    recent_messages = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "severity": item.get("severity"),
            "title": item.get("title"),
            "task_id": item.get("task_id"),
        }
        for item in messages[-10:]
    ]
    audit = {
        "updated_at": _utc(),
        "recent_log_tail": _tail_log(15),
        "recent_messages": recent_messages,
        "open_policy_violations": sum(
            1
            for item in messages
            if item.get("status", "open") == "open" and item.get("severity") == "error"
        ),
    }
    _save_json(AUDIT, audit)
    return audit


def _reputation_summary(reputation: dict[str, Any]) -> dict[str, Any]:
    capabilities = reputation.get("capabilities") or {}
    workers = reputation.get("workers") or {}
    top_capabilities = sorted(
        [{"capability_id": key, **(value or {})} for key, value in capabilities.items()],
        key=lambda item: float(item.get("score", 0.0) or 0.0),
        reverse=True,
    )[:8]
    top_workers = sorted(
        [{"worker": key, **(value or {})} for key, value in workers.items()],
        key=lambda item: float(item.get("score", 0.0) or 0.0),
        reverse=True,
    )[:8]
    return {
        "capability_count": len(capabilities),
        "worker_count": len(workers),
        "top_capabilities": top_capabilities,
        "top_workers": top_workers,
    }


def _policy_engine() -> dict[str, Any]:
    return {
        "approval_policy": _load_json(POLICY, {}),
        "guard_policy": _load_json(GUARD_POLICY, {}),
        "quality_policy": _load_json(QUALITY_POLICY, {}),
    }


def run_control_layer(
    verification_snapshot: dict[str, Any] | None = None,
    *,
    quality_snapshot: dict[str, Any] | None = None,
    refresh_autonomy: bool = False,
    refresh_tool_health: bool = False,
    refresh_release_operations: bool = False,
) -> dict[str, Any]:
    previous_payload = _load_json(OUT, {})

    def load_snapshot(path: Path, default: Any, previous: Any = None):
        payload = _load_json(path, None)
        if payload not in (None, {}, []):
            return payload
        if previous not in (None, {}, []):
            return previous
        return default

    def quality_counts(quality_payload: dict[str, Any]) -> tuple[int, int]:
        promoted_platforms = quality_payload.get("promoted_platforms")
        if isinstance(promoted_platforms, list):
            platform_count = len(promoted_platforms)
        else:
            platform_count = sum(
                1
                for item in (quality_payload.get("platform_scores") or [])
                if (item or {}).get("quality_status") == "promote"
            )
        promoted_candidates = quality_payload.get("promoted_candidates")
        if isinstance(promoted_candidates, list):
            candidate_count = len(promoted_candidates)
        else:
            candidate_count = sum(
                1
                for item in (quality_payload.get("platform_scores") or [])
                if (item or {}).get("quality_status") == "candidate"
            )
        return platform_count, candidate_count

    def patch_summary() -> dict[str, Any]:
        submissions = list((_load_json(DATA / "patch_submissions.json", {}) or {}).get("submissions") or [])
        previous_patch = previous_payload.get("patch_system") or {}
        ready_count = sum(1 for item in submissions if item.get("merge_status") == "ready")
        blocked_count = sum(
            1
            for item in submissions
            if item.get("merge_status") == "blocked" and item.get("status") not in {"rejected", "merged"}
        )
        review_pending_count = sum(
            1
            for item in submissions
            if item.get("merge_status") in {"review_pending", "pending_review"}
            or (
                item.get("status") in {"submitted", "pending_review", "approved"}
                and item.get("merge_status") not in {"ready", "blocked", "merged"}
            )
        )
        merged_count = sum(
            1
            for item in submissions
            if item.get("status") == "merged" or item.get("merge_status") == "merged"
        )
        open_count = sum(
            1 for item in submissions if item.get("status") not in {"merged", "rejected", "cancelled", "closed"}
        )
        verified_count = sum(1 for item in submissions if item.get("verification_status") == "pass")
        recent = [
            {
                "patch_id": item.get("patch_id"),
                "status": item.get("status"),
                "title": item.get("title"),
                "verification_status": item.get("verification_status"),
            }
            for item in submissions[-5:]
        ][::-1]
        return {
            "status": "attention" if blocked_count or review_pending_count else "pass",
            "submission_count": len(submissions),
            "open_count": open_count,
            "verified_count": verified_count,
            "ready_count": ready_count,
            "merged_count": merged_count,
            "review_pending_count": review_pending_count,
            "queue": {
                "ready_count": ready_count,
                "blocked_count": blocked_count,
                "review_pending_count": review_pending_count,
            },
            "recent": recent or list((previous_patch.get("recent") or []))[:5],
        }

    try:
        guard = run_guard()
    except Exception:
        guard = _load_json(GUARD, {"status": "unknown"})
    quality = quality_snapshot or load_snapshot(
        QUALITY,
        {"status": "unknown", "overall_score": 0.0},
        previous_payload.get("quality_system"),
    )
    evolution = _load_json(EVOLUTION, {"allowed": False})
    usage = _load_json(USAGE, {"strong_ratio": 0.0, "strong_allowed": True})
    messages = _load_json(CORE_MESSAGES, [])
    capabilities = _load_json(CAPABILITIES, {}).get("capabilities", [])
    platforms = _load_json(PLATFORMS, {}).get("platforms", [])
    kernel_mode = load_kernel_mode()
    governance_enabled = is_component_enabled("governance", kernel_mode)
    observer_enabled = is_component_enabled("observer", kernel_mode)
    experiments_enabled = is_component_enabled("experiments", kernel_mode)
    task_engine = _load_json(TASK_ENGINE, {})

    previous_state = previous_payload.get("state_kernel") or {}
    supply = task_engine.get("supply_after_seed") or {}
    active_tasks = int(
        supply.get("active_task_count", previous_state.get("active_tasks", previous_state.get("agents_running", 0)))
        or 0
    )
    open_messages = [item for item in messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_messages if item.get("severity") == "error"]
    state_kernel = {
        "agents_running": active_tasks,
        "active_tasks": active_tasks,
        "failed_tasks": int(previous_state.get("failed_tasks", 0) or 0),
        "capabilities": len(capabilities),
        "platforms": len(platforms),
        "open_escalations": len(open_messages),
        "open_error_escalations": len(open_errors),
        "task_ids": list(previous_state.get("task_ids") or [])[:8],
        "platform_ids": [item.get("platform_id") for item in platforms[:8]],
    }
    resource = _resource_governor(guard, usage)
    audit = _audit_system(messages)
    policy = _policy_engine()

    tools = list_tools()
    knowledge = load_snapshot(
        DATA / "knowledge_base.json",
        {
            "decision_patterns": [],
            "failure_solutions": [],
            "agent_knowledge": [],
            "experiment_patterns": [],
            "repo_learning": {},
            "embedding": {},
        },
        previous_payload.get("knowledge_system"),
    )
    experiment_plan = _load_json(DATA / "experiment_plan.json", {}) if experiments_enabled else _disabled_status("experiment_plan", kernel_mode)
    capability_reputation = _load_json(CAPABILITY_REPUTATION, {"capabilities": {}, "workers": {}})
    project_graph = load_snapshot(
        DATA / "project_graph.json",
        {"project_count": 0, "platform_count": 0, "edges": [], **_disabled_status("project_graph", kernel_mode)},
        previous_payload.get("project_graph"),
    )
    organization = load_snapshot(
        DATA / "organization_model.json",
        {
            "departments": {},
            "teams": {},
            "functional_groups": {},
            "project_allocations": [],
            **_disabled_status("organization_layer", kernel_mode),
        },
        previous_payload.get("organization_layer"),
    )
    global_policy = load_snapshot(
        DATA / "global_policy_state.json",
        {"organization_priority": {"departments": []}, **_disabled_status("global_policy_engine", kernel_mode)},
        previous_payload.get("global_policy_engine"),
    )
    cross_project = load_snapshot(
        DATA / "cross_project_coordination.json",
        {"candidate_count": 0, "selected": [], **_disabled_status("cross_project_coordination", kernel_mode)},
        previous_payload.get("cross_project_coordination"),
    )
    experiment_run = _load_json(DATA / "experiment_run.json", {}) if experiments_enabled else _disabled_status("experiment_run", kernel_mode)
    experiment_eval = _load_json(DATA / "experiment_evaluation.json", {}) if experiments_enabled else _disabled_status("experiment_evaluation", kernel_mode)
    self_model = load_snapshot(DATA / "self_model_runtime.json", {}, previous_payload.get("self_model"))
    platform_health = previous_payload.get("platform_runtime") or {"status": "signal-only", "platform_count": len(platforms), "unhealthy_count": 0}
    decision_status = _load_json(DECISION_ENGINE, {})
    code_graph = load_snapshot(
        DATA / "code_knowledge_graph.json",
        {"module_count": 0, "edge_count": 0, "domains": [], **_disabled_status("code_knowledge_graph", kernel_mode)},
        previous_payload.get("code_knowledge_graph"),
    )
    ownership_graph = load_snapshot(
        DATA / "module_ownership_graph.json",
        {"module_count": 0, "teams": {}, **_disabled_status("module_ownership_graph", kernel_mode)},
        previous_payload.get("module_ownership_graph"),
    )
    review_policy_graph = load_snapshot(
        DATA / "review_policy_graph.json",
        {"review_edge_count": 0, "module_count": 0, **_disabled_status("review_policy_graph", kernel_mode)},
        previous_payload.get("review_policy_graph"),
    )
    organization_workboard = load_snapshot(
        DATA / "organization_workboard.json",
        {"department_count": 0, "top_departments": [], "departments": {}, **_disabled_status("organization_workboard", kernel_mode)},
        (previous_payload.get("organization_layer") or {}).get("workboard"),
    )
    branch_workboard = load_snapshot(
        DATA / "branch_workboard.json",
        {"lane_count": 0, "active_lane_count": 0, "department_priority_map": {}, "active_lanes": [], **_disabled_status("branch_workboard", kernel_mode)},
        (previous_payload.get("branch_system") or {}).get("workboard"),
    )
    dependency_impact = load_snapshot(
        DATA / "dependency_impact.json",
        {"focus_modules": [], "impacted_modules": [], "affected_teams": [], **_disabled_status("dependency_impact_engine", kernel_mode)},
        previous_payload.get("dependency_impact_engine"),
    )
    architecture = load_snapshot(
        DATA / "architecture_validation.json",
        {"status": "disabled", "violation_count": 0, "reason": "architecture validation disabled by lean_execution"},
        previous_payload.get("architecture_validator"),
    )
    verification = verification_snapshot or load_snapshot(DATA / "verification_status.json", {"status": "attention"}, previous_payload.get("verification_engine"))
    patch_system = patch_summary()
    engineering_os_status = (
        "lean_execution"
        if kernel_mode.get("profile") == "lean_execution"
        else "pass"
        if (
            architecture.get("status") == "pass"
            and (verification.get("patch_gate") or {}).get("status") == "pass"
            and (verification.get("delayed_verification") or {}).get("status") == "pass"
            and (verification.get("release_gate") or {}).get("status") == "pass"
            and (patch_system.get("queue") or {}).get("blocked_count", 0) == 0
        )
        else "attention"
    )
    lab_status = load_snapshot(
        DATA / "automation_lab_status.json",
        _disabled_status("automation_lab", kernel_mode),
        previous_payload.get("automation_lab"),
    )
    release_ops = (
        run_release_operations_status()
        if refresh_release_operations
        else load_snapshot(
            DATA / "release_operations_status.json",
            {
                "release_train": {"status": "signal-only", "blocked_patch_count": 0},
                "operations_readiness": {"runtime_ok": True, "verification_ok": True, "control_ok": True},
                **_disabled_status("release_operations", kernel_mode),
            },
            previous_payload.get("release_operations"),
        )
    )
    change_attribution = run_change_attribution_status() if refresh_release_operations else load_snapshot(
        DATA / "change_attribution_status.json",
        {"status": "unknown", "recent_changes": [], "decision_summary": {}},
        previous_payload.get("change_attribution"),
    )
    self_repair_playbooks = run_self_repair_playbooks() if refresh_release_operations else load_snapshot(
        DATA / "self_repair_playbooks_status.json",
        {"status": "unknown", "active_playbooks": [], "catalog": []},
        previous_payload.get("self_repair_playbooks"),
    )
    autonomy = run_autonomy_score(
        quality_snapshot=quality,
        release_operations_snapshot=release_ops,
    ) if refresh_autonomy else load_snapshot(
        DATA / "autonomy_score.json",
        {},
        previous_payload.get("autonomy_score"),
    )
    rnd_department = load_snapshot(DATA / "rnd_department_status.json", _disabled_status("rnd_department", kernel_mode), previous_payload.get("rnd_department"))
    rnd_delivery_pipeline = load_snapshot(DATA / "rnd_delivery_pipeline_status.json", _disabled_status("rnd_delivery_pipeline", kernel_mode), previous_payload.get("rnd_delivery_pipeline"))
    rnd_asset_governance = load_snapshot(DATA / "rnd_asset_governance_status.json", _disabled_status("rnd_asset_governance", kernel_mode), previous_payload.get("rnd_asset_governance"))
    governance_contract = load_governance_contract()
    governance_split = summarize_governance_contract(governance_contract)
    economics = load_snapshot(DATA / "economics_engine_status.json", {"status": "signal-only", "score": None}, previous_payload.get("economics_engine"))
    tool_history = _load_json(DATA / "tool_health_history.json", {})
    if isinstance(tool_history, list):
        tool_recent = tool_history
    else:
        tool_recent = tool_history.get("recent") or []
    latest_tool_health = (
        run_tool_health_audit()
        if refresh_tool_health
        else (tool_recent[-1] if tool_recent else previous_payload.get("tool_health") or {})
    )
    tool_health = {
        "status": latest_tool_health.get("status", "signal-only"),
        "issue_count": int(latest_tool_health.get("issue_count", len(latest_tool_health.get("issues", []))) or 0),
        "issues": list(latest_tool_health.get("issues", []))[:10],
    }
    memory_quality_scorecard = load_snapshot(
        DATA / "memory_quality_scorecard.json",
        {
            "status": "unknown",
            "overall_score": None,
            "write_quality": {"status": "unknown"},
            "recall_hit_rate": {"status": "unknown"},
            "behavior_binding": {"status": "unknown"},
            "anti_drift": {"status": "unknown"},
        },
        previous_payload.get("memory_quality_scorecard"),
    )
    memory_muscle_benchmark = load_snapshot(
        DATA / "memory_muscle_benchmark.json",
        {
            "status": "unknown",
            "overall_score": None,
            "sediment": {"status": "unknown"},
            "promote": {"status": "unknown"},
            "recall": {"status": "unknown"},
            "binding": {"status": "unknown"},
            "reproduce": {"status": "unknown"},
        },
        previous_payload.get("memory_muscle_benchmark"),
    )
    environment_repair = _load_json(DATA / "environment_repair_status.json", {})
    ai_testing = load_ai_test_status() or previous_payload.get("ai_testing") or {
        "status": "disabled",
        "pass_rate": None,
        "error_count": 0,
        "failing_case_ids": [],
    }
    refresh_identity = bool(
        refresh_autonomy
        or refresh_tool_health
        or verification_snapshot is not None
        or quality_snapshot is not None
    )
    identity_kernel = identity_kernel_status(refresh=refresh_identity)
    identity_gate = {
        "status": identity_kernel.get("status"),
        "consistency": identity_kernel.get("consistency") or {},
        "memory": identity_kernel.get("memory") or {},
        "authority": identity_kernel.get("authority") or {},
        "runtime": identity_kernel.get("runtime") or {},
        "updated_at": identity_kernel.get("updated_at"),
    }
    decision = _decision_engine(guard, quality, evolution, state_kernel, verification, ai_testing, kernel_mode)
    if identity_gate.get("status") != "stable":
        decision = {
            **decision,
            "mode": "attention",
            "decisions": [
                {
                    "decision": "gate-on-identity",
                    "reason": f"identity kernel status={identity_gate.get('status')}",
                    "applies_to": "control-plane",
                },
                *decision.get("decisions", []),
            ],
            "decision_count": int(decision.get("decision_count") or 0) + 1,
        }
    execution_policy = _derive_execution_policy(
        decision, verification, ai_testing, kernel_mode, guard, identity_gate
    )
    identity_runtime = dict(identity_gate.get("runtime") or {})
    identity_runtime.update(
        {
            "control_status": execution_policy,
            "autonomy_stage": autonomy.get("stage"),
            "autonomy_score": autonomy.get("score"),
            "quality_status": quality.get("status"),
            "quality_score": quality.get("overall_score"),
        }
    )
    identity_gate["runtime"] = identity_runtime
    promoted_platform_count, promoted_candidate_count = quality_counts(quality)

    def _merge_signals(*paths: tuple[str, str]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for policy in (
            verification.get("signal_policy") or {},
            autonomy.get("signal_policy") or {},
            self_model.get("signal_policy") or {},
        ):
            for bucket, _label in paths:
                category = {
                    "runtime_blockers": "runtime_blocker",
                    "maturity_signals": "maturity",
                    "release_gate_signals": "release",
                }.get(bucket, "advisory")
                effect_map = {
                    "runtime_blocker": "degrade_freeze_recovery",
                    "maturity": "dashboard_weekly_trend",
                    "release": "stage_gate_release_claims",
                    "advisory": "observe_only",
                }
                for item in policy.get(bucket) or []:
                    if isinstance(item, dict):
                        code = str(item.get("code") or "").strip()
                        signal_item = dict(item)
                    else:
                        code = str(item or "").strip()
                        signal_item = {
                            "code": code,
                            "category": category,
                            "source": "legacy",
                            "detail": None,
                            "effect": effect_map.get(category),
                            "affects_runtime": category == "runtime_blocker",
                            "affects_release": category in {"runtime_blocker", "release"},
                            "affects_reporting": True,
                            "whitelisted": False,
                        }
                    if not code or code in merged:
                        continue
                    merged[code] = signal_item
        return list(merged.values())

    runtime_signals = _merge_signals(("runtime_blockers", "Runtime"))
    maturity_signals = _merge_signals(("maturity_signals", "Maturity"))
    release_signals = _merge_signals(("release_gate_signals", "Release Readiness"))
    verification_release_gate = verification.get("release_gate") or {}
    promotion_gate = release_ops.get("promotion_gate") or {}
    release_claim_policy = release_ops.get("release_claim_policy") or {}
    release_blocking_enforced = bool(release_ops.get("blocking_enforced"))
    release_blocks_promotion = bool(promotion_gate.get("blocks_promotion"))
    release_blocks_verification = bool(verification_release_gate.get("blocks_release") or release_claim_policy.get("blocks_release"))
    release_hard_gate = bool(verification_release_gate.get("hard_gate_recommended"))
    release_mode = (
        "blocking_gate"
        if release_blocking_enforced or release_blocks_promotion or release_blocks_verification
        else "gated_ready"
    )
    release_status = (
        "blocked"
        if release_blocks_promotion or release_blocks_verification
        else str(release_claim_policy.get("status") or verification_release_gate.get("status") or promotion_gate.get("status") or "pass")
    )
    release_dashboard_signals = release_signals if release_status != "pass" else []
    signal_dashboard = {
        "Runtime": {
            "status": "blocked" if runtime_signals else "healthy",
            "signal_count": len(runtime_signals),
            "signals": runtime_signals,
        },
        "Maturity": {
            "status": "attention" if maturity_signals else "ok",
            "signal_count": len(maturity_signals),
            "signals": maturity_signals,
        },
        "Release Readiness": {
            "status": "attention" if release_dashboard_signals else "ready",
            "signal_count": len(release_dashboard_signals),
            "signals": release_dashboard_signals,
        },
    }

    payload = {
        "updated_at": _utc(),
        "status": decision["mode"],
        "kernel_mode": kernel_mode,
        "enabled_components": kernel_mode.get("enabled_components", []),
        "disabled_components": kernel_mode.get("disabled_components", []),
        "policy_engine": policy,
        "control_policy": {
            "mode": "weak_control",
            "execution": execution_policy,
            "verification": {
                "mode": (verification.get("delayed_verification") or verification.get("patch_gate", {})).get("mode", "delayed"),
                "status": (verification.get("delayed_verification") or verification.get("patch_gate", {})).get("status"),
            },
            "release": {
                "mode": release_mode,
                "status": release_status,
                "blocks_release": release_blocks_verification,
                "blocks_promotion": release_blocks_promotion,
                "hard_gate_recommended": release_hard_gate,
                "blocking_enforced": release_blocking_enforced,
            },
            "signal_dashboard": signal_dashboard,
        },
        "governance_contract": governance_contract,
        "governance_split": governance_split,
        "decision_engine": decision,
        "state_kernel": state_kernel,
        "audit_system": audit,
        "resource_governor": resource,
        "task_engine": {
            "status": task_engine.get("status"),
            "seeded_goal_count": len(task_engine.get("seeded_goals", [])),
            "repaired_graph_count": len(task_engine.get("repaired_graphs", [])),
            "active_task_count": (task_engine.get("supply_after_seed") or {}).get("active_task_count"),
            "ready_node_count": (task_engine.get("supply_after_seed") or {}).get("ready_node_count"),
            "pools": (task_engine.get("supply_after_seed") or {}).get("pools", {}),
        },
        "quality_system": {
            "status": quality.get("status"),
            "overall_score": quality.get("overall_score"),
            "promoted_platform_count": promoted_platform_count,
            "promoted_candidate_count": promoted_candidate_count,
            "readiness_checks": quality.get("readiness_checks") or [],
            "readiness_summary": quality.get("readiness_summary") or {
                "status": "attention" if quality.get("status") != "promote" else "pass",
                "failing_checks": [],
                "next_action": "observe-only",
            },
        },
        "safety_system": {"status": guard.get("status"), "reasons": guard.get("reasons", [])},
        "evolution_system": {
            "allowed": False if kernel_mode.get("kernel_freeze") else evolution.get("allowed"),
            "reason": "kernel freeze active" if kernel_mode.get("kernel_freeze") else evolution.get("reason"),
            "selected_count": evolution.get("selected_count", 0),
        },
        "tool_system": {
            "tool_count": len(tools),
            "domains": sorted({item.get("domain") for item in tools if item.get("domain")}),
            "providers": sorted({item.get("provider") for item in tools if item.get("provider")})[:12],
        },
        "tool_health": tool_health,
        "memory_quality_scorecard": {
            "status": memory_quality_scorecard.get("status"),
            "overall_score": memory_quality_scorecard.get("overall_score"),
            "write_quality": (memory_quality_scorecard.get("write_quality") or {}).get("status"),
            "recall_hit_rate": (memory_quality_scorecard.get("recall_hit_rate") or {}).get("status"),
            "behavior_binding": (memory_quality_scorecard.get("behavior_binding") or {}).get("status"),
            "anti_drift": (memory_quality_scorecard.get("anti_drift") or {}).get("status"),
        },
        "memory_muscle_benchmark": {
            "status": memory_muscle_benchmark.get("status"),
            "overall_score": memory_muscle_benchmark.get("overall_score"),
            "sediment": (memory_muscle_benchmark.get("sediment") or {}).get("status"),
            "promote": (memory_muscle_benchmark.get("promote") or {}).get("status"),
            "recall": (memory_muscle_benchmark.get("recall") or {}).get("status"),
            "binding": (memory_muscle_benchmark.get("binding") or {}).get("status"),
            "reproduce": (memory_muscle_benchmark.get("reproduce") or {}).get("status"),
        },
        "economics_engine": {
            "status": economics.get("status"),
            "score": economics.get("score"),
            "currency": (economics.get("currency_system") or {}).get("unit"),
            "price_index_mfc": (economics.get("resource_market") or {}).get("price_index"),
            "open_task_count": (economics.get("task_market") or {}).get("open_task_count"),
            "reward_pool_mfc": (economics.get("task_market") or {}).get("reward_pool_mfc"),
            "total_budget_mfc": (economics.get("agent_budget_system") or {}).get("total_budget_mfc"),
            "suspended_agent_count": (economics.get("bankruptcy_system") or {}).get("suspended_agent_count"),
            "completed_value_mfc": (economics.get("ai_gdp") or {}).get("completed_value_mfc"),
        },
        "environment_repair": {
            "status": environment_repair.get("status", "unknown"),
            "mode": environment_repair.get("mode"),
            "db_runtime_passed": (environment_repair.get("db_runtime") or {}).get("passed"),
            "verification_status": (environment_repair.get("verification") or {}).get("status"),
            "workspace": environment_repair.get("workspace"),
        },
        "knowledge_system": {
            "decision_patterns": len(knowledge.get("decision_patterns", [])),
            "failure_solutions": len(knowledge.get("failure_solutions", [])),
            "agent_knowledge": len(knowledge.get("agent_knowledge", [])),
            "experiment_patterns": len(knowledge.get("experiment_patterns", [])),
            "repo_learning_chunks": (knowledge.get("repo_learning") or {}).get("chunk_count", 0),
            "embedding_backend": (knowledge.get("embedding") or {}).get("backend"),
        },
        "code_knowledge_graph": {
            "module_count": code_graph.get("module_count", 0),
            "edge_count": code_graph.get("edge_count", 0),
            "domains": code_graph.get("domains", []),
            "status": code_graph.get("status", "pass" if observer_enabled else "disabled"),
        },
        "module_ownership_graph": {
            "module_count": ownership_graph.get("module_count", 0),
            "team_count": len(ownership_graph.get("teams", {})),
            "status": ownership_graph.get("status", "pass" if governance_enabled else "disabled"),
        },
        "review_policy_graph": {
            "review_edge_count": review_policy_graph.get("review_edge_count", 0),
            "module_count": review_policy_graph.get("module_count", 0),
            "status": review_policy_graph.get("status", "pass" if governance_enabled else "disabled"),
        },
        "dependency_impact_engine": {
            "focus_modules": len(dependency_impact.get("focus_modules", [])),
            "impacted_modules": len(dependency_impact.get("impacted_modules", [])),
            "affected_teams": dependency_impact.get("affected_teams", []),
            "status": dependency_impact.get("status", "pass" if governance_enabled else "disabled"),
        },
        "project_graph": {
            "project_count": project_graph.get("project_count", 0),
            "platform_count": project_graph.get("platform_count", 0),
            "edge_count": len(project_graph.get("edges", [])),
            "status": project_graph.get("status", "pass" if governance_enabled else "disabled"),
        },
        "cross_project_coordination": {
            "candidate_count": cross_project.get("candidate_count", 0),
            "selected": cross_project.get("selected", [])[:3],
            "status": cross_project.get("status", "pass" if governance_enabled else "disabled"),
        },
        "organization_layer": {
            "department_count": len((organization.get("departments") or {})),
            "team_count": len((organization.get("teams") or {})),
            "functional_group_count": len((organization.get("functional_groups") or {})),
            "project_allocation_count": len((organization.get("project_allocations") or [])),
            "top_departments": global_policy.get("organization_priority", {}).get("departments", []),
            "workboard": organization_workboard,
            "status": organization.get("status", "pass" if governance_enabled else "disabled"),
        },
        "rnd_department": rnd_department,
        "rnd_delivery_pipeline": rnd_delivery_pipeline,
        "rnd_asset_governance": rnd_asset_governance,
        "branch_system": {
            "lane_count": branch_workboard.get("lane_count", 0),
            "active_lane_count": branch_workboard.get("active_lane_count", 0),
            "department_priority_map": branch_workboard.get("department_priority_map", {}),
            "active_lanes": branch_workboard.get("active_lanes", []),
            "workboard": branch_workboard,
            "status": branch_workboard.get("status", "pass" if governance_enabled else "disabled"),
        },
        "architecture_validator": {
            "status": architecture.get("status"),
            "violation_count": architecture.get("violation_count", 0),
        },
        "verification_engine": {
            "status": verification.get("status"),
            "compileall_passed": (verification.get("compileall") or {}).get("passed", False),
            "patch_gate_status": (verification.get("patch_gate") or {}).get("status"),
            "delayed_verification_status": (verification.get("delayed_verification") or {}).get("status"),
            "release_gate_status": (verification.get("release_gate") or {}).get("status"),
            "runtime_health_status": (verification.get("runtime_health") or {}).get("status"),
            "tool_health_status": (verification.get("tool_health") or {}).get("status"),
            "signal_policy": verification.get("signal_policy") or {},
        },
        "identity_gate": identity_gate,
        "ai_testing": ai_testing,
        "reputation_system": _reputation_summary(capability_reputation),
        "patch_system": patch_system,
        "engineering_os": {
            "status": engineering_os_status,
            "code_graph_modules": code_graph.get("module_count", 0),
            "architecture_status": architecture.get("status"),
            "patch_gate_status": (verification.get("patch_gate") or {}).get("status"),
            "delayed_verification_status": (verification.get("delayed_verification") or {}).get("status"),
            "release_gate_status": (verification.get("release_gate") or {}).get("status"),
            "patch_ready_count": (patch_system.get("queue") or {}).get("ready_count", 0),
            "patch_blocked_count": (patch_system.get("queue") or {}).get("blocked_count", 0),
            "active_branch_lane_count": branch_workboard.get("active_lane_count", 0),
            "signal_dashboard": signal_dashboard,
            "signal_policy": {
                "verification": verification.get("signal_policy") or {},
                "autonomy": autonomy.get("signal_policy") or {},
                "self_model": self_model.get("signal_policy") or {},
            },
        },
        "signal_dashboard": signal_dashboard,
        "signal_policy": {
            "verification": verification.get("signal_policy") or {},
            "self_model": self_model.get("signal_policy") or {},
            "autonomy": autonomy.get("signal_policy") or {},
        },
        "global_policy_engine": global_policy,
        "experiment_system": {
            "plan_candidate_count": experiment_plan.get("candidate_count", 0),
            "selected": experiment_plan.get("selected"),
            "run_status": experiment_run.get("status"),
            "evaluation_status": experiment_eval.get("status"),
            "evaluation_score": experiment_eval.get("score"),
            "adopt": experiment_eval.get("adopt", False),
        },
        "autonomous_decision_system": {
            "action": decision_status.get("action"),
            "reason": decision_status.get("reason"),
            "active_goals": decision_status.get("active_goals", 0),
            "candidate_count": decision_status.get("candidate_count", 0),
            "selected": decision_status.get("selected"),
        },
        "autonomy_score": autonomy,
        "platform_runtime": platform_health,
        "automation_lab": lab_status,
        "release_operations": release_ops,
        "change_attribution": change_attribution,
        "self_repair_playbooks": self_repair_playbooks,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_control_layer(), ensure_ascii=False, indent=2))
