from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

INTENT_PATH = DATA / "report_intent.json"
EXECUTION_PATH = DATA / "report_execution.json"
DECISIONS_PATH = DATA / "report_decisions.json"
EVIDENCE_PATH = DATA / "report_evidence.json"
CAPABILITY_PATH = DATA / "capability_status.json"
SYSTEM_REPORT_PATH = DATA / "system_report.json"
DECISION_LEDGER_PATH = DATA / "decision_ledger.jsonl"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_ts(value: Any) -> str | None:
    stamp = _parse_ts(value)
    return stamp.isoformat().replace("+00:00", "Z") if stamp is not None else None


def _path_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _first_non_empty(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _task_rows() -> list[dict[str, Any]]:
    payload = _load_json(DATA / "tasks.json", [])
    return payload if isinstance(payload, list) else []


def _active_rows() -> list[dict[str, Any]]:
    runtime = _load_json(DATA / "self_model_runtime.json", {})
    state = runtime.get("state") if isinstance(runtime, dict) else {}
    tasks = (state or {}).get("tasks") if isinstance(state, dict) else {}
    active = (tasks or {}).get("active") if isinstance(tasks, dict) else []
    return active if isinstance(active, list) else []


def _goal_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        goal = _first_non_empty(item.get("goal"), item.get("title"), item.get("prompt"), item.get("id"))
        if goal:
            names.append(goal)
    return names


def _task_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"active": 0, "pending": 0, "running": 0, "blocked": 0, "completed": 0, "failed": 0}
    for item in rows:
        if not isinstance(item, dict):
            continue
        status = _lower(item.get("status"))
        if status in {"queued", "planning", "running", "waiting_approval"}:
            counts["active"] += 1
        if status in {"queued", "planning"}:
            counts["pending"] += 1
        if status == "running":
            counts["running"] += 1
        if status in {"blocked", "waiting_approval"}:
            counts["blocked"] += 1
        if status in {"completed", "done", "succeeded", "released"}:
            counts["completed"] += 1
        if status in {"failed", "timed_out", "rejected"}:
            counts["failed"] += 1
    return counts


def _latest_row_timestamp(rows: list[dict[str, Any]]) -> str | None:
    latest: datetime | None = None
    for item in rows:
        if not isinstance(item, dict):
            continue
        stamp = _parse_ts(item.get("updated_at") or item.get("created_at"))
        if stamp is not None and (latest is None or stamp > latest):
            latest = stamp
    return latest.isoformat().replace("+00:00", "Z") if latest is not None else None


def _worker_allocation(rows: list[dict[str, Any]]) -> dict[str, int]:
    allocation = {"planner": 0, "executor": 0, "verifier": 0}
    for item in rows:
        if not isinstance(item, dict):
            continue
        status = _lower(item.get("status"))
        if status in {"queued", "planning"}:
            allocation["planner"] += 1
        elif status == "running":
            allocation["executor"] += 1
        elif status in {"waiting_approval", "verifying", "verification"}:
            allocation["verifier"] += 1
    return allocation


def _goal_reason(goal_primary: str, production_focus: dict[str, Any], control_layer: dict[str, Any]) -> str:
    if _lower(production_focus.get("enabled")) in {"true", "1", "yes"}:
        return _first_non_empty(
            production_focus.get("directive_reason"),
            production_focus.get("reason"),
            default="single-product priority",
        )
    if "toyos" in goal_primary.lower():
        return "ToyOS is the current highest-value delivery line"
    return _first_non_empty(
        (control_layer.get("decision_engine") or {}).get("reason"),
        default="current goal preserved by runtime policy",
    )


def _goal_mode(goal_primary: str, self_model_runtime: dict[str, Any]) -> str:
    state = self_model_runtime.get("state") if isinstance(self_model_runtime, dict) else {}
    mode = _first_non_empty(
        (state or {}).get("mode"),
        self_model_runtime.get("mode"),
        self_model_runtime.get("goal_mode"),
        default="unknown",
    )
    if mode != "unknown":
        return mode
    return "toyos_priority_mode" if "toyos" in goal_primary.lower() else "delivery_mode"


def _goal_details(self_model_runtime: dict[str, Any]) -> dict[str, Any]:
    state = self_model_runtime.get("state") if isinstance(self_model_runtime, dict) else {}
    goal = self_model_runtime.get("goal") if isinstance(self_model_runtime, dict) else None
    goal = goal if isinstance(goal, dict) else {}
    state_goal = (state or {}).get("goal") if isinstance(state, dict) else None
    state_goal = state_goal if isinstance(state_goal, dict) else {}
    primary = _first_non_empty(
        goal.get("primary"),
        goal.get("goal"),
        goal.get("target"),
        state_goal.get("primary"),
        state_goal.get("goal"),
        state_goal.get("target"),
        self_model_runtime.get("primary_goal"),
        default="unknown",
    )
    mode = _first_non_empty(
        goal.get("mode"),
        state_goal.get("mode"),
        (state or {}).get("mode"),
        self_model_runtime.get("mode"),
        self_model_runtime.get("goal_mode"),
        default="unknown",
    )
    priority = _first_non_empty(goal.get("priority"), state_goal.get("priority"), default="unknown")
    rationale = goal.get("rationale") if isinstance(goal.get("rationale"), list) else []
    if not rationale and isinstance(state_goal.get("rationale"), list):
        rationale = state_goal.get("rationale")
    return {"primary": primary, "mode": mode, "priority": priority, "rationale": rationale}


def _build_intent(
    self_model_runtime: dict[str, Any],
    control_layer: dict[str, Any],
    production_focus: dict[str, Any],
    goal_primary: str,
) -> dict[str, Any]:
    details = _goal_details(self_model_runtime)
    primary_target = _first_non_empty(details.get("primary"), goal_primary, default="unknown")
    priority_reason = _first_non_empty(
        _goal_reason(primary_target, production_focus, control_layer),
        "; ".join(details.get("rationale", [])),
        default="current goal preserved by runtime policy",
    )
    return {
        "primary_goal": primary_target,
        "goal_mode": _first_non_empty(details.get("mode"), _goal_mode(primary_target, self_model_runtime), default="unknown"),
        "priority_reason": priority_reason,
        "operator_override": bool(_lower((control_layer.get("control_policy") or {}).get("mode")) == "manual"),
        "expected_next_delivery": (
            "toyos_buildable_verified_artifact"
            if "toyos" in primary_target.lower()
            else "verified_delivery_artifact"
        ),
        "primary_focus": {
            "enabled": bool(production_focus.get("enabled")),
            "single_product_mode": bool(production_focus.get("single_product_mode")),
            "primary_artifact_id": production_focus.get("primary_artifact_id"),
            "primary_target": production_focus.get("primary_target"),
        },
    }


def _execution_status(
    task_counts: dict[str, int],
    daemon_state: dict[str, Any],
    intent: dict[str, Any],
) -> tuple[str, str, str]:
    running = bool(daemon_state.get("running", _lower(daemon_state.get("status")) == "running"))
    if not running:
        return "daemon_stopped", "daemon not running", "restore daemon continuity"
    if task_counts["running"] > 0:
        return "active_execution", "running tasks present", "continue current execution lane"
    if task_counts["active"] > 0:
        return "active_planning", "active tasks present but not yet running", "advance planning into execution"
    if task_counts["pending"] > 0:
        return "queued_only", "queue contains pending tasks", "dispatch queued tasks"
    if intent.get("primary_goal") and _lower(intent.get("primary_goal")) != "unknown":
        return "idle_with_goal", "goal set but no active tasks", "generate runnable tasks from the goal"
    return "idle", "no active goal and no active tasks", "wait for new intent"


def _build_execution(
    self_model_runtime: dict[str, Any],
    control_layer: dict[str, Any],
    verification: dict[str, Any],
    reality_dashboard: dict[str, Any],
    daemon_state: dict[str, Any],
    tasks: list[dict[str, Any]],
    active_rows: list[dict[str, Any]],
    intent: dict[str, Any],
) -> dict[str, Any]:
    task_counts = _task_status_counts(tasks)
    active_names = _goal_names(active_rows)
    status, blocker, recommendation = _execution_status(task_counts, daemon_state, intent)
    queue_health = "healthy"
    if status == "idle_with_goal":
        queue_health = "starved"
    elif task_counts["pending"] > 0:
        queue_health = "warm"
    blocked_on = blocker
    release_gate = _first_non_empty((verification.get("release_gate") or {}).get("status"), reality_dashboard.get("status"), default="unknown")
    if _lower((verification.get("runtime_health") or {}).get("status")) == "attention":
        blocked_on = "runtime_health_attention"
    if _lower(release_gate) in {"blocked", "attention"}:
        blocked_on = f"release_gate_{release_gate}"
    return {
        "active_task_count": task_counts["active"],
        "pending_tasks": task_counts["pending"],
        "running_tasks": active_names[:8],
        "current_worker_allocation": _worker_allocation(active_rows),
        "last_dispatch_at": _latest_row_timestamp(tasks) or _latest_row_timestamp(active_rows),
        "queue_health": queue_health,
        "blocked_on": blocked_on,
        "execution_status": status,
        "current_action": recommendation,
        "task_counts": task_counts,
        "control_layer_status": _first_non_empty(control_layer.get("status"), default="unknown"),
    }


def _decision_entry(
    *,
    decision_type: str,
    decision: str,
    reason: str,
    impact: str,
    source: str,
    ts: str | None = None,
) -> dict[str, Any]:
    return {
        "ts": ts or _utc(),
        "decision_type": decision_type,
        "decision": decision,
        "reason": reason,
        "impact": impact,
        "source": source,
    }


def _historical_decisions() -> list[dict[str, Any]]:
    rows = _load_json(DATA / "decision_log.json", [])
    rows = rows if isinstance(rows, list) else []
    ts = _path_mtime(DATA / "decision_log.json")
    history: list[dict[str, Any]] = []
    for item in rows[-20:]:
        if not isinstance(item, dict):
            continue
        history.append(
            _decision_entry(
                decision_type=_first_non_empty(item.get("source"), default="historical"),
                decision=_first_non_empty(item.get("decision"), item.get("project"), default="unknown"),
                reason=_first_non_empty(item.get("reason"), item.get("source"), default="historical decision"),
                impact=_first_non_empty(item.get("project"), item.get("source"), default="state memory"),
                source="decision_log.json",
                ts=ts,
            )
        )
    return history


def _build_decisions(
    self_model_runtime: dict[str, Any],
    control_layer: dict[str, Any],
    verification: dict[str, Any],
    production_focus: dict[str, Any],
    decision_engine: dict[str, Any],
) -> dict[str, Any]:
    goal_details = _goal_details(self_model_runtime)
    goal_primary = _first_non_empty(goal_details.get("primary"), default="unknown")
    latest: list[dict[str, Any]] = [
        _decision_entry(
            decision_type="goal_selection",
            decision=f"set_primary_goal_{goal_primary}",
            reason=_first_non_empty(
                _goal_reason(goal_primary, production_focus, control_layer),
                "; ".join(goal_details.get("rationale", [])),
                default="current goal preserved by runtime policy",
            ),
            impact="primary goal is preserved as the top-level target",
            source="self_model_runtime",
            ts=_fmt_ts(self_model_runtime.get("updated_at")),
        ),
        _decision_entry(
            decision_type="control_policy",
            decision=f"control_mode_{_first_non_empty((control_layer.get('control_policy') or {}).get('mode'), default='unknown')}",
            reason=_first_non_empty((control_layer.get("control_policy") or {}).get("execution"), control_layer.get("status"), default="current control policy"),
            impact="defines how aggressively the system may act",
            source="control_layer_status.json",
            ts=_fmt_ts(control_layer.get("updated_at")),
        ),
        _decision_entry(
            decision_type="release_gate",
            decision=f"release_{_first_non_empty((verification.get('release_gate') or {}).get('status'), default='unknown')}",
            reason=_first_non_empty(
                (verification.get("release_gate") or {}).get("reason"),
                (verification.get("delayed_verification") or {}).get("reason"),
                default="release gate evaluated from verification evidence",
            ),
            impact="release promotion is constrained by verification state",
            source="verification_status.json",
            ts=_fmt_ts(verification.get("updated_at")),
        ),
    ]
    for item in (decision_engine.get("decision_engine") or {}).get("decisions", []):
        if not isinstance(item, dict):
            continue
        latest.append(
            _decision_entry(
                decision_type="decision_engine",
                decision=str(item.get("decision") or "unknown").strip(),
                reason=str(item.get("reason") or "decision engine state").strip(),
                impact=str(item.get("applies_to") or "runtime").strip(),
                source="decision_engine_status.json",
                ts=_fmt_ts(decision_engine.get("updated_at")),
            )
        )
    historical = _historical_decisions()
    return {
        "latest_decisions": latest[:8],
        "historical_decisions": historical,
        "decision_count": len(latest) + len(historical),
    }


def _latest_artifact(record: dict[str, Any]) -> dict[str, Any]:
    rows = record.get("artifacts") if isinstance(record, dict) else []
    rows = rows if isinstance(rows, list) else []
    chosen: dict[str, Any] | None = None
    chosen_stamp: datetime | None = None
    for item in rows:
        if not isinstance(item, dict):
            continue
        stamp = _parse_ts(((item.get("checks") or {}).get("latest_evidence_at")) or item.get("updated_at") or item.get("created_at"))
        if chosen is None or (stamp is not None and (chosen_stamp is None or stamp > chosen_stamp)):
            chosen = item
            chosen_stamp = stamp
    return chosen or {}


def _build_evidence(
    artifact_registry: dict[str, Any],
    verification: dict[str, Any],
    reality_dashboard: dict[str, Any],
    production_focus: dict[str, Any],
) -> dict[str, Any]:
    latest = _latest_artifact(artifact_registry)
    latest_artifact_id = str(latest.get("artifact_id") or "").strip()
    latest_status = str(latest.get("status") or latest.get("delivery_status") or "").strip() or "unknown"
    verified = latest.get("verified") if isinstance(latest.get("verified"), dict) else {}
    value = latest.get("value") if isinstance(latest.get("value"), dict) else {}
    release_gate = verification.get("release_gate") or {}
    release_readiness = "blocked"
    if _lower(artifact_registry.get("status")) == "pass" and _lower(verification.get("status")) == "pass":
        release_readiness = "ready"
    elif _lower(artifact_registry.get("status")) == "pass" and _lower((verification.get("delayed_verification") or {}).get("status")) == "pass":
        release_readiness = "conditional"
    elif _lower(reality_dashboard.get("status")) == "pass":
        release_readiness = "conditional"
    block_reason = _first_non_empty(
        release_gate.get("reason"),
        (verification.get("delayed_verification") or {}).get("reason"),
        (reality_dashboard.get("top_issues") or [{}])[0].get("title") if reality_dashboard.get("top_issues") else None,
        default="no fresh delivery evidence or verification gap",
    )
    if release_readiness == "ready":
        block_reason = ""
    return {
        "artifacts_last_24h": _safe_int(reality_dashboard.get("artifacts_produced_last_24h")),
        "valuable_artifacts_last_24h": _safe_int(reality_dashboard.get("products_real")),
        "latest_artifact": latest_artifact_id,
        "latest_artifact_status": latest_status,
        "latest_artifact_verified": bool(verified),
        "latest_artifact_value_contract": bool(value.get("valuable")),
        "latest_artifact_ts": _fmt_ts(((latest.get("checks") or {}).get("latest_evidence_at")) or latest.get("updated_at")),
        "verification_status": str(verification.get("status") or "unknown"),
        "release_readiness": release_readiness,
        "block_reason": block_reason,
        "focus_artifact_id": str(production_focus.get("primary_artifact_id") or "").strip(),
        "evidence_sources": {
            "artifact_registry": str(DATA / "artifact_registry.json"),
            "verification_status": str(DATA / "verification_status.json"),
            "reality_dashboard": str(DATA / "reality_dashboard.json"),
        },
    }


def _build_capability_status(
    assistant_capabilities: list[dict[str, Any]],
    control_layer: dict[str, Any],
    evidence: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    assistant_summary = assistant_capabilities[0] if assistant_capabilities else {}
    capability_text = str(assistant_summary.get("summary") or "").lower()
    enabled_components = {
        str(item).strip().lower()
        for item in (control_layer.get("enabled_components") or [])
        if str(item).strip()
    }
    release_ready = _lower(evidence.get("release_readiness")) == "ready"
    return {
        "plan_generation": {"status": "available", "reason": "assistant capability and control layer support planning"},
        "task_dispatch": {
            "status": "available" if {"orchestrator", "scheduler", "task_queue"} & enabled_components else "conditional",
            "reason": "task dispatch is wired through the control layer",
        },
        "task_restock_from_goal": {
            "status": "missing" if execution.get("execution_status") == "idle_with_goal" else "available",
            "reason": "goal-to-queue restocking is not guaranteed by current runtime state",
        },
        "code_execution": {
            "status": "available" if "compile" in capability_text or "build" in capability_text else "conditional",
            "reason": "local execution and build work are covered by assistant capability hints",
        },
        "docker_build": {
            "status": "conditional",
            "reason": "Docker execution is policy-gated rather than guaranteed",
        },
        "qemu_validation": {
            "status": "available" if "qemu" in capability_text else "conditional",
            "reason": "ToyOS validation path uses local QEMU smoke tests when available",
        },
        "artifact_registration": {
            "status": "available" if _lower(control_layer.get("status")) in {"stable", "pass"} else "conditional",
            "reason": "artifact registry is writable from the local orchestrator",
        },
        "release_promotion": {
            "status": "available" if release_ready else "conditional",
            "reason": "promotion depends on verified evidence and current release readiness",
        },
    }


def _can_do_now(capability: dict[str, Any]) -> list[str]:
    mapping = {
        "plan_generation": "plan",
        "task_dispatch": "route",
        "code_execution": "execute_workspace_code",
        "qemu_validation": "run_qemu_validation",
        "artifact_registration": "register_artifacts",
        "release_promotion": "promote_release_candidate",
    }
    return [mapping[name] for name, item in capability.items() if isinstance(item, dict) and item.get("status") == "available" and name in mapping]


def _cannot_do_now(capability: dict[str, Any]) -> list[str]:
    mapping = {
        "task_restock_from_goal": "autonomously_restock_mainline_tasks",
    }
    return [mapping[name] for name, item in capability.items() if isinstance(item, dict) and item.get("status") == "missing" and name in mapping]


def _summary_state(intent: dict[str, Any], execution: dict[str, Any], evidence: dict[str, Any]) -> str:
    if execution.get("execution_status") == "idle_with_goal":
        return "goal_set_but_execution_starved"
    if execution.get("execution_status") in {"queued_only", "active_planning", "active_execution"}:
        return "goal_in_execution"
    if _lower(evidence.get("release_readiness")) == "blocked":
        return "goal_ready_but_release_blocked"
    return "idle_or_converged"


def _build_system_report(
    *,
    intent: dict[str, Any],
    execution: dict[str, Any],
    decisions: dict[str, Any],
    evidence: dict[str, Any],
    capability: dict[str, Any],
    goal_primary: str,
) -> dict[str, Any]:
    latest_decision = decisions.get("latest_decisions", [{}])[0] if decisions.get("latest_decisions") else {}
    top_blocker = _first_non_empty(execution.get("blocked_on"), evidence.get("block_reason"), default="none")
    current_action = _first_non_empty(execution.get("current_action"), default="idle")
    if current_action == "generate runnable tasks from the goal":
        current_action = "idle_waiting_for_restock"
    report = {
        "as_of": _utc(),
        "system_state": _summary_state(intent, execution, evidence),
        "primary_goal": intent.get("primary_goal"),
        "goal_mode": intent.get("goal_mode"),
        "current_action": current_action,
        "current_release_gate": evidence.get("release_readiness"),
        "can_do_now": _can_do_now(capability),
        "cannot_do_now": _cannot_do_now(capability),
        "completed_recently": [
            f"artifacts_last_24h={evidence.get('artifacts_last_24h', 0)}",
            f"latest_artifact={evidence.get('latest_artifact') or 'unknown'}",
            f"verification={evidence.get('verification_status')}",
        ],
        "latest_key_decision": _first_non_empty(latest_decision.get("decision"), default="unknown"),
        "top_blocker": top_blocker,
        "recommended_next_action": (
            "generate 3 concrete ToyOS mainline tasks immediately"
            if "toyos" in goal_primary.lower() or "toyos" in str(intent.get("primary_goal") or "").lower()
            else "convert the current goal into runnable queue items"
        ),
        "summary_sentences": [
            f"Current top goal: {intent.get('primary_goal')}.",
            f"Current execution status: {execution.get('execution_status')}, queue health: {execution.get('queue_health')}.",
            f"Latest key decision: {latest_decision.get('decision')}.",
            f"Current capability set can do: {', '.join(_can_do_now(capability)) or 'none'}.",
            f"Next action: {'generate 3 concrete ToyOS mainline tasks immediately' if 'toyos' in goal_primary.lower() else 'restore queue flow from goal to task dispatch'}.",
        ],
        "report_files": {
            "intent": str(INTENT_PATH),
            "execution": str(EXECUTION_PATH),
            "decisions": str(DECISIONS_PATH),
            "evidence": str(EVIDENCE_PATH),
            "capability": str(CAPABILITY_PATH),
            "decision_ledger": str(DECISION_LEDGER_PATH),
        },
    }
    return report


def _write_decision_ledger(entries: list[dict[str, Any]]) -> None:
    lines = [json.dumps(item, ensure_ascii=False) for item in entries]
    atomic_write_text(DECISION_LEDGER_PATH, "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def build_report_chain(*, write_outputs: bool = True) -> dict[str, Any]:
    self_model_runtime = _load_json(DATA / "self_model_runtime.json", {})
    control_layer = _load_json(DATA / "control_layer_status.json", {})
    verification = _load_json(DATA / "verification_status.json", {})
    reality_dashboard = _load_json(DATA / "reality_dashboard.json", {})
    artifact_registry = _load_json(DATA / "artifact_registry.json", {})
    decision_engine = _load_json(DATA / "decision_engine_status.json", {})
    daemon_state = _load_json(DATA / "factory_daemon_state.json", {})
    production_focus = _load_json(DATA / "production_focus_status.json", {})
    assistant_capabilities = _load_json(DATA / "assistant_capabilities.json", [])
    tasks = _task_rows()
    active_rows = _active_rows()

    goal_template = production_focus.get("goal_template") if isinstance(production_focus, dict) else {}
    goal_template = goal_template if isinstance(goal_template, dict) else {}
    goal_details = _goal_details(self_model_runtime)
    goal_primary = _first_non_empty(goal_details.get("primary"), goal_template.get("target"), default="unknown")

    intent = _build_intent(self_model_runtime, control_layer, production_focus, goal_primary)
    execution = _build_execution(
        self_model_runtime,
        control_layer,
        verification,
        reality_dashboard,
        daemon_state if isinstance(daemon_state, dict) else {},
        tasks,
        active_rows,
        intent,
    )
    decisions = _build_decisions(self_model_runtime, control_layer, verification, production_focus, decision_engine)
    evidence = _build_evidence(artifact_registry, verification, reality_dashboard, production_focus)
    capability = _build_capability_status(assistant_capabilities, control_layer, evidence, execution)
    system_report = _build_system_report(
        intent=intent,
        execution=execution,
        decisions=decisions,
        evidence=evidence,
        capability=capability,
        goal_primary=goal_primary,
    )

    decision_ledger = list(decisions.get("historical_decisions", [])) + list(decisions.get("latest_decisions", []))
    if write_outputs:
        atomic_write_json(INTENT_PATH, intent)
        atomic_write_json(EXECUTION_PATH, execution)
        atomic_write_json(DECISIONS_PATH, decisions)
        atomic_write_json(EVIDENCE_PATH, evidence)
        atomic_write_json(CAPABILITY_PATH, capability)
        atomic_write_json(SYSTEM_REPORT_PATH, system_report)
        _write_decision_ledger(decision_ledger)

    return {
        "updated_at": _utc(),
        "intent": intent,
        "execution": execution,
        "decisions": decisions,
        "evidence": evidence,
        "capability": capability,
        "system_report": system_report,
        "delivery": {
            "intent": str(INTENT_PATH),
            "execution": str(EXECUTION_PATH),
            "decisions": str(DECISIONS_PATH),
            "evidence": str(EVIDENCE_PATH),
            "capability": str(CAPABILITY_PATH),
            "system_report": str(SYSTEM_REPORT_PATH),
            "decision_ledger": str(DECISION_LEDGER_PATH),
        },
    }


if __name__ == "__main__":
    print(json.dumps(build_report_chain(write_outputs=True), ensure_ascii=False, indent=2))
