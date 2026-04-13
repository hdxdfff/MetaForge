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
CANDIDATES = DATA / 'self_patch_candidates.json'
OUT = DATA / 'evolution_patch_record.json'


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
    candidates = load_json(CANDIDATES, {'candidates': []})
    branch = f"codex/evolution-{utc_iso().replace(':', '').replace('-', '')[:15].lower()}"
    payload = {
        'updated_at': utc_iso(),
        'status': 'prepared' if candidates.get('candidates') else 'idle',
        'branch': branch,
        'candidate_count': len(candidates.get('candidates', [])),
        'targets': [item.get('target') for item in candidates.get('candidates', [])],
        'notes': 'Patch branch prepared logically; actual git branch creation is handled by the API layer when a repo is available.',
    }
    atomic_write_json(OUT, payload)
    append_trace('patch-prep', 'prepare logical patch branch for evolution candidates', 'run prepare_self_patch_branch.py', f"status={payload['status']} branch={branch}", 'promote candidate after sandbox check', worker='cheap-worker')
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
