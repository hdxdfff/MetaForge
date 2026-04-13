#!/usr/bin/env bash
set -euo pipefail

docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.quality_system import _load_json, _latest_attempts, _parse_ts, _task_requested_requeue
from tools.quality_system import TASKS, list_goals, ACTIVE_GOAL_STATUSES, ACTIVE_TASK_STATUSES, _task_score
from datetime import datetime, timezone, timedelta
import json

tasks = _load_json(TASKS, [])
goals = list_goals()
active_goal_ids = {
    str(item.get("goal_id") or "").strip()
    for item in goals
    if item.get("status") in ACTIVE_GOAL_STATUSES
}

filtered_tasks = list(tasks)
if active_goal_ids:
    active_tasks = [item for item in tasks if str(item.get("goal_id") or "").strip() in active_goal_ids]
    if active_tasks:
        filtered_tasks = active_tasks

now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=12)
stale_cutoff = now - timedelta(minutes=20)
recovery_cutoff = now - timedelta(minutes=20)

scored_tasks = []
for item in filtered_tasks:
    ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
    if ts is None or ts >= cutoff:
        scored_tasks.append(item)
if not scored_tasks:
    scored_tasks = filtered_tasks[-10:]
scored_tasks = _latest_attempts(scored_tasks)

open_tasks = [item for item in scored_tasks if item.get("status") in ACTIVE_TASK_STATUSES]
completed = [item for item in scored_tasks if item.get("status") == "completed"]
failed = [
    item
    for item in scored_tasks
    if item.get("status") in {"failed", "timed_out"} and not _task_requested_requeue(item)
]
recent_recovery_failures = []
for item in scored_tasks:
    if item.get("status") not in {"failed", "timed_out"} or _task_requested_requeue(item):
        continue
    goal_id = str(item.get("goal_id") or "").strip()
    ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
    if goal_id in active_goal_ids and ts is not None and ts >= recovery_cutoff:
        recent_recovery_failures.append(item)

stale_active = []
for item in scored_tasks:
    if item.get("status") not in {"queued", "planning", "running", "waiting_approval"}:
        continue
    ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
    if ts is not None and ts <= stale_cutoff:
        stale_active.append(item)

summary = {
    "active_goal_ids": sorted(active_goal_ids),
    "task_score": _task_score(tasks, active_goal_ids=active_goal_ids),
    "filtered_count": len(filtered_tasks),
    "scored_count": len(scored_tasks),
    "open_count": len(open_tasks),
    "completed_count": len(completed),
    "failed_count": len(failed),
    "recent_recovery_failure_count": len(recent_recovery_failures),
    "stale_active_count": len(stale_active),
    "failed_ids": [item.get("id") for item in failed],
    "recent_recovery_failure_ids": [item.get("id") for item in recent_recovery_failures],
    "open_ids": [item.get("id") for item in open_tasks],
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY'
