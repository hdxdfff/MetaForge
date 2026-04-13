#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 bash -lc '
set -euo pipefail
cd /workspace
python - <<'"'"'PY'"'"'
import json
from pathlib import Path

tasks = json.loads(Path("/workspace/data/tasks.json").read_text(encoding="utf-8-sig"))
matches = []
for t in tasks:
    title = str(t.get("title") or "")
    prompt = str(t.get("prompt") or "")
    repo = str(t.get("repo_path") or "")
    if "ToyOS" in title or "toy-os-demo" in repo or "ToyOS" in prompt or repo.startswith("/workspace"):
        result = t.get("result") or {}
        matches.append({
            "id": t.get("id"),
            "title": title,
            "status": t.get("status"),
            "repo_path": repo,
            "execution_mode": t.get("execution_mode"),
            "execution_lane": t.get("execution_lane"),
            "updated_at": t.get("updated_at"),
            "execution_evidence_path": result.get("execution_evidence_path"),
            "production_evidence_status": (result.get("production_evidence") or {}).get("status"),
            "delivery_state": result.get("delivery_state"),
        })
print(json.dumps({"task_count": len(matches), "tasks": matches[-20:]}, ensure_ascii=False, indent=2))

runtime_root = Path("/workspace/factory/runtime/tasks")
runtime_hits = []
if runtime_root.exists():
    for child in sorted(runtime_root.iterdir()):
        if not child.is_dir():
            continue
        evidence = child / "execution-evidence.json"
        context = child / "context.json"
        if evidence.exists() or context.exists():
            payload = {}
            if evidence.exists():
                try:
                    payload = json.loads(evidence.read_text(encoding="utf-8-sig"))
                except Exception:
                    payload = {}
            title = str(payload.get("task_title") or payload.get("title") or "")
            repo = str(payload.get("repo_path") or "")
            if "ToyOS" in title or "toy-os-demo" in repo or repo.startswith("/workspace"):
                runtime_hits.append({
                    "task_id": child.name,
                    "repo_path": repo,
                    "title": title,
                    "completed": payload.get("completed"),
                    "status": payload.get("task_status") or payload.get("status"),
                    "has_steps": bool(payload.get("steps")),
                })
print(json.dumps({"runtime_count": len(runtime_hits), "runtime": runtime_hits[-20:]}, ensure_ascii=False, indent=2))
PY
'
