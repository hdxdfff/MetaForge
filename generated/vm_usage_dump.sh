python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path
payload = json.loads(Path('/srv/orchestrator-mvp/data/usage_tracker.json').read_text(encoding='utf-8'))
print(json.dumps(payload, ensure_ascii=False))
PY
