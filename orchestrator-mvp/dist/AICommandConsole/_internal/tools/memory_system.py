from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.dialogue_memory import load_dialogue_memory, rebuild_dialogue_memory
from tools.goal_storage_audit import run_goal_storage_audit
from tools.io_utils import atomic_write_json
from tools.memory_objects import summarize_memory_objects

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
GOALS = FACTORY / "goals" / "goal_registry.json"
TASKS = DATA / "tasks.json"
GRAPHS = FACTORY / "graphs"

GOAL_MEMORY = DATA / "goal_memory.json"
TASK_HISTORY = DATA / "task_history.json"
DECISION_LOG = DATA / "decision_log.json"
AGENT_EXPERIENCE = DATA / "agent_experience.json"
MEMORY_KERNEL = DATA / "memory_kernel.json"

MAX_TASK_HISTORY = 200
MAX_DECISIONS = 200


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


def _load_graph(graph_id: str | None) -> dict[str, Any]:
    if not graph_id:
        return {}
    path = GRAPHS / f"{graph_id}.json"
    return _load_json(path, {})


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") or {}
    error = result.get("error")
    return {
        "task_id": task.get("id"),
        "status": task.get("status"),
        "goal": task.get("goal"),
        "repo_path": task.get("repo_path"),
        "updated_at": task.get("updated_at"),
        "error": error[:240] if isinstance(error, str) else None,
    }


def _build_goal_memory(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for goal in goals:
        graph = _load_graph(goal.get("graph_id"))
        nodes = graph.get("nodes", [])
        items.append(
            {
                "goal_id": goal.get("goal_id"),
                "target": goal.get("target"),
                "type": goal.get("type"),
                "status": goal.get("status"),
                "graph_id": goal.get("graph_id"),
                "task_ids": goal.get("task_ids", []),
                "created_at": goal.get("created_at"),
                "updated_at": goal.get("updated_at"),
                "progress": {
                    "total_nodes": len(nodes),
                    "completed_nodes": sum(1 for node in nodes if node.get("status") == "completed"),
                    "running_nodes": sum(1 for node in nodes if node.get("status") == "running"),
                    "blocked_nodes": sum(1 for node in nodes if node.get("status") == "blocked"),
                },
                "next_nodes": [
                    {
                        "id": node.get("id"),
                        "title": node.get("title"),
                        "role": node.get("role"),
                    }
                    for node in nodes
                    if node.get("status") in {"pending", "running"}
                ][:5],
            }
        )
    return items


def _build_task_history(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        tasks,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return [_task_summary(task) for task in ranked[:MAX_TASK_HISTORY]]


def _build_decision_log(
    actions: list[dict[str, Any]] | None,
    goals: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing = _load_json(DECISION_LOG, [])
    history = existing[-MAX_DECISIONS:]
    now = _utc()

    seen = {
        (
            item.get("type"),
            item.get("goal_id"),
            item.get("task_id"),
            item.get("node_id"),
            item.get("summary"),
        )
        for item in history
    }

    for goal in goals:
        summary = f"Goal {goal.get('goal_id')} is {goal.get('status')} for target {goal.get('target')}"
        key = ("goal-state", goal.get("goal_id"), None, None, summary)
        if key not in seen:
            history.append(
                {
                    "at": now,
                    "type": "goal-state",
                    "goal_id": goal.get("goal_id"),
                    "summary": summary,
                }
            )
            seen.add(key)

    for action in actions or []:
        summary = action.get("phase") or "unknown-action"
        key = (
            "brain-loop-action",
            action.get("goal_id"),
            action.get("task_id"),
            action.get("node_id"),
            summary,
        )
        if key in seen:
            continue
        history.append(
            {
                "at": now,
                "type": "brain-loop-action",
                "goal_id": action.get("goal_id"),
                "task_id": action.get("task_id"),
                "node_id": action.get("node_id"),
                "summary": summary,
                "details": action,
            }
        )
        seen.add(key)

    for task in tasks:
        if task.get("status") not in {"failed", "waiting_approval"}:
            continue
        summary = f"Task {task.get('id')} is {task.get('status')}"
        key = ("task-exception", None, task.get("id"), None, summary)
        if key in seen:
            continue
        history.append(
            {
                "at": now,
                "type": "task-exception",
                "task_id": task.get("id"),
                "summary": summary,
                "details": _task_summary(task),
            }
        )
        seen.add(key)

    return history[-MAX_DECISIONS:]


def _build_agent_experience(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "worker": None,
            "completed": 0,
            "failed": 0,
            "waiting_approval": 0,
            "running": 0,
            "last_task_id": None,
            "last_goal": None,
            "last_repo_path": None,
            "last_status": None,
            "last_updated_at": None,
        }
    )

    for task in tasks:
        workers = {step.get("worker") for step in task.get("plan", []) if step.get("worker")}
        if not workers:
            workers = {"supervisor"}
        for worker in workers:
            item = stats[worker]
            item["worker"] = worker
            status = task.get("status")
            if status == "completed":
                item["completed"] += 1
            elif status == "failed":
                item["failed"] += 1
            elif status == "waiting_approval":
                item["waiting_approval"] += 1
            elif status in {"queued", "planning", "running"}:
                item["running"] += 1
            updated = task.get("updated_at") or ""
            if not item["last_updated_at"] or updated >= item["last_updated_at"]:
                item["last_task_id"] = task.get("id")
                item["last_goal"] = task.get("goal")
                item["last_repo_path"] = task.get("repo_path")
                item["last_status"] = status
                item["last_updated_at"] = updated

    result = []
    for worker, item in sorted(stats.items()):
        total = item["completed"] + item["failed"] + item["waiting_approval"] + item["running"]
        item["success_rate"] = round(item["completed"] / total, 3) if total else 0.0
        result.append(item)
    return result


def rebuild_memory(actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    goals = _load_json(GOALS, [])
    tasks = _load_json(TASKS, [])

    goal_memory = _build_goal_memory(goals)
    task_history = _build_task_history(tasks)
    decision_log = _build_decision_log(actions, goals, tasks)
    agent_experience = _build_agent_experience(tasks)
    goal_storage = run_goal_storage_audit()
    dialogue_memory = load_dialogue_memory() or rebuild_dialogue_memory()
    memory_objects = summarize_memory_objects()

    kernel = {
        "updated_at": _utc(),
        "goal_count": len(goal_memory),
        "task_history_count": len(task_history),
        "decision_count": len(decision_log),
        "agent_count": len(agent_experience),
        "top_goals": goal_memory[:5],
        "recent_decisions": decision_log[-8:],
        "agent_summary": agent_experience[:8],
        "goal_storage": goal_storage,
        "memory_objects": memory_objects,
        "dialogue_memory": {
            "updated_at": dialogue_memory.get("updated_at"),
            "session_count": dialogue_memory.get("session_count", 0),
            "message_count": dialogue_memory.get("message_count", 0),
            "recent_topics": dialogue_memory.get("recent_topics", [])[:6],
            "recent_decisions": dialogue_memory.get("recent_decisions", [])[:6],
            "active_handoff": dialogue_memory.get("active_handoff", {}),
        },
    }

    _save_json(GOAL_MEMORY, goal_memory)
    _save_json(TASK_HISTORY, task_history)
    _save_json(DECISION_LOG, decision_log)
    _save_json(AGENT_EXPERIENCE, agent_experience)
    _save_json(MEMORY_KERNEL, kernel)
    return kernel


if __name__ == "__main__":
    print(json.dumps(rebuild_memory(), ensure_ascii=False, indent=2))
