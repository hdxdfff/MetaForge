from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.ai_guard import is_core_path, is_workspace_path
from tools.io_utils import atomic_write_json, atomic_write_text
from tools.privilege_policy import decide
from tools.security_audit import append_security_audit


def guarded_write_json(path: str | Path, payload: Any, *, actor: str, purpose: str, allow_core_write: bool = False) -> dict[str, Any]:
    return _guarded_write(path, payload, actor=actor, purpose=purpose, writer='json', allow_core_write=allow_core_write)


def guarded_write_text(path: str | Path, content: str, *, actor: str, purpose: str, allow_core_write: bool = False, encoding: str = 'utf-8') -> dict[str, Any]:
    return _guarded_write(path, content, actor=actor, purpose=purpose, writer='text', allow_core_write=allow_core_write, encoding=encoding)


def _guarded_write(path: str | Path, payload: Any, *, actor: str, purpose: str, writer: str, allow_core_write: bool, encoding: str = 'utf-8') -> dict[str, Any]:
    target = Path(path).resolve()
    target_str = str(target)
    if is_core_path(target_str):
        action = 'filesystem.write_core'
    else:
        action = 'filesystem.write_workspace'
    decision = decide(action, target_path=target_str)
    if action == 'filesystem.write_core' and allow_core_write:
        approved = True
        reason = 'Core write explicitly allowed by caller.'
    else:
        approved = decision.approved
        reason = decision.reason
    append_security_audit(
        action='guarded_write_review',
        actor=actor,
        result='approved' if approved else 'denied',
        target=target_str,
        severity='warning' if not approved else 'info',
        details={'purpose': purpose, 'action': action, 'reason': reason, 'mode': decision.mode, 'workspace_path': is_workspace_path(target_str), 'core_path': is_core_path(target_str)},
    )
    if not approved:
        raise RuntimeError(f'Guarded write denied for {target_str}: {reason}')
    if writer == 'json':
        atomic_write_json(target, payload)
    else:
        atomic_write_text(target, str(payload), encoding=encoding)
    append_security_audit(
        action='guarded_write',
        actor=actor,
        result='success',
        target=target_str,
        details={'purpose': purpose, 'action': action, 'writer': writer},
    )
    return {'path': target_str, 'action': action, 'writer': writer, 'reason': reason}
