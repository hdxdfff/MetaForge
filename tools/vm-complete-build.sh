#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
PYTHONPATH=/srv/orchestrator-mvp python3 - <<'PY'
from tools.task_state_tools import complete_tasks

task_id = "56855aac306a4b2e8552fa305a115358"
summary = (
    "ToyOS runnable baseline build refreshed successfully; "
    "current build outputs and logs are current and verifiable."
)

updated = complete_tasks([task_id], summary)
print(updated)
PY
