from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json
from tools.memory_objects import memory_integrity_report

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CODEX_ROOT = ROOT.parent
SYSTEM_IDENTITY_PATH = CODEX_ROOT / "METAFORGE_OS_SYSTEM_IDENTITY.json"
CORE_AGENT_PATH = DATA / "core_agent_profile.json"
SELF_MODEL_PATH = DATA / "self_model_runtime.json"
CONTROL_SESSION_PATH = DATA / "control_session.json"
CONTROL_CENTER_PATH = DATA / "control_center_state.json"
DAEMON_STATE_PATH = DATA / "factory_daemon_state.json"
KERNEL_PATH = DATA / "identity_kernel.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _source_revision(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        stat = path.stat()
        parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
    return "|".join(parts)


def _system_identity_payload(
    *,
    kernel: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = previous or _load_json(SYSTEM_IDENTITY_PATH, {})
    identity = kernel.get("identity") or {}
    operator = kernel.get("operator") or {}
    authority = kernel.get("authority") or {}
    runtime = kernel.get("runtime") or {}
    memory = kernel.get("memory") or {}
    consistency = kernel.get("consistency") or {}
    continuity = kernel.get("continuity") or {}
    policy = kernel.get("policy") or {}
    live_state = {
        "updated_at": kernel.get("updated_at"),
        "status": kernel.get("status"),
        "summary": kernel.get("summary"),
        "operator": operator,
        "authority": authority,
        "runtime": runtime,
        "memory": memory,
        "consistency": consistency,
        "continuity": continuity,
        "identity_revision": continuity.get("identity_revision"),
    }
    payload = {
        "name": previous.get("name") or identity.get("name"),
        "system_id": previous.get("system_id") or identity.get("system_id"),
        "type": previous.get("type") or identity.get("type"),
        "mission": previous.get("mission") or identity.get("mission"),
        "primary_operator_surface": previous.get("primary_operator_surface") or identity.get("primary_operator_surface"),
        "execution_entrypoint": previous.get("execution_entrypoint") or str(CODEX_ROOT / "factoryctl.cmd"),
        "persistent_state_root": previous.get("persistent_state_root") or str(DATA),
        "identity_questions": previous.get("identity_questions") or policy.get("identity_questions") or {},
        "components": previous.get("components") or identity.get("components") or [],
        "core_capabilities": previous.get("core_capabilities") or identity.get("core_capabilities") or [],
        "operating_modes": previous.get("operating_modes") or identity.get("operating_modes") or [],
        "governance_rules": previous.get("governance_rules") or policy.get("governance_rules") or [],
        "fallback_strategy": previous.get("fallback_strategy") or policy.get("fallback_strategy") or {},
        "departments": previous.get("departments") or ["planning", "engineering", "qa", "operations", "research"],
        "live_state": live_state,
        "last_updated": kernel.get("updated_at"),
        "live_revision": continuity.get("identity_revision"),
        "source_paths": {
            "kernel": str(KERNEL_PATH),
            "core_agent": str(CORE_AGENT_PATH),
            "self_model_runtime": str(SELF_MODEL_PATH),
            "control_session": str(CONTROL_SESSION_PATH),
            "control_center": str(CONTROL_CENTER_PATH),
            "daemon_state": str(DAEMON_STATE_PATH),
            "memory_integrity": str(DATA / "memory_objects.jsonl"),
        },
    }
    return payload


def refresh_system_identity_ssot(*, kernel: dict[str, Any] | None = None) -> dict[str, Any]:
    kernel = kernel or build_identity_kernel()
    payload = _system_identity_payload(kernel=kernel)
    atomic_write_json(SYSTEM_IDENTITY_PATH, payload)
    return payload


def system_identity_status(*, refresh: bool = False) -> dict[str, Any]:
    if refresh or not SYSTEM_IDENTITY_PATH.exists():
        return refresh_system_identity_ssot()
    payload = _load_json(SYSTEM_IDENTITY_PATH, {})
    if not payload:
        return refresh_system_identity_ssot()
    return payload


def _consistency_findings(
    *,
    system_identity: dict[str, Any],
    core_agent: dict[str, Any],
    self_model_runtime: dict[str, Any],
    control_session: dict[str, Any],
    control_center: dict[str, Any],
    daemon_state: dict[str, Any],
    memory_integrity: dict[str, Any],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    state = self_model_runtime.get("state") or {}
    goal = self_model_runtime.get("goal") or {}
    daemon = state.get("daemon") or {}
    state_health = str(state.get("health") or "unknown")
    daemon_status = str(daemon.get("status") or "unknown")
    daemon_running = bool(daemon.get("running"))
    control_status = str(state.get("control_status") or "unknown")
    runtime_goal = str(goal.get("primary") or "")
    runtime_mode = str(goal.get("mode") or "")
    system_name = str(system_identity.get("name") or "")
    system_id = str(system_identity.get("system_id") or "")
    runtime_name = str((self_model_runtime.get("identity") or {}).get("name") or "")
    runtime_system_id = str((self_model_runtime.get("identity") or {}).get("system_id") or "")
    operator_interface = str(core_agent.get("operator_interface") or "")
    control_center_active = bool(not control_center.get("paused"))

    if system_name and runtime_name and system_name != runtime_name:
        findings.append({
            "code": "system_name_mismatch",
            "severity": "warning",
            "detail": f"system_identity.name={system_name} differs from self_model_runtime.identity.name={runtime_name}",
        })
    if system_id and runtime_system_id and system_id != runtime_system_id:
        findings.append({
            "code": "system_id_mismatch",
            "severity": "warning",
            "detail": f"system_identity.system_id={system_id} differs from self_model_runtime.identity.system_id={runtime_system_id}",
        })
    if runtime_goal and runtime_goal != "restore_toyos_delivery":
        findings.append({
            "code": "goal_drift",
            "severity": "attention",
            "detail": f"runtime goal primary is {runtime_goal}",
        })
    if runtime_mode and runtime_mode != "toyos_priority_mode":
        findings.append({
            "code": "mode_drift",
            "severity": "attention",
            "detail": f"runtime goal mode is {runtime_mode}",
        })
    if operator_interface and operator_interface != "codex":
        findings.append({
            "code": "operator_interface_mismatch",
            "severity": "warning",
            "detail": f"core_agent.operator_interface={operator_interface}",
        })
    if daemon_running != (daemon_status == "running"):
        findings.append({
            "code": "daemon_running_mismatch",
            "severity": "warning",
            "detail": f"daemon.running={daemon_running} but daemon.status={daemon_status}",
        })
    if daemon_state.get("status") == "stale" and daemon_running:
        findings.append({
            "code": "daemon_state_stale",
            "severity": "attention",
            "detail": f"factory_daemon_state.json reports stale while runtime treats daemon as running",
        })
    if control_status != "active" and control_center_active:
        findings.append({
            "code": "control_status_mismatch",
            "severity": "warning",
            "detail": f"state.control_status={control_status} while control_center is active",
        })
    if memory_integrity.get("status") != "ok":
        findings.append({
            "code": "memory_integrity_bad",
            "severity": "warning",
            "detail": f"memory integrity is {memory_integrity.get('status')}",
        })
    if (memory_integrity.get("stale_cache_entry_count") or 0) > 0:
        findings.append({
            "code": "stale_memory_cache",
            "severity": "attention",
            "detail": f"stale cache entries={memory_integrity.get('stale_cache_entry_count')}",
        })
    if not control_session.get("active"):
        findings.append({
            "code": "inactive_control_session",
            "severity": "warning",
            "detail": "control session is inactive",
        })

    overall = "ok"
    if any(item.get("severity") in {"warning", "critical"} for item in findings):
        overall = "attention"
    return {
        "status": overall,
        "finding_count": len(findings),
        "findings": findings,
    }


def build_identity_kernel(
    *,
    system_identity: dict[str, Any] | None = None,
    core_agent: dict[str, Any] | None = None,
    self_model_runtime: dict[str, Any] | None = None,
    control_session: dict[str, Any] | None = None,
    control_center: dict[str, Any] | None = None,
    daemon_state: dict[str, Any] | None = None,
    memory_integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_identity = system_identity or _load_json(SYSTEM_IDENTITY_PATH, {})
    core_agent = core_agent or _load_json(CORE_AGENT_PATH, {})
    self_model_runtime = self_model_runtime or _load_json(SELF_MODEL_PATH, {})
    control_session = control_session or _load_json(CONTROL_SESSION_PATH, {})
    control_center = control_center or _load_json(CONTROL_CENTER_PATH, {})
    daemon_state = daemon_state or _load_json(DAEMON_STATE_PATH, {})
    memory_integrity = memory_integrity or memory_integrity_report()
    if not system_identity:
        system_identity = self_model_runtime.get("identity") or {}
    consistency = _consistency_findings(
        system_identity=system_identity,
        core_agent=core_agent,
        self_model_runtime=self_model_runtime,
        control_session=control_session,
        control_center=control_center,
        daemon_state=daemon_state,
        memory_integrity=memory_integrity,
    )

    identity = {
        "name": system_identity.get("name"),
        "system_id": system_identity.get("system_id"),
        "type": system_identity.get("type"),
        "mission": system_identity.get("mission"),
        "primary_operator_surface": system_identity.get("primary_operator_surface"),
        "components": (system_identity.get("components") or [])[:12],
        "core_capabilities": (system_identity.get("core_capabilities") or [])[:12],
        "operating_modes": (system_identity.get("operating_modes") or [])[:8],
    }
    operator = {
        "name": core_agent.get("name"),
        "mode": core_agent.get("mode"),
        "role": core_agent.get("role"),
        "operator_interface": core_agent.get("operator_interface"),
        "expensive_model_policy": core_agent.get("expensive_model_policy"),
        "updated_at": core_agent.get("updated_at"),
    }
    authority = {
        "session_active": bool((control_session or {}).get("active")),
        "session_owner": control_session.get("owner"),
        "session_role": control_session.get("role"),
        "session_scope": control_session.get("scope"),
        "control_center_status": control_center.get("status"),
        "control_center_paused": bool(control_center.get("paused")),
        "control_center_reason": control_center.get("reason"),
    }
    state = self_model_runtime.get("state") or {}
    goal = self_model_runtime.get("goal") or {}
    world = self_model_runtime.get("world") or {}
    memory = {
        "status": memory_integrity.get("status"),
        "verified_object_count": memory_integrity.get("verified_object_count"),
        "candidate_count": memory_integrity.get("candidate_count"),
        "expired_handoffs": memory_integrity.get("expired_handoffs") or [],
        "stale_cache_entry_count": memory_integrity.get("stale_cache_entry_count"),
        "current_memory_revision": memory_integrity.get("current_memory_revision"),
    }
    runtime = {
        "health": state.get("health"),
        "control_status": state.get("control_status"),
        "autonomy_stage": ((state.get("autonomy") or {}).get("stage")),
        "autonomy_score": ((state.get("autonomy") or {}).get("score")),
        "quality_status": ((state.get("quality") or {}).get("status")),
        "quality_score": ((state.get("quality") or {}).get("score")),
        "daemon_status": ((state.get("daemon") or {}).get("status")),
        "daemon_running": bool((state.get("daemon") or {}).get("running")),
        "goal_primary": goal.get("primary"),
        "goal_mode": goal.get("mode"),
        "workspace_root": world.get("workspace_root"),
        "primary_workspaces": world.get("primary_workspaces") or [],
        "production_focus": ((state.get("production_focus") or {}).get("primary_artifact_id")),
        "blocked_count": len(state.get("blockers") or []),
    }
    continuity = {
        "last_verified_at": memory_integrity.get("last_verified_at"),
        "daemon_last_tick_at": ((daemon_state or {}).get("last_tick_at")),
        "daemon_freshness_seconds": ((daemon_state or {}).get("freshness_seconds")),
        "identity_revision": _source_revision([
            SYSTEM_IDENTITY_PATH,
            CORE_AGENT_PATH,
            SELF_MODEL_PATH,
            CONTROL_SESSION_PATH,
            CONTROL_CENTER_PATH,
            DAEMON_STATE_PATH,
            DATA / "memory_objects.jsonl",
            DATA / "memory_candidates.jsonl",
        ]),
    }
    status = "stable"
    if memory.get("status") != "ok":
        status = "attention"
    if runtime["health"] != "healthy" or runtime["daemon_status"] not in {"running", "fresh"}:
        status = "attention"
    if authority["control_center_paused"]:
        status = "attention"
    if consistency["status"] != "ok":
        status = "attention"

    return {
        "updated_at": _utc(),
        "status": status,
        "summary": f"{identity.get('name')} on {operator.get('operator_interface')} with goal={runtime.get('goal_primary')}",
        "identity": identity,
        "operator": operator,
        "authority": authority,
        "runtime": runtime,
        "memory": memory,
        "consistency": consistency,
        "continuity": continuity,
        "policy": {
            "fallback_strategy": system_identity.get("fallback_strategy") or {},
            "governance_rules": system_identity.get("governance_rules") or [],
            "identity_questions": system_identity.get("identity_questions") or {},
        },
        "sources": {
            "system_identity": str(SYSTEM_IDENTITY_PATH),
            "core_agent": str(CORE_AGENT_PATH),
            "self_model_runtime": str(SELF_MODEL_PATH),
            "control_session": str(CONTROL_SESSION_PATH),
            "control_center": str(CONTROL_CENTER_PATH),
            "daemon_state": str(DAEMON_STATE_PATH),
            "memory_integrity": str(DATA / "memory_objects.jsonl"),
        },
    }


def refresh_identity_kernel() -> dict[str, Any]:
    kernel = build_identity_kernel()
    atomic_write_json(KERNEL_PATH, kernel)
    refresh_system_identity_ssot(kernel=kernel)
    return kernel


def identity_kernel_status(*, refresh: bool = False) -> dict[str, Any]:
    if refresh or not KERNEL_PATH.exists():
        return refresh_identity_kernel()
    kernel = _load_json(KERNEL_PATH, {})
    if not kernel:
        return refresh_identity_kernel()
    return kernel
