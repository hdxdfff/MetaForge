#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 bash -lc '
set -euo pipefail
cd /workspace
python tools/release_operations.py >/tmp/release_ops.out
tail -n 40 /tmp/release_ops.out
python - <<'"'"'PY'"'"'
import json
from pathlib import Path

tasks = json.loads(Path("/workspace/data/tasks.json").read_text(encoding="utf-8-sig"))
items = [
    t for t in tasks
    if str(t.get("repo_path") or "").startswith("/workspace")
    and str(t.get("execution_mode") or "").strip().lower() == "production"
]
preview = []
for t in items[-10:]:
    result = t.get("result") or {}
    evidence = result.get("production_evidence") or {}
    preview.append(
        {
            "id": t.get("id"),
            "title": t.get("title"),
            "status": t.get("status"),
            "repo_path": t.get("repo_path"),
            "updated_at": t.get("updated_at"),
            "production_evidence_status": evidence.get("status"),
            "delivery_state": result.get("delivery_state"),
        }
    )
print(json.dumps({"count": len(items), "latest": preview}, ensure_ascii=False))
PY
'
