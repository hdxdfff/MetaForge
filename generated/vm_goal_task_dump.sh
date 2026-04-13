python3 - <<'PY'
import json
from pathlib import Path
root = Path('/srv/orchestrator-mvp')
tasks = json.loads((root / 'data' / 'tasks.json').read_text(encoding='utf-8-sig'))
goal_id = 'goal_7f38832417'
subset = []
for t in tasks:
    if str(t.get('goal_id') or '') != goal_id:
        continue
    subset.append({
        'id': t.get('id'),
        'status': t.get('status'),
        'title': t.get('title'),
        'node_id': t.get('node_id'),
        'created_at': t.get('created_at'),
        'updated_at': t.get('updated_at'),
        'requeue_requested': t.get('requeue_requested'),
        'result_summary': t.get('result_summary'),
        'result': t.get('result'),
    })
print(json.dumps(subset, ensure_ascii=False))
PY
