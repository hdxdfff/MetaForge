from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tools.control_plane_policy import load_control_policy, project_approval_policy, save_control_policy


@dataclass
class PolicyDecision:
    action: str
    mode: str
    approved: bool
    reason: str
    constraints: dict[str, Any]


def load_policy() -> dict[str, Any]:
    return project_approval_policy(load_control_policy())


def save_policy(policy: dict[str, Any]) -> None:
    control_policy = load_control_policy()
    control_policy["approvals"] = policy
    save_control_policy(control_policy)


def decide(action: str, **context: Any) -> PolicyDecision:
    policy = load_policy()
    rule = policy.get(action, {"mode": "MANUAL"})
    mode = str(rule.get("mode", "MANUAL")).upper()
    constraints = {k: v for k, v in rule.items() if k != "mode"}

    if mode == "AUTO":
        return PolicyDecision(action=action, mode=mode, approved=True, reason="Policy AUTO", constraints=constraints)

    if mode == "AUTO-LIMIT":
        if action == "install_package":
            package = context.get("package")
            allowed = constraints.get("allowlist", [])
            ok = package in allowed if package else False
            return PolicyDecision(action, mode, ok, "Package allowlist matched" if ok else "Package not on allowlist", constraints)
        if action == "filesystem.write_workspace":
            target = str(context.get("target_path") or "")
            prefixes = constraints.get("path_prefixes") or []
            ok = any(target.startswith(str(prefix)) for prefix in prefixes if prefix)
            return PolicyDecision(action, mode, ok, "Target path inside workspace" if ok else "Target path outside workspace", constraints)
        if action == "git.push":
            remote = context.get("remote")
            allowed = constraints.get("allowed_remotes", [])
            ok = remote in allowed if remote else False
            return PolicyDecision(action, mode, ok, "Remote allowlist matched" if ok else "Remote not on allowlist", constraints)
        if action == "docker.run":
            image = context.get("image") or ""
            allowed_images = constraints.get("allow_images", [])
            ok = any(str(image).startswith(prefix) for prefix in allowed_images)
            return PolicyDecision(action, mode, ok, "Image allowlist matched" if ok else "Image not on allowlist", constraints)
        return PolicyDecision(action, mode, False, "AUTO-LIMIT rule requires explicit constraint handler", constraints)

    return PolicyDecision(action=action, mode=mode, approved=False, reason="Manual approval required", constraints=constraints)


if __name__ == "__main__":
    print(json.dumps(load_policy(), ensure_ascii=False, indent=2))
