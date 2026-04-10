from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
QUALITY = DATA / 'quality_status.json'
GUARD = DATA / 'health_status.json'
USAGE = DATA / 'usage_tracker.json'
OUT = DATA / 'evolution_control.json'


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def main() -> int:
    quality = _load_json(QUALITY, {'status': 'unknown', 'promoted_candidates': []})
    guard = _load_json(GUARD, {'allow_evolution': True, 'status': 'unknown'})
    usage = _load_json(USAGE, {'strong_allowed': True, 'strong_ratio': 0.0})

    ratio_sample_sufficient = bool(usage.get('recent_window_sample_sufficient', False))
    usage_blocks_evolution = ratio_sample_sufficient and not bool(usage.get('strong_allowed', True))
    allow = bool(guard.get('allow_evolution', True)) and not usage_blocks_evolution
    promoted = quality.get('promoted_candidates', [])
    selected = promoted[:2] if allow else []
    payload = {
        'updated_at': _utc(),
        'allowed': allow,
        'reason': 'ok' if allow else 'guard or usage blocked evolution',
        'guard_status': guard.get('status'),
        'strong_allowed': usage.get('strong_allowed', True),
        'strong_ratio': usage.get('strong_ratio', 0.0),
        'recent_window_sample_sufficient': ratio_sample_sufficient,
        'usage_blocks_evolution': usage_blocks_evolution,
        'quality_status': quality.get('status'),
        'selected_candidates': selected,
        'selected_count': len(selected),
    }
    atomic_write_json(OUT, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
