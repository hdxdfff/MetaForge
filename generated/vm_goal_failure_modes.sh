python3 - <<'PY'
import json
from pathlib import Path
root = Path('/srv/orchestrator-mvp')
tasks = json.loads((root / 'data' / 'tasks.json').read_text(encoding='utf-8-sig'))
goal_id = 'goal_7f38832417'
rows = []
for t in tasks:
    if str(t.get('goal_id') or '') != goal_id:
        continue
    status = str(t.get('status') or '')
    if status not in {'failed','timed_out','queued','planning','running','waiting_approval','completed'}:
        continue
    result = t.get('result') if isinstance(t.get('result'), dict) else {}
    rows.append({
        'id': t.get('id'),
        'status': status,
        'node_id': t.get('node_id'),
        'title': t.get('title'),
        'execution_mode': result.get('execution_mode'),
        'reason': result.get('reason'),
        'summary': result.get('summary'),
        'heartbeat_timeout': result.get('heartbeat_timeout'),
        'requeue_requested': bool(t.get('requeue_requested')) or bool(result.get('requeue_requested')),
    })
rows.sort(key=lambda r: (r['status'], r['node_id'] or '', r['id'] or ''))
print(json.dumps(rows, ensure_ascii=False))
PY
