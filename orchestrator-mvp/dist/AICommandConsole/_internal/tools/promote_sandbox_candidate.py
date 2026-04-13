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
PATCH = DATA / 'evolution_patch_record.json'
SANDBOX = DATA / 'sandbox_upgrade_state.json'
OUT = DATA / 'evolution_adoption_state.json'


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
    patch = load_json(PATCH, {})
    sandbox = load_json(SANDBOX, {})
    ok = patch.get('status') == 'prepared' and sandbox.get('status') == 'ready'
    payload = {
        'updated_at': utc_iso(),
        'status': 'candidate' if ok else 'blocked',
        'branch': patch.get('branch'),
        'sandbox_status': sandbox.get('status'),
        'candidate_count': patch.get('candidate_count', 0),
        'artifacts': patch.get('targets', []),
        'notes': 'Ready to record a release candidate if a repository path is attached.' if ok else 'Sandbox or patch preparation not ready.',
    }
    atomic_write_json(OUT, payload)
    append_trace('adoption', 'promote sandbox-validated upgrade to candidate', 'run promote_sandbox_candidate.py', f"status={payload['status']}", 'record release candidate or wait', worker='supervisor')
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
