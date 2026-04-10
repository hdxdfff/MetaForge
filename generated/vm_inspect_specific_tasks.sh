#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 bash -lc '
set -euo pipefail
cd /workspace
python - <<'"'"'PY'"'"'
import json
from pathlib import Path

task_ids = [
    "9cde4293d97940cfbc5595760591a2d5",
    "e5aade41d42a42389544b3ad43db03a5",
    "59ecaf4eef7a404c89bbe2076a466f01",
    "a42e316436aa4ec1b16f87e0e7f461eb",
]
tasks = {str(t.get("id")): t for t in json.loads(Path("/workspace/data/tasks.json").read_text(encoding="utf-8-sig"))}
out = []
for task_id in task_ids:
    t = tasks.get(task_id) or {}
    result = t.get("result") or {}
    out.append(
        {
            "id": task_id,
            "title": t.get("title"),
            "status": t.get("status"),
            "repo_path": t.get("repo_path"),
            "execution_mode": t.get("execution_mode"),
            "execution_lane": t.get("execution_lane"),
            "artifact_spec": t.get("artifact_spec"),
            "scheduler_hint_artifact_spec": (t.get("scheduler_hint") or {}).get("artifact_spec"),
            "result_keys": sorted(result.keys()) if isinstance(result, dict) else [],
            "summary": result.get("summary") if isinstance(result, dict) else None,
            "execution_evidence_path": result.get("execution_evidence_path") if isinstance(result, dict) else None,
            "production_evidence": result.get("production_evidence") if isinstance(result, dict) else None,
        }
    )
print(json.dumps(out, ensure_ascii=False, indent=2))
PY
'
