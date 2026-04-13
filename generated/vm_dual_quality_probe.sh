#!/usr/bin/env bash
set -euo pipefail

echo "== host /srv =="
cd /srv/orchestrator-mvp
python3 - <<'PY'
from tools.quality_system import _load_json, TASKS, list_goals, ACTIVE_GOAL_STATUSES, _task_score
import json, pathlib

tasks = _load_json(TASKS, [])
goals = list_goals()
active = {
    str(item.get("goal_id") or "").strip()
    for item in goals
    if item.get("status") in ACTIVE_GOAL_STATUSES
}
quality_path = pathlib.Path("/srv/orchestrator-mvp/data/quality_system.json")
payload = json.loads(quality_path.read_text(encoding="utf-8"))
print(json.dumps({
    "quality_updated_at": payload.get("updated_at"),
    "quality_overall_score": payload.get("overall_score"),
    "quality_task_score": payload.get("task_score"),
    "task_score_live": _task_score(tasks, active_goal_ids=active),
    "task_count": len(tasks),
    "active_goal_ids": sorted(active),
}, ensure_ascii=False, indent=2))
PY

echo "== container /workspace =="
docker exec orchestrator-mvp-orchestrator-1 sh -lc 'cd /workspace && python3 - <<'"'"'PY'"'"'
from tools.quality_system import _load_json, TASKS, list_goals, ACTIVE_GOAL_STATUSES, _task_score
import json, pathlib

tasks = _load_json(TASKS, [])
goals = list_goals()
active = {
    str(item.get("goal_id") or "").strip()
    for item in goals
    if item.get("status") in ACTIVE_GOAL_STATUSES
}
quality_path = pathlib.Path("/workspace/data/quality_system.json")
payload = json.loads(quality_path.read_text(encoding="utf-8"))
print(json.dumps({
    "quality_updated_at": payload.get("updated_at"),
    "quality_overall_score": payload.get("overall_score"),
    "quality_task_score": payload.get("task_score"),
    "task_score_live": _task_score(tasks, active_goal_ids=active),
    "task_count": len(tasks),
    "active_goal_ids": sorted(active),
}, ensure_ascii=False, indent=2))
PY'
