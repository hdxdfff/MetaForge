#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.quality_system import run_quality
import json

print(json.dumps(run_quality(), ensure_ascii=False, indent=2))
PY'
