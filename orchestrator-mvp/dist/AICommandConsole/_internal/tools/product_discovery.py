from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / 'data' / 'tasks.json'
OUT = ROOT / 'factory' / 'goals' / 'product_ideas.json'


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
    corpus = ' '.join((task.get('prompt') or '') + ' ' + (task.get('goal') or '') for task in tasks).lower()
    ideas = []
    if 'network' in corpus or '???' in corpus:
        ideas.append({'id': 'idea-network-lab-assistant', 'created_at': utc_iso(), 'name': 'Network Lab Assistant', 'source': 'local task history', 'status': 'discovered'})
    if 'database' in corpus or 'sql' in corpus:
        ideas.append({'id': 'idea-db-lab-assistant', 'created_at': utc_iso(), 'name': 'Database Lab Assistant', 'source': 'local task history', 'status': 'discovered'})
    if 'toyos' in corpus or 'kernel' in corpus:
        ideas.append({'id': 'idea-systems-lab-factory', 'created_at': utc_iso(), 'name': 'Systems Lab Factory', 'source': 'local task history', 'status': 'discovered'})
    atomic_write_json(OUT, ideas)
    append_trace('product-discovery', 'discover local product ideas from task history', 'run product_discovery.py', f"ideas={len(ideas)}", 'update meta-factory candidates', worker='cheap-worker')
    print(json.dumps({'updated_at': utc_iso(), 'idea_count': len(ideas), 'ideas': ideas}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
