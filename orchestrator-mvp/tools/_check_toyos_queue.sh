#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
import json
from pathlib import Path

path = Path("/srv/orchestrator-mvp/data/tasks.json")
data = json.loads(path.read_text())
if isinstance(data, dict):
    rows = [(tid, task) for tid, task in data.items()]
else:
    rows = []
    for idx, task in enumerate(data):
        tid = task.get("id") or task.get("task_id") or str(idx)
        rows.append((tid, task))

for tid, task in rows:
    title = task.get("title") or task.get("name") or ""
    if "ToyOS" not in title:
        continue
    state = task.get("state") or task.get("status") or ""
    print(json.dumps({
        "id": tid,
        "title": title,
        "state": state,
        "executor": task.get("executor") or task.get("surface") or task.get("preferred_surface"),
    }, ensure_ascii=False))
PY
