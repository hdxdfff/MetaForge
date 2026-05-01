from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"

from tools.io_utils import atomic_write_json

from tools.architecture_validator import run_architecture_validation
from tools.ai_test_automation import load_ai_test_status
from tools.artifact_audit import audit_artifacts, build_reality_dashboard
from tools.code_knowledge_graph import build_code_knowledge_graph
from tools.governance_contract import load_governance_contract, summarize_governance_contract
from tools.platform_registry import platform_health_summary
from tools.signal_policy import summarize_signal_policy
from tools.quality_system import run_quality
from tools.module_ownership import patch_review_queue
from tools.project_graph import analyze_project_impact
from tools.tool_health_audit import run_tool_health_audit, read_tool_health_history
OUT = DATA / "verification_status.json"
TASKS = DATA / "tasks.json"
CORE_MESSAGES = DATA / "core_messages.json"
GRAPHS = ROOT / "factory" / "graphs"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _run_compileall() -> dict[str, Any]:
    python_exe = ROOT.parent / "tools" / "python311-embed" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)
    command = [
        str(python_exe),
        "-m",
        "compileall",
        str(ROOT / "app"),
        str(ROOT / "runtime"),
        str(ROOT / "tools"),
        str(ROOT / "agents"),
        str(ROOT / "state"),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
    return {
        "command": command,
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "stdout_tail": completed.stdout.splitlines()[-20:],
        "stderr_tail": completed.stderr.splitlines()[-20:],
    }


def _task_health() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    messages = _load_json(CORE_MESSAGES, [])
    active = [item for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"}]
    failed = [item for item in tasks if item.get("status") == "failed"]
    timed_out = [item for item in tasks if item.get("status") == "timed_out"]
    open_errors = [item for item in messages if item.get("status", "open") == "open" and item.get("severity") == "error"]
    queued_backlog = [item for item in active if item.get("status") in {"queued", "planning"}]
    stalled_active: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for item in active:
        if item.get("status") in {"queued", "planning"}:
            continue
        max_runtime = int(item.get("max_runtime_seconds") or 0)
        created_at = _parse_timestamp(item.get("created_at"))
        updated_at = _parse_timestamp(item.get("updated_at"))
        last_activity = updated_at or created_at
        if last_activity is None:
            continue
        age_seconds = max(0.0, (now - last_activity).total_seconds())
        if max_runtime > 0:
            stall_threshold = max(900, int(max_runtime * 1.25))
        else:
            stall_threshold = 6 * 60 * 60
        if age_seconds > stall_threshold:
            stalled_active.append(item)
    # Historical failures stay visible as counts, but health should reflect current unresolved load.
    healthy = len(open_errors) == 0 and len(stalled_active) == 0
    return {
        "active_tasks": len(active),
        "queued_backlog_tasks": len(queued_backlog),
        "failed_tasks": len(failed),
        "timed_out_tasks": len(timed_out),
        "open_error_escalations": len(open_errors),
        "stalled_active_tasks": len(stalled_active),
        "healthy": healthy,
    }


def _refresh_control_layer_snapshot(verification_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from tools.meta_factory_control import run_control_layer

        payload = run_control_layer(verification_snapshot=verification_payload)
        return {
            "attempted": True,
            "status": payload.get("status"),
            "updated_at": payload.get("updated_at"),
        }
    except Exception as exc:
        return {
            "attempted": True,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _tool_health_blocks_patch_gate(tool_health: dict[str, Any]) -> bool:
    issues = [str(item or '').strip() for item in (tool_health.get('issues') or []) if str(item or '').strip()]
    if not issues:
        return False
    blocking_issues = [item for item in issues if item != 'control-layer-lags-quality']
    return bool(blocking_issues)


def _governance_gate(governance_contract: dict[str, Any]) -> dict[str, Any]:
    split = summarize_governance_contract(governance_contract)
    passed = bool(split.get("status") == "pass")
    return {
        "status": "pass" if passed else "blocked",
        "passed": passed,
        "blocked": not passed,
        "blocked_reason": None if passed else "governance-contract-invalid",
        "incident_classification": split.get("incident_classification"),
        "governance_split": split,
        "next_action": "observe" if passed else "restore-governance-contract",
    }



def _ai_testing_check(ai_testing: dict[str, Any]) -> dict[str, Any]:
    status = str(ai_testing.get("status") or "missing").strip().lower()
    release_signal = str(ai_testing.get("release_signal") or "signal_only").strip().lower()
    pass_rate = float(ai_testing.get("pass_rate", 0.0) or 0.0)
    error_count = int(ai_testing.get("error_count", 0) or 0)
    total_cases = int(ai_testing.get("total_cases", 0) or 0)
    passed_cases = int(ai_testing.get("passed_cases", 0) or 0)
    all_passed = bool(ai_testing.get("all_passed")) if "all_passed" in ai_testing else bool(total_cases and passed_cases == total_cases)
    failing_case_ids = [str(item) for item in (ai_testing.get("failing_case_ids") or []) if str(item).strip()]
    failed_release_blocker_case_ids = [
        str(item)
        for item in (ai_testing.get("failed_release_blocker_case_ids") or []) if str(item).strip()
    ]
    failure_domain = str(ai_testing.get("failure_domain") or "").strip() or None
    transport_blocked = bool(ai_testing.get("transport_blocked"))
    transport_block_reason = str(ai_testing.get("transport_block_reason") or "").strip() or None
    stale = bool(ai_testing.get("stale"))
    signal_reasons: list[str] = []
    if status in {"degraded", "attention", "missing", "warning"}:
        signal_reasons.append(f"status={status}")
    if release_signal not in {"ready", "signal_only", "sampled_async"}:
        signal_reasons.append(f"release_signal={release_signal}")
    if error_count > 0:
        signal_reasons.append(f"errors={error_count}")
    if stale:
        signal_reasons.append("status=stale")
    if transport_blocked:
        signal_reasons.append(f"transport_blocked={transport_block_reason or 'unknown'}")
    if total_cases <= 0:
        signal_reasons.append("total_cases=0")
    elif not all_passed and not transport_blocked:
        signal_reasons.append(f"failing_cases={','.join(failing_case_ids[:5]) or 'unknown'}")
    if failed_release_blocker_case_ids:
        signal_reasons.append(f"release_blocker_failures={','.join(failed_release_blocker_case_ids[:5])}")
    blocking_reasons: list[str] = []
    if failed_release_blocker_case_ids:
        blocking_reasons.append("ai_release_blocker_failures")
    if stale:
        blocking_reasons.append("ai_testing_stale")
    if transport_blocked:
        blocking_reasons.append("ai_testing_provider_unavailable")
    if release_signal not in {"ready", "signal_only", "sampled_async"}:
        blocking_reasons.append("ai_release_signal_invalid")
    return {
        "mode": "sampled_async",
        "status": status,
        "release_signal": release_signal,
        "pass_rate": pass_rate,
        "passed_cases": passed_cases,
        "total_cases": total_cases,
        "all_passed": all_passed,
        "error_count": error_count,
        "error_types": list(ai_testing.get("error_types", []))[:10],
        "failing_case_ids": failing_case_ids[:10],
        "failed_release_blocker_case_ids": failed_release_blocker_case_ids[:10],
        "failure_domain": failure_domain,
        "case_failures_are_behavioral": bool(ai_testing.get("case_failures_are_behavioral", True)),
        "stale": stale,
        "stale_seconds": ai_testing.get("stale_seconds"),
        "transport_blocked": transport_blocked,
        "transport_block_reason": transport_block_reason,
        "provider_diagnostics": ai_testing.get("provider_diagnostics") or {},
        "signal_reasons": signal_reasons,
        "blocking_reasons": blocking_reasons,
        "signal_only": not bool(blocking_reasons),
        "blocks_execution": False,
        "blocks_patch_gate": False,
        "blocks_release": bool(blocking_reasons),
        "passed": not bool(blocking_reasons),
    }


def _fact_consistency_check(quality: dict[str, Any], ai_testing_check: dict[str, Any]) -> dict[str, Any]:
    contradictions: list[str] = []
    ai_signal_only = bool(ai_testing_check.get("signal_only"))
    if quality.get("status") == "promote" and not ai_testing_check.get("passed") and not ai_signal_only:
        contradictions.append("quality-promote-with-ai-testing-failures")
    if ai_testing_check.get("error_count", 0) > 0 and not ai_signal_only:
        contradictions.append("runtime-claims-with-broken-ai-test-lane")
    return {
        "contradictions": contradictions,
        "passed": not contradictions,
    }


def _delayed_verification_state(checks: dict[str, Any]) -> dict[str, Any]:
    hard_checks = [
        name
        for name in (
            "compileall",
            "code_graph",
            "architecture",
            "platform_runtime",
            "tool_health",
            "fact_consistency",
            "governance_gate",
        )
        if not bool((checks.get(name) or {}).get("passed"))
    ]
    advisory_checks = [
        name
        for name in ("quality", "artifact_audit", "reality_dashboard", "governance_gate")
        if not bool((checks.get(name) or {}).get("passed"))
    ]
    return {
        "mode": "delayed",
        "status": "pass" if not hard_checks else "attention",
        "passed": not hard_checks,
        "blocks_execution": False,
        "pending_checks": hard_checks,
        "pending_count": len(hard_checks),
        "advisory_checks": advisory_checks,
        "advisory_count": len(advisory_checks),
        "next_action": "observe" if not hard_checks else "drain-verification-backlog",
    }


def _release_sample_gate(checks: dict[str, Any]) -> dict[str, Any]:
    sampled_checks = [
        ("compileall", "code integrity", bool((checks.get("compileall") or {}).get("passed")), None),
        (
            "architecture",
            "architecture validation",
            str((checks.get("architecture") or {}).get("status") or "").strip().lower() == "pass",
            str((checks.get("architecture") or {}).get("status") or "unknown"),
        ),
        (
            "ai_testing",
            "AI release lane",
            True,
            ",".join((checks.get("ai_testing") or {}).get("signal_reasons") or []) or None,
        ),
        (
            "artifact_audit",
            "valuable artifact evidence",
            bool((checks.get("artifact_audit") or {}).get("passed")),
            (
                f"valuable_artifact_count={(checks.get('artifact_audit') or {}).get('valuable_artifact_count', 0)} "
                f"issue_count={(checks.get('artifact_audit') or {}).get('issue_count', 0)}"
            ),
        ),
        (
            "reality_dashboard",
            "fresh production evidence",
            float((checks.get("reality_dashboard") or {}).get("artifacts_produced_last_24h", 0) or 0) > 0,
            (
                f"products_real={(checks.get('reality_dashboard') or {}).get('products_real', 0)} "
                f"artifacts_produced_last_24h={(checks.get('reality_dashboard') or {}).get('artifacts_produced_last_24h', 0)}"
            ),
        ),
        (
            "fact_consistency",
            "fact consistency",
            bool((checks.get("fact_consistency") or {}).get("passed")),
            ",".join((checks.get("fact_consistency") or {}).get("contradictions") or []) or None,
        ),
    ]
    sample_results = [
        {
            "name": name,
            "label": label,
            "passed": passed,
            "reason": reason,
        }
        for name, label, passed, reason in sampled_checks
    ]
    sample_failures = [item["name"] for item in sample_results if not item["passed"]]
    blocking_sample_failures = [
        name for name in sample_failures if name not in {"artifact_audit", "reality_dashboard"}
    ]
    hard_gate_recommended = bool(blocking_sample_failures)
    return {
        "mode": "blocking_gate" if hard_gate_recommended else "advisory_signal",
        "status": "pass" if not blocking_sample_failures else "attention",
        "passed": not hard_gate_recommended,
        "signal_only": not hard_gate_recommended,
        "blocks_execution": False,
        "blocks_release": hard_gate_recommended,
        "sample_size": len(sample_results),
        "sampled_checks": sample_results,
        "sample_failures": sample_failures,
        "blocking_sample_failures": blocking_sample_failures,
        "hard_gate_recommended": hard_gate_recommended,
        "blocking_reasons": list(blocking_sample_failures),
        "next_action": "release-ready" if not sample_failures else ("hold-release-candidate" if hard_gate_recommended else "observe-release-signal"),
    }


def _signal_policy(
    checks: dict[str, Any],
    delayed_verification: dict[str, Any],
    release_gate: dict[str, Any],
    ai_testing_check: dict[str, Any],
    governance_gate: dict[str, Any],
) -> dict[str, Any]:
    runtime_blockers: list[str] = []
    hard_block = any(
        not bool((checks.get(name) or {}).get("passed"))
        for name in ("compileall", "code_graph", "architecture", "platform_runtime", "fact_consistency")
    )
    if hard_block:
        runtime_blockers.append("verification_hard_block")
    if not bool((checks.get("tool_health") or {}).get("passed")):
        runtime_blockers.append("critical_tool_health_failure")
    if not bool((checks.get("task_runtime") or {}).get("healthy")):
        runtime_blockers.append("daemon_unhealthy")

    maturity_signals: list[str] = []
    quality = checks.get("quality") or {}
    if not bool(quality.get("passed")):
        maturity_signals.append(f"quality:{quality.get('status') or 'attention'}")
    artifact_audit = checks.get("artifact_audit") or {}
    if not bool(artifact_audit.get("passed")):
        maturity_signals.append("artifact_audit")
    reality_dashboard = checks.get("reality_dashboard") or {}
    if not bool(reality_dashboard.get("passed")):
        maturity_signals.append("reality_dashboard")
    ai_status = str(ai_testing_check.get("status") or "missing").strip().lower()
    if ai_status in {"degraded", "attention", "warning", "missing"} or not bool(ai_testing_check.get("passed")):
        maturity_signals.append(f"ai_testing:{ai_status}")
    if not bool(delayed_verification.get("passed")):
        maturity_signals.append("verification_delay")
    if not bool(governance_gate.get("passed")):
        maturity_signals.append("governance_contract")

    release_gate_signals: list[str] = []
    if not bool(release_gate.get("passed")) or (release_gate.get("blocking_sample_failures") or []):
        release_gate_signals.append("release_gate_not_confirmed")
    if not bool(delayed_verification.get("passed")):
        release_gate_signals.append("verification_delay")
    if not bool(governance_gate.get("passed")):
        release_gate_signals.append("governance_contract_not_confirmed")

    return summarize_signal_policy(
        runtime_blockers=runtime_blockers,
        maturity_signals=maturity_signals,
        release_gate_signals=release_gate_signals,
        advisory_signals=(release_gate.get("sample_failures") or []),
        source="verification_engine",
    )


def _verification_scope() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    active_goal_ids = {item.get("goal_id") for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"}}
    modules = set()
    teams = set()
    projects = set()
    graph_node_count = 0
    for path in GRAPHS.glob("*.json"):
        graph = _load_json(path, {})
        if graph.get("goal_id") not in active_goal_ids:
            continue
        meta = graph.get("meta") or {}
        dep = meta.get("dependency_impact") or {}
        proj = meta.get("project_impact") or {}
        for item in dep.get("verification_scope", []) or []:
            modules.add(item)
        for item in dep.get("affected_teams", []) or []:
            teams.add(item)
        for item in proj.get("related_projects", []) or []:
            if item.get("project_id"):
                projects.add(item.get("project_id"))
        graph_node_count += len(graph.get("nodes", []))

    patch_queue = patch_review_queue()
    for item in patch_queue.get("recent", []) or []:
        for module in item.get("module_focus", []) or []:
            if module:
                modules.add(module)
        context_package = item.get('context_package') or {}
        for module in context_package.get('dependency_modules', []) or []:
            if module:
                modules.add(module)
        for layer in context_package.get('layers', []) or []:
            if layer:
                teams.add(f'layer:{layer}')
        for team in item.get("owner_teams", []) or []:
            if team:
                teams.add(team)
        for team in item.get("reviewer_teams", []) or []:
            if team:
                teams.add(team)
        project_context = context_package.get('project_context') or {}
        project_name = project_context.get('project_name')
        if project_name:
            projects.add(project_name)

    if modules:
        patch_project_impact = analyze_project_impact("patch verification scope", focus_modules=sorted(modules))
        for item in patch_project_impact.get("related_projects", []) or []:
            if item.get("project_id"):
                projects.add(item.get("project_id"))

    return {
        "modules": sorted(modules),
        "teams": sorted(teams),
        "projects": sorted(projects),
        "graph_node_count": graph_node_count,
        "patch_queue_count": patch_queue.get("approved_count", 0) + patch_queue.get("ready_count", 0) + patch_queue.get("blocked_count", 0),
    }


def run_verification(refresh_control_layer: bool = False) -> dict[str, Any]:
    compileall_result = _run_compileall()
    code_graph = build_code_knowledge_graph()
    architecture = run_architecture_validation()
    quality = run_quality()
    platforms = platform_health_summary()
    tasks = _task_health()
    tool_health = run_tool_health_audit()
    tool_health_history = read_tool_health_history(limit=10)
    artifact_audit = audit_artifacts(write_outputs=True)
    reality_dashboard = build_reality_dashboard(write_outputs=True)
    ai_testing = load_ai_test_status()
    ai_testing_check = _ai_testing_check(ai_testing)
    governance_contract = load_governance_contract()
    governance_gate = _governance_gate(governance_contract)
    fact_consistency = _fact_consistency_check(quality, ai_testing_check)
    verification_scope = _verification_scope()

    checks = {
        "compileall": compileall_result,
        "code_graph": {
            "module_count": code_graph.get("module_count", 0),
            "edge_count": code_graph.get("edge_count", 0),
            "layers": code_graph.get("layers", []),
            "passed": code_graph.get("module_count", 0) > 0 and code_graph.get("edge_count", 0) > 0,
        },
        "architecture": {
            **architecture,
            "passed": str(architecture.get("status") or "").strip().lower() == "pass",
        },
        "quality": {
            "status": quality.get("status"),
            "overall_score": quality.get("overall_score"),
            "passed": float(quality.get("overall_score", 0.0) or 0.0) >= 0.75,
        },
        "platform_runtime": {
            "platform_count": platforms.get("platform_count", 0),
            "unhealthy_count": platforms.get("unhealthy_count", 0),
            "passed": platforms.get("unhealthy_count", 0) == 0,
        },
        "tool_health": {
            "status": tool_health.get("status"),
            "issue_count": len(tool_health.get("issues", [])),
            "issues": tool_health.get("issues", [])[:10],
            "blocking_issues": [
                item for item in (tool_health.get("issues", []) or [])
                if item != "control-layer-lags-quality"
            ][:10],
            "passed": not _tool_health_blocks_patch_gate(tool_health),
            "history_recent_count": tool_health_history.get("recent_count", 0),
            "recent_failures": tool_health_history.get("recent_failures", [])[:5],
        },
        "ai_testing": ai_testing_check,
        "artifact_audit": {
            "status": artifact_audit.get("status"),
            "artifact_count": artifact_audit.get("artifact_count", 0),
            "real_artifact_count": artifact_audit.get("real_artifact_count", 0),
            "valuable_artifact_count": artifact_audit.get("valuable_artifact_count", 0),
            "prototype_artifact_count": artifact_audit.get("prototype_artifact_count", 0),
            "issue_count": len(artifact_audit.get("issues", [])),
            "passed": str(artifact_audit.get("status") or "").strip().lower() == "pass",
        },
        "reality_dashboard": {
            "status": reality_dashboard.get("status"),
            "products_real": reality_dashboard.get("products_real", 0),
            "conversion_rate": reality_dashboard.get("conversion_rate", 0.0),
            "artifacts_produced_last_24h": reality_dashboard.get("artifacts_produced_last_24h", 0),
            "tasks_completed_last_24h": reality_dashboard.get("tasks_completed_last_24h", 0),
            "passed": reality_dashboard.get("status") == "pass",
        },
        "fact_consistency": fact_consistency,
        "governance_contract": governance_contract,
        "governance_gate": governance_gate,
        "task_runtime": tasks,
        "verification_scope": {
            "module_count": len(verification_scope.get("modules", [])),
            "team_count": len(verification_scope.get("teams", [])),
            "project_count": len(verification_scope.get("projects", [])),
            "graph_node_count": verification_scope.get("graph_node_count", 0),
            "modules": verification_scope.get("modules", [])[:20],
            "teams": verification_scope.get("teams", []),
            "projects": verification_scope.get("projects", []),
        },
    }
    delayed_verification = _delayed_verification_state(checks)
    release_gate = _release_sample_gate(checks)
    signal_policy = _signal_policy(checks, delayed_verification, release_gate, ai_testing_check, governance_gate)

    patch_gate_passed = delayed_verification.get("passed", False)
    governance_gate_passed = governance_gate.get("passed", False)
    runtime_health_passed = tasks.get("healthy")
    passed = bool(patch_gate_passed and runtime_health_passed and governance_gate_passed)
    payload = {
        "updated_at": _utc(),
        **checks,
        "execution_policy": {
            "mode": "signal_only",
            "status": "pass",
            "blocks_execution": False,
        },
        "delayed_verification": delayed_verification,
        "release_gate": release_gate,
        "patch_gate": {
            **delayed_verification,
            "legacy_name": "patch_gate",
            "reasons": list(delayed_verification.get("pending_checks") or []),
        },
        "signal_policy": signal_policy,
        "runtime_health": {
            "status": "pass" if runtime_health_passed else "attention",
            "passed": runtime_health_passed,
        },
        "governance_gate": governance_gate,
        "status": "pass" if passed else "attention",
    }
    atomic_write_json(OUT, payload)
    if refresh_control_layer:
        payload["control_layer_refresh"] = _refresh_control_layer_snapshot(payload)
        atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_verification(refresh_control_layer=False), ensure_ascii=False, indent=2))
