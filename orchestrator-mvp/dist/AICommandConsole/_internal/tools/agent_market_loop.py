from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'tasks.json'
OUT = ROOT / 'factory' / 'market' / 'agent_scores.json'


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
    tasks = load_json(DATA, [])
    buckets = {
        'coder_agent': {'role': 'coder', 'runs': 0, 'success': 0, 'duration_proxy': 0, 'cost': 0},
        'reviewer_agent': {'role': 'reviewer', 'runs': 0, 'success': 0, 'duration_proxy': 0, 'cost': 0},
        'tester_agent': {'role': 'tester', 'runs': 0, 'success': 0, 'duration_proxy': 0, 'cost': 0},
    }
    role_map = {'coder': 'coder_agent', 'reviewer': 'reviewer_agent', 'shell': 'tester_agent', 'docker': 'tester_agent'}
    for task in tasks:
        for step in task.get('plan', []):
            agent = role_map.get(step.get('worker'))
            if not agent:
                continue
            buckets[agent]['runs'] += 1
            if step.get('status') == 'completed':
                buckets[agent]['success'] += 1
            buckets[agent]['duration_proxy'] += 1
            buckets[agent]['cost'] += (task.get('cheap_lane') or {}).get('calls_used', 0)
    result = {'updated_at': utc_iso(), 'agents': []}
    for name, item in buckets.items():
        runs = item['runs']
        result['agents'].append({
            'agent': name,
            'role': item['role'],
            'success_rate': round(item['success'] / runs, 4) if runs else 0.0,
            'avg_duration': round(item['duration_proxy'] / runs, 4) if runs else 0.0,
            'cost_score': round(item['cost'] / runs, 4) if runs else 0.0,
            'runs': runs,
        })
    atomic_write_json(OUT, result)
    append_trace('agent-market', 'score internal agents from task history', 'run agent_market_loop.py', f"agents={len(result['agents'])}", 'run architecture search', worker='cheap-worker')
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
