#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
from pathlib import Path

root = Path("/srv/orchestrator-mvp/factory/runtime/tasks")
for path in sorted(root.iterdir()) if root.exists() else []:
    if path.is_dir():
        print(path.name)
PY
