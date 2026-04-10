#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
import json
from pathlib import Path

from tools.tool_stack import launch_task

workspace = "/workspace/generated/toy-os-demo"
request = "ToyOS Throughput Smoke Pack"
result = launch_task(request, workspace=workspace, prefer="Goose")
report = {
    "workspace": workspace,
    "request": request,
    "result": {
        "ok": result.get("ok"),
        "surface": result.get("surface"),
        "returncode": result.get("returncode"),
        "status": result.get("status"),
        "summary": result.get("summary"),
    },
}
path = Path("/workspace/generated/toy-os-demo/toyos-throughput-smoke-pack-run.json")
path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
PY
