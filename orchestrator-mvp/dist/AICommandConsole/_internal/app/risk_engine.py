from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.provider_gateway import provider_gateway

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TASKS_PATH = DATA / "tasks.json"
DAEMON_STATE_PATH = DATA / "factory_daemon_state.json"
FACTORY_STATE_PATH = DATA / "factory_state.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
VERIFICATION_STATUS_PATH = DATA / "verification_status.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
GOAL_BACKLOG_PATH = DATA / "goal_backlog_status.json"
QUALITY_STATUS_PATH = DATA / "quality_status.json"
RELEASE_OPERATIONS_PATH = DATA / "release_operations_status.json"
REPAIR_HISTORY_PATH = DATA / "repair_history.json"
SEMANTIC_HEALTH_PATH = DATA / "semantic_health.json"
RISK_STATUS_PATH = DATA / "risk_status.json"
INCIDENT_LEDGER_PATH = DATA / "incident_ledger.json"
RISK_CATALOG_PATH = DATA / "risk_catalog.json"

TASK_ACTIVE_STATUSES = {"planning", "running", "execution_finished", "verification_pending", "verification_running"}
TASK_COMPLETED_STATUSES = {"completed", "delivery_ready", "released"}

DEFAULT_RISK_CATALOG: dict[str, dict[str, Any]] = {
    "runtime.queue_starvation": {
        "title": "Queue starvation under active goal",
        "domain": "runtime",
        "severity": "high",
        "kind": "semantic_failure",
        "blast_radius": "system",
        "candidate_root_causes": ["task_replenisher_stalled", "admission_gate_too_strict", "scheduler_not_generating_work"],
        "allowed_actions": ["rebuild_priority_tasks", "poke_scheduler", "soft_restart_dispatcher"],
        "forbidden_actions": ["clear_all_tasks", "reset_factory_state"],
        "verification_plan": ["queue_depth_gt_0", "new_task_created_for_goal", "dispatch_resumed_within_120s"],
        "rollback_plan": "restore_previous_queue_snapshot",
    },
    "runtime.false_liveness": {
        "title": "Daemon alive but semantically idle",
        "domain": "runtime",
        "severity": "high",
        "kind": "semantic_failure",
        "blast_radius": "system",
        "candidate_root_causes": ["dispatcher_stalled", "goal_pipeline_idle", "artifact_updates_suppressed"],
        "allowed_actions": ["poke_scheduler", "soft_restart_dispatcher", "rebuild_priority_tasks"],
        "forbidden_actions": ["clear_all_tasks", "reset_factory_state"],
        "verification_plan": ["dispatch_success_last_30m_gt_0", "artifact_updates_last_24h_gt_0", "active_tasks_gt_0"],
        "rollback_plan": "restore_previous_dispatch_snapshot",
    },
    "verification.misalignment": {
        "title": "Completion promoted before evidence closed",
        "domain": "verification",
        "severity": "critical",
        "kind": "verification_failure",
        "blast_radius": "system",
        "candidate_root_causes": ["artifact_registry_not_refreshed", "verification_pipeline_degraded", "promotion_gate_bypassed"],
        "allowed_actions": ["re_run_verification", "freeze_release_train"],
        "forbidden_actions": ["promote_without_evidence", "inherit_previous_verdict"],
        "verification_plan": ["verification_pending_checks_empty", "artifact_evidence_present", "promotion_claims_match_bottom_state"],
        "rollback_plan": "revert_to_pre_promotion_state",
    },
    "routing.model_degradation": {
        "title": "Model routing degraded to weak or failing routes",
        "domain": "routing",
        "severity": "high",
        "kind": "provider_failure",
        "blast_radius": "workspace",
        "candidate_root_causes": ["provider_auth_failure", "quota_preserve_lock", "fallback_route_misconfigured"],
        "allowed_actions": ["switch_provider_fallback", "re_run_verification"],
        "forbidden_actions": ["disable_route_audit", "clear_provider_history"],
        "verification_plan": ["provider_last_error_cleared", "fallback_route_selected", "strong_model_route_available"],
        "rollback_plan": "restore_previous_provider_route_selection",
    },
    "config.drift": {
        "title": "State or policy files drifted out of sync",
        "domain": "config",
        "severity": "medium",
        "kind": "configuration_drift",
        "blast_radius": "workspace",
        "candidate_root_causes": ["status_files_updated_out_of_order", "policy_hash_changed_without_record", "verification_and_audit_disagree"],
        "allowed_actions": ["re_run_verification", "poke_scheduler"],
        "forbidden_actions": ["overwrite_policy_history", "discard_audit_evidence"],
        "verification_plan": ["control_and_verification_status_align", "artifact_audit_and_verification_align"],
        "rollback_plan": "restore_previous_config_snapshot",
    },
    "continuity.distortion": {
        "title": "Continuity claimed but write path failed",
        "domain": "continuity",
        "severity": "critical",
        "kind": "continuity_failure",
        "blast_radius": "system",
        "candidate_root_causes": ["state_write_permission_error", "epoch_transition_failure", "durable_checkpoint_missing"],
        "allowed_actions": ["freeze_release_train", "re_run_verification"],
        "forbidden_actions": ["reset_factory_state", "discard_durable_checkpoint"],
        "verification_plan": ["state_write_errors_cleared", "continuity_mode_not_lied_about"],
        "rollback_plan": "restore_previous_durable_checkpoint",
    },
    "release.promotion_mismatch": {
        "title": "Release promoted while gates still open",
        "domain": "release",
        "severity": "critical",
        "kind": "release_mispromotion",
        "blast_radius": "system",
        "candidate_root_causes": ["pending_verification_checks", "quality_status_not_ready", "release_train_claimed_ready_too_early"],
        "allowed_actions": ["freeze_release_train", "re_run_verification"],
        "forbidden_actions": ["promote_without_gate_confirmation"],
        "verification_plan": ["pending_checks_empty", "quality_signal_ready", "release_train_not_claiming_ready"],
        "rollback_plan": "revoke_release_promotion",
    },
    "repair.secondary_damage": {
        "title": "Repair action caused collateral damage",
        "domain": "repair",
        "severity": "high",
        "kind": "secondary_damage",
        "blast_radius": "workspace",
        "candidate_root_causes": ["queue_cleared_by_rebuild", "provider_auth_scopes_missing_after_switch", "verification_evidence_lost_after_repair"],
        "allowed_actions": ["re_run_verification", "freeze_release_train"],
        "forbidden_actions": ["repeat_same_action_without_review", "clear_history"],
        "verification_plan": ["queue_not_lost", "provider_auth_scopes_valid", "evidence_chain_intact"],
        "rollback_plan": "restore_pre_repair_snapshot",
    },
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
    return default


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _task_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    active = 0
    completed = 0
    recent_completed = 0
    recent_60m_cutoff = datetime.now(timezone.utc) - timedelta(minutes=60)
    for task in tasks:
        status = str(task.get("status") or "unknown").strip().lower()
        statuses[status] = statuses.get(status, 0) + 1
        if status in TASK_ACTIVE_STATUSES:
            active += 1
        if status in TASK_COMPLETED_STATUSES:
            completed += 1
        updated = _parse_time(task.get("updated_at") or task.get("created_at"))
        if status in TASK_COMPLETED_STATUSES and updated is not None and updated >= recent_60m_cutoff:
            recent_completed += 1
    queue_depth = sum(statuses.get(name, 0) for name in ("queued", "planning", "waiting_approval"))
    worker_idle_ratio = 1.0 if active == 0 else round(max(0.0, 1.0 - min(active / max(len(tasks), 1), 1.0)), 2)
    return {
        "total_tasks": len(tasks),
        "active_tasks": active,
        "completed_tasks": completed,
        "completed_tasks_last_60m": recent_completed,
        "queue_depth": queue_depth,
        "worker_idle_ratio": worker_idle_ratio,
        "status_counts": statuses,
    }


def _artifact_summary(artifact_registry: dict[str, Any]) -> dict[str, Any]:
    artifacts = artifact_registry.get("artifacts") or []
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    fresh = 0
    for item in artifacts:
        checks = item.get("checks") or {}
        updated = _parse_time(checks.get("latest_evidence_at") or checks.get("build_timestamp") or checks.get("updated_at"))
        if updated is not None and updated >= recent_cutoff:
            fresh += 1
    return {
        "artifact_count": int(artifact_registry.get("artifact_count") or len(artifacts)),
        "real_artifact_count": int(artifact_registry.get("real_artifact_count") or 0),
        "valuable_artifact_count": int(artifact_registry.get("valuable_artifact_count") or 0),
        "artifact_updates_last_24h": fresh,
    }


def _provider_summary(provider_state: dict[str, Any]) -> dict[str, Any]:
    failures = 0
    auth_like = 0
    route_count = 0
    for provider in (provider_state.get("providers") or {}).values():
        for route in (provider.get("routes") or []):
            route_count += 1
            last_error = str(route.get("last_error") or "").lower()
            if any(token in last_error for token in ("401", "429", "missing scopes", "auth", "unauthorized")):
                failures += 1
                auth_like += 1
    return {
        "provider_route_count": route_count,
        "provider_failure_count": failures,
        "provider_auth_failure_count": auth_like,
    }


def _repair_history_summary(repair_history: list[dict[str, Any]]) -> dict[str, Any]:
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = 0
    names: list[str] = []
    for item in repair_history:
        updated = _parse_time(item.get("finished_at") or item.get("started_at") or item.get("updated_at"))
        if updated is None or updated < recent_cutoff:
            continue
        recent += 1
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    latest = repair_history[-1] if repair_history else {}
    return {
        "repair_actions_last_24h": recent,
        "repair_action_names_last_24h": names[:10],
        "latest_repair_action": latest.get("name"),
        "latest_repair_result": latest.get("result"),
        "latest_repair_finished_at": latest.get("finished_at") or latest.get("updated_at"),
    }


def _catalog() -> dict[str, Any]:
    payload = _load_json(RISK_CATALOG_PATH, {})
    if isinstance(payload, dict) and payload.get("risks"):
        return payload
    return {"version": "v1", "risks": DEFAULT_RISK_CATALOG}


def build_runtime_snapshot() -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    daemon_state = _load_json(DAEMON_STATE_PATH, {})
    factory_state = _load_json(FACTORY_STATE_PATH, {})
    control_layer = _load_json(CONTROL_LAYER_PATH, {})
    verification_status = _load_json(VERIFICATION_STATUS_PATH, {})
    artifact_registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    goal_backlog = _load_json(GOAL_BACKLOG_PATH, {})
    quality_status = _load_json(QUALITY_STATUS_PATH, {})
    release_ops = _load_json(RELEASE_OPERATIONS_PATH, {})
    repair_history = _load_json(REPAIR_HISTORY_PATH, [])
    provider_state = provider_gateway.get_state()
    identity_kernel = _load_json(DATA / "identity_kernel.json", {})
    self_model_runtime = _load_json(DATA / "self_model_runtime.json", {})

    task_summary = _task_summary(tasks)
    artifact_summary = _artifact_summary(artifact_registry)
    provider_summary = _provider_summary(provider_state)
    repair_summary = _repair_history_summary(repair_history)
    continuity = factory_state.get("consistency") or {}
    delayed_verification = verification_status.get("delayed_verification") or {}
    release_train = release_ops.get("release_train") or {}
    goal_primary = (
        daemon_state.get("last_self_model_goal")
        or (identity_kernel.get("runtime") or {}).get("goal_primary")
        or self_model_runtime.get("goal")
        or factory_state.get("goal_primary")
    )
    goal_mode = (
        daemon_state.get("last_self_model_mode")
        or (identity_kernel.get("runtime") or {}).get("goal_mode")
        or self_model_runtime.get("mode")
        or factory_state.get("goal_mode")
    )
    heartbeat_at = daemon_state.get("heartbeat_at")
    heartbeat_fresh = False
    if heartbeat_at:
        parsed = _parse_time(heartbeat_at)
        heartbeat_fresh = parsed is not None and parsed >= datetime.now(timezone.utc) - timedelta(minutes=5)
    daemon_running = bool(daemon_state.get("running")) or str(daemon_state.get("status") or "").strip().lower() == "running"
    state_write_error_recent = any(
        token in str(daemon_state.get("last_error") or "").lower()
        for token in ("permissionerror", "state_write", "access denied")
    ) or any("state_write_permission_denied" in str(item).lower() for item in (continuity.get("findings") or []))

    return {
        "updated_at": _utc(),
        "goal_primary": goal_primary,
        "goal_mode": goal_mode,
        "daemon_running": daemon_running,
        "daemon_status": daemon_state.get("status") or factory_state.get("daemon", {}).get("status"),
        "daemon_cycle": int(daemon_state.get("cycle") or factory_state.get("daemon", {}).get("cycle") or 0),
        "daemon_last_tick_at": daemon_state.get("last_tick_at") or factory_state.get("daemon", {}).get("last_tick_at"),
        "daemon_heartbeat_fresh": heartbeat_fresh,
        "control_layer_status": control_layer.get("status"),
        "control_layer_quality_status": control_layer.get("quality_status") or (control_layer.get("quality_system") or {}).get("status"),
        "quality_status": quality_status.get("status"),
        "quality_score": quality_status.get("overall_score"),
        "verification_status": verification_status.get("status"),
        "verification_pending_checks_count": int(delayed_verification.get("pending_count") or len(delayed_verification.get("pending_checks") or [])),
        "verification_pending_checks": list(delayed_verification.get("pending_checks") or []),
        "artifact_registry_status": artifact_registry.get("status"),
        "artifact_updates_last_24h": artifact_summary["artifact_updates_last_24h"],
        "release_train_status": str(release_train.get("status") or "").strip().lower(),
        "release_gate_status": str(verification_status.get("release_gate", {}).get("status") or "").strip().lower(),
        "continuity_mode": str(continuity.get("runtime_continuity") or continuity.get("state_continuity") or "").strip().lower(),
        "state_write_error_recent": state_write_error_recent,
        "queue_depth": task_summary["queue_depth"],
        "active_tasks": task_summary["active_tasks"],
        "completed_tasks_last_60m": task_summary["completed_tasks_last_60m"],
        "worker_idle_ratio": task_summary["worker_idle_ratio"],
        "task_status_counts": task_summary["status_counts"],
        "goal_backlog": goal_backlog,
        "goal_backlog_last_success_at": goal_backlog.get("last_replenished_at"),
        "provider_gateway": provider_state,
        "provider_route_count": provider_summary["provider_route_count"],
        "provider_failure_count": provider_summary["provider_failure_count"],
        "provider_auth_failure_count": provider_summary["provider_auth_failure_count"],
        "repair_history": repair_history,
        "repair_actions_last_24h": repair_summary["repair_actions_last_24h"],
        "latest_repair_action": repair_summary["latest_repair_action"],
        "latest_repair_result": repair_summary["latest_repair_result"],
        "latest_repair_finished_at": repair_summary["latest_repair_finished_at"],
        "raw": {
            "factory_state": factory_state,
            "control_layer": control_layer,
            "verification_status": verification_status,
            "artifact_registry": artifact_registry,
            "quality_status": quality_status,
            "release_operations": release_ops,
            "daemon_state": daemon_state,
            "self_model_runtime": self_model_runtime,
        },
    }


def _risk_template(risk_id: str, snapshot: dict[str, Any], *, confidence: float, signals: dict[str, Any], note: str | None = None) -> dict[str, Any]:
    catalog = _catalog().get("risks") or {}
    spec = dict(catalog.get(risk_id) or DEFAULT_RISK_CATALOG[risk_id])
    payload = {
        "risk_id": risk_id,
        "title": spec["title"],
        "domain": spec["domain"],
        "severity": spec["severity"],
        "kind": spec["kind"],
        "detected_at": _utc(),
        "signals": signals,
        "blast_radius": spec["blast_radius"],
        "confidence": round(float(confidence), 4),
        "candidate_root_causes": list(spec["candidate_root_causes"]),
        "allowed_actions": list(spec["allowed_actions"]),
        "forbidden_actions": list(spec["forbidden_actions"]),
        "verification_plan": list(spec["verification_plan"]),
        "rollback_plan": spec["rollback_plan"],
        "source_snapshot": {
            "goal_primary": snapshot.get("goal_primary"),
            "goal_mode": snapshot.get("goal_mode"),
            "daemon_cycle": snapshot.get("daemon_cycle"),
            "queue_depth": snapshot.get("queue_depth"),
            "active_tasks": snapshot.get("active_tasks"),
        },
    }
    if note:
        payload["note"] = note
    payload["signal_fingerprint"] = hashlib.sha256(
        json.dumps(
            {"risk_id": risk_id, "signals": signals, "goal_primary": snapshot.get("goal_primary"), "daemon_cycle": snapshot.get("daemon_cycle")},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return payload


def _detect_queue_starvation(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("goal_primary") and int(snapshot.get("active_tasks") or 0) == 0 and int(snapshot.get("queue_depth") or 0) == 0 and float(snapshot.get("worker_idle_ratio") or 0.0) > 0.8 and int(snapshot.get("completed_tasks_last_60m") or 0) == 0)


def _detect_false_liveness(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("daemon_running") and snapshot.get("daemon_heartbeat_fresh") and int(snapshot.get("completed_tasks_last_60m") or 0) == 0 and int(snapshot.get("artifact_updates_last_24h") or 0) == 0 and snapshot.get("goal_primary"))


def _detect_verification_misalignment(snapshot: dict[str, Any]) -> bool:
    pending = int(snapshot.get("verification_pending_checks_count") or 0)
    release_status = str(snapshot.get("release_train_status") or "").lower()
    return bool(pending > 0 and (release_status == "ready" or str(snapshot.get("verification_status") or "").lower() == "pass" or str(snapshot.get("quality_status") or "").lower() in {"ready", "pass", "promote"}))


def _detect_model_routing_degradation(snapshot: dict[str, Any]) -> bool:
    auth_failures = int(snapshot.get("provider_auth_failure_count") or 0)
    route_count = int(snapshot.get("provider_route_count") or 0)
    return bool(route_count > 0 and auth_failures > 0 and (int(snapshot.get("provider_failure_count") or 0) >= auth_failures or "cheap only" in str(snapshot.get("goal_mode") or "").lower()))


def _detect_config_drift(snapshot: dict[str, Any]) -> bool:
    factory_control = ((snapshot.get("raw") or {}).get("factory_state") or {}).get("control_layer") or {}
    control_layer = (snapshot.get("raw") or {}).get("control_layer") or {}
    verification = (snapshot.get("raw") or {}).get("verification_status") or {}
    return bool(
        (str(factory_control.get("status") or "") and str(factory_control.get("status") or "") != str(control_layer.get("status") or ""))
        or str(((control_layer.get("signal_policy") or {}).get("verification") or {}).get("policy_version") or "")
        != str(((verification.get("signal_policy") or {}).get("policy_version") or ""))
        or str((control_layer.get("quality_status") or (control_layer.get("quality_system") or {}).get("status") or ""))
        != str(snapshot.get("quality_status") or "")
    )


def _detect_continuity_distortion(snapshot: dict[str, Any]) -> bool:
    return bool(str(snapshot.get("continuity_mode") or "").startswith("preserv") and bool(snapshot.get("state_write_error_recent")))


def _detect_release_mispromotion(snapshot: dict[str, Any]) -> bool:
    pending = int(snapshot.get("verification_pending_checks_count") or 0)
    quality_status = str(snapshot.get("quality_status") or "").lower()
    release_status = str(snapshot.get("release_train_status") or "").lower()
    return bool(pending > 0 and quality_status not in {"ready", "pass"} and release_status in {"ready", "candidate"})


def _detect_repair_secondary_damage(snapshot: dict[str, Any]) -> bool:
    latest = str(snapshot.get("latest_repair_action") or "").lower()
    queue_depth = int(snapshot.get("queue_depth") or 0)
    active_tasks = int(snapshot.get("active_tasks") or 0)
    provider_auth_failure_count = int(snapshot.get("provider_auth_failure_count") or 0)
    return bool(
        latest in {"rebuild_priority_tasks", "poke_scheduler", "switch_provider_fallback", "freeze_release_train"}
        and (
            (latest in {"rebuild_priority_tasks", "poke_scheduler"} and queue_depth == 0 and active_tasks == 0 and snapshot.get("goal_primary"))
            or (latest == "switch_provider_fallback" and provider_auth_failure_count > 0)
            or (latest == "freeze_release_train" and str(snapshot.get("release_train_status") or "").lower() == "blocked")
        )
    )


class RiskEngine:
    def scan(self, snapshot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        snapshot = snapshot or build_runtime_snapshot()
        risks: list[dict[str, Any]] = []
        if _detect_queue_starvation(snapshot):
            risks.append(_risk_template("runtime.queue_starvation", snapshot, confidence=0.93, signals={"goal_primary": snapshot.get("goal_primary"), "queue_depth": snapshot.get("queue_depth"), "active_tasks": snapshot.get("active_tasks"), "worker_idle_ratio": snapshot.get("worker_idle_ratio"), "completed_tasks_last_60m": snapshot.get("completed_tasks_last_60m")}))
        if _detect_false_liveness(snapshot):
            risks.append(_risk_template("runtime.false_liveness", snapshot, confidence=0.9, signals={"daemon_running": snapshot.get("daemon_running"), "daemon_heartbeat_fresh": snapshot.get("daemon_heartbeat_fresh"), "completed_tasks_last_60m": snapshot.get("completed_tasks_last_60m"), "artifact_updates_last_24h": snapshot.get("artifact_updates_last_24h"), "goal_primary": snapshot.get("goal_primary")}))
        if _detect_verification_misalignment(snapshot):
            risks.append(_risk_template("verification.misalignment", snapshot, confidence=0.92, signals={"verification_pending_checks_count": snapshot.get("verification_pending_checks_count"), "release_train_status": snapshot.get("release_train_status"), "quality_status": snapshot.get("quality_status"), "artifact_registry_status": snapshot.get("artifact_registry_status")}))
        if _detect_model_routing_degradation(snapshot):
            risks.append(_risk_template("routing.model_degradation", snapshot, confidence=0.88, signals={"provider_route_count": snapshot.get("provider_route_count"), "provider_failure_count": snapshot.get("provider_failure_count"), "provider_auth_failure_count": snapshot.get("provider_auth_failure_count"), "latest_repair_action": snapshot.get("latest_repair_action")}))
        if _detect_config_drift(snapshot):
            risks.append(_risk_template("config.drift", snapshot, confidence=0.77, signals={"factory_control_status": ((snapshot.get("raw") or {}).get("factory_state") or {}).get("control_layer", {}).get("status"), "control_layer_status": snapshot.get("control_layer_status"), "verification_status": snapshot.get("verification_status"), "quality_status": snapshot.get("quality_status")}))
        if _detect_continuity_distortion(snapshot):
            risks.append(_risk_template("continuity.distortion", snapshot, confidence=0.91, signals={"continuity_mode": snapshot.get("continuity_mode"), "state_write_error_recent": snapshot.get("state_write_error_recent"), "daemon_last_tick_at": snapshot.get("daemon_last_tick_at")}))
        if _detect_release_mispromotion(snapshot):
            risks.append(_risk_template("release.promotion_mismatch", snapshot, confidence=0.96, signals={"verification_pending_checks_count": snapshot.get("verification_pending_checks_count"), "quality_status": snapshot.get("quality_status"), "release_train_status": snapshot.get("release_train_status"), "release_gate_status": snapshot.get("release_gate_status")}))
        if _detect_repair_secondary_damage(snapshot):
            risks.append(_risk_template("repair.secondary_damage", snapshot, confidence=0.8, signals={"latest_repair_action": snapshot.get("latest_repair_action"), "latest_repair_result": snapshot.get("latest_repair_result"), "queue_depth": snapshot.get("queue_depth"), "provider_auth_failure_count": snapshot.get("provider_auth_failure_count")}))
        return risks

