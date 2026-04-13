from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.control_plane_policy import DEFAULT_CONTROL_POLICY, load_control_policy, save_control_policy
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODE_PATH = DATA / "kernel_mode.json"

DEFAULT_COMPONENTS = {
    "orchestrator": True,
    "scheduler": True,
    "task_queue": True,
    "model_router": True,
    "workspace": True,
    "governance": True,
    "observer": True,
    "policy_contract": True,
    "approval": True,
    "security_review": True,
    "experiments": True,
    "github_learning": True,
    "coordination": True,
    "release_train": True,
    "platform_generation": True,
}

LEAN_COMPONENTS = {
    **DEFAULT_COMPONENTS,
    "governance": False,
    "observer": False,
    "policy_contract": False,
    "approval": False,
    "security_review": False,
    "experiments": False,
    "github_learning": False,
    "coordination": False,
    "release_train": False,
    "platform_generation": False,
}

DEFAULT_MODEL_ROUTER = {
    "default_lane": "reasoning",
    "fallback_lane": "strategic",
    "local_lane_enabled": False,
}

DEFAULT_MODE = {
    "profile": "standard",
    "kernel_freeze": False,
    "manual_lock": False,
    "auto_exit": True,
    "operator_role": "operator",
    "execution_mode": "production",
    "security_mode": "minimal",
    "task_type": "production",
    "workspace_write_scope": "workspace_only",
    "task_auto_approve": False,
    "components": DEFAULT_COMPONENTS,
    "model_router": DEFAULT_MODEL_ROUTER,
    "reasons": [],
}

LEAN_MODE = {
    **DEFAULT_MODE,
    "profile": "lean_execution",
    "kernel_freeze": True,
    "task_auto_approve": True,
    "components": LEAN_COMPONENTS,
    "reasons": [
        "lean_execution_profile",
        "keep_only_execution_kernel",
    ],
}

INTERACTION_ONLY_MODE = {
    **DEFAULT_MODE,
    "profile": "interaction_only",
    "kernel_freeze": True,
    "task_auto_approve": False,
    "components": LEAN_COMPONENTS,
    "reasons": [
        "interaction_only_profile",
        "route_requests_to_executors",
        "disable_self_repair_loops",
    ],
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


def _clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _normalize_reason_list(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _auto_reasons(signals: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    control = signals.get("control") or {}
    daemon = signals.get("daemon") or {}
    state_kernel = control.get("state_kernel") or {}
    control_decisions = ((control.get("decision_engine") or {}).get("decisions") or [])

    control_status = str(control.get("status") or "").strip().lower()
    active_tasks = int(state_kernel.get("active_tasks", 0) or 0)
    runtime_blocking_decisions = {"throttle-runtime", "throttle-meta", "throttle-evolution", "kernel-freeze"}
    has_runtime_block = any(
        str(item.get("decision") or "").strip() in runtime_blocking_decisions
        or str(item.get("applies_to") or "").strip() == "control-plane"
        for item in control_decisions
        if isinstance(item, dict)
    )
    if control_status in {"constrained", "operator_attention"} and active_tasks == 0 and has_runtime_block:
        reasons.append("control_constrained_with_zero_active_tasks")

    daemon_status = str(daemon.get("status") or "").strip().lower()
    if daemon.get("last_error") or daemon_status in {"error", "stale", "operator_attention"}:
        reasons.append("daemon_fault_signal")

    return reasons


def _base_mode(profile: str) -> dict[str, Any]:
    if profile == "lean_execution":
        return _clone(LEAN_MODE)
    if profile == "interaction_only":
        return _clone(INTERACTION_ONLY_MODE)
    return _clone(DEFAULT_MODE)


def _normalize_mode(raw: dict[str, Any] | None, *, signals: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or {}
    profile = str(raw.get("profile") or "").strip().lower() or "standard"
    mode = _base_mode(profile)
    base_configured = bool(mode.get("kernel_freeze", False))
    has_explicit_freeze = "kernel_freeze" in raw
    configured = bool(raw.get("kernel_freeze", base_configured))
    manual_lock = bool(raw.get("manual_lock", mode.get("manual_lock", False)))
    auto_exit = bool(raw.get("auto_exit", mode.get("auto_exit", True)))
    reasons = _normalize_reason_list(mode.get("reasons"))
    reasons.extend(item for item in _normalize_reason_list(raw.get("reasons")) if item not in reasons)
    auto = _auto_reasons(signals or {})

    source = "default"
    if manual_lock:
        enabled = configured
        source = "manual_lock"
        if enabled and "manual_lock" not in reasons:
            reasons.append("manual_lock")
    elif has_explicit_freeze:
        enabled = configured
        source = "file"
    elif base_configured:
        enabled = True
        source = "profile"
    else:
        enabled = bool(auto)
        if enabled:
            source = "auto"

    if source == "auto" and auto:
        reasons.extend(item for item in auto if item not in reasons)
    elif manual_lock and not auto_exit and auto:
        reasons.extend(item for item in auto if item not in reasons)

    components = dict(mode.get("components") or {})
    raw_components = raw.get("components") or {}
    if isinstance(raw_components, dict):
        for name, value in raw_components.items():
            components[str(name)] = bool(value)

    for item in raw.get("disabled_components") or []:
        name = str(item or "").strip()
        if name:
            components[name] = False
    for item in raw.get("enabled_components") or []:
        name = str(item or "").strip()
        if name:
            components[name] = True

    model_router = dict(mode.get("model_router") or {})
    model_router.update(raw.get("model_router") or {})

    active_components = sorted(name for name, enabled_flag in components.items() if enabled_flag)
    disabled_components = sorted(name for name, enabled_flag in components.items() if not enabled_flag)

    return {
        "profile": profile,
        "kernel_freeze": enabled,
        "manual_lock": manual_lock,
        "auto_exit": auto_exit,
        "source": source,
        "reasons": reasons,
        "operator_role": str(raw.get("operator_role") or mode.get("operator_role") or "operator"),
        "execution_mode": str(raw.get("execution_mode") or mode.get("execution_mode") or "production"),
        "security_mode": str(raw.get("security_mode") or mode.get("security_mode") or "minimal"),
        "task_type": str(raw.get("task_type") or mode.get("task_type") or "production"),
        "workspace_write_scope": str(raw.get("workspace_write_scope") or mode.get("workspace_write_scope") or "workspace_only"),
        "task_auto_approve": bool(raw.get("task_auto_approve", mode.get("task_auto_approve", False))),
        "components": components,
        "enabled_components": active_components,
        "disabled_components": disabled_components,
        "model_router": model_router,
    }


def load_kernel_mode(signals: dict[str, Any] | None = None) -> dict[str, Any]:
    return _normalize_mode(_load_json(MODE_PATH, {}), signals=signals)


def is_component_enabled(component: str, mode: dict[str, Any] | None = None) -> bool:
    current = mode or load_kernel_mode()
    return bool((current.get("components") or {}).get(component, False))


def _is_internal_runtime_scheduler(scheduled_by: str | None, hint: dict[str, Any]) -> bool:
    candidates = [
        str(scheduled_by or "").strip().lower(),
        str(hint.get("scheduled_by") or "").strip().lower(),
        str(hint.get("caller") or "").strip().lower(),
    ]
    return any(
        candidate.startswith("runtime.") or candidate in {"brain-loop", "factory-daemon", "codex-control"}
        for candidate in candidates
        if candidate
    )


def should_auto_approve_task(
    *,
    requested: bool,
    execution_mode: str | None = None,
    scheduler_hint: dict[str, Any] | None = None,
    scheduled_by: str | None = None,
) -> bool:
    hint = scheduler_hint or {}
    effective_mode = str(execution_mode or hint.get("execution_mode") or "").strip().lower()
    if not effective_mode:
        factory_pool = str(hint.get("factory_pool") or "").strip().lower()
        if factory_pool in {"production", "ops"}:
            effective_mode = "production"

    if requested:
        return True

    if _is_internal_runtime_scheduler(scheduled_by, hint):
        return True

    mode = load_kernel_mode()
    if not bool(mode.get("task_auto_approve")):
        return False
    return effective_mode in {"production", "ops", ""}


def _workspace_manager_from(policy: dict[str, Any]) -> dict[str, Any]:
    current = policy.get("workspace_manager") or {}
    fallback = DEFAULT_CONTROL_POLICY.get("workspace_manager") or {}
    return {
        "write_roots": list(current.get("write_roots") or fallback.get("write_roots") or []),
        "core_roots": list(current.get("core_roots") or fallback.get("core_roots") or []),
    }


def _base_control_policy(current: dict[str, Any]) -> dict[str, Any]:
    policy = _clone(DEFAULT_CONTROL_POLICY)
    policy["workspace_manager"] = _workspace_manager_from(current)
    return policy


def _lean_control_policy(current: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    policy = _base_control_policy(current)
    policy["governance"].update(
        {
            "runtime_profile": mode.get("profile"),
            "active_modules": mode.get("enabled_components"),
            "disabled_modules": mode.get("disabled_components"),
        }
    )

    approvals = policy.setdefault("approvals", {})
    approvals["resolve_error_escalations"] = {"mode": "AUTO"}
    approvals["approved_patch"] = {"mode": "AUTO"}

    tooling = policy.setdefault("tooling", {})
    roles = tooling.setdefault("roles", {})
    for role_name in ("coder", "tester", "ops"):
        role = dict(roles.get(role_name) or {})
        allowed = [str(item) for item in (role.get("allow") or []) if str(item).strip()]
        if role_name == "coder":
            for action in ("shell_exec", "read_policy"):
                if action not in allowed:
                    allowed.append(action)
        role["allow"] = allowed
        role["approval_required"] = []
        roles[role_name] = role
    tooling["default_role"] = "coder"
    policy["tooling"] = tooling
    return policy


def _standard_control_policy(current: dict[str, Any], mode: dict[str, Any]) -> dict[str, Any]:
    policy = _base_control_policy(current)
    policy["governance"].update(
        {
            "runtime_profile": mode.get("profile"),
            "active_modules": mode.get("enabled_components"),
            "disabled_modules": mode.get("disabled_components"),
        }
    )
    approvals = policy.setdefault("approvals", {})
    approvals["resolve_error_escalations"] = {"mode": "AUTO"}
    return policy


def _policy_for_mode(mode: dict[str, Any], current_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    current = current_policy or load_control_policy()
    if mode.get("profile") == "lean_execution":
        return _lean_control_policy(current, mode)
    return _standard_control_policy(current, mode)


def apply_execution_profile(profile: str, *, reason: str | None = None, operator: str = "codex") -> dict[str, Any]:
    selected = str(profile or "").strip().lower() or "standard"
    mode = _normalize_mode(
        {
            "profile": selected,
            "kernel_freeze": selected == "lean_execution",
            "manual_lock": False,
            "auto_exit": True,
            "reasons": [reason] if reason else [],
            "updated_by": operator,
        }
    )
    atomic_write_json(
        MODE_PATH,
        {
            "profile": mode.get("profile"),
            "kernel_freeze": mode.get("kernel_freeze"),
            "manual_lock": False,
            "auto_exit": True,
            "reasons": mode.get("reasons"),
            "components": mode.get("components"),
            "task_auto_approve": mode.get("task_auto_approve"),
            "model_router": mode.get("model_router"),
            "updated_at": _utc(),
            "updated_by": operator,
        },
    )
    normalized = load_kernel_mode()
    control_policy = save_control_policy(_policy_for_mode(normalized))
    return {
        "kernel_mode": normalized,
        "control_policy": control_policy,
    }

