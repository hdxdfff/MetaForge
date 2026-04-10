#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
PYTHONPATH=/srv/orchestrator-mvp python3 - <<'PY'
from tools.task_state_tools import complete_tasks

task_id = "5cd7acfb8dc540d38ceb16ab4d31c6d1"
summary = (
    "ToyOS execution environment audit completed against current evidence; "
    "bootstrap paths and local dependencies are confirmed."
)

updated = complete_tasks([task_id], summary)
print(updated)
PY
