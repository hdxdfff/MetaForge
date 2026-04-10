from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

CONTROL_POLICY_FILE = DATA / "control_policy.json"
APPROVAL_POLICY_FILE = DATA / "approval_policy.json"
SESSION_POLICY_FILE = DATA / "session_policy.json"
TOOL_POLICY_FILE = DATA / "tool_policy.json"
GUARD_POLICY_FILE = DATA / "guard_policy.json"


DEFAULT_CONTROL_POLICY: dict[str, Any] = {
    "version": 1,
    "governance": {
        "primary_control_plane": "orchestrator",
        "agent_runtime": "codex",
        "host_role": "resource-provider",
        "legacy_policy_views": [
            "approval_policy.json",
            "session_policy.json",
            "tool_policy.json",
        ],
    },
    "workspace_manager": {
        "write_roots": [
            str(ROOT / "workspace"),
            str(ROOT / "factory" / "workspace"),
        ],
        "core_roots": [
            str(ROOT / "app"),
            str(ROOT / "runtime"),
            str(ROOT / "tools"),
            str(ROOT / "brain"),
            str(ROOT / "state"),
        ],
    },
    "approvals": {
        "deploy_production": {"mode": "MANUAL"},
        "create_workspace": {"mode": "AUTO"},
        "dispatch_low_risk_goal_nodes": {"mode": "AUTO"},
        "modify_agents": {"mode": "MANUAL"},
        "modify_controller": {"mode": "MANUAL"},
        "resolve_warning_escalations": {"mode": "AUTO"},
        "resolve_error_escalations": {"mode": "MANUAL"},
        "approved_patch": {"mode": "MANUAL"},
        "filesystem.write_workspace": {
            "mode": "AUTO-LIMIT",
            "path_prefixes": [
                str(ROOT / "workspace"),
                str(ROOT / "factory" / "workspace"),
            ],
        },
        "filesystem.write_core": {"mode": "MANUAL"},
        "filesystem.delete": {"mode": "MANUAL"},
        "git.push": {
            "mode": "AUTO-LIMIT",
            "allowed_remotes": ["origin", "github", "gitee"],
        },
        "install_package": {
            "mode": "AUTO-LIMIT",
            "allowlist": ["numpy", "torch", "opencv-python", "pytest", "fastapi", "uvicorn"],
        },
        "docker.run": {
            "mode": "AUTO-LIMIT",
            "allow_images": ["python", "node", "postgres", "redis", "nginx"],
        },
    },
    "sessions": {
        "roles": {
            "guest": ["status", "brain-snapshot"],
            "observer": [
                "status",
                "brain-snapshot",
                "operator-report",
                "inbox",
                "goals",
                "daemon-status",
                "branch-workboard",
                "branch-status",
                "organization-workboard",
                "project-graph",
            ],
            "planner": [
                "status",
                "brain-snapshot",
                "operator-report",
                "inbox",
                "goals",
                "daemon-status",
                "branch-workboard",
                "branch-status",
                "organization-workboard",
                "project-graph",
                "branch-context",
                "branch-goal",
                "branch-capability-goal",
                "branch-test-goal",
                "branch-production-goal",
                "goal-new",
                "compile-goal",
                "brain-loop",
                "dispatch",
                "change-request",
                "replan",
            ],
            "operator": ["*"],
        },
        "single_control_session": False,
        "default_role_without_token": "observer",
    },
    "tooling": {
        "version": 1,
        "default_role": "observer",
        "worker_role_map": {
            "coder": "coder",
            "reviewer": "reviewer",
            "tester": "tester",
            "ops": "ops",
            "shell": "ops",
            "docker": "ops",
            "planner": "supervisor",
        },
        "roles": {
            "observer": {
                "allow": ["read_repo", "read_policy", "read_audit"],
                "deny": ["shell_exec", "docker_exec", "install_package", "git_push", "file_write_core"],
                "approval_required": [],
            },
            "coder": {
                "allow": ["read_repo", "file_write_workspace", "patch_workspace", "run_tests"],
                "deny": ["file_write_core", "install_package", "git_push"],
                "approval_required": ["shell_exec", "docker_exec"],
            },
            "tester": {
                "allow": ["read_repo", "run_tests", "shell_exec", "file_write_workspace"],
                "deny": ["file_write_core", "install_package", "git_push"],
                "approval_required": ["docker_exec"],
            },
            "reviewer": {
                "allow": ["read_repo", "read_policy", "read_audit"],
                "deny": ["shell_exec", "docker_exec", "install_package", "git_push", "file_write_core"],
                "approval_required": [],
            },
            "ops": {
                "allow": ["read_repo", "shell_exec", "docker_exec", "git_push", "file_write_workspace"],
                "deny": ["file_write_core"],
                "approval_required": ["shell_exec", "docker_exec", "git_push", "install_package"],
            },
            "supervisor": {
                "allow": ["read_repo", "read_policy", "read_audit", "post_core_message"],
                "deny": ["shell_exec", "docker_exec", "install_package", "git_push", "file_write_core"],
                "approval_required": [],
            },
            "security": {
                "allow": ["read_policy", "read_audit", "post_core_message", "veto_execution"],
                "deny": ["shell_exec", "docker_exec", "git_push", "install_package", "file_write_core"],
                "approval_required": [],
            },
        },
    },
}


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _clone(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _normalize_string_list(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalize_tool_role(role_policy: dict[str, Any] | None) -> dict[str, list[str]]:
    role_policy = role_policy or {}
    return {
        "allow": _normalize_string_list(role_policy.get("allow")),
        "deny": _normalize_string_list(role_policy.get("deny")),
        "approval_required": _normalize_string_list(role_policy.get("approval_required")),
    }


def _merge_approvals(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    merged = {key: dict(value or {}) for key, value in (base or {}).items()}
    for action, rule in (overlay or {}).items():
        if isinstance(rule, str):
            merged[action] = {"mode": str(rule).upper()}
            continue
        if not isinstance(rule, dict):
            continue
        item = dict(merged.get(action, {}))
        item.update(rule)
        item["mode"] = str(item.get("mode", "MANUAL")).upper()
        merged[action] = item
    return merged


def _merge_sessions(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    overlay = overlay or {}
    merged = {
        "roles": {name: _normalize_string_list(commands) for name, commands in (base.get("roles") or {}).items()},
        "single_control_session": bool(base.get("single_control_session", True)),
        "default_role_without_token": str(base.get("default_role_without_token", "observer")),
    }
    for role, commands in (overlay.get("roles") or {}).items():
        merged["roles"][role] = _normalize_string_list(commands)
    if "single_control_session" in overlay:
        merged["single_control_session"] = bool(overlay.get("single_control_session"))
    if overlay.get("default_role_without_token"):
        merged["default_role_without_token"] = str(overlay.get("default_role_without_token"))
    return merged


def _merge_tooling(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    overlay = overlay or {}
    merged = {
        "version": int(overlay.get("version", base.get("version", 1)) or 1),
        "default_role": str(overlay.get("default_role", base.get("default_role", "observer"))),
        "worker_role_map": dict(base.get("worker_role_map") or {}),
        "roles": {name: _normalize_tool_role(role) for name, role in (base.get("roles") or {}).items()},
    }
    merged["worker_role_map"].update({str(key): str(value) for key, value in (overlay.get("worker_role_map") or {}).items()})
    for role, role_policy in (overlay.get("roles") or {}).items():
        merged["roles"][role] = _normalize_tool_role(role_policy)
    return merged


def _normalize_control_policy(policy: dict[str, Any]) -> dict[str, Any]:
    normalized = _clone(DEFAULT_CONTROL_POLICY)
    normalized["version"] = int(policy.get("version", normalized["version"]) or normalized["version"])
    normalized["governance"].update(policy.get("governance") or {})

    workspace_manager = dict(normalized.get("workspace_manager") or {})
    workspace_manager.update(policy.get("workspace_manager") or {})
    workspace_manager["write_roots"] = _normalize_string_list(workspace_manager.get("write_roots"))
    workspace_manager["core_roots"] = _normalize_string_list(workspace_manager.get("core_roots"))
    normalized["workspace_manager"] = workspace_manager

    normalized["approvals"] = _merge_approvals(normalized.get("approvals") or {}, policy.get("approvals"))
    normalized["sessions"] = _merge_sessions(normalized.get("sessions") or {}, policy.get("sessions"))
    normalized["tooling"] = _merge_tooling(normalized.get("tooling") or {}, policy.get("tooling"))

    write_roots = workspace_manager["write_roots"]
    if write_roots:
        workspace_rule = dict(normalized["approvals"].get("filesystem.write_workspace", {}))
        workspace_rule["mode"] = str(workspace_rule.get("mode", "AUTO-LIMIT")).upper()
        workspace_rule["path_prefixes"] = write_roots
        normalized["approvals"]["filesystem.write_workspace"] = workspace_rule

    return normalized


def _load_legacy_overlay() -> dict[str, Any]:
    guard_policy = _load_json(GUARD_POLICY_FILE, {})
    return {
        "workspace_manager": {
            "write_roots": guard_policy.get("workspace_paths") or [],
            "core_roots": guard_policy.get("protect_core_paths") or [],
        },
        "approvals": _load_json(APPROVAL_POLICY_FILE, {}),
        "sessions": _load_json(SESSION_POLICY_FILE, {}),
        "tooling": _load_json(TOOL_POLICY_FILE, {}),
    }


def load_control_policy() -> dict[str, Any]:
    policy = _normalize_control_policy(_load_legacy_overlay())
    current = _load_json(CONTROL_POLICY_FILE, {})
    if current:
        policy = _normalize_control_policy({**policy, **current})
    if not CONTROL_POLICY_FILE.exists():
        save_control_policy(policy)
    return policy


def project_approval_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active = policy or load_control_policy()
    return _merge_approvals({}, active.get("approvals"))


def project_session_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active = policy or load_control_policy()
    return _merge_sessions({}, active.get("sessions"))


def project_tool_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    active = policy or load_control_policy()
    return _merge_tooling({}, active.get("tooling"))


def save_control_policy(policy: dict[str, Any], *, sync_legacy_views: bool = True) -> dict[str, Any]:
    normalized = _normalize_control_policy(policy)
    atomic_write_json(CONTROL_POLICY_FILE, normalized)
    if sync_legacy_views:
        atomic_write_json(APPROVAL_POLICY_FILE, project_approval_policy(normalized))
        atomic_write_json(SESSION_POLICY_FILE, project_session_policy(normalized))
        atomic_write_json(TOOL_POLICY_FILE, project_tool_policy(normalized))
    return normalized


if __name__ == "__main__":
    print(json.dumps(load_control_policy(), ensure_ascii=False, indent=2))
