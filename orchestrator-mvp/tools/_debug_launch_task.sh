#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

python3 - <<'PY'
from tools.tool_stack import launch_task

result = launch_task(
    "Build current runnable baseline for Restore ToyOS real artifact delivery",
    workspace="/workspace/generated/toy-os-demo",
)
print(result)
PY
