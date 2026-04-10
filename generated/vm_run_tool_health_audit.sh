#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.tool_health_audit import run_tool_health_audit, append_tool_health_history
import json

payload = run_tool_health_audit()
history = append_tool_health_history(payload)

print(json.dumps({
    "payload": payload,
    "history": history,
}, ensure_ascii=False, indent=2))
PY'
