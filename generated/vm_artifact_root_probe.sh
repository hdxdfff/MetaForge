#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools import artifact_audit

print(artifact_audit.GENERATED)
print(sorted(path.name for path in artifact_audit._artifact_dirs()))
PY'
