#!/bin/sh
set -eu

cid="$(docker ps -q --filter name=orchestrator-mvp-orchestrator-1 | head -n 1)"
echo "cid=$cid"
echo "--- docker ps"
docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}\t{{.Command}}'
echo "--- top"
docker top "$cid" | head -n 20
echo "--- logs"
docker logs --tail 80 "$cid" 2>&1 || true
echo "--- workspace data"
docker exec "$cid" sh -lc 'pwd; ls -lah /workspace/data | head -n 40'
echo "--- daemon log tail"
docker exec "$cid" sh -lc 'tail -n 40 /workspace/data/factory_daemon.log 2>/dev/null || true'
echo "--- event log tail"
docker exec "$cid" sh -lc 'tail -n 40 /workspace/data/factory_events.jsonl 2>/dev/null || true'
echo "--- daemon state"
docker exec "$cid" sh -lc 'python - <<'"'"'"'"'"'PY'"'"'"'"'"'
import json
from pathlib import Path
path = Path("/workspace/data/factory_daemon_state.json")
data = json.loads(path.read_text())
for key in ["status", "running", "consecutive_error_count", "last_error", "last_tick_at", "updated_at"]:
    print(f"{key}={data.get(key)!r}")
tb = data.get("last_traceback")
if tb:
    print("--- last_traceback")
    print(tb)
PY'
