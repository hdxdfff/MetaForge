from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
TELEMETRY = DATA / 'telemetry_events.json'
OUT = DATA / 'evolution_evaluation.json'


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
    tele = load_json(TELEMETRY, {})
    findings = []
    if tele.get('task_failed', 0) > 0:
        findings.append({
            'kind': 'failure-rate',
            'severity': 'high' if tele.get('task_failed', 0) >= 3 else 'medium',
            'reason': f"{tele.get('task_failed', 0)} failed tasks detected",
            'proposal': 'Strengthen templates, tests, or task decomposition for repeated failures.',
            'cheap_worker_ok': True,
        })
    if tele.get('core_escalations_total', 0) > 0 and tele.get('cheap_calls_total', 0) > 0:
        ratio = tele.get('core_escalations_total', 0) / max(1, tele.get('cheap_calls_total', 1))
        if ratio > 0.1:
            findings.append({
                'kind': 'core-budget-pressure',
                'severity': 'medium',
                'reason': f'Core escalation ratio is above target: {ratio:.2f}',
                'proposal': 'Push more planning, testing, and report work into cheap-first loops.',
                'cheap_worker_ok': True,
            })
    payload = {
        'updated_at': utc_iso(),
        'telemetry_snapshot': tele,
        'findings': findings,
        'status': 'attention' if findings else 'stable',
    }
    atomic_write_json(OUT, payload)
    append_trace('evaluation', 'analyze telemetry and failures', 'run evaluator_loop.py', f"findings={len(findings)} status={payload['status']}", 'run self patch loop', worker='cheap-worker')
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
