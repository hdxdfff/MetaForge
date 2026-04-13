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

from tools.control_plane_policy import load_control_policy, project_approval_policy, project_tool_policy
from tools.execution_trace import append_trace
from tools.identity_kernel import build_identity_kernel
from tools.io_utils import atomic_write_json, atomic_write_text

AUTONOMY_SCORE_PATH = DATA / "autonomy_score.json"
INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"
INDUSTRIAL_READINESS_PATH = DATA / "industrial_readiness.json"
RELEASE_OPERATIONS_PATH = DATA / "release_operations_status.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
QUEUE_PRESSURE_PATH = DATA / "queue_pressure_analysis.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
SLO_REGISTRY_PATH = DATA / "production_slo_registry.json"
BUDGET_SUPPRESSION_PATH = DATA / "budget_suppression_report.json"
CONTROL_PLANE_PATH = DATA / "autonomy_control_plane.json"
CONTROL_PLANE_MD_PATH = DATA / "autonomy_control_plane.md"
CONTROL_PLANE_SUMMARY_PATH = DATA / "autonomy_control_plane_summary.json"
CONTROL_PLANE_SUMMARY_MD_PATH = DATA / "autonomy_control_plane_summary.md"

AUTO_EXECUTE_TASK_CLASSES = {
    "observe_only": {
        "task_types": ["status_check", "report_refresh", "dashboard_refresh", "doc_patch"],
        "queues": ["fastlane", "maintenance"],
    },
    "verification_and_smoke": {
        "task_types": ["artifact_audit", "qemu_smoke_run", "harness_regression_run", "runtime_health_validation"],
        "queues": ["regression", "fastlane"],
    },
    "repair_first": {
        "task_types": ["self_repair", "execution_repair", "verification_repair", "rollback_repair"],
        "queues": ["fastlane", "build_test", "regression"],
    },
}

MANUAL_APPROVAL_TASK_CLASSES = {
    "release": {
        "task_types": ["deploy_production", "release_candidate", "git_push"],
        "queues": ["release", "deployment"],
    },
    "core_mutation": {
        "task_types": ["modify_agents", "modify_controller", "filesystem.write_core", "filesystem.delete"],
        "queues": ["governance", "maintenance"],
    },
    "external_change": {
        "task_types": ["install_package", "docker.run", "cross_repo_change"],
        "queues": ["build_test", "ops", "deployment"],
    },
}

LIMITED_AUTONOMY_TASK_CLASSES = {
    "budgeted_growth": {
        "task_types": ["technical_artifact", "artifact_growth", "capability_expansion", "new_artifact_bootstrap", "new_demo_creation"],
        "queues": ["incubation", "build_test", "regression"],
        "budget_pool": "P2",
    },
    "sandbox_low_risk_growth": {
        "task_types": ["doc_patch", "report_refresh", "json_fix", "manifest_patch", "config_fix", "unit_test_run", "build_fix", "artifact_audit"],
        "queues": ["fastlane", "build_test", "regression"],
        "budget_pool": "P2",
    },
    "research": {
        "task_types": ["exploration_intake", "experiment", "research_probe"],
        "queues": ["exploration", "research"],
        "budget_pool": "P3",
    },
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _normalize_list(values: Any) -> list[str]:
    result: list[str] = []
    for item in values or []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _closed_pools(industrial_operations: dict[str, Any], budget_suppression: dict[str, Any]) -> list[str]:
    pools = list((budget_suppression or {}).get("closed_pools") or [])
    if pools:
        return pools
    pools = list((industrial_operations.get("budget_suppression") or {}).get("closed_pools") or [])
    if pools:
        return pools
    gates = ((industrial_operations.get("budget_control") or {}).get("gates") or {})
    derived: list[str] = []
    if not gates.get("allow_p2"):
        derived.append("P2")
    if not gates.get("allow_p3"):
        derived.append("P3")
    return derived


def _policy_summary(control_policy: dict[str, Any]) -> dict[str, Any]:
    approvals = project_approval_policy(control_policy)
    tooling = project_tool_policy(control_policy)
    return {
        "control_policy_path": str(DATA / "control_policy.json"),
        "approval_policy_path": str(DATA / "approval_policy.json"),
        "session_policy_path": str(DATA / "session_policy.json"),
        "tool_policy_path": str(DATA / "tool_policy.json"),
        "approvals": approvals,
        "tooling": tooling,
    }


def _task_matrix(
    industrial_operations: dict[str, Any],
    control_policy: dict[str, Any],
    approval_policy: dict[str, Any],
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    gates = (industrial_operations.get("budget_control") or {}).get("gates") or {}
    budget = (industrial_operations.get("budget_control") or {}).get("replenishment") or {}
    base = {
        "always_auto": {
            "task_types": ["status_check", "report_refresh", "dashboard_refresh"],
            "reason": "Read-only governance work does not change system state.",
            "approval": "AUTO",
        },
        "repair_first": {
            "task_types": ["self_repair", "execution_repair", "verification_repair", "rollback_repair"],
            "reason": "Repair tasks are allowed when repair-first mode is active and budgets remain.",
            "approval": "AUTO-LIMIT",
            "budget_pool": "P1",
        },
        "budgeted_growth": {
            "task_types": ["technical_artifact", "artifact_growth", "capability_expansion", "new_artifact_bootstrap", "new_demo_creation"],
            "reason": "Capability growth is only allowed when P2 is open.",
            "approval": "AUTO-LIMIT" if gates.get("allow_p2") else "BLOCKED",
            "budget_pool": "P2",
        },
        "sandbox_low_risk_growth": {
            "task_types": ["doc_patch", "report_refresh", "json_fix", "manifest_patch", "config_fix", "unit_test_run", "build_fix", "artifact_audit"],
            "reason": "Low-risk P2 sandbox work is only allowed when the dedicated sandbox gate is open.",
            "approval": "AUTO-LIMIT" if gates.get("allow_p2_sandbox") else "BLOCKED",
            "budget_pool": "P2",
        },
        "sandbox_research": {
            "task_types": ["exploration_intake", "experiment", "research_probe"],
            "reason": "Research is only allowed when P3 is open and the system is healthy.",
            "approval": "AUTO-LIMIT" if gates.get("allow_p3") else "BLOCKED",
            "budget_pool": "P3",
        },
        "manual_release": {
            "task_types": ["deploy_production", "release_candidate", "git_push", "modify_controller", "modify_agents", "filesystem.delete", "filesystem.write_core"],
            "reason": "High-impact release and core mutations require manual approval.",
            "approval": "MANUAL",
        },
    }
    approval_modes = {
        action: str(rule.get("mode") or "MANUAL").upper()
        for action, rule in approval_policy.items()
        if isinstance(rule, dict)
    }
    tooling_roles = {
        role: {
            "allow": _normalize_list(rule.get("allow")),
            "deny": _normalize_list(rule.get("deny")),
            "approval_required": _normalize_list(rule.get("approval_required")),
        }
        for role, rule in (tool_policy.get("roles") or {}).items()
        if isinstance(rule, dict)
    }
    return {
        "auto_execute": {
            "task_classes": base["always_auto"],
            "approval_mode": "AUTO",
        },
        "auto_execute_with_limits": {
            "task_classes": {
                "repair_first": base["repair_first"],
                "verification_and_smoke": AUTO_EXECUTE_TASK_CLASSES["verification_and_smoke"],
            },
            "approval_mode": "AUTO-LIMIT",
            "budget_constraint": {
                "allow_p2": bool(gates.get("allow_p2")),
                "allow_p2_sandbox": bool(gates.get("allow_p2_sandbox")),
                "allow_p3": bool(gates.get("allow_p3")),
                "repair_first": bool(gates.get("repair_first")),
                "budget_exhausted": {
                    key: bool((value or {}).get("budget_exhausted"))
                    for key, value in budget.items()
                    if isinstance(value, dict)
                },
            },
        },
        "requires_manual_approval": {
            "task_classes": {
                "release": base["manual_release"],
                "core_mutation": MANUAL_APPROVAL_TASK_CLASSES["core_mutation"],
                "external_change": MANUAL_APPROVAL_TASK_CLASSES["external_change"],
            },
            "approval_mode": "MANUAL",
            "approval_sources": approval_modes,
        },
        "sandbox_only": {
            "task_classes": {
                "budgeted_growth": base["budgeted_growth"],
                "sandbox_low_risk_growth": base["sandbox_low_risk_growth"],
                "research": base["sandbox_research"],
            },
            "approval_mode": "AUTO-LIMIT" if gates.get("allow_p2") or gates.get("allow_p2_sandbox") or gates.get("allow_p3") else "BLOCKED",
            "budget_gate": {
                "allow_p2": bool(gates.get("allow_p2")),
                "allow_p2_sandbox": bool(gates.get("allow_p2_sandbox")),
                "allow_p3": bool(gates.get("allow_p3")),
            },
        },
        "tooling": tooling_roles,
    }


def _resources_and_recovery(
    industrial_operations: dict[str, Any],
    industrial_readiness: dict[str, Any],
    release_operations: dict[str, Any],
    control_layer: dict[str, Any],
    queue_pressure: dict[str, Any],
    autonomy_score: dict[str, Any],
    budget_suppression: dict[str, Any],
) -> dict[str, Any]:
    budget_control = industrial_operations.get("budget_control") or {}
    artifact_registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    return {
        "resources": {
            "workspace_manager": {
                "write_roots": (load_control_policy().get("workspace_manager") or {}).get("write_roots") or [],
                "core_roots": (load_control_policy().get("workspace_manager") or {}).get("core_roots") or [],
            },
            "task_pools": (industrial_operations.get("task_pools") or {}),
            "budget_control": budget_control,
            "queue_pressure": {
                "pressure": queue_pressure.get("pressure"),
                "active_pressure_score": queue_pressure.get("active_pressure_score"),
            },
            "artifact_registry_status": str(artifact_registry.get("status") or ""),
            "control_layer_status": str(control_layer.get("status") or ""),
            "release_operations_status": str(release_operations.get("status") or ""),
            "industrial_readiness_status": str(industrial_readiness.get("status") or ""),
        },
        "recovery": {
            "auto_repair_sources": {
                "failure_taxonomy": str((industrial_operations.get("failure_taxonomy_path") or "")),
                "incident_summary": str(DATA / "incident_ledger_summary.json"),
                "rollback_drill": str(DATA / "release_rollback_drill.json"),
            },
            "auto_recovery_success_rate": industrial_readiness.get("slo_compliance", {}).get("auto_recovery_success_rate", {}).get("value"),
            "mttr_minutes": industrial_readiness.get("slo_compliance", {}).get("mttr_minutes", {}).get("value"),
            "retry_policy": {
                "repair_first": bool((industrial_operations.get("release_freeze") or {}).get("repair_first")),
                "allow_p0": bool((industrial_operations.get("release_freeze") or {}).get("allow_p0", True)),
                "allow_p1": bool((industrial_operations.get("release_freeze") or {}).get("allow_p1", True)),
                "allow_p2": bool((industrial_operations.get("release_freeze") or {}).get("allow_p2", False)),
                "allow_p3": bool((industrial_operations.get("release_freeze") or {}).get("allow_p3", False)),
            },
            "rollback": {
                "failed_release_rollback_time_minutes": industrial_readiness.get("slo_compliance", {}).get("failed_release_rollback_time_minutes", {}).get("value"),
                "rollback_measurement_source": industrial_readiness.get("economics_summary", {}).get("rollback_measurement", {}).get("source"),
            },
            "freeze_and_fuse": {
                "freeze_triggered": bool((industrial_operations.get("release_freeze") or {}).get("freeze_triggered")),
                "freeze_reasons": list((industrial_operations.get("release_freeze") or {}).get("freeze_reasons") or []),
                "closed_pools": _closed_pools(industrial_operations, budget_suppression),
                "sandbox_open_pools": ["P2"] if bool((industrial_operations.get("budget_control") or {}).get("gates", {}).get("allow_p2_sandbox")) else [],
                "release_gate_signal_count": int((autonomy_score.get("signal_policy") or {}).get("release_gate_signal_count") or 0),
            },
        },
    }


def _human_controls(industrial_operations: dict[str, Any]) -> dict[str, Any]:
    return {
        "editable_fields": [
            "industrial_operations.budget_control.gates.allow_p2",
            "industrial_operations.budget_control.gates.allow_p2_sandbox",
            "industrial_operations.budget_control.gates.allow_p3",
            "industrial_operations.budget_control.policy",
            "control_policy.approvals",
            "tool_policy.roles",
            "session_policy.roles",
        ],
        "approval_required_for": [
            "modify_controller",
            "modify_agents",
            "deploy_production",
            "filesystem.write_core",
            "filesystem.delete",
            "git.push",
            "install_package",
            "docker.run",
        ],
        "operator_questions": [
            "Can this task auto-execute?",
            "Do we need approval?",
            "Which budget pool does it consume?",
            "What is the rollback plan?",
            "What is the fuse condition?",
        ],
        "summary": {
            "current_operating_state": str(industrial_operations.get("status") or ""),
            "closed_pools": list((industrial_operations.get("budget_suppression") or {}).get("closed_pools") or []),
            "budget_enforced": bool((industrial_operations.get("budget_control") or {}).get("gates", {}).get("budget_enforced")),
        },
    }


def _homepage_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary") or {}
    execution_policy = report.get("execution_policy") or {}
    resources = report.get("resources") or {}
    recovery = report.get("recovery") or {}
    human_controls = report.get("human_controls") or {}
    policy_views = report.get("policy_views") or {}
    auto_limits = (execution_policy.get("auto_execute_with_limits") or {}).get("budget_constraint") or {}
    sandbox = (execution_policy.get("sandbox_only") or {}).get("budget_gate") or {}
    budgets = resources.get("budget_control") or {}
    replenishment = budgets.get("replenishment") or {}
    task_pools = resources.get("task_pools") or {}
    control_plane_closed_pools = list(summary.get("closed_pools") or [])
    auto_open = [name for name, value in {
        "P0": bool(budgets.get("gates", {}).get("allow_p0")),
        "P1": bool(budgets.get("gates", {}).get("allow_p1")),
        "P2": bool(budgets.get("gates", {}).get("allow_p2")),
        "P3": bool(budgets.get("gates", {}).get("allow_p3")),
    }.items() if value]
    auto_closed = [name for name, value in {
        "P0": not bool(budgets.get("gates", {}).get("allow_p0")),
        "P1": not bool(budgets.get("gates", {}).get("allow_p1")),
        "P2": not bool(budgets.get("gates", {}).get("allow_p2")),
        "P3": not bool(budgets.get("gates", {}).get("allow_p3")),
    }.items() if value]
    return {
        "status": report.get("status"),
        "updated_at": report.get("updated_at"),
        "headline": {
            "autonomy_stage": summary.get("autonomy_stage"),
            "control_status": summary.get("control_status"),
            "release_status": summary.get("release_status"),
            "industrial_operations_status": summary.get("industrial_operations_status"),
            "industrial_readiness_status": summary.get("industrial_readiness_status"),
            "closed_pools": control_plane_closed_pools,
        },
        "what_can_auto_run": {
            "auto_execute": (execution_policy.get("auto_execute") or {}).get("task_classes") or {},
            "auto_execute_with_limits": (execution_policy.get("auto_execute_with_limits") or {}).get("task_classes") or {},
        },
        "what_needs_approval": (execution_policy.get("requires_manual_approval") or {}).get("task_classes") or {},
        "sandbox_controls": {
            "allow_p2": bool(sandbox.get("allow_p2")),
            "allow_p2_sandbox": bool(sandbox.get("allow_p2_sandbox")),
            "allow_p3": bool(sandbox.get("allow_p3")),
            "approval_mode": (execution_policy.get("sandbox_only") or {}).get("approval_mode"),
        },
        "budget_caps": {
            "task_pools": {
                "limits": task_pools.get("limits") or {},
                "priority_order": task_pools.get("priority_order") or [],
            },
            "daily_budgets": budgets.get("daily_budgets") or {},
            "usage_24h": budgets.get("usage_24h") or {},
            "replenishment": replenishment,
            "open_pools": auto_open,
            "closed_pools": auto_closed,
        },
        "recovery_summary": {
            "auto_recovery_success_rate": recovery.get("auto_recovery_success_rate"),
            "mttr_minutes": recovery.get("mttr_minutes"),
            "failed_release_rollback_time_minutes": (recovery.get("rollback") or {}).get("failed_release_rollback_time_minutes"),
            "freeze_triggered": bool((recovery.get("freeze_and_fuse") or {}).get("freeze_triggered")),
            "release_gate_signal_count": (recovery.get("freeze_and_fuse") or {}).get("release_gate_signal_count"),
        },
        "human_controls": {
            "editable_fields": human_controls.get("editable_fields") or [],
            "approval_required_for": human_controls.get("approval_required_for") or [],
            "operator_questions": human_controls.get("operator_questions") or [],
        },
        "policy_files": policy_views,
    }


def _render_homepage_summary_md(summary: dict[str, Any]) -> str:
    headline = summary.get("headline") or {}
    budget_caps = summary.get("budget_caps") or {}
    recovery = summary.get("recovery_summary") or {}
    human = summary.get("human_controls") or {}
    what_can_auto = summary.get("what_can_auto_run") or {}
    manual = summary.get("what_needs_approval") or {}
    sandbox = summary.get("sandbox_controls") or {}
    lines: list[str] = [
        "# Autonomy Control Plane Summary",
        "",
        f"- status: {summary.get('status')}",
        f"- updated_at: {summary.get('updated_at')}",
        f"- autonomy_stage: {headline.get('autonomy_stage')}",
        f"- control_status: {headline.get('control_status')}",
        f"- release_status: {headline.get('release_status')}",
        f"- industrial_operations_status: {headline.get('industrial_operations_status')}",
        f"- industrial_readiness_status: {headline.get('industrial_readiness_status')}",
        f"- closed_pools: {', '.join(headline.get('closed_pools') or []) or 'none'}",
        f"- sandbox_p2_allowed: {sandbox.get('allow_p2_sandbox')}",
        "",
        "## P2 Sandbox",
        "",
        f"- status: {'pass' if sandbox.get('allow_p2_sandbox') else 'blocked'}",
        "- lane: p2_low_risk",
        f"- allow_p2_sandbox: {sandbox.get('allow_p2_sandbox')}",
        "- budget_pool: P2",
        f"- budget_gate: {'sandbox_open' if sandbox.get('allow_p2_sandbox') else 'sandbox_closed'}",
        "- admission_lane: sandbox_low_risk",
        "- task_classes: doc_patch, report_refresh, json_fix, manifest_patch, config_fix, unit_test_run, build_fix, artifact_audit",
        "- operator_action: can edit this field set in the control plane summary while P2 remains sandbox-only",
        "",
        "## Auto-Executable",
        "",
    ]
    auto_classes = what_can_auto.get("auto_execute") or {}
    auto_limited = what_can_auto.get("auto_execute_with_limits") or {}
    for label, payload in [
        ("AUTO", auto_classes),
        ("AUTO-LIMIT", auto_limited),
    ]:
        task_types = payload.get("task_types") or []
        if task_types:
            lines.append(f"- {label}: {', '.join(task_types)}")
    lines += [
        "",
        "## Requires Approval",
        "",
    ]
    for label, payload in manual.items():
        task_types = (payload or {}).get("task_types") or []
        if task_types:
            lines.append(f"- {label}: {', '.join(task_types)}")
    lines += [
        "",
        "## Budget / Pools",
        "",
        f"- open_pools: {', '.join(budget_caps.get('open_pools') or []) or 'none'}",
        f"- closed_pools: {', '.join(budget_caps.get('closed_pools') or []) or 'none'}",
        f"- daily_budgets: {json.dumps(budget_caps.get('daily_budgets') or {}, ensure_ascii=False)}",
        f"- usage_24h: {json.dumps(budget_caps.get('usage_24h') or {}, ensure_ascii=False)}",
        "",
        "## Recovery / Fuse",
        "",
        f"- auto_recovery_success_rate: {recovery.get('auto_recovery_success_rate')}",
        f"- mttr_minutes: {recovery.get('mttr_minutes')}",
        f"- failed_release_rollback_time_minutes: {recovery.get('failed_release_rollback_time_minutes')}",
        f"- freeze_triggered: {recovery.get('freeze_triggered')}",
        f"- release_gate_signal_count: {recovery.get('release_gate_signal_count')}",
        "",
        "## Operator Controls",
        "",
        *[f"- editable: {item}" for item in human.get("editable_fields") or []],
        *[f"- approval_required: {item}" for item in human.get("approval_required_for") or []],
        "",
        "## Policy Files",
        "",
    ]
    policy_files = summary.get("policy_files") or {}
    for key, value in policy_files.items():
        if key in {"approvals", "tooling"}:
            continue
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def run_autonomy_control_plane() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    control_policy = load_control_policy()
    approval_policy = project_approval_policy(control_policy)
    tool_policy = project_tool_policy(control_policy)
    industrial_operations = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    industrial_readiness = _load_json(INDUSTRIAL_READINESS_PATH, {})
    release_operations = _load_json(RELEASE_OPERATIONS_PATH, {})
    control_layer = _load_json(CONTROL_LAYER_PATH, {})
    queue_pressure = _load_json(QUEUE_PRESSURE_PATH, {})
    autonomy_score = _load_json(AUTONOMY_SCORE_PATH, {})
    slo_registry = _load_json(SLO_REGISTRY_PATH, {})
    budget_suppression = _load_json(BUDGET_SUPPRESSION_PATH, {})
    identity_kernel = build_identity_kernel()

    task_matrix = _task_matrix(industrial_operations, control_policy, approval_policy, tool_policy)
    resources = _resources_and_recovery(industrial_operations, industrial_readiness, release_operations, control_layer, queue_pressure, autonomy_score, budget_suppression)
    human_controls = _human_controls(industrial_operations)
    autonomy_stage = str(autonomy_score.get("stage") or "")
    control_status = str(control_layer.get("status") or "")
    release_status = str(release_operations.get("status") or "")
    budget_gates = ((industrial_operations.get("budget_control") or {}).get("gates") or {})
    report = {
        "updated_at": _utc(),
        "status": "pass",
        "summary": {
            "autonomy_stage": autonomy_stage,
            "control_status": control_status,
            "release_status": release_status,
            "industrial_operations_status": str(industrial_operations.get("status") or ""),
            "industrial_readiness_status": str(industrial_readiness.get("status") or ""),
            "budget_enforced": bool(budget_gates.get("budget_enforced")),
            "closed_pools": _closed_pools(industrial_operations, budget_suppression),
        },
        "execution_policy": task_matrix,
        "resources": resources["resources"],
        "recovery": resources["recovery"],
        "human_controls": human_controls,
        "policy_views": _policy_summary(control_policy),
        "identity": {
            "system": identity_kernel.get("identity", {}),
            "operator": identity_kernel.get("operator", {}),
            "authority": identity_kernel.get("authority", {}),
            "runtime": identity_kernel.get("runtime", {}),
        },
        "slo_registry_path": str(SLO_REGISTRY_PATH),
        "source_files": {
            "control_policy": str(DATA / "control_policy.json"),
            "approval_policy": str(DATA / "approval_policy.json"),
            "session_policy": str(DATA / "session_policy.json"),
            "tool_policy": str(DATA / "tool_policy.json"),
            "industrial_operations": str(INDUSTRIAL_OPERATIONS_PATH),
            "industrial_readiness": str(INDUSTRIAL_READINESS_PATH),
            "release_operations": str(RELEASE_OPERATIONS_PATH),
            "control_layer": str(CONTROL_LAYER_PATH),
            "autonomy_score": str(AUTONOMY_SCORE_PATH),
            "queue_pressure": str(QUEUE_PRESSURE_PATH),
            "budget_suppression": str(BUDGET_SUPPRESSION_PATH),
            "production_slo_registry": str(SLO_REGISTRY_PATH),
        },
    }
    homepage_summary = _homepage_summary(report)
    summary = report["summary"]
    atomic_write_json(CONTROL_PLANE_PATH, report)
    atomic_write_json(CONTROL_PLANE_SUMMARY_PATH, homepage_summary)
    atomic_write_text(
        CONTROL_PLANE_MD_PATH,
        "\n".join(
            [
                "# Autonomy Control Plane",
                "",
                f"- status: {report['status']}",
                f"- autonomy_stage: {summary.get('autonomy_stage')}",
                f"- control_status: {summary.get('control_status')}",
                f"- release_status: {summary.get('release_status')}",
                f"- budget_enforced: {summary.get('budget_enforced')}",
                f"- closed_pools: {', '.join(summary.get('closed_pools') or []) or 'none'}",
                "",
                "## Human Controls",
                "",
                *[f"- {item}" for item in human_controls["operator_questions"]],
                "",
                "## Approval-Required Actions",
                "",
                *[f"- {item}" for item in human_controls["approval_required_for"]],
            ]
        )
        + "\n",
    )
    atomic_write_text(CONTROL_PLANE_SUMMARY_MD_PATH, _render_homepage_summary_md(homepage_summary))
    append_trace(
        "industrial-readiness",
        "build autonomy control plane",
        "run autonomy_control_plane.py",
        f"status={report['status']} closed_pools={','.join(report['summary']['closed_pools']) or 'none'}",
        "refresh autonomy control plane or adjust approval/budget policy",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={
            "control_plane_path": str(CONTROL_PLANE_PATH),
            "control_plane_summary_path": str(CONTROL_PLANE_SUMMARY_PATH),
            "closed_pools": report["summary"]["closed_pools"],
        },
    )
    return report


def main() -> int:
    _ = argparse.ArgumentParser(description="Build the autonomy control plane snapshot.").parse_args()
    print(json.dumps(run_autonomy_control_plane(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
