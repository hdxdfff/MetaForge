import json
from pathlib import Path

from tools.tool_stack import launch_task

workspace = "/workspace/generated/toy-os-demo"
tasks = [
    "Audit ToyOS execution environment",
    "Localize ToyOS build break",
    "Run ToyOS boot and QEMU smoke",
]
results = []
for task in tasks:
    result = launch_task(task, workspace=workspace, prefer="Goose")
    results.append(
        {
            "request": task,
            "ok": result.get("ok"),
            "surface": result.get("surface"),
            "returncode": result.get("returncode"),
            "status": result.get("status"),
            "summary": result.get("summary"),
        }
    )

report = {"workspace": workspace, "results": results}
report_path = Path("/workspace/generated/toy-os-demo/toyos-queued-run.json")
report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
