from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.goal_engine import ACTIVE_STATUSES, ENGINE, _utc
from tools.replan_engine import build_replan

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
GRAPHS = ROOT / "factory" / "graphs"
OUT = DATA / "goal_runtime_status.json"

TASK_ACTIVE = {"queued", "planning", "running", "waiting_approval"}
TASK_FAILED = {"failed", "timed_out", "cancelled"}
TASK_DONE = {"completed"}

def _parse_time(value: str | None):
    if not value:
        return None
    try:
        return value.replace("Z", "+00:00")
    except Exception:
        return None


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.1 * (attempt + 1))
        except Exception:
            return default
    return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


GRAPH_ACTIVE = {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge", "blocked"}


def _save_graph(graph_id: str | None, graph: dict[str, Any]) -> None:
    if not graph_id:
        return
    _save_json(GRAPHS / f"{graph_id}.json", graph)


def _task_goal_id(task: dict[str, Any]) -> str | None:
    goal_id = task.get("goal_id")
    if goal_id:
        return str(goal_id)
    hint = task.get("scheduler_hint") or {}
    value = hint.get("goal_id")
    return str(value) if value else None


def _task_node_id(task: dict[str, Any]) -> str | None:
    node_id = task.get("node_id")
    if node_id:
        return str(node_id)
    hint = task.get("scheduler_hint") or {}
    value = hint.get("node_id")
    return str(value) if value else None


def _match_task_for_node(goal_id: str | None, node_id: str | None, tasks: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not goal_id or not node_id:
        return None
    for task in tasks.values():
        if _task_goal_id(task) != str(goal_id):
            continue
        if _task_node_id(task) != str(node_id):
            continue
        return task
    return None


def _repair_graph_runtime(graph_id: str | None, graph: dict[str, Any], tasks: dict[str, dict[str, Any]], goal_id: str | None = None) -> bool:
    if not graph_id or not graph:
        return False
    changed = False
    nodes = graph.get("nodes", []) or []
    for node in nodes:
        if str(node.get("status") or "") == "completed":
            if node.get("task_id") is not None:
                node["task_id"] = None
                changed = True
            continue
        task_id = node.get("task_id")
        if task_id and str(task_id) in tasks:
            task = tasks.get(str(task_id)) or {}
            task_status = str(task.get("status") or "")
            desired = node.get("status")
            if task_status in {"completed", "delivery_ready", "released"}:
                desired = "completed"
            elif task_status in {"verification_failed", "failed", "timed_out", "cancelled", "waiting_approval"}:
                desired = "blocked"
            elif task_status in {"queued", "planning", "running", "execution_finished", "verification_pending", "verification_running", "verification_passed"}:
                desired = "running"
            if desired != node.get("status"):
                node["status"] = desired
                changed = True
            continue
        matched = _match_task_for_node(goal_id, node.get("id"), tasks)
        if matched is not None:
            matched_id = matched.get("id")
            if matched_id and node.get("task_id") != matched_id:
                node["task_id"] = matched_id
                changed = True
            task_status = str(matched.get("status") or "")
            desired = node.get("status")
            if task_status in {"completed", "delivery_ready", "released"}:
                desired = "completed"
            elif task_status in {"verification_failed", "failed", "waiting_approval"}:
                desired = "blocked"
            elif task_status in {"queued", "planning", "running", "execution_finished", "verification_pending", "verification_running", "verification_passed"}:
                desired = "running"
            if desired != node.get("status"):
                node["status"] = desired
                changed = True
            continue
        if not task_id:
            continue
        node["task_id"] = None
        if str(node.get("status") or "") in GRAPH_ACTIVE:
            node["status"] = "pending"
        changed = True
    if changed:
        graph_status = str(graph.get("status") or "")
        statuses = [str(node.get("status") or "") for node in nodes]
        if graph_status in {"running", "blocked"} and not any(status in GRAPH_ACTIVE for status in statuses):
            graph["status"] = "planned"
        elif any(status in GRAPH_ACTIVE for status in statuses):
            graph["status"] = "running"
        _save_graph(graph_id, graph)
    return changed

def _graph(graph_id: str | None) -> dict[str, Any]:
    if not graph_id:
        return {}
    return _load_json(GRAPHS / f"{graph_id}.json", {})


def _load_tasks() -> list[dict[str, Any]]:
    return _load_json(TASKS, [])


def _task_map(tasks_payload: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    tasks = tasks_payload if tasks_payload is not None else _load_tasks()
    return {item.get("id"): item for item in tasks if item.get("id")}


def _task_requested_requeue(task: dict[str, Any]) -> bool:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    if bool(task.get("requeue_requested")) or bool(result.get("requeue_requested")):
        return True
    if bool(result.get("heartbeat_timeout")):
        return True
    summary = str(result.get("summary") or task.get("result_summary") or "").lower()
    return "requested requeue" in summary or "heartbeat exceeded" in summary

def _canonical_task_ids(goal: dict[str, Any], graph: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    goal_task_ids = [task_id for task_id in goal.get("task_ids", []) or [] if task_id]
    graph_task_ids: list[str] = []
    for node in graph.get("nodes", []) or []:
        task_id = node.get("task_id")
        if task_id and task_id not in graph_task_ids:
            graph_task_ids.append(task_id)
    runtime_task_ids: list[str] = []
    goal_id = str(goal.get("goal_id") or "")
    for task in tasks.values():
        if _task_goal_id(task) != goal_id:
            continue
        if str(task.get("status") or "") not in TASK_ACTIVE:
            continue
        task_id = task.get("id")
        if task_id and task_id not in runtime_task_ids:
            runtime_task_ids.append(task_id)
    canonical = [task_id for task_id in graph_task_ids if task_id in tasks]
    for task_id in runtime_task_ids:
        if task_id in tasks and task_id not in canonical:
            canonical.append(task_id)
    stale = [task_id for task_id in goal_task_ids if task_id not in canonical]
    return canonical, stale



def _dedupe_goal_tasks(goal: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    goal_id = str(goal.get("goal_id") or "")
    for task in tasks.values():
        if _task_goal_id(task) != goal_id:
            continue
        node_id = _task_node_id(task)
        if not node_id:
            continue
        groups.setdefault(str(node_id), []).append(task)
    changed = False
    retired: list[str] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda item: (_parse_time(item.get("updated_at") or item.get("created_at")) or "", str(item.get("id") or "")),
            reverse=True,
        )
        keeper = ordered[0]
        for stale in ordered[1:]:
            if str(stale.get("status") or "") not in TASK_ACTIVE:
                continue
            stale["status"] = "completed"
            stale["updated_at"] = _utc()
            result = stale.setdefault("result", {})
            result["summary"] = f"Superseded by newer runtime task {keeper.get('id')} for node {(_task_node_id(stale) or 'unknown')}."
            result["superseded_by"] = keeper.get("id")
            result["dedupe_reconciled"] = True
            retired.append(str(stale.get("id") or ""))
            changed = True
    return changed, [item for item in retired if item]
def _repair_task_metadata(goal: dict[str, Any], graph: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> bool:
    changed = False
    goal_id = str(goal.get("goal_id") or "")
    graph_id = str(goal.get("graph_id") or "")
    node_lookup = {
        str(node.get("id") or ""): node
        for node in graph.get("nodes", []) or []
        if node.get("id")
    }
    for task in tasks.values():
        if _task_goal_id(task) != goal_id:
            continue
        task_changed = False
        if not task.get("goal_id") and goal_id:
            task["goal_id"] = goal_id
            task_changed = True
        if not task.get("graph_id") and graph_id:
            task["graph_id"] = graph_id
            task_changed = True
        node_id = _task_node_id(task)
        if not task.get("node_id") and node_id:
            task["node_id"] = node_id
            task_changed = True
        node = node_lookup.get(str(node_id or ""))
        node_title = (node or {}).get("title")
        if not task.get("title") and node_title:
            task["title"] = node_title
            task_changed = True
        if not task.get("scheduled_by"):
            hint = task.get("scheduler_hint") or {}
            scheduled_by = hint.get("scheduled_by")
            if scheduled_by:
                task["scheduled_by"] = scheduled_by
                task_changed = True
        changed = changed or task_changed
    return changed
def _summarize_task_states(goal: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    related = [tasks[task_id] for task_id in goal.get("task_ids", []) or [] if task_id in tasks]
    statuses = [str(item.get("status") or "") for item in related]
    recoverable_failures = [
        item for item in related if str(item.get("status") or "") in TASK_FAILED and _task_requested_requeue(item)
    ]
    terminal_failures = [
        item for item in related if str(item.get("status") or "") in TASK_FAILED and not _task_requested_requeue(item)
    ]
    return {
        "tasks": related,
        "statuses": statuses,
        "has_active": any(status in TASK_ACTIVE for status in statuses),
        "has_failed": bool(terminal_failures),
        "has_recovering_timeout": bool(recoverable_failures),
        "has_waiting": any(status == "waiting_approval" for status in statuses),
        "all_completed": bool(statuses) and all(status in TASK_DONE for status in statuses),
        "failed_count": len(terminal_failures),
        "recovering_count": len(recoverable_failures),
        "completed_count": sum(1 for status in statuses if status in TASK_DONE),
    }


def _refresh_decomposition(goal: dict[str, Any], graph: dict[str, Any], task_summary: dict[str, Any]) -> bool:
    decomposition = list(goal.get("decomposition") or [])
    if not decomposition:
        return False
    original = json.dumps(decomposition, ensure_ascii=False, sort_keys=True)
    graph_nodes = graph.get("nodes", []) or []
    completed_nodes = sum(1 for node in graph_nodes if node.get("status") == "completed")
    total_nodes = len(graph_nodes)
    has_graph = bool(graph)
    is_running = goal.get("status") in {"running", "planned"} or task_summary.get("has_active")
    is_completed = goal.get("status") == "completed" or graph.get("status") == "completed" or task_summary.get("all_completed")

    for index, step in enumerate(decomposition):
        desired = "pending"
        if is_completed:
            desired = "completed"
        elif index == 0 and has_graph:
            desired = "completed"
        elif index == 1 and (task_summary.get("tasks") or graph_nodes):
            desired = "completed"
        elif index == 2 and is_running:
            desired = "in_progress"
        elif index == 3 and (completed_nodes >= total_nodes and total_nodes > 0):
            desired = "completed"
        step["status"] = desired
    goal["decomposition"] = decomposition
    return json.dumps(decomposition, ensure_ascii=False, sort_keys=True) != original



def _graph_activity(graph: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> dict[str, bool]:
    nodes = graph.get("nodes", []) or []
    statuses = [str(node.get("status") or "") for node in nodes]

    def _live_task(node: dict[str, Any]) -> dict[str, Any] | None:
        task_id = node.get("task_id")
        if not task_id:
            return None
        return tasks.get(str(task_id))

    running_like = {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge"}
    blocked_like = {"blocked"}

    has_running = any(
        str(node.get("status") or "") in running_like and _live_task(node) is not None
        for node in nodes
    )
    has_blocked = any(
        str(node.get("status") or "") in blocked_like and _live_task(node) is not None
        for node in nodes
    )
    return {
        "has_running": has_running,
        "has_blocked": has_blocked,
        "all_completed": bool(statuses) and all(status in {"completed", "ready_for_merge"} for status in statuses),
    }

def _append_reflection(goal: dict[str, Any], success: bool, summary: str, blockers: list[str] | None = None) -> bool:
    blockers = list(blockers or [])
    entry = {
        "at": goal.get("updated_at"),
        "success": success,
        "summary": summary,
        "blockers": blockers,
    }
    reflections = goal.setdefault("reflection", [])
    if reflections:
        last = reflections[-1]
        if last.get("success") == entry["success"] and last.get("summary") == entry["summary"]:
            return False
    reflections.append(entry)
    return True




def _failed_task_details(task_summary: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for task in task_summary.get("tasks", []):
        status = str(task.get("status") or "")
        if status not in TASK_FAILED:
            continue
        result = task.get("result") or {}
        failed.append({
            "task_id": task.get("id"),
            "node_id": _task_node_id(task),
            "status": status,
            "summary": result.get("summary") or task.get("title") or "task failed",
        })
    return failed


def _build_failure_replan_request(goal: dict[str, Any], graph: dict[str, Any], task_summary: dict[str, Any], blockers: list[str]) -> str:
    failed_tasks = _failed_task_details(task_summary)
    graph_nodes = [
        {
            "id": node.get("id"),
            "title": node.get("title"),
            "status": node.get("status"),
            "task_id": node.get("task_id"),
        }
        for node in (graph.get("nodes", []) or [])
        if str(node.get("status") or "") in {"blocked", "failed", "running", "pending"}
    ][:8]
    payload = {
        "goal_id": goal.get("goal_id"),
        "target": goal.get("target"),
        "goal_type": goal.get("type"),
        "status": goal.get("status"),
        "blockers": blockers,
        "failed_tasks": failed_tasks,
        "graph_status": graph.get("status"),
        "graph_nodes": graph_nodes,
    }
    return "Runtime failure replan request:\n" + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _attach_failure_replan(goal: dict[str, Any], graph: dict[str, Any], task_summary: dict[str, Any], blockers: list[str]) -> bool:
    request = _build_failure_replan_request(goal, graph, task_summary, blockers)
    metadata = goal.setdefault("metadata", {})
    existing = metadata.get("failure_replan") or {}
    if existing.get("request") == request and existing.get("status") in {"planned", "error"}:
        return False
    try:
        package = build_replan(request, apply=False)
        metadata["failure_replan"] = {
            "updated_at": _utc(),
            "status": package.get("status"),
            "request": request,
            "hold_candidate_count": len(package.get("hold_candidates", [])),
            "new_goal_proposals": [
                item.get("target")
                for item in (package.get("new_goal_proposals") or [])[:6]
                if item.get("target")
            ],
            "impacted_task_ids": list(package.get("impacted_task_ids", []))[:10],
            "risk_level": (package.get("analysis") or {}).get("risk_level"),
            "next_mode": ((package.get("analysis") or {}).get("recommendation") or {}).get("next_mode"),
        }
    except Exception as exc:
        metadata["failure_replan"] = {
            "updated_at": _utc(),
            "status": "error",
            "request": request,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return True
def sync_goal_runtime() -> dict[str, Any]:
    tasks_payload = _load_tasks()
    tasks = _task_map(tasks_payload)
    goals = ENGINE.load_goals()
    changed = False
    tasks_changed = False
    summary = {
        "updated": 0,
        "completed": 0,
        "failed": 0,
        "on_hold": 0,
        "running": 0,
        "planned": 0,
        "decomposition_updates": 0,
        "task_link_repairs": 0,
        "task_deduplications": 0,
    }

    for goal in goals:
        previous_status = str(goal.get("status") or "pending")
        deduped_task_ids: list[str] = []
        graph = _graph(goal.get("graph_id"))
        deduped_changed, deduped_task_ids = _dedupe_goal_tasks(goal, tasks)
        if deduped_changed:
            changed = True
            tasks_changed = True
            summary["task_deduplications"] += len(deduped_task_ids)
        if _repair_graph_runtime(goal.get("graph_id"), graph, tasks, goal.get("goal_id")):
            changed = True
        if _repair_task_metadata(goal, graph, tasks):
            changed = True
            tasks_changed = True
        canonical_task_ids, stale_task_ids = _canonical_task_ids(goal, graph, tasks)
        if canonical_task_ids != list(goal.get("task_ids") or []):
            metadata = goal.setdefault("metadata", {})
            runtime_sync = metadata.setdefault("runtime_sync", {})
            runtime_sync["last_task_link_repair_at"] = _utc()
            runtime_sync["stale_task_ids"] = stale_task_ids
            runtime_sync["canonical_task_ids"] = canonical_task_ids
            goal["task_ids"] = canonical_task_ids
            changed = True
            summary["task_link_repairs"] += 1
        if deduped_task_ids:
            metadata = goal.setdefault("metadata", {})
            runtime_sync = metadata.setdefault("runtime_sync", {})
            runtime_sync["deduped_task_ids"] = deduped_task_ids
            runtime_sync["last_task_dedup_at"] = _utc()
        task_summary = _summarize_task_states(goal, tasks)
        graph_activity = _graph_activity(graph, tasks)
        desired_status = previous_status
        blockers: list[str] = []
        status_reason = None

        has_graph_nodes = bool(graph.get("nodes") or [])
        if graph.get("status") == "completed" or graph_activity.get("all_completed") or (task_summary.get("all_completed") and not has_graph_nodes):
            desired_status = "completed"
            status_reason = "runtime-sync-completed"
        elif task_summary.get("has_waiting"):
            desired_status = "on_hold"
            status_reason = "runtime-sync-waiting-approval"
            blockers.append("Linked task is waiting for approval or operator guidance.")
        elif task_summary.get("has_active") or graph_activity.get("has_running"):
            desired_status = "running"
            status_reason = "runtime-sync-active-task"
        elif task_summary.get("has_recovering_timeout"):
            desired_status = "planned" if goal.get("graph_id") else "pending"
            status_reason = "runtime-sync-awaiting-requeue"
        elif task_summary.get("has_failed") or graph_activity.get("has_blocked"):
            desired_status = "failed"
            status_reason = "runtime-sync-failed"
            blockers.append("One or more linked tasks failed or timed out.")
        elif goal.get("graph_id") and previous_status in {"pending", "planned", "running"}:
            desired_status = "planned"
            status_reason = "runtime-sync-graph-present"

        if _refresh_decomposition(goal, graph, task_summary):
            summary["decomposition_updates"] += 1
            changed = True

        if previous_status != desired_status:
            goal["status"] = desired_status
            goal["updated_at"] = _utc()
            ENGINE._refresh_lifecycle(goal, previous_status, desired_status, status_reason)
            changed = True
            summary["updated"] += 1
            if desired_status == "completed":
                summary["completed"] += 1
                changed = _append_reflection(goal, True, "Goal completed through runtime task/graph synchronization.") or changed
            elif desired_status == "failed":
                summary["failed"] += 1
                changed = _append_reflection(goal, False, "Goal failed because one or more linked tasks failed or timed out.", blockers) or changed
                changed = _attach_failure_replan(goal, graph, task_summary, blockers) or changed
            elif desired_status == "on_hold":
                summary["on_hold"] += 1
                changed = _append_reflection(goal, False, "Goal is blocked waiting for approval or operator guidance.", blockers) or changed
            elif desired_status == "running":
                summary["running"] += 1
            elif desired_status == "planned":
                summary["planned"] += 1

        evaluation = goal.setdefault("evaluation", {})
        if blockers != evaluation.get("blockers", []):
            evaluation["blockers"] = blockers
            changed = True
        if goal.get("status") != "failed":
            metadata = goal.setdefault("metadata", {})
            if metadata.pop("failure_replan", None) is not None:
                changed = True

        goal["evaluation"] = ENGINE._rebuild_evaluation(goal)
        goal["scoring"] = ENGINE._score_goal(goal, scoring=goal.get("scoring"))
        goal["priority_score"] = goal["scoring"]["priority_score"]
        goal["priority_band"] = goal["scoring"]["priority_band"]

    if changed:
        ENGINE.save_goals(goals)
    if tasks_changed:
        _save_json(TASKS, tasks_payload)

    payload = {
        "status": "updated" if changed else "no-change",
        "goal_count": len(goals),
        "active_goal_count": len([goal for goal in goals if goal.get("status") in ACTIVE_STATUSES]),
        **summary,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(sync_goal_runtime(), ensure_ascii=False, indent=2))















