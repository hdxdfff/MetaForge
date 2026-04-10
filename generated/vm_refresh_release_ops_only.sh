#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.release_operations import run_release_operations_status
import json

print(json.dumps(run_release_operations_status(), ensure_ascii=False, indent=2))
PY'
