#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 bash -lc '
set -euo pipefail
cd /workspace
python - <<'"'"'PY'"'"'
import json
from pathlib import Path
from tools.release_operations import _task_eligible_for_delivery_ready, _task_has_delivery_evidence
from tools.task_state_tools import resolved_delivery_evidence, _task_repo_is_vm_authoritative, _task_has_verified_audit, _resolved_task_repo_path

task_ids = [
    "9cde4293d97940cfbc5595760591a2d5",
    "e5aade41d42a42389544b3ad43db03a5",
    "59ecaf4eef7a404c89bbe2076a466f01",
    "a42e316436aa4ec1b16f87e0e7f461eb",
]
tasks = {str(t.get("id")): t for t in json.loads(Path("/workspace/data/tasks.json").read_text(encoding="utf-8-sig"))}
rows = []
for task_id in task_ids:
    task = tasks[task_id]
    rows.append(
        {
            "id": task_id,
            "title": task.get("title"),
            "status": task.get("status"),
            "repo_path": task.get("repo_path"),
            "resolved_repo_path": _resolved_task_repo_path(task),
            "vm_authoritative": _task_repo_is_vm_authoritative(task),
            "verified_audit": _task_has_verified_audit(task),
            "eligible": _task_eligible_for_delivery_ready(task),
            "has_delivery_evidence": _task_has_delivery_evidence(task),
            "resolved_delivery_evidence": resolved_delivery_evidence(task),
        }
    )
print(json.dumps(rows, ensure_ascii=False, indent=2))
PY
'
