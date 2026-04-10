python3 - <<'PY'
import json
from pathlib import Path
root = Path('/srv/orchestrator-mvp')
paths = {
  'platform_registry': root / 'factory' / 'platform_registry.json',
  'capability_registry': root / 'factory' / 'capability_registry.json',
}
out = {}
for name, path in paths.items():
    if not path.exists():
        out[name] = {'exists': False}
        continue
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    key = 'platforms' if 'platform' in name else 'capabilities'
    out[name] = {
        'exists': True,
        'count': len((payload or {}).get(key) or []),
        'path': str(path),
    }
print(json.dumps(out, ensure_ascii=False))
PY
