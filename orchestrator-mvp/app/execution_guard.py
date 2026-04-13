from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .config import settings
from .models import StepSpec, TaskRecord, WorkerType
from tools.security_audit import append_security_audit
from tools.tool_policy import authorize_tool_action, build_task_tool_policy


BLOCKED_OPERATORS = ["|", ";", "&&", "||", ">", "<"]
HIGH_RISK_PATTERNS = [
    "rm -rf",
    "del /f",
    "format ",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "poweroff",
    "git reset --hard",
    "git clean -fd",
]
SANDBOX_HINTS = ["docker", "pytest", "qemu", "build", "compile", "npm", "cargo", "cmake", "make"]


def normalize_command_prefix(token: str) -> str:
    cleaned = str(token or "").strip().strip("\"'")
    prefix = Path(cleaned).name.lower().strip("\"'")
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if prefix.endswith(suffix):
            return prefix[: -len(suffix)]
    return prefix


def evaluate_execution_guard(
    task: TaskRecord, step: StepSpec, *, action: str, command: str, workdir: str | None
) -> dict[str, Any]:
    policy_decision = authorize_tool_action(
        task.tool_policy, action, auto_approve=task.auto_approve
    )
    if not policy_decision.get("allowed") and action in {"shell_exec", "docker_exec"}:
        rerouted = _authorize_step_worker_action(task, step, action)
        if rerouted.get("allowed"):
            policy_decision = rerouted
    if not policy_decision.get("allowed"):
        result = {
            "allowed": False,
            "reason": str(policy_decision.get("reason") or "Denied by tool policy."),
            "require_sandbox": False,
            "risk_level": "high",
        }
        append_security_audit(
            action="execution_guard",
            actor="execution_guard",
            result="denied",
            target=action,
            severity="warning",
            details={
                "task_id": task.id,
                "step_id": step.id,
                "reason": result["reason"],
                "command": command,
                "workdir": workdir,
            },
        )
        return result

    lowered = (command or "").lower()
    for pattern in list(settings.denied_command_patterns) + HIGH_RISK_PATTERNS:
        if pattern and pattern.lower() in lowered:
            result = {
                "allowed": False,
                "reason": f"Command contains denied pattern: {pattern}",
                "require_sandbox": False,
                "risk_level": "high",
            }
            append_security_audit(
                action="execution_guard",
                actor="execution_guard",
                result="denied",
                target=action,
                severity="error",
                details={
                    "task_id": task.id,
                    "step_id": step.id,
                    "reason": result["reason"],
                    "command": command,
                },
            )
            return result

    for operator in BLOCKED_OPERATORS:
        if operator in command:
            result = {
                "allowed": False,
                "reason": f"Command contains blocked control operator: {operator}",
                "require_sandbox": False,
                "risk_level": "high",
            }
            append_security_audit(
                action="execution_guard",
                actor="execution_guard",
                result="denied",
                target=action,
                severity="warning",
                details={
                    "task_id": task.id,
                    "step_id": step.id,
                    "reason": result["reason"],
                    "command": command,
                },
            )
            return result

    tokens = shlex.split(command, posix=False) if command else []
    if tokens:
        prefix = normalize_command_prefix(tokens[0])
        allowed_prefixes = {item.lower() for item in settings.allowed_command_prefixes}
        if prefix not in allowed_prefixes:
            result = {
                "allowed": False,
                "reason": f"Command prefix '{prefix}' is not in ORCH_ALLOWED_COMMAND_PREFIXES.",
                "require_sandbox": False,
                "risk_level": "high",
            }
            append_security_audit(
                action="execution_guard",
                actor="execution_guard",
                result="denied",
                target=action,
                severity="warning",
                details={
                    "task_id": task.id,
                    "step_id": step.id,
                    "reason": result["reason"],
                    "command": command,
                },
            )
            return result

    if workdir:
        resolved = Path(workdir).resolve()
        roots = [Path(root).resolve() for root in settings.allowed_workdirs]
        if not any(str(resolved).lower().startswith(str(root).lower()) for root in roots):
            result = {
                "allowed": False,
                "reason": f"Working directory '{workdir}' is outside ORCH_ALLOWED_WORKDIRS.",
                "require_sandbox": False,
                "risk_level": "high",
            }
            append_security_audit(
                action="execution_guard",
                actor="execution_guard",
                result="denied",
                target=action,
                severity="warning",
                details={
                    "task_id": task.id,
                    "step_id": step.id,
                    "reason": result["reason"],
                    "workdir": workdir,
                },
            )
            return result

    require_sandbox = (
        bool(task.vm_template)
        or bool((task.security_review or {}).get("sandbox_required"))
        or bool((task.worker_vm_policy or {}).get("worker_vm_required"))
        or action == "docker_exec"
        or any(token in lowered for token in SANDBOX_HINTS)
    )
    result = {
        "allowed": True,
        "reason": "Approved by execution guard.",
        "require_sandbox": require_sandbox,
        "risk_level": "medium" if require_sandbox else "low",
    }
    append_security_audit(
        action="execution_guard",
        actor="execution_guard",
        result="approved",
        target=action,
        severity="info",
        details={
            "task_id": task.id,
            "step_id": step.id,
            "require_sandbox": require_sandbox,
            "command": command,
            "workdir": workdir,
        },
    )
    return result



def _authorize_step_worker_action(task: TaskRecord, step: StepSpec, action: str) -> dict[str, Any]:
    if step.worker not in {WorkerType.shell, WorkerType.docker}:
        return {"allowed": False, "reason": "Step worker is not eligible for execution reroute."}
    if not bool(task.auto_approve or (task.tool_policy or {}).get("auto_approve")):
        return {"allowed": False, "reason": "Execution reroute requires auto-approve."}
    preferred_worker = "docker" if step.worker == WorkerType.docker else "shell"
    rerouted_policy = build_task_tool_policy(
        preferred_worker=preferred_worker,
        tool_route=task.tool_route,
        repo_path=task.repo_path,
        execution_lane=task.execution_lane,
        auto_approve=bool(task.auto_approve or (task.tool_policy or {}).get("auto_approve")),
        scheduled_by=task.scheduled_by,
    )
    decision = authorize_tool_action(
        rerouted_policy,
        action,
        auto_approve=bool(task.auto_approve or rerouted_policy.get("auto_approve")),
    )
    if decision.get("allowed"):
        task.tool_policy = rerouted_policy
        return {
            "allowed": True,
            "reason": f"Approved after rerouting execution authority to role {rerouted_policy.get('role')}.",
            "rerouted_role": rerouted_policy.get("role"),
        }
    return decision
