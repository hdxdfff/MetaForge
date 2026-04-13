from __future__ import annotations

from typing import Any

from tools.control_plane_policy import project_tool_policy


def load_tool_policy() -> dict[str, Any]:
    return project_tool_policy()


def resolve_task_role(preferred_worker: str | None, tool_route: dict[str, Any] | None = None, repo_path: str | None = None) -> str:
    policy = load_tool_policy()
    worker_key = (preferred_worker or "").strip().lower()
    if worker_key:
        return policy["worker_role_map"].get(worker_key, policy["default_role"])
    domain = str((((tool_route or {}).get("selected") or {}).get("domain")) or "").lower()
    if domain in {"system", "infrastructure", "containers"}:
        return "ops"
    if domain in {"review", "audit"}:
        return "reviewer"
    if domain in {"code", "testing"}:
        return "coder"
    if repo_path:
        return "coder"
    return policy["default_role"]


def build_task_tool_policy(*, preferred_worker: str | None, tool_route: dict[str, Any] | None, repo_path: str | None, execution_lane: str | None, auto_approve: bool, scheduled_by: str | None = None) -> dict[str, Any]:
    policy = load_tool_policy()
    role = resolve_task_role(preferred_worker, tool_route=tool_route)
    role_policy = policy["roles"].get(role, policy["roles"][policy["default_role"]])
    selected_tool = (tool_route or {}).get("selected") or {}
    allowed_actions = list(dict.fromkeys(role_policy.get("allow", [])))
    denied_actions = list(dict.fromkeys(role_policy.get("deny", [])))
    approval_required = list(dict.fromkeys(role_policy.get("approval_required", [])))
    execution_lane_name = str(execution_lane or "host-control").strip().lower()
    scheduled_by_name = str(scheduled_by or "").strip().lower()
    internal_runtime_task = scheduled_by_name.startswith(("runtime.", "brain-loop", "factory-daemon", "codex-control"))
    if internal_runtime_task and repo_path and role in {"coder", "reviewer", "tester", "ops"}:
        if "shell_exec" not in allowed_actions:
            allowed_actions.append("shell_exec")
        denied_actions = [item for item in denied_actions if item != "shell_exec"]
        approval_required = [item for item in approval_required if item != "shell_exec"]
    if selected_tool:
        allowed_actions.append("read_tool_context")
    return {
        "version": policy.get("version", 1),
        "role": role,
        "allowed_actions": sorted(set(allowed_actions)),
        "denied_actions": sorted(set(denied_actions)),
        "approval_required": sorted(set(approval_required)),
        "auto_approve": bool(auto_approve or internal_runtime_task),
        "repo_path": repo_path,
        "execution_lane": execution_lane_name,
        "selected_tool": selected_tool,
    }


def authorize_tool_action(snapshot: dict[str, Any] | None, action: str, *, auto_approve: bool = False) -> dict[str, Any]:
    snap = snapshot or {}
    allowed = set(snap.get("allowed_actions", []))
    denied = set(snap.get("denied_actions", []))
    approval_required = set(snap.get("approval_required", []))
    if action in denied:
        return {"allowed": False, "reason": f"Action {action} is denied for role {snap.get('role', 'unknown')}."}
    if action not in allowed:
        return {"allowed": False, "reason": f"Action {action} is not granted for role {snap.get('role', 'unknown')}."}
    if action in approval_required and not (auto_approve or snap.get("auto_approve")):
        return {"allowed": False, "reason": f"Action {action} requires explicit approval for role {snap.get('role', 'unknown')}."}
    return {"allowed": True, "reason": "approved"}
