from __future__ import annotations

from tools.goal_engine import ACTIVE_STATUSES
from tools.goal_registry import list_goals, rank_goals
from tools.goal_runtime import sync_goal_runtime


def load_goals(status: str | None = None) -> list[dict]:
    sync_goal_runtime()
    goals = list_goals()
    if status is None:
        return goals
    return [goal for goal in goals if goal.get("status") == status]


def active_goals() -> list[dict]:
    sync_goal_runtime()
    return rank_goals(statuses=ACTIVE_STATUSES)
