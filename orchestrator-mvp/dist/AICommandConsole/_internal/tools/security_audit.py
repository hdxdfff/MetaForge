from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
AUDIT_TAIL = DATA / 'audit_log.json'
AUDIT_CHAIN = DATA / 'audit_log_chain.jsonl'
AUDIT_STATE = DATA / 'audit_log_state.json'


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _digest(payload: dict[str, Any], previous_hash: str) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True) + previous_hash
    return hashlib.sha256(material.encode('utf-8')).hexdigest()


def append_security_audit(*, action: str, actor: str, result: str, target: str = '', details: dict[str, Any] | None = None, severity: str = 'info', category: str = 'security') -> dict[str, Any]:
    state = _load_json(AUDIT_STATE, {'last_hash': '', 'count': 0})
    event = {
        'timestamp': utc_iso(),
        'category': category,
        'severity': severity,
        'actor': actor,
        'action': action,
        'target': target,
        'result': result,
        'details': details or {},
    }
    previous_hash = str(state.get('last_hash') or '')
    event_hash = _digest(event, previous_hash)
    record = {
        **event,
        'previous_hash': previous_hash,
        'event_hash': event_hash,
        'sequence': int(state.get('count', 0) or 0) + 1,
    }
    AUDIT_CHAIN.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_CHAIN.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    state = {'last_hash': event_hash, 'count': record['sequence'], 'updated_at': record['timestamp']}
    atomic_write_json(AUDIT_STATE, state)
    tail = _load_json(AUDIT_TAIL, {'entries': []})
    entries = list(tail.get('entries', []))
    entries.append(record)
    atomic_write_json(AUDIT_TAIL, {'entries': entries[-500:]})
    return record
