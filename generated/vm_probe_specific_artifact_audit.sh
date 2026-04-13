#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 bash -lc '
set -euo pipefail
cd /workspace
python - <<'"'"'PY'"'"'
import json
from pathlib import Path
from datetime import datetime
from tools.artifact_audit import validate_task_artifact_completion
from tools.task_state_tools import _resolved_task_repo_path

task_id = "e5aade41d42a42389544b3ad43db03a5"
tasks = {str(t.get("id")): t for t in json.loads(Path("/workspace/data/tasks.json").read_text(encoding="utf-8-sig"))}
task = tasks[task_id]
created_at_raw = task.get("created_at") or task.get("updated_at")
created_at = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
repo_root = Path(_resolved_task_repo_path(task))
spec = task.get("artifact_spec")
payload = {
    "task_id": task_id,
    "repo_root": str(repo_root),
    "created_at": created_at_raw,
    "artifact_spec": spec,
}
try:
    payload["validation"] = validate_task_artifact_completion(
        repo_root=repo_root,
        artifact_spec=spec,
        created_at=created_at,
    )
except Exception as exc:
    payload["error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
'
