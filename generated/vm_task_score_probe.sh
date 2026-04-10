docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<"PY"
import json
from tools.quality_system import _load_json, TASKS, _task_score, _latest_attempts, _task_requested_requeue, ACTIVE_TASK_STATUSES, _parse_ts, _recovering_goal_ids
from tools.goal_registry import list_goals
from datetime import datetime, timezone, timedelta

tasks = _load_json(TASKS, [])
goals = list_goals()
active_goal_ids = {str(item.get("goal_id") or "").strip() for item in goals if item.get("status") in {"pending","planned","running"}}
if not active_goal_ids:
    active_goal_ids = _recovering_goal_ids(tasks)
filtered_tasks = tasks
if active_goal_ids:
    active_tasks = [item for item in tasks if str(item.get("goal_id") or "").strip() in active_goal_ids]
    if active_tasks:
        filtered_tasks = active_tasks
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=12)
scored = []
for item in filtered_tasks:
    ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
    if ts is None or ts >= cutoff:
        scored.append(item)
if not scored:
    scored = filtered_tasks[-10:]
scored = _latest_attempts(scored)
open_tasks = [item for item in scored if item.get("status") in ACTIVE_TASK_STATUSES]
completed = sum(1 for item in scored if item.get("status") == "completed")
failed = sum(1 for item in scored if item.get("status") in {"failed", "timed_out"} and not _task_requested_requeue(item))
stale_active = 0
for item in scored:
    if item.get("status") not in ACTIVE_TASK_STATUSES:
        continue
    ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
    if ts is not None and ts <= now - timedelta(minutes=20):
        stale_active += 1
payload = {
    "active_goal_ids": sorted(active_goal_ids),
    "filtered_count": len(filtered_tasks),
    "scored_count": len(scored),
    "open_count": len(open_tasks),
    "completed": completed,
    "failed": failed,
    "stale_active": stale_active,
    "task_score": _task_score(tasks, active_goal_ids=active_goal_ids),
    "scored_rows": [
        {
            "id": item.get("id"),
            "goal_id": item.get("goal_id"),
            "node_id": item.get("node_id"),
            "status": item.get("status"),
            "title": item.get("title"),
        }
        for item in scored
    ],
}
print(json.dumps(payload, ensure_ascii=False))
PY'
