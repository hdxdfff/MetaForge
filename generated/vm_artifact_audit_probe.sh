#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
import json
import pathlib

path = pathlib.Path("data/artifact_registry.json")
data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
print(json.dumps({
    "updated_at": data.get("updated_at"),
    "status": data.get("status"),
    "artifact_count": data.get("artifact_count"),
    "real_artifact_count": data.get("real_artifact_count"),
    "valuable_artifact_count": data.get("valuable_artifact_count"),
    "prototype_artifact_count": data.get("prototype_artifact_count"),
    "issues": data.get("issues"),
    "artifacts": data.get("artifacts"),
}, ensure_ascii=False, indent=2))
PY'
