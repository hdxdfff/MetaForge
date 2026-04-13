python3 - <<'PY'
import json
from pathlib import Path
root = Path('/srv/orchestrator-mvp')
tasks = json.loads((root / 'data' / 'tasks.json').read_text(encoding='utf-8-sig'))
cap_payload = json.loads((root / 'factory' / 'capability_registry.json').read_text(encoding='utf-8-sig'))
active = [t for t in tasks if str(t.get('status') or '') in {'queued','planning','running','waiting_approval'}]
completed = [t for t in tasks if str(t.get('status') or '') == 'completed']
failed = [t for t in tasks if str(t.get('status') or '') in {'failed','timed_out'}]
print(json.dumps({
  'task_count': len(tasks),
  'active_count': len(active),
  'completed_count': len(completed),
  'failed_count': len(failed),
  'capability_count': len((cap_payload or {}).get('capabilities') or [])
}, ensure_ascii=False))
PY
