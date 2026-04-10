from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / 'data' / 'evolution_evaluation.json'
MARKET = ROOT / 'factory' / 'market' / 'agent_scores.json'
OUT = ROOT / 'factory' / 'evaluations' / 'architecture_proposals.json'


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
    evaluation = load_json(EVAL, {'findings': []})
    market = load_json(MARKET, {'agents': []})
    proposals = []
    if any(item.get('kind') == 'failure-rate' for item in evaluation.get('findings', [])):
        proposals.append({
            'id': f'arch-{utc_iso().replace(":", "")[:14]}',
            'created_at': utc_iso(),
            'reason': 'Failure rate suggests stronger separation of generation and validation.',
            'proposal': 'Insert explicit evaluator/fixer stage after generation for all system templates.',
            'expected_gain': 'higher template success rate',
            'status': 'proposed',
        })
    if any(agent.get('runs', 0) > 0 and agent.get('success_rate', 0) < 0.6 for agent in market.get('agents', [])):
        proposals.append({
            'id': f'arch-{utc_iso().replace(":", "")[:14]}-market',
            'created_at': utc_iso(),
            'reason': 'At least one agent underperforms in the market.',
            'proposal': 'Run parallel cheap-worker competition before reviewer selection on targeted tasks.',
            'expected_gain': 'better cheap-lane output selection',
            'status': 'proposed',
        })
    atomic_write_json(OUT, proposals)
    append_trace('architecture-search', 'propose structural improvements', 'run architecture_search.py', f"proposals={len(proposals)}", 'run product discovery', worker='cheap-worker')
    print(json.dumps({'updated_at': utc_iso(), 'proposal_count': len(proposals), 'proposals': proposals}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
