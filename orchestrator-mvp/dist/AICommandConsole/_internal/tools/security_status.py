from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.ai_guard import guard_snapshot
from tools.vm_orchestrator import vm_status

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
AUDIT_TAIL = DATA / 'audit_log.json'
AUDIT_CHAIN = DATA / 'audit_log_chain.jsonl'
AUDIT_STATE = DATA / 'audit_log_state.json'
TASKS = DATA / 'tasks.json'


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def read_security_audit_tail(limit: int = 50) -> list[dict[str, Any]]:
    if AUDIT_CHAIN.exists():
        lines = AUDIT_CHAIN.read_text(encoding='utf-8').splitlines()[-max(1, min(limit, 500)):]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except Exception:
                continue
        return events
    return list(_load_json(AUDIT_TAIL, {'entries': []}).get('entries', []))[-limit:]


def security_status(limit: int = 25) -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    audit_tail = read_security_audit_tail(limit=limit)
    blocked_tasks = [task for task in tasks if (task.get('result') or {}).get('state') in {'blocked_by_prompt_guard', 'held_by_safety_agent'}]
    prompt_blocks = [task for task in tasks if (task.get('result') or {}).get('state') == 'blocked_by_prompt_guard']
    safety_holds = [task for task in tasks if (task.get('result') or {}).get('state') == 'held_by_safety_agent']
    return {
        'guard': guard_snapshot(),
        'audit_state': _load_json(AUDIT_STATE, {'last_hash': '', 'count': 0}),
        'audit_tail': audit_tail,
        'blocked_task_count': len(blocked_tasks),
        'prompt_block_count': len(prompt_blocks),
        'safety_hold_count': len(safety_holds),
        'blocked_tasks': [
            {
                'id': task.get('id'),
                'title': task.get('title'),
                'status': task.get('status'),
                'reason': (task.get('result') or {}).get('reason'),
            }
            for task in blocked_tasks[-10:]
        ],
        'sandbox': vm_status(),
    }
