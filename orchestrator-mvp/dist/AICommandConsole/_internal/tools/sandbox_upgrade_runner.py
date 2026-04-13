from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = DATA / 'sandbox_upgrade_state.json'
CANDIDATES = DATA / 'self_patch_candidates.json'
SANDBOX = ROOT / 'sandbox' / 'evolution'


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
    payload = load_json(CANDIDATES, {'candidates': []})
    SANDBOX.mkdir(parents=True, exist_ok=True)
    touched = []
    for name in ['templates', 'data']:
        src = ROOT / name
        dst = SANDBOX / name
        if dst.exists():
            shutil.rmtree(dst)
        if src.exists():
            shutil.copytree(src, dst)
            touched.append(str(dst))
    state = {
        'updated_at': utc_iso(),
        'candidate_count': len(payload.get('candidates', [])),
        'sandbox_root': str(SANDBOX),
        'mirrored_paths': touched,
        'status': 'ready' if payload.get('candidates') else 'idle',
    }
    atomic_write_json(OUT, state)
    append_trace('sandbox', 'mirror upgrade targets into sandbox', 'run sandbox_upgrade_runner.py', f"status={state['status']} mirrored={len(touched)}", 'prepare patch branch if candidates exist', worker='local-runtime')
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
