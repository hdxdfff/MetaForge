from __future__ import annotations

from typing import Any

from tools.ai_guard import is_core_path, is_workspace_path
from tools.kernel_mode import is_component_enabled, load_kernel_mode
from tools.security_audit import append_security_audit


def assess_task_security(*, prompt_guard: dict[str, Any], tool_policy: dict[str, Any], repo_path: str | None, execution_lane: str | None, vm_template: dict[str, Any] | None, auto_approve: bool) -> dict[str, Any]:
    reasons: list[str] = []
    controls: list[str] = []
    verdict = 'allow'
    hold_before_execution = False
    sandbox_required = False
    kernel_mode = load_kernel_mode()

    prompt_decision = str(prompt_guard.get('decision') or 'allow')
    if prompt_decision == 'block':
        verdict = 'block'
        hold_before_execution = True
        reasons.append('Prompt guard blocked the request.')
        controls.append('manual_security_review')

    allowed_actions = set(tool_policy.get('allowed_actions', []))
    approval_required = set(tool_policy.get('approval_required', []))
    if 'shell_exec' in allowed_actions or 'docker_exec' in allowed_actions:
        sandbox_required = True
        controls.append('sandbox_execution')
    if approval_required and not auto_approve:
        controls.append('manual_approval')

    if not is_component_enabled('security_review', kernel_mode) and prompt_decision != 'block':
        review = {
            'verdict': 'allow',
            'hold_before_execution': False,
            'sandbox_required': sandbox_required,
            'required_controls': sorted(set(controls)),
            'reasons': [f"Security review disabled by {kernel_mode.get('profile', 'standard')} profile."],
            'reviewer': 'safety_agent',
        }
        append_security_audit(
            action='task_security_review',
            actor='safety_agent',
            result=review['verdict'],
            target=repo_path or execution_lane or 'task',
            severity='info',
            details=review,
        )
        return review

    if repo_path and is_core_path(repo_path):
        verdict = 'review' if verdict == 'allow' else verdict
        hold_before_execution = True
        reasons.append('Task targets a protected core path.')
        controls.append('core_path_review')
    elif repo_path and not is_workspace_path(repo_path):
        verdict = 'review' if verdict == 'allow' else verdict
        reasons.append('Task targets a path outside the normal workspace roots.')
        controls.append('workspace_scope_review')

    if sandbox_required and (execution_lane == 'host-control' and not vm_template):
        reasons.append('Task is execution-capable and should be rerouted through sandbox entry.')

    review = {
        'verdict': verdict,
        'hold_before_execution': hold_before_execution,
        'sandbox_required': sandbox_required,
        'required_controls': sorted(set(controls)),
        'reasons': reasons or ['No elevated security concerns detected.'],
        'reviewer': 'safety_agent',
    }
    append_security_audit(
        action='task_security_review',
        actor='safety_agent',
        result=review['verdict'],
        target=repo_path or execution_lane or 'task',
        severity='warning' if review['verdict'] in {'review', 'block'} else 'info',
        details=review,
    )
    return review
