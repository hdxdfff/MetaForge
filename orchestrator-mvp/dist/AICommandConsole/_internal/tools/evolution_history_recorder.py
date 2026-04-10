from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = DATA / 'evolution_history.json'
SOURCES = {
    'telemetry': DATA / 'telemetry_events.json',
    'evaluation': DATA / 'evolution_evaluation.json',
    'patch': DATA / 'evolution_patch_record.json',
    'adoption': DATA / 'evolution_adoption_state.json',
}


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
    history = load_json(OUT, [])
    snapshot = {name: load_json(path, {'status': 'not-run'}) for name, path in SOURCES.items()}
    history.append({'created_at': utc_iso(), 'snapshot': snapshot})
    history = history[-50:]
    atomic_write_json(OUT, history)
    print(json.dumps({'ok': True, 'count': len(history)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
