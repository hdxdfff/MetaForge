#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
import json
from pathlib import Path

from tools.tool_stack import launch_task

workspace = "/workspace/generated/toy-os-demo"
tasks = [
    "Audit ToyOS execution environment",
    "Localize ToyOS build break",
    "Build current runnable baseline for Restore ToyOS real artifact delivery",
]
results = []
for task in tasks:
    result = launch_task(task, workspace=workspace, prefer="Goose")
    results.append({
        "request": task,
        "ok": result.get("ok"),
        "surface": result.get("surface"),
        "returncode": result.get("returncode"),
        "summary": result.get("summary"),
    })

report = {
    "workspace": workspace,
    "results": results,
}
report_path = Path("/workspace/generated/toy-os-demo/toyos-tech-debt-run.json")
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
PY
