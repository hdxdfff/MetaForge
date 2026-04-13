from __future__ import annotations

import json
from typing import Any

from tools.goal_engine import ACTIVE_STATUSES, ENGINE


def create_goal(
    target: str,
    goal_type: str = "build_platform",
    notes: str = "",
    lane: str = "mainline",
    lane_role: str | None = None,
    branch_name: str | None = None,
    branch_context_ref: str | None = None,
    assigned_department: str | None = None,
    source_session: str | None = None,
    shares_mainline_context: bool = True,
    upstream_context_refs: list[str] | None = None,
    **extra: Any,
) -> dict:
    return ENGINE.create_goal(
        target,
        goal_type=goal_type,
        notes=notes,
        lane=lane,
        lane_role=lane_role,
        branch_name=branch_name,
        branch_context_ref=branch_context_ref,
        assigned_department=assigned_department,
        source_session=source_session,
        shares_mainline_context=shares_mainline_context,
        upstream_context_refs=upstream_context_refs,
        **extra,
    )


def list_goals() -> list[dict]:
    return ENGINE.list_goals()


def get_goal(goal_id: str) -> dict:
    return ENGINE.get_goal(goal_id)


def update_goal(goal_id: str, **updates: Any) -> dict:
    return ENGINE.update_goal(goal_id, **updates)


def rank_goals(limit: int | None = None, statuses: set[str] | None = None) -> list[dict]:
    return ENGINE.rank_goals(statuses=statuses or ACTIVE_STATUSES, limit=limit)


def select_goal(statuses: set[str] | None = None) -> dict | None:
    return ENGINE.select_goal(statuses=statuses or ACTIVE_STATUSES)


def reflect_goal(goal_id: str, **kwargs: Any) -> dict:
    return ENGINE.reflect_goal(goal_id, **kwargs)


def goal_report(top_n: int = 8) -> dict:
    return ENGINE.goal_report(top_n=top_n)


if __name__ == "__main__":
    print(json.dumps(list_goals(), ensure_ascii=False, indent=2))
