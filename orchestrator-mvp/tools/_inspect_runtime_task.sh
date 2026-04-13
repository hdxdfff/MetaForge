#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

root_dir = Path("/srv/orchestrator-mvp/factory/runtime/tasks")
task_id = os.environ.get("TASK_ID")
if not task_id and root_dir.exists():
    candidates = []
    for path in root_dir.iterdir():
        if path.is_dir():
            context = path / "context.json"
            if context.exists():
                candidates.append((context.stat().st_mtime, path.name))
    if candidates:
        candidates.sort()
        task_id = candidates[-1][1]
root = root_dir / task_id if task_id else root_dir
payload = {"task_id": task_id, "exists": root.exists(), "path": str(root)}
if root.exists():
    for name in ("context.json", "evidence.json", "status.json", "result.json"):
        p = root / name
        if p.exists():
            try:
                payload[name] = json.loads(p.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                payload[name] = {"error": str(exc)}
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
