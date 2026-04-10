from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def main() -> int:
    tasks = load_json(DATA / 'tasks.json', [])
    network = load_json(DATA / 'network_state.json', {})
    core = load_json(DATA / 'core_messages.json', [])
    failed = [task for task in tasks if task.get('status') in {'failed', 'waiting_approval'}]
    summary = {
        'failed_or_paused_tasks': len(failed),
        'recent_failed_task_ids': [task.get('id') for task in failed[:10]],
        'network_status': network.get('status'),
        'current_proxy': network.get('current_proxy') or network.get('proxy_url'),
        'open_core_messages': len([m for m in core if m.get('status') == 'open']),
        'suggested_next_actions': [],
    }
    if summary['failed_or_paused_tasks']:
        summary['suggested_next_actions'].append('review paused tasks and convert them into bounded follow-up tasks')
    if summary['network_status'] == 'offline':
        summary['suggested_next_actions'].append('reload network config or rotate upstream proxy')
    if summary['open_core_messages']:
        summary['suggested_next_actions'].append('triage open core messages')
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
