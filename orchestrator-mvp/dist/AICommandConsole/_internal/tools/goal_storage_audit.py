from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
GOALS = FACTORY / "goals" / "goal_registry.json"
TASKS = DATA / "tasks.json"
MEMORY_KERNEL = DATA / "memory_kernel.json"
BRAIN_LOOP = DATA / "brain_loop_state.json"
META_FACTORY = DATA / "meta_factory_state.json"
OUT = DATA / "goal_storage_audit.json"
GRAPHS = FACTORY / "graphs"

ACTIVE_GOAL_STATUSES = {"pending", "planned", "running", "on_hold"}
ACTIVE_TASK_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
RECENT_GOAL_WINDOW = timedelta(hours=24)
RECENT_TASK_WINDOW = timedelta(hours=6)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            time.sleep(0.1 * (attempt + 1))
        except json.JSONDecodeError:
            time.sleep(0.1 * (attempt + 1))
        except Exception:
            return default
    return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _task_goal_id(task: dict[str, Any]) -> str | None:
    hint = task.get("scheduler_hint") or {}
    goal_id = hint.get("goal_id")
    return str(goal_id).strip() if goal_id else None


def _task_node_id(task: dict[str, Any]) -> str | None:
    hint = task.get("scheduler_hint") or {}
    node_id = hint.get("node_id")
    return str(node_id).strip() if node_id else None


def _task_scheduled_by_runtime(task: dict[str, Any]) -> bool:
    hint = task.get("scheduler_hint") or {}
    return str(hint.get("scheduled_by") or "").strip().lower() == "runtime.scheduler"


def _load_graph(graph_id: str | None) -> dict[str, Any]:
    if not graph_id:
        return {}
    return _load_json(GRAPHS / f"{graph_id}.json", {})


def _graph_has_active_nodes(graph: dict[str, Any]) -> bool:
    for node in graph.get("nodes", []) or []:
        if node.get("status") in {"running", "ready", "queued", "pending"}:
            return True
    return False


def _goal_is_recent(goal: dict[str, Any], now: datetime) -> bool:
    updated = _parse_time(goal.get("updated_at") or goal.get("created_at"))
    if updated is None:
        return True
    return updated >= now - RECENT_GOAL_WINDOW


def _task_is_recent(task: dict[str, Any], now: datetime) -> bool:
    updated = _parse_time(task.get("updated_at") or task.get("created_at"))
    if updated is None:
        return True
    return updated >= now - RECENT_TASK_WINDOW


def _recent_goal_ids_from_actions() -> list[str]:
    sources = []
    brain = _load_json(BRAIN_LOOP, {})
    meta = _load_json(META_FACTORY, {})
    sources.extend(brain.get("actions", []) or [])
    for loop_payload in (meta.get("loops") or {}).values():
        if isinstance(loop_payload, dict):
            actions = loop_payload.get("actions") or []
            if isinstance(actions, list):
                sources.extend(actions)
    goal_ids: list[str] = []
    for item in sources:
        goal_id = item.get("goal_id")
        if goal_id and goal_id not in goal_ids:
            goal_ids.append(goal_id)
    return goal_ids[:50]


def run_goal_storage_audit() -> dict[str, Any]:
    goals = _load_json(GOALS, [])
    tasks = _load_json(TASKS, [])
    memory = _load_json(MEMORY_KERNEL, {})
    now = datetime.now(timezone.utc)

    goal_ids = [goal.get("goal_id") for goal in goals if goal.get("goal_id")]
    unique_goal_ids = set(goal_ids)
    active_goals = [goal for goal in goals if goal.get("status") in ACTIVE_GOAL_STATUSES]
    active_goal_ids = {goal.get("goal_id") for goal in active_goals if goal.get("goal_id")}
    recent_goals = [goal for goal in goals if _goal_is_recent(goal, now)]

    active_goal_graphs: dict[str, dict[str, Any]] = {
        str(goal.get("goal_id")): _load_graph(goal.get("graph_id"))
        for goal in active_goals
        if goal.get("goal_id")
    }

    missing_graph_goal_ids = [
        goal.get("goal_id")
        for goal in active_goals
        if goal.get("graph_id") and not (GRAPHS / f"{goal['graph_id']}.json").exists()
    ]

    task_ids = {task.get("id") for task in tasks if task.get("id")}
    recent_active_goals = [goal for goal in active_goals if _goal_is_recent(goal, now)]

    running_goals_missing_tasks = []
    for goal in recent_active_goals:
        if goal.get("status") != "running":
            continue
        graph = active_goal_graphs.get(str(goal.get("goal_id"))) or {}
        has_task_links = bool(goal.get("task_ids") or [])
        if not has_task_links and not _graph_has_active_nodes(graph):
            running_goals_missing_tasks.append(goal.get("goal_id"))

    missing_task_goal_ids: list[str] = []
    for goal in recent_active_goals:
        tracked_task_ids = goal.get("task_ids") or []
        if not tracked_task_ids:
            continue
        for task_id in tracked_task_ids:
            if task_id not in task_ids:
                missing_task_goal_ids.append(goal.get("goal_id"))
                break

    active_tasks = [task for task in tasks if task.get("status") in ACTIVE_TASK_STATUSES]
    managed_active_tasks = [
        task for task in active_tasks
        if _task_is_recent(task, now) and (_task_scheduled_by_runtime(task) or _task_goal_id(task))
    ]
    active_tasks_with_goal_id = [task for task in managed_active_tasks if _task_goal_id(task)]
    active_tasks_linked = [task for task in active_tasks_with_goal_id if _task_goal_id(task) in unique_goal_ids]
    active_tasks_broken_link = [task for task in active_tasks_with_goal_id if _task_goal_id(task) not in unique_goal_ids]
    managed_active_tasks_without_goal_link = [task for task in managed_active_tasks if _task_scheduled_by_runtime(task) and not _task_goal_id(task)]
    managed_active_tasks_without_node_link = [task for task in managed_active_tasks if _task_scheduled_by_runtime(task) and not _task_node_id(task)]

    recent_action_goal_ids = _recent_goal_ids_from_actions()
    recent_action_missing = [goal_id for goal_id in recent_action_goal_ids if goal_id not in unique_goal_ids]

    memory_goal_count = int(memory.get("goal_count", 0) or 0)
    memory_top_goal_ids = {item.get("goal_id") for item in memory.get("top_goals", []) if item.get("goal_id")}
    active_goal_ids_not_in_memory_top = sorted(goal_id for goal_id in active_goal_ids if goal_id not in memory_top_goal_ids)[:20]

    issues: list[str] = []
    warnings: list[str] = []
    if len(goal_ids) != len(unique_goal_ids):
        issues.append("duplicate-goal-ids")
    if missing_graph_goal_ids:
        issues.append("active-goals-missing-graphs")
    if running_goals_missing_tasks:
        warnings.append("running-goals-missing-runtime-links")
    if missing_task_goal_ids:
        warnings.append("active-goal-task-links-missing")
    if active_tasks_broken_link:
        issues.append("active-task-goal-links-broken")
    if managed_active_tasks_without_goal_link:
        issues.append("runtime-managed-tasks-missing-goal-links")
    if recent_action_missing:
        issues.append("recent-action-goals-not-persisted")
    if managed_active_tasks_without_node_link:
        warnings.append("runtime-managed-tasks-missing-node-links")
    if memory_goal_count and memory_goal_count != len(goals):
        warnings.append("memory-kernel-goal-count-lagging")

    persistence_issues = [
        issue
        for issue in issues
        if issue in {
            "duplicate-goal-ids",
            "active-goals-missing-graphs",
            "recent-action-goals-not-persisted",
        }
    ]
    queue_issues = [
        issue
        for issue in issues
        if issue in {
            "active-task-goal-links-broken",
            "runtime-managed-tasks-missing-goal-links",
        }
    ]
    status = "healthy" if not issues else "attention"
    payload = {
        "updated_at": _utc(),
        "status": status,
        "stored_successfully": not persistence_issues,
        "goal_registry_confirmed": not persistence_issues,
        "task_queue_confirmed": not queue_issues,
        "goal_registry": {
            "goal_count": len(goals),
            "unique_goal_id_count": len(unique_goal_ids),
            "active_goal_count": len(active_goals),
            "recent_goal_count_24h": len(recent_goals),
        },
        "graph_integrity": {
            "active_goals_with_graph": sum(1 for goal in active_goals if goal.get("graph_id")),
            "missing_graph_goal_ids": missing_graph_goal_ids[:20],
            "running_goals_missing_tasks": running_goals_missing_tasks[:20],
            "missing_task_goal_ids": missing_task_goal_ids[:20],
        },
        "task_queue": {
            "active_task_count": len(active_tasks),
            "managed_active_task_count": len(managed_active_tasks),
            "managed_active_tasks_with_goal_link": len(active_tasks_with_goal_id),
            "managed_active_tasks_linked_to_existing_goal": len(active_tasks_linked),
            "managed_active_tasks_broken_goal_link": [task.get("id") for task in active_tasks_broken_link[:20]],
            "managed_active_tasks_without_goal_link": [task.get("id") for task in managed_active_tasks_without_goal_link[:20]],
            "managed_active_tasks_without_node_link": [task.get("id") for task in managed_active_tasks_without_node_link[:20]],
        },
        "state_confirmation": {
            "recent_action_goal_ids": recent_action_goal_ids,
            "recent_action_missing_goal_ids": recent_action_missing,
            "memory_kernel_goal_count": memory_goal_count,
            "memory_kernel_top_goal_ids": sorted(memory_top_goal_ids)[:20],
            "active_goal_ids_not_in_memory_top": active_goal_ids_not_in_memory_top,
        },
        "issues": issues,
        "warnings": warnings,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_goal_storage_audit(), ensure_ascii=False, indent=2))
