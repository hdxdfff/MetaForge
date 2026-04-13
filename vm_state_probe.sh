#!/bin/sh
set -eu
cid="$(docker ps -q --filter name=orchestrator-mvp-orchestrator-1 | head -n 1)"
docker exec "$cid" sh -lc 'python - <<"PY"
import json
from pathlib import Path
for p in [Path("/workspace/data/factory_daemon_state.json"), Path("/workspace/data/status_cache.json")]:
    print(f"--- {p}")
    try:
        data = json.loads(p.read_text())
    except Exception as exc:
        print(type(exc).__name__, exc)
        continue
    for key in ["status", "running", "consecutive_error_count", "last_error", "last_traceback", "last_tick_at", "updated_at"]:
        if key in data:
            print(key, repr(data.get(key))[:1200])
PY'
