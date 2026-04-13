from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
OUT = DATA / "organization_workboard.json"

ORGANIZATION = DATA / "organization_model.json"
TASKS = DATA / "tasks.json"
PATCHES = DATA / "patch_submissions.json"
GOALS = FACTORY / "goals" / "goal_registry.json"
PROJECT_COORD = DATA / "cross_project_coordination.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _goal_departments(goal: dict[str, Any], project_allocations: list[dict[str, Any]]) -> set[str]:
    departments = set()
    assigned_department = str(goal.get('assigned_department') or '').strip()
    if assigned_department:
        departments.add(assigned_department)
    target = str(goal.get('target') or '').lower()
    for item in project_allocations:
        name = str(item.get('name') or '').lower()
        if not name or name not in target:
            continue
        owner = item.get('owner_department')
        if owner:
            departments.add(owner)
        for department in item.get('support_departments') or []:
            if department:
                departments.add(department)
    return departments


def _task_departments(task: dict[str, Any], goal_lookup: dict[str, dict[str, Any]]) -> set[str]:
    departments = set()
    hint = task.get('scheduler_hint') or {}
    assigned_department = hint.get('assigned_department')
    if assigned_department:
        departments.add(str(assigned_department))
    goal = goal_lookup.get(str(task.get('goal_id') or ''))
    if goal and goal.get('assigned_department'):
        departments.add(str(goal.get('assigned_department')))
    return {item for item in departments if item}


def build_organization_workboard() -> dict[str, Any]:
    organization = _load_json(ORGANIZATION, {})
    tasks = _load_json(TASKS, [])
    patches = (_load_json(PATCHES, {}) or {}).get('submissions', [])
    goals = _load_json(GOALS, [])
    coordination = _load_json(PROJECT_COORD, {})
    policy = _load_json(GLOBAL_POLICY, {})

    departments = organization.get('departments') or {}
    project_allocations = organization.get('project_allocations') or []
    top_departments = [item.get('department') for item in (policy.get('organization_priority', {}) or {}).get('departments', []) if item.get('department')]
    goal_lookup = {str(goal.get('goal_id') or ''): goal for goal in goals}

    board = {}
    for department, summary in departments.items():
        dept_projects = {item.get('project_id') for item in project_allocations if item.get('owner_department') == department or department in (item.get('support_departments') or [])}
        active_goals = [
            goal.get('target')
            for goal in goals
            if goal.get('status') in {'pending', 'planned', 'running'} and department in _goal_departments(goal, project_allocations)
        ]
        active_tasks = [
            item for item in tasks
            if item.get('status') in {'queued', 'planning', 'running', 'waiting_approval'} and department in _task_departments(item, goal_lookup)
        ]
        pending_reviews = [item for item in patches if item.get('status') in {'proposed', 'approved'} and any(assn.get('department') == department and assn.get('status') != 'approved' for assn in (item.get('review_assignments') or []))]
        coord_candidates = [item for item in (coordination.get('selected') or []) if department in (item.get('departments') or [])]
        active_goals = list(dict.fromkeys(goal for goal in active_goals if goal))
        board[department] = {
            'project_count': len(dept_projects),
            'projects': sorted(dept_projects)[:12],
            'active_goal_count': len(active_goals),
            'active_goals': active_goals[:8],
            'active_task_count': len(active_tasks),
            'pending_review_count': len(pending_reviews),
            'coordination_count': len(coord_candidates),
            'default_worker': summary.get('default_worker'),
            'focus': summary.get('focus', []),
            'priority_rank': (top_departments.index(department) + 1) if department in top_departments else None,
        }

    payload = {
        'updated_at': _utc(),
        'department_count': len(board),
        'top_departments': top_departments,
        'departments': board,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == '__main__':
    print(json.dumps(build_organization_workboard(), ensure_ascii=False, indent=2))
