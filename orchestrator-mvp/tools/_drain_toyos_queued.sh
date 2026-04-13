#!/usr/bin/env bash
set -euo pipefail

cd /srv/orchestrator-mvp
export PYTHONPATH=/srv/orchestrator-mvp

.venv/bin/python - <<'PY'
import json
from pathlib import Path

from tools.tool_stack import launch_task

workspace = "/workspace/generated/toy-os-demo"
queued_titles = [
    "Audit ToyOS execution environment",
    "Localize ToyOS build break",
    "Isolate ToyOS failing test",
]
results = []
for title in queued_titles:
    result = launch_task(title, workspace=workspace, prefer="Goose")
    results.append({
        "request": title,
        "ok": result.get("ok"),
        "surface": result.get("surface"),
        "returncode": result.get("returncode"),
        "status": result.get("status"),
        "summary": result.get("summary"),
    })

report = {
    "workspace": workspace,
    "queued_titles": queued_titles,
    "results": results,
}
report_path = Path("/workspace/generated/toy-os-demo/toyos-queued-drain.json")
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
PY
