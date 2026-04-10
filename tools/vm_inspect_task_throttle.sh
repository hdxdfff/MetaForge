#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

def load(path_str):
    path = Path(path_str)
    print(f"## {path}")
    if not path.exists():
        print("missing")
        return None
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    print(json.dumps(data, ensure_ascii=False, indent=2)[:12000])
    return data

tasks_path = Path("/workspace/data/tasks.json")
guard_path = Path("/workspace/data/guard_state.json")
daemon_path = Path("/workspace/data/factory_daemon_state.json")
autonomy_path = Path("/workspace/data/autonomy_score.json")

guard = load(str(guard_path))
print()
daemon = load(str(daemon_path))
print()
autonomy = load(str(autonomy_path))
print()

if tasks_path.exists():
    tasks = json.loads(tasks_path.read_text(encoding="utf-8-sig"))
    now = datetime.now(timezone.utc)
    last_hour = now - timedelta(hours=1)
    recent = []
    for task in tasks:
        created = task.get("created_at")
        if not created:
            continue
        ts = created[:-1] + "+00:00" if created.endswith("Z") else created
        try:
            created_dt = datetime.fromisoformat(ts)
        except Exception:
            continue
        if created_dt >= last_hour:
            recent.append(task)
    print(f"## {tasks_path}")
    print(f"recent_count={len(recent)}")
    print("status_counts=" + json.dumps(Counter(t.get("status") for t in recent), ensure_ascii=False))
    print("scheduled_by_counts=" + json.dumps(Counter(t.get("scheduled_by") for t in recent).most_common(10), ensure_ascii=False))
    print("sample_recent_tasks=")
    for task in recent[:30]:
        print(json.dumps({
            "created_at": task.get("created_at"),
            "status": task.get("status"),
            "scheduled_by": task.get("scheduled_by"),
            "id": task.get("id"),
            "title": task.get("title"),
        }, ensure_ascii=False))
else:
    print(f"## {tasks_path}")
    print("missing")
PY
