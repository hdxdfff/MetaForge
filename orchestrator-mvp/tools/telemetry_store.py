from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.io_utils import atomic_write_json
from execution_trace import append_trace

DATA = ROOT / 'data'
TASKS = DATA / 'tasks.json'
STATE = DATA / 'meta_factory_state.json'
OUT = DATA / 'telemetry_events.json'


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def main() -> int:
    tasks = load_json(TASKS, [])
    meta = load_json(STATE, {})
    total = len(tasks)
    completed = sum(1 for t in tasks if t.get('status') == 'completed')
    failed = sum(1 for t in tasks if t.get('status') == 'failed')
    waiting = sum(1 for t in tasks if t.get('status') == 'waiting_approval')
    cheap_calls = sum((t.get('cheap_lane') or {}).get('calls_used', 0) for t in tasks)
    escalations = sum(t.get('escalation_count', 0) for t in tasks)
    payload = {
        'updated_at': utc_iso(),
        'task_total': total,
        'task_completed': completed,
        'task_failed': failed,
        'task_waiting': waiting,
        'task_success_rate': round((completed / total), 4) if total else 0.0,
        'cheap_calls_total': cheap_calls,
        'core_escalations_total': escalations,
        'meta_factory_status': meta.get('status'),
        'candidate_count': meta.get('candidate_count', 0),
    }
    atomic_write_json(OUT, payload)
    append_trace('telemetry', 'collect runtime metrics', 'run telemetry_store.py', f"success_rate={payload['task_success_rate']} failed={payload['task_failed']}", 'run evaluator loop', worker='cheap-worker')
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
