from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = ROOT / 'data' / 'execution_trace.jsonl'


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def append_trace(
    phase: str,
    reason: str,
    action: str,
    result: str,
    next_step: str,
    *,
    worker: str = 'system',
    level: str = 'info',
    data: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    event = {
        'timestamp': utc_iso(),
        'phase': phase,
        'worker': worker,
        'level': level,
        'reason': reason,
        'action': action,
        'result': result,
        'next': next_step,
        'data': data or {},
    }
    if duration_ms is not None:
        event['duration_ms'] = max(0, int(duration_ms))
    TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRACE_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event


def read_tail(limit: int = 100) -> list[dict[str, Any]]:
    if not TRACE_PATH.exists():
        return []
    lines = TRACE_PATH.read_text(encoding='utf-8').splitlines()[-max(1, min(limit, 500)):]
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events
