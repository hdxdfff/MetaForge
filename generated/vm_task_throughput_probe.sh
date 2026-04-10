python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
root = Path('/srv/orchestrator-mvp')
tasks = json.loads((root / 'data' / 'tasks.json').read_text(encoding='utf-8-sig'))
active_statuses = {'queued','planning','running','waiting_approval'}
cutoff = datetime.now(timezone.utc) - timedelta(hours=12)

def parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace('Z','+00:00'))
    except Exception:
        return None

recent = []
for t in tasks:
    ts = parse_ts(t.get('updated_at') or t.get('created_at'))
    if ts is None or ts >= cutoff:
        recent.append(t)
by_goal = {}
for t in recent:
    gid = str(t.get('goal_id') or '')
    by_goal.setdefault(gid, {'completed':0,'failed':0,'active':0,'titles':set(),'ids':[]})
    s = str(t.get('status') or '')
    if s == 'completed': by_goal[gid]['completed'] += 1
    elif s in {'failed','timed_out'}: by_goal[gid]['failed'] += 1
    elif s in active_statuses: by_goal[gid]['active'] += 1
    by_goal[gid]['titles'].add(str(t.get('title') or ''))
    by_goal[gid]['ids'].append(str(t.get('id') or ''))
rows = []
for gid, stats in by_goal.items():
    rows.append({'goal_id': gid, 'completed': stats['completed'], 'failed': stats['failed'], 'active': stats['active'], 'title_count': len(stats['titles'])})
rows.sort(key=lambda x: (-x['failed'], -x['active'], x['goal_id']))
print(json.dumps(rows[:20], ensure_ascii=False))
PY
