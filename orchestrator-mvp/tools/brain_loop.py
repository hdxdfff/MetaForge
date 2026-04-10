from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".venv" / "Lib" / "site-packages"))

from tools.io_utils import atomic_write_json
from fastapi.testclient import TestClient
from app.main import app, orchestrator
from app.models import DispatchTaskRequest, ExecutionMode
from tools.context_kernel import rebuild
from tools.goal_registry import create_goal, get_goal, list_goals, rank_goals, reflect_goal, update_goal
from tools.memory_system import rebuild_memory
from tools.privilege_policy import decide, load_policy
from tools.taskgraph_compiler import compile_goal
from runtime.platform_generator import generate_pending_platforms
from runtime.scheduler import schedule_nodes
from tools.ai_guard import allow_platform_generation
from tools.decision_engine import decide_next_goal
from tools.platform_verification_sweep import run_sweep
from tools.platform_registry import platform_health_summary
from tools.prompt_improvement_sweep import run_prompt_improvement_sweep
from tools.scheduler_optimization_sweep import run_scheduler_optimization_sweep
from tools.task_state_tools import complete_tasks
from tools.goal_runtime import sync_goal_runtime
from tools.goal_storage_audit import run_goal_storage_audit
from tools.experiment_planner import plan_experiments
from tools.experiment_executor import run_experiment
from tools.experiment_evaluator import evaluate_experiment
from tools.capability_distillation import distill_capabilities
from tools.knowledge_engine import rebuild_knowledge
from tools.global_policy_engine import run_global_policy
from tools.cross_project_coordination import run_cross_project_coordination
from tools.release_operations import run_release_operations_status
from tools.release_train_runtime import run_release_train
from tools.coordination_runtime import run_coordination
from tools.runtime_maintenance import run_maintenance
from tools.verification_engine import run_verification
from tools.tool_health_audit import run_tool_health_audit
from tools.ai_testing_compat import load_ai_test_status
from tools.github_learning_engine import (
    scan_github_repositories,
    clone_learning_target,
    github_learning_status,
)
from tools.github_capability_library import refresh_github_capability_library
from tools.module_ownership import (
    create_patch_submission,
    find_patch_submission,
    patch_submission_gate,
    auto_triage_patch_submissions,
    merge_ready_patch_ids,
    auto_merge_ready_submissions,
)
from tools.scheduling_kernel import build_scheduling_snapshot
from tools.factory_task_engine import run_factory_task_engine
from tools.goal_backlog_replenisher import build_goal_backlog_plan, record_goal_backlog_result
from tools.kernel_mode import is_component_enabled, load_kernel_mode, should_auto_approve_task
from tools.production_focus import goal_matches_focus, write_production_focus_status

client = TestClient(app)
FACTORY = ROOT / "factory"
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
FACTORY_TASK_ENGINE_STATUS = DATA / "factory_task_engine_status.json"
LOGS = FACTORY / "logs"
APPROVAL = DATA / "approval_policy.json"
TASK_CHECKPOINTS = DATA / "task_checkpoints.json"
LOOP_STATE = DATA / "brain_loop_state.json"
CONTROL_CENTER_STATE = DATA / "control_center_state.json"
DEFAULT_MIN_ACTIVE_GOALS = 3
DEFAULT_MIN_ACTIVE_TASKS = 3
DEFAULT_MAX_ACTIVE_TASKS = 12
MAX_TASKS_PER_TICK = 1
MAX_STEP_TIME_MS = 5000
DEFAULT_RUNTIME_SYNC_EVERY = 5
DEFAULT_TASK_ENGINE_EVERY = 5
DEFAULT_CONTEXT_REBUILD_EVERY = 30
DEFAULT_MEMORY_REBUILD_EVERY = 30
DEFAULT_GLOBAL_POLICY_EVERY = 15
DEFAULT_GOAL_SCAN_LIMIT = 3
TOYOS_MAINLINE_RETRY_LIMIT = 2
TOYOS_ACTIVE_TASK_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
TOYOS_FINISHING_TASK_STATUSES = {"execution_finished"}
GOAL_BLOCKING_TERMINAL_STATUSES = {"failed", "timed_out", "cancelled"}
BLOCKED_RUNNING_GOAL_HOLD_MINUTES = 15
UNBLOCK_REPAIR_TASK_TTL_MINUTES = 20


def _brain_loop_latest_path() -> Path:
    primary = LOGS / "brain_loop_latest.json"
    if LOGS.exists() and os.access(LOGS, os.W_OK):
        return primary
    fallback = DATA / "logs" / "brain_loop_latest.json"
    fallback.parent.mkdir(parents=True, exist_ok=True)
    return fallback
DELIVERY_NODE_KIND_PRIORITY = {
    "artifact-build": 5,
    "artifact-test": 4,
    "artifact-audit": 3,
    "artifact-evidence": 3,
    "implementation": 2,
    "module-implementation": 2,
    "verification": 2,
    "planning": 1,
    "architecture": 1,
}
VALIDATION_ONLY_MARKERS = (
    "syntax",
    "strategy validation",
    "reuse probe",
    "read_only_syntax_check",
    "analysis only",
    "design note",
)
DELIVERY_MARKERS = (
    "build",
    "qemu",
    "kernel.bin",
    "deliver",
    "artifact",
    "release",
    "score-report",
    "build-report",
)
FIRST_ARTIFACT_NODE_KINDS = {"artifact-build", "artifact-test", "artifact-evidence"}
FIRST_ARTIFACT_SUPERSEDED_KINDS = {
    "architecture",
    "planning",
    "cross-project-coordination",
    "cross-project-work-package",
    "cross-project-coordination-package",
    "artifact-audit",
}


def _dispatch_task_direct(payload: dict) -> dict:
    request = DispatchTaskRequest.model_validate(payload)
    task = asyncio.run(orchestrator.dispatch_task(request))
    return task.model_dump(mode="json")


def _capability_count() -> int:
    registry = _load_json(FACTORY / "capability_registry.json", {})
    return len(registry.get("capabilities", []))


def _healthy_platform(platform_id: str | None) -> bool:
    if not platform_id:
        return False
    summary = platform_health_summary()
    for item in summary.get("platforms", []):
        if item.get("platform_id") == platform_id:
            return item.get("health") == "healthy"
    return False


def _open_goal_targets(goals: list[dict]) -> set[str]:
    return {
        str(item.get("target") or "").strip().lower()
        for item in goals
        if item.get("status") in {"pending", "planned", "running"}
    }


def _ensure_cross_project_goal(
    goals: list[dict], actions: list[dict], allow_goal_generation: bool
) -> dict | None:
    if not allow_goal_generation:
        return None
    coordination = run_cross_project_coordination(limit=3)
    selected = coordination.get("selected") or []
    if not selected:
        return coordination
    open_targets = _open_goal_targets(goals)
    for item in selected:
        target = str(item.get("target") or "").strip()
        if not target or target.lower() in open_targets:
            continue
        goal = create_goal(
            target,
            goal_type="build_product",
            notes="Auto-generated cross-project coordination objective from project graph and organization layer.",
        )
        actions.append(
            {
                "phase": "cross-project-goal-seed",
                "goal_id": goal.get("goal_id"),
                "target": goal.get("target"),
                "projects": [proj.get("project_id") for proj in item.get("projects", [])],
                "departments": item.get("departments", []),
                "score": item.get("score"),
            }
        )
        goals.append(goal)
        break
    return coordination


def _ensure_unblock_goal(
    goals: list[dict],
    actions: list[dict],
    blocked_candidates: list[dict],
    allow_goal_generation: bool,
) -> dict | None:
    if not allow_goal_generation:
        return None
    open_targets = _open_goal_targets(goals)
    for item in blocked_candidates:
        goal = item.get("goal") or {}
        graph = item.get("graph") or {}
        node = item.get("node") or {}
        base_target = str(goal.get("target") or goal.get("notes") or "blocked work").strip()
        node_title = str(node.get("title") or node.get("kind") or node.get("id") or "blocked node").strip()
        target = f"Unblock {base_target}: {node_title}"
        if target.lower() in open_targets:
            continue
        reason = str(item.get("reason") or "dependency blocked").strip()
        unblock_goal = create_goal(
            target,
            goal_type="repair",
            notes=f"Auto-generated unblock goal from blocked node {node.get('id') or node_title}. Reason: {reason}",
            lane="operations",
            assigned_department="operations_department",
            factory_pool="ops",
            priority_class="recovery",
            release_tier="experimental",
            shares_mainline_context=False,
        )
        actions.append(
            {
                "phase": "unblock-goal-seed",
                "goal_id": unblock_goal.get("goal_id"),
                "target": unblock_goal.get("target"),
                "source_goal_id": goal.get("goal_id"),
                "source_graph_id": graph.get("graph_id"),
                "source_node_id": node.get("id"),
                "reason": reason,
            }
        )
        goals.append(unblock_goal)
        return unblock_goal
    return None


def _has_active_repair_task(
    task_snapshot: list[dict] | None,
    *,
    goal_id: str,
    node_id: str,
) -> bool:
    if not goal_id or not node_id:
        return False
    now = datetime.now(timezone.utc)
    for task in task_snapshot or []:
        if str(task.get("goal_id") or "").strip() != str(goal_id).strip():
            continue
        if str(task.get("node_id") or "").strip() != str(node_id).strip():
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"completed", "failed", "timed_out", "cancelled"}:
            updated_at = _parse_time(str(task.get("updated_at") or task.get("created_at") or ""))
            if updated_at is not None:
                age_minutes = (now - updated_at).total_seconds() / 60.0
                if age_minutes >= UNBLOCK_REPAIR_TASK_TTL_MINUTES:
                    continue
            return True
    return False


def _dispatch_unblock_repair_task(
    candidate: dict,
    *,
    task_snapshot: list[dict] | None,
) -> dict:
    goal_value = candidate.get("goal") or {}
    goal = goal_value if isinstance(goal_value, dict) else {"target": str(goal_value)}
    graph = candidate.get("graph") or {}
    node_value = candidate.get("node") or {}
    node = node_value if isinstance(node_value, dict) else {}
    goal_id = str(goal.get("goal_id") or candidate.get("goal_id") or "").strip()
    graph_id = str(graph.get("graph_id") or candidate.get("graph_id") or "").strip()
    node_id = str(node.get("id") or candidate.get("node_id") or candidate.get("task_id") or "").strip()
    node_title = str(
        node.get("title")
        or candidate.get("title")
        or node_id
        or candidate.get("task_id")
        or "blocked node"
    ).strip()
    if _has_active_repair_task(task_snapshot, goal_id=goal_id, node_id=node_id):
        return {
            "status": "skipped",
            "reason": "active-repair-task-exists",
            "goal_id": goal_id,
            "graph_id": graph_id,
            "node_id": node_id,
        }
    prompt = (
        f"Repair the blocked work item for goal {goal.get('target') or candidate.get('goal') or goal_id}.\n\n"
        f"Blocked node: {node_title}\n"
        f"Reason: {candidate.get('reason') or candidate.get('blockers') or 'dependency blocked'}\n\n"
        "Generate the smallest unblock action, dependency repair, or evidence repair needed to move the work out of "
        "blocked state."
    )
    payload = {
        "prompt": prompt,
        "title": f"Repair blocked node: {node_title}",
        "goal": str(goal.get("target") or candidate.get("goal") or goal_id or node_title),
        "goal_id": goal_id or None,
        "graph_id": graph_id or None,
        "node_id": node_id or None,
        "scheduled_by": "brain_loop",
        "auto_approve": True,
        "caller": "brain-loop-unblock",
        "repo_path": goal.get("repo_path") or goal.get("workspace") or candidate.get("repo_path"),
        "execution_mode": ExecutionMode.research.value,
        "task_type": "path_repair",
        "queue_name": "unblock",
        "verification_level": "L2",
        "max_runtime_seconds": 1800,
        "retry_limit": 1,
        "decomposition_depth": 0,
        "max_decomposition_depth": 0,
        "rollback_rule": "mark_failed_and_requeue_split",
        "admission_lane": "unblock",
        "admission_reason": "auto-unblock-repair",
        "scheduler_hint": {
            "admission_mode": "direct",
            "unblock_lane": "unblock",
            "block_relief_score": 100,
            "source_goal_id": goal_id,
            "source_graph_id": graph_id or None,
            "source_node_id": node_id,
            "block_reason": candidate.get("reason"),
        },
    }
    task = _dispatch_task_direct(payload)
    if goal_id and task.get("id"):
        goal_task_ids = list(goal.get("task_ids") or [])
        if task["id"] not in goal_task_ids:
            goal_task_ids.append(task["id"])
        update_goal(goal_id, task_ids=goal_task_ids, status="running")
    return {
        "status": "dispatched",
        "goal_id": goal_id,
        "graph_id": graph.get("graph_id"),
        "node_id": node_id,
        "task_id": task.get("id"),
        "task_type": payload["task_type"],
        "queue_name": payload["queue_name"],
        "reason": candidate.get("reason"),
    }


def _write_soak_state(actions: list[dict]) -> None:
    soak_path = DATA / "soak_state.json"
    existing = _load_json(soak_path, {"samples": []})
    samples = existing.get("samples", [])
    samples.append(
        {
            "at": _utc(),
            "action_count": len(actions),
            "active_actions": [item.get("phase") for item in actions[:10]],
        }
    )
    existing["samples"] = samples[-500:]
    existing["updated_at"] = _utc()
    _save_json(soak_path, existing)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _goal_corpus(goal: dict | None) -> str:
    goal = goal or {}
    parts = [
        goal.get("target"),
        goal.get("notes"),
        goal.get("repo_path"),
        goal.get("primary_artifact_id"),
        " ".join(str(item) for item in (goal.get("tags") or []) if item),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _is_toyos_goal(goal: dict | None) -> bool:
    corpus = _goal_corpus(goal)
    return any(marker in corpus for marker in ("toyos", "toy-os", "generated/toy-os-demo", "generated\toy-os-demo"))


def _is_toyos_mainline_goal(goal: dict | None) -> bool:
    goal = goal or {}
    if not _is_toyos_goal(goal):
        return False
    lane = str(goal.get("lane") or "").strip().lower()
    goal_type = str(goal.get("type") or "").strip().lower()
    release_tier = str(goal.get("release_tier") or "").strip().lower()
    return lane == "mainline" or goal_type == "build_product" or release_tier == "mainline"


def _is_toyos_task(task: dict | None) -> bool:
    task = task or {}
    scheduler_hint = task.get("scheduler_hint") or {}
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("prompt"),
        task.get("repo_path"),
        scheduler_hint.get("goal_target"),
        scheduler_hint.get("node_title"),
        " ".join(str(item) for item in (scheduler_hint.get("required_artifacts") or []) if item),
    ]
    corpus = " ".join(str(part or "") for part in parts).lower()
    return any(marker in corpus for marker in ("toyos", "toy-os", "generated/toy-os-demo", "generated\toy-os-demo"))


def _delivery_node_priority(node: dict | None) -> int:
    node = node or {}
    kind = str(node.get("kind") or "").strip().lower()
    corpus = " ".join(str(part or "") for part in [node.get("title"), node.get("prompt"), kind]).lower()
    score = DELIVERY_NODE_KIND_PRIORITY.get(kind, 1)
    if any(marker in corpus for marker in DELIVERY_MARKERS):
        score += 2
    if any(marker in corpus for marker in VALIDATION_ONLY_MARKERS):
        score -= 3
    return score


def _graph_meta(graph: dict) -> dict:
    meta = graph.setdefault("meta", {})
    if not isinstance(meta, dict):
        meta = {}
        graph["meta"] = meta
    return meta


def _record_first_artifact(goal: dict, graph: dict, actions: list[dict]) -> bool:
    meta = _graph_meta(graph)
    if meta.get("first_artifact_observed_at"):
        return False
    for node in graph.get("nodes", []):
        if node.get("status") != "completed":
            continue
        if str(node.get("kind") or "").strip().lower() not in FIRST_ARTIFACT_NODE_KINDS:
            continue
        stamp = str(node.get("completed_at") or _utc())
        meta["first_artifact_observed_at"] = stamp
        meta["first_artifact_node_id"] = node.get("id")
        meta["first_artifact_wait_ticks"] = 0
        actions.append({
            "phase": "first-artifact-observed",
            "goal_id": goal.get("goal_id"),
            "graph_id": graph.get("graph_id"),
            "node_id": node.get("id"),
            "at": stamp,
        })
        return True
    return False


def _terminate_runtime_task(task_id: str, reason: str) -> bool:
    task_id = str(task_id or "").strip()
    if not task_id:
        return False
    changed = False
    tasks = _load_json(TASKS, [])
    for item in tasks:
        if str(item.get("id") or "") != task_id:
            continue
        item["status"] = "timed_out"
        item["updated_at"] = _utc()
        result = item.setdefault("result", {})
        if isinstance(result, dict):
            result.setdefault("summary", reason)
            result["error"] = reason
        changed = True
        break
    if changed:
        _save_json(TASKS, tasks)
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    checkpoint = checkpoints.get(task_id)
    if isinstance(checkpoint, dict):
        checkpoint["task_status"] = "timed_out"
        checkpoint["status"] = "timed_out"
        checkpoint["updated_at"] = _utc()
        checkpoint["heartbeat_at"] = _utc()
        checkpoint["error"] = reason
        checkpoints[task_id] = checkpoint
        _save_json(TASK_CHECKPOINTS, checkpoints)
        changed = True
    return changed


def _enforce_first_artifact_policy(goal: dict, graph: dict, actions: list[dict]) -> bool:
    meta = _graph_meta(graph)
    policy = meta.get("first_artifact_policy") or {}
    required = bool(policy.get("required")) or str(meta.get("route_strategy") or "") == "artifact-first"
    if not required:
        return False
    if meta.get("first_artifact_observed_at"):
        meta["first_artifact_wait_ticks"] = 0
        return False
    node_statuses = {str(node.get("status") or "") for node in graph.get("nodes", [])}
    if not node_statuses.intersection({"pending", "running", "blocked", "waiting_patch", "waiting_patch_verification"}):
        return False
    max_wait_ticks = max(1, int(policy.get("max_wait_ticks") or 3))
    wait_ticks = int(meta.get("first_artifact_wait_ticks") or 0) + 1
    meta["first_artifact_wait_ticks"] = wait_ticks
    if wait_ticks < max_wait_ticks:
        return True
    rerouted = False
    reroute_reason = f"first_artifact_timeout_after_{wait_ticks}_ticks"
    build_node_id = "bootstrap_build" if any(node.get("id") == "bootstrap_build" for node in graph.get("nodes", [])) else "artifact_build"
    test_node_id = "bootstrap_test" if any(node.get("id") == "bootstrap_test" for node in graph.get("nodes", [])) else "artifact_test"
    audit_node_id = "bootstrap_audit" if any(node.get("id") == "bootstrap_audit" for node in graph.get("nodes", [])) else None
    for node in graph.get("nodes", []):
        kind = str(node.get("kind") or "").strip().lower()
        if kind not in FIRST_ARTIFACT_SUPERSEDED_KINDS:
            continue
        if str(node.get("status") or "") not in {"pending", "running", "blocked", "waiting_patch", "waiting_patch_verification", "ready_for_merge"}:
            continue
        task_id = node.get("task_id")
        if task_id:
            _terminate_runtime_task(str(task_id), reroute_reason)
            node["superseded_task_id"] = task_id
        node["task_id"] = None
        node["status"] = "completed"
        node["completed_at"] = _utc()
        node.setdefault("result", {})["summary"] = "Superseded by first-artifact reroute."
        rerouted = True
    for node in graph.get("nodes", []):
        node_id = str(node.get("id") or "")
        if node_id == build_node_id and node.get("status") != "completed":
            if node.get("task_id"):
                _terminate_runtime_task(str(node.get("task_id")), reroute_reason)
            node["task_id"] = None
            node["status"] = "pending"
            node["dependencies"] = []
            node["updated_at"] = _utc()
            rerouted = True
        elif node_id == test_node_id and node.get("status") != "completed":
            if node.get("task_id"):
                _terminate_runtime_task(str(node.get("task_id")), reroute_reason)
            node["task_id"] = None
            node["status"] = "pending"
            node["dependencies"] = [build_node_id]
            node["updated_at"] = _utc()
            rerouted = True
        elif audit_node_id and node_id == audit_node_id and node.get("status") != "completed":
            if node.get("task_id"):
                _terminate_runtime_task(str(node.get("task_id")), reroute_reason)
            node["task_id"] = None
            node["status"] = "pending"
            node["dependencies"] = [test_node_id]
            node["updated_at"] = _utc()
            rerouted = True
    if rerouted:
        meta["first_artifact_wait_ticks"] = 0
        meta["first_artifact_rerouted_at"] = _utc()
        meta["first_artifact_reroute_count"] = int(meta.get("first_artifact_reroute_count") or 0) + 1
        actions.append({
            "phase": "first-artifact-reroute",
            "goal_id": goal.get("goal_id"),
            "graph_id": graph.get("graph_id"),
            "reason": reroute_reason,
            "build_node_id": build_node_id,
            "test_node_id": test_node_id,
            "audit_node_id": audit_node_id,
        })
    return rerouted


def _select_project_ready_nodes(goal: dict, ready_nodes: list[dict]) -> list[dict]:
    if not _is_toyos_mainline_goal(goal):
        return list(ready_nodes)
    ordered = sorted(ready_nodes, key=_delivery_node_priority, reverse=True)
    return ordered[:1]


def _active_toyos_mainline_task(task_snapshot: list[dict] | None) -> dict | None:
    for task in task_snapshot or []:
        status = str(task.get("status") or "").strip().lower()
        if status not in TOYOS_ACTIVE_TASK_STATUSES:
            continue
        if _is_toyos_task(task):
            return task
    return None


def _prioritize_toyos_mainline_goals(goals: list[dict], task_snapshot: list[dict] | None) -> tuple[list[dict], dict | None]:
    toyos_goals = [goal for goal in goals if _is_toyos_mainline_goal(goal) and str(goal.get("status") or "") in {"pending", "planned", "running"}]
    if not toyos_goals:
        return list(goals), None
    active_task = _active_toyos_mainline_task(task_snapshot)
    if active_task:
        return list(goals), None
    prioritized_ids = {str(goal.get("goal_id") or "") for goal in toyos_goals if goal.get("goal_id")}
    ordered = toyos_goals + [goal for goal in goals if str(goal.get("goal_id") or "") not in prioritized_ids]
    return ordered, {
        "phase": "prioritize-toyos-mainline",
        "goal_ids": [goal.get("goal_id") for goal in toyos_goals],
        "goal_count": len(toyos_goals),
    }


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _blocked_running_goal_state(goal: dict, task_snapshot: list[dict] | None) -> dict | None:
    if str(goal.get("status") or "").strip().lower() != "running":
        return None
    linked_task_ids = [str(task_id or "").strip() for task_id in (goal.get("task_ids") or []) if str(task_id or "").strip()]
    if not linked_task_ids:
        return None
    tasks_by_id = {
        str(task.get("id") or "").strip(): task
        for task in (task_snapshot or [])
        if str(task.get("id") or "").strip()
    }
    linked_tasks: list[dict] = []
    terminal_statuses: list[str] = []
    latest_terminal_at: datetime | None = None
    for task_id in linked_task_ids:
        task = tasks_by_id.get(task_id)
        if not task:
            return None
        status = str(task.get("status") or "").strip().lower()
        if status in TOYOS_ACTIVE_TASK_STATUSES:
            return None
        if status == "completed" or status not in GOAL_BLOCKING_TERMINAL_STATUSES:
            return None
        linked_tasks.append(task)
        terminal_statuses.append(status)
        task_time = (
            _parse_timestamp(task.get("updated_at"))
            or _parse_timestamp(task.get("completed_at"))
            or _parse_timestamp(task.get("created_at"))
        )
        if task_time and (latest_terminal_at is None or task_time > latest_terminal_at):
            latest_terminal_at = task_time
    if not linked_tasks or latest_terminal_at is None:
        return None
    age_minutes = max(0.0, (datetime.now(timezone.utc) - latest_terminal_at).total_seconds() / 60.0)
    if age_minutes < BLOCKED_RUNNING_GOAL_HOLD_MINUTES:
        return None
    return {
        "reason": "linked_tasks_terminal_without_active_work",
        "linked_task_ids": linked_task_ids,
        "terminal_statuses": terminal_statuses,
        "latest_terminal_at": latest_terminal_at.isoformat().replace("+00:00", "Z"),
        "age_minutes": round(age_minutes, 2),
    }


def _node_retry_limit(goal: dict, node: dict) -> int:
    if _is_toyos_mainline_goal(goal):
        return TOYOS_MAINLINE_RETRY_LIMIT
    execution_mode = str(node.get("execution_mode") or "").strip().lower()
    if execution_mode == "production" or bool((node.get("artifact_spec") or {}).get("required_artifacts")):
        return 1
    return 0


def _should_retry_failed_node(goal: dict, node: dict, status: str) -> bool:
    if status not in {"failed", "timed_out"}:
        return False
    return int(node.get("retry_count") or 0) < _node_retry_limit(goal, node)


def _load_json(path: Path, default):
    if not path.exists():
        return default
    for delay in (0.0, 0.01, 0.02):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            if delay:
                time.sleep(delay)
        except Exception:
            return default
    return default


def _save_json(path: Path, payload):
    atomic_write_json(path, payload)


def _load_control_center_state() -> dict:
    state = _load_json(CONTROL_CENTER_STATE, {"paused": False, "status": "active"})
    paused = bool(state.get("paused"))
    return {
        "paused": paused,
        "status": "paused" if paused else str(state.get("status") or "active"),
        "reason": state.get("reason") or "",
        "updated_at": state.get("updated_at"),
    }


def _active_task_count(tasks: list[dict]) -> int:
    return sum(1 for item in tasks if str(item.get("status") or "") in TOYOS_ACTIVE_TASK_STATUSES)


def _task_corpus(task: dict) -> str:
    scheduler_hint = task.get("scheduler_hint") or {}
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("prompt"),
        task.get("repo_path"),
        scheduler_hint.get("goal_target"),
        scheduler_hint.get("node_title"),
        " ".join(str(item) for item in (scheduler_hint.get("required_artifacts") or []) if item),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _task_state_counts(tasks: list[dict]) -> dict[str, int]:
    counts = {
        "true_running": 0,
        "execution_finishing": 0,
        "pending": 0,
        "blocked": 0,
        "recovery_running": 0,
        "mainline_running": 0,
    }
    for task in tasks:
        status = str(task.get("status") or "").strip().lower()
        corpus = _task_corpus(task)
        scheduler_hint = task.get("scheduler_hint") or {}
        if status in TOYOS_ACTIVE_TASK_STATUSES:
            counts["true_running"] += 1
            if any(marker in corpus for marker in ("recovery", "execution recovery", "recover stable execution output")) or bool(scheduler_hint.get("recovery_task")):
                counts["recovery_running"] += 1
            if any(marker in corpus for marker in ("toyos", "toy-os", "generated/toy-os-demo")) or str(task.get("execution_mode") or "").strip().lower() == "production":
                counts["mainline_running"] += 1
        elif status in TOYOS_FINISHING_TASK_STATUSES:
            counts["execution_finishing"] += 1
        elif status in {"queued", "waiting_approval"}:
            counts["pending"] += 1
        elif status in {"blocked", "failed", "timed_out", "cancelled", "verification_failed"}:
            counts["blocked"] += 1
    return counts


def _compact_goal_for_scan(goal: dict) -> dict:
    return {
        "goal_id": goal.get("goal_id"),
        "type": goal.get("type"),
        "target": goal.get("target"),
        "notes": goal.get("notes"),
        "status": goal.get("status"),
        "created_at": goal.get("created_at"),
        "updated_at": goal.get("updated_at"),
        "graph_id": goal.get("graph_id"),
        "task_ids": list(goal.get("task_ids") or []),
        "assigned_department": goal.get("assigned_department"),
        "goal_class": goal.get("goal_class"),
        "platform_generated": goal.get("platform_generated"),
        "platform_id": goal.get("platform_id"),
        "priority_score": goal.get("priority_score"),
        "priority_band": goal.get("priority_band"),
        "factory_pool": goal.get("factory_pool"),
        "priority_class": goal.get("priority_class"),
        "release_tier": goal.get("release_tier"),
        "tags": list(goal.get("tags") or []),
    }


def _hydrate_goal_for_scan(goal: dict) -> dict:
    if goal.get("graph_id") or goal.get("decomposition") is not None:
        return goal
    goal_id = str(goal.get("goal_id") or "").strip()
    if not goal_id:
        return goal
    try:
        return get_goal(goal_id)
    except Exception:
        return goal


def _int_or_none(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _cached_active_task_count(previous_state: dict | None = None) -> tuple[int | None, str | None]:
    previous_state = previous_state or {}
    for source, value in (
        (
            "previous_runtime_pressure_true_running",
            _int_or_none(((previous_state.get("runtime_pressure") or {}).get("true_running_task_count"))),
        ),
        (
            "previous_runtime_pressure",
            _int_or_none(((previous_state.get("runtime_pressure") or {}).get("active_task_count_after"))),
        ),
        (
            "previous_task_engine_true_running",
            _int_or_none((((previous_state.get("task_engine") or {}).get("supply_after_seed") or {}).get("true_running_task_count"))),
        ),
        (
            "previous_task_engine",
            _int_or_none((((previous_state.get("task_engine") or {}).get("supply_after_seed") or {}).get("active_task_count"))),
        ),
        (
            "previous_goal_storage_true_running",
            _int_or_none((((previous_state.get("goal_storage") or {}).get("task_queue") or {}).get("true_running_task_count"))),
        ),
        (
            "previous_goal_storage",
            _int_or_none((((previous_state.get("goal_storage") or {}).get("task_queue") or {}).get("active_task_count"))),
        ),
    ):
        if value is not None:
            return value, source

    engine_status = _load_json(FACTORY_TASK_ENGINE_STATUS, {})
    for source, value in (
        (
            "factory_task_engine_status_true_running",
            _int_or_none((((engine_status.get("supply_after_seed") or {}).get("true_running_task_count")))),
        ),
        (
            "factory_task_engine_status",
            _int_or_none((((engine_status.get("supply_after_seed") or {}).get("active_task_count")))),
        ),
        (
            "factory_task_engine_status_before_seed_true_running",
            _int_or_none((((engine_status.get("supply_before_seed") or {}).get("true_running_task_count")))),
        ),
        (
            "factory_task_engine_status_before_seed",
            _int_or_none((((engine_status.get("supply_before_seed") or {}).get("active_task_count")))),
        ),
    ):
        if value is not None:
            return value, source
    return None, None


def _load_active_task_count(
    *,
    previous_state: dict | None = None,
    focus: dict | None = None,
    task_snapshot: list[dict] | None = None,
) -> tuple[int, str]:
    focus = focus or {}
    if focus.get("single_product_mode"):
        if task_snapshot is not None:
            snapshot = task_snapshot
        else:
            cached_count, cached_source = _cached_active_task_count(previous_state)
            if cached_count is not None:
                return cached_count, str(cached_source)
            snapshot = _load_json(TASKS, [])
        focus_goal_ids = {
            str(goal.get("goal_id") or "")
            for goal in list_goals()
            if goal.get("status") in {"pending", "planned", "running"} and goal_matches_focus(goal, focus)
        }
        scoped_task_snapshot = [
            task for task in snapshot if str(task.get("goal_id") or "") in focus_goal_ids
        ]
        return _active_task_count(scoped_task_snapshot), "tasks.json.focus"

    cached_count, cached_source = _cached_active_task_count(previous_state)
    snapshot = task_snapshot if task_snapshot is not None else _load_json(TASKS, [])
    live_count = _active_task_count(snapshot)
    if cached_count is None:
        return live_count, "tasks.json.full"
    if live_count != cached_count:
        return live_count, f"tasks.json.reconciled:{cached_source}"
    return cached_count, str(cached_source)


def _seed_goal_pressure(
    actions: list[dict],
    *,
    allow_goal_generation: bool,
    min_active_goals: int,
    max_iterations: int = 4,
) -> dict:
    active_goals = [
        item for item in list_goals() if item.get("status") in {"pending", "planned", "running"}
    ]
    if len(active_goals) >= min_active_goals:
        return {"created": 0, "attempted": 0, "reason": "goal-floor-satisfied"}
    if not allow_goal_generation:
        return {"created": 0, "attempted": 0, "reason": "goal-generation-disabled"}

    attempted = 0
    created = 0
    while attempted < max_iterations:
        active_goals = [
            item for item in list_goals() if item.get("status") in {"pending", "planned", "running"}
        ]
        if len(active_goals) >= min_active_goals:
            break
        decision = decide_next_goal()
        attempted += 1
        actions.append(
            {
                "phase": "task-pressure-goal-seed",
                "action": decision.get("action"),
                "reason": decision.get("reason"),
                "selected": decision.get("selected"),
                "target_active_goals": min_active_goals,
                "current_active_goals": len(active_goals),
            }
        )
        if decision.get("action") != "create-goal":
            break
        created += 1

    final_active_goals = len(
        [item for item in list_goals() if item.get("status") in {"pending", "planned", "running"}]
    )
    return {
        "created": created,
        "attempted": attempted,
        "final_active_goals": final_active_goals,
        "reason": "goal-pressure-maintained"
        if final_active_goals >= min_active_goals
        else "goal-pressure-incomplete",
    }


def _graph_path(graph_id: str) -> Path:
    return FACTORY / "graphs" / f"{graph_id}.json"


def _load_graph(graph_id: str) -> dict:
    return _load_json(_graph_path(graph_id), {})


def _save_graph(graph: dict):
    graph["updated_at"] = _utc()
    _save_json(_graph_path(graph["graph_id"]), graph)


def _runtime_task_status(task_id: str, checkpoints: dict[str, dict] | None = None) -> str | None:
    if not task_id:
        return None
    checkpoint = (checkpoints or {}).get(task_id) or {}
    status = str(checkpoint.get("task_status") or checkpoint.get("status") or "").strip().lower()
    if status:
        return status
    for name in ("execution-evidence.json", "context.json"):
        payload = _load_json(FACTORY / "runtime" / "tasks" / task_id / name, {})
        status = str(payload.get("task_status") or payload.get("status") or "").strip().lower()
        if status:
            return status
    return None


def _latest_task_record_for_node(goal: dict | None, graph: dict, node: dict) -> dict | None:
    goal = goal or {}
    goal_id = str(goal.get("goal_id") or "").strip()
    graph_id = str(graph.get("graph_id") or goal.get("graph_id") or "").strip()
    node_id = str(node.get("id") or "").strip()
    if not graph_id or not node_id:
        return None
    metadata = goal.get("metadata") or {}
    runtime_upgrade = metadata.get("runtime_contract_upgrade") or {}
    reference_time = (
        _parse_timestamp(node.get("updated_at"))
        or _parse_timestamp(runtime_upgrade.get("upgraded_at"))
        or _parse_timestamp(goal.get("updated_at"))
        or _parse_timestamp(goal.get("created_at"))
    )
    best_task: dict | None = None
    best_time: datetime | None = None
    for task in _load_json(TASKS, []):
        if goal_id and str(task.get("goal_id") or "").strip() != goal_id:
            continue
        if str(task.get("graph_id") or "").strip() != graph_id:
            continue
        if str(task.get("node_id") or "").strip() != node_id:
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"queued", "planning", "running", "waiting_approval", "completed", "failed", "timed_out", "cancelled"}:
            continue
        task_time = (
            _parse_timestamp(task.get("updated_at"))
            or _parse_timestamp(task.get("completed_at"))
            or _parse_timestamp(task.get("created_at"))
        )
        if task_time is None:
            continue
        if reference_time is not None and task_time < reference_time:
            continue
        if best_time is None or task_time > best_time:
            best_task = task
            best_time = task_time
    return best_task


def _complete_graph(graph: dict) -> None:
    changed = False
    for node in graph.get("nodes", []):
        if node.get("status") != "completed":
            node["status"] = "completed"
            changed = True
    if changed or graph.get("status") != "completed":
        graph["status"] = "completed"
        _save_graph(graph)


def _mark_node_completed(graph: dict, node_id: str, summary: str) -> bool:
    changed = False
    for node in graph.get("nodes", []):
        if node.get("id") != node_id:
            continue
        if node.get("status") != "completed":
            node["status"] = "completed"
            changed = True
        result = node.setdefault("result", {})
        if result.get("summary") != summary:
            result["summary"] = summary
            changed = True
        if node.get("completed_at") is None:
            node["completed_at"] = _utc()
            changed = True
    return changed


def _should_native_engineering_progress(goal: dict, graph: dict) -> bool:
    goal_type = str(goal.get("type") or "")
    target = str(goal.get("target") or "").lower()
    notes = str(goal.get("notes") or "").lower()
    if goal_type not in {"build_product", "build_platform"}:
        return False
    strategic_markers = ("strengthen ", "expand ", "improve ", "optimize ")
    if target.startswith(strategic_markers):
        return True
    if "auto-generated" in notes or "global-policy" in notes:
        return True
    return False


def _auto_progress_engineering_graph(goal: dict, graph: dict, actions: list[dict]) -> bool:
    if not _should_native_engineering_progress(goal, graph):
        return False
    changed = False
    summaries = {
        "architecture_contract": "Runtime-native architecture contract synthesized from project context kernel, code knowledge graph, ownership map, and global policy.",
        "engineering_plan": "Runtime-native engineering plan synthesized from dependency-aware taskgraph and module ownership map.",
    }
    for node_id, summary in summaries.items():
        changed = _mark_node_completed(graph, node_id, summary) or changed
    if changed:
        graph["status"] = "running"
        actions.append(
            {
                "phase": "native-engineering-planning",
                "goal_id": goal.get("goal_id"),
                "target": goal.get("target"),
                "completed_nodes": list(summaries.keys()),
            }
        )
    return changed


def _refresh_node_statuses(goal: dict | None, graph: dict, checkpoints: dict[str, dict] | None = None):
    changed = False
    for node in graph.get("nodes", []):
        patch_id = node.get("patch_submission_id")
        if patch_id and not node.get("task_id"):
            patch = find_patch_submission(patch_id=patch_id)
            if patch:
                desired_status = node.get("status")
                if patch.get("status") == "rejected":
                    desired_status = "blocked"
                elif patch.get("merge_status") == "merged":
                    desired_status = "completed"
                elif patch.get("merge_status") == "ready":
                    desired_status = "ready_for_merge"
                elif patch.get("status") in {"open", "proposed"}:
                    desired_status = "waiting_patch"
                elif patch.get("status") == "approved":
                    desired_status = "waiting_patch_verification"
                if desired_status != node.get("status"):
                    node["status"] = desired_status
                    changed = True
                if node.get("patch_submission_status") != patch.get("status"):
                    node["patch_submission_status"] = patch.get("status")
                    changed = True
                if node.get("patch_merge_status") != patch.get("merge_status"):
                    node["patch_merge_status"] = patch.get("merge_status")
                    changed = True
                if node.get("patch_verification_status") != patch.get("verification_status"):
                    node["patch_verification_status"] = patch.get("verification_status")
                    changed = True
                continue
        task_id = node.get("task_id")
        if not task_id:
            recovered_task = _latest_task_record_for_node(goal or {}, graph, node)
            if recovered_task:
                recovered_status = str(recovered_task.get("status") or "").strip().lower()
                recovered_task_id = str(recovered_task.get("id") or "").strip()
                if recovered_status == "completed":
                    node["status"] = "completed"
                    node["completed_at"] = recovered_task.get("updated_at") or recovered_task.get("completed_at") or _utc()
                    node["last_completion_task_id"] = recovered_task_id
                    node.setdefault("result", {})["summary"] = str(
                        ((recovered_task.get("result") or {}).get("summary"))
                        or recovered_task.get("title")
                        or "Recovered completed runtime task."
                    )
                    changed = True
                elif recovered_status in {"queued", "planning", "running", "waiting_approval"}:
                    node["task_id"] = recovered_task_id
                    node["status"] = "running" if recovered_status in {"planning", "running"} else "pending"
                    changed = True
            continue
        status = _runtime_task_status(str(task_id), checkpoints)
        if not status:
            continue
        mapped = node.get("status")
        if status == "completed":
            mapped = "completed"
        elif status in {"failed", "timed_out"}:
            if _should_retry_failed_node(goal or {}, node, status):
                payload = _load_json(FACTORY / "runtime" / "tasks" / str(task_id) / "execution-evidence.json", {})
                result = payload.get("result") if isinstance(payload, dict) else {}
                summary = ""
                if isinstance(result, dict):
                    summary = str(result.get("summary") or result.get("error") or "").strip()
                if not summary:
                    summary = f"terminal_status={status}"
                node["status"] = "pending"
                node["task_id"] = None
                node["updated_at"] = _utc()
                node["last_failure_task_id"] = task_id
                node["last_failure_status"] = status
                node["last_failure_summary"] = summary
                node["last_failure_at"] = _utc()
                node["retry_count"] = int(node.get("retry_count", 0) or 0) + 1
                node["retry_mode"] = "same_goal_repair"
                changed = True
                continue
            mapped = "blocked"
        elif status == "waiting_approval":
            mapped = "blocked"
        elif status in {"queued", "planning", "running"}:
            mapped = "running"
        if mapped != node.get("status"):
            node["status"] = mapped
            changed = True
    node_statuses = [node.get("status") for node in graph.get("nodes", [])]
    if node_statuses and all(
        status in {"completed", "ready_for_merge"} for status in node_statuses
    ):
        graph["status"] = "completed"
        changed = True
    elif any(status == "blocked" for status in node_statuses):
        graph["status"] = "attention"
        changed = True
    else:
        graph["status"] = (
            "running"
            if any(
                status
                in {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge"}
                for status in node_statuses
            )
            else graph.get("status", "ready")
        )
    return changed


def _ready_nodes(graph: dict) -> list[dict]:
    completed = {node["id"] for node in graph.get("nodes", []) if node.get("status") == "completed"}
    ready = []
    for node in graph.get("nodes", []):
        if node.get("status") != "pending":
            continue
        deps = set(node.get("dependencies") or [])
        if deps.issubset(completed):
            ready.append(node)
    return ready


def _module_artifact_paths(module_focus: list[str] | None) -> list[str]:
    paths: list[str] = []
    for item in module_focus or []:
        module_name = str(item or "").strip()
        if not module_name:
            continue
        if module_name.startswith(("app.", "runtime.", "tools.", "agents.", "state.")):
            candidate = f"{module_name.replace('.', '/')}.py"
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _build_dispatch_artifact_spec(
    goal: dict, graph: dict, node: dict, selected: dict | None = None
) -> dict:
    selected = selected or {}
    graph_meta = graph.get("meta") or {}
    spec = dict((graph_meta.get("artifact_spec") or {}))
    node_spec = node.get("artifact_spec") or {}
    if node_spec:
        spec.update(node_spec)
    if not spec:
        spec = {
            "artifact_id": f"{graph.get('graph_id')}:{node.get('id')}",
            "artifact_type": "software_component",
            "type": "software_component",
            "deliverables": ["source_code", "build_script", "test_suite"],
            "expected_outputs": ["source_code", "build_script", "test_suite"],
            "verification": {
                "build_required": True,
                "tests_required": True,
            },
            "registry": "artifact_registry",
        }
    spec.setdefault("artifact_id", f"{graph.get('graph_id')}:{node.get('id')}")
    spec.setdefault("artifact_type", spec.get("type") or "software_component")
    spec.setdefault("type", spec.get("artifact_type") or "software_component")
    expected_outputs = [
        str(item)
        for item in (spec.get("expected_outputs") or spec.get("deliverables") or [])
        if str(item).strip()
    ]
    if not expected_outputs:
        expected_outputs = ["source_code", "build_script", "test_suite"]
    spec["expected_outputs"] = expected_outputs
    spec.setdefault("deliverables", list(expected_outputs))
    verification = dict(spec.get("verification") or {})
    verification.setdefault("build_required", True)
    verification.setdefault("tests_required", True)
    spec["verification"] = verification
    spec.setdefault("registry", "artifact_registry")
    required_artifacts = [
        str(item) for item in (spec.get("required_artifacts") or []) if str(item).strip()
    ]
    if not required_artifacts:
        required_artifacts = [
            str(item) for item in (node.get("required_artifacts") or []) if str(item).strip()
        ]
    if not required_artifacts:
        required_artifacts = _module_artifact_paths(
            (node.get("module_focus") or []) or (selected.get("module_focus") or [])
        )
    if required_artifacts:
        spec["required_artifacts"] = required_artifacts
        spec.setdefault("min_fresh_artifacts", max(1, min(len(required_artifacts), 3)))
        if not spec.get("evidence"):
            spec["evidence"] = [
                item for item in required_artifacts if item.endswith((".json", ".log", ".txt"))
            ]
    if not spec.get("test_command") and (
        verification.get("tests_required") or "test_suite" in expected_outputs
    ):
        spec["test_command"] = "pytest"
    return spec


def _dispatch_node(
    goal: dict,
    graph: dict,
    node: dict,
    *,
    selected: dict | None = None,
    kernel_entry: dict | None = None,
    auto_approve: bool = False,
) -> dict:
    vm_template = None
    graph_meta = graph.get("meta") or {}
    if graph_meta.get("vm_template"):
        vm_template = graph_meta.get("vm_template")
    if selected is None:
        scheduled = schedule_nodes(
            [node],
            capability_route=goal.get("capability_route"),
            vm_template=vm_template,
            worker_vm_policy=(graph_meta.get("worker_vm_policy") or {}),
        )
        selected = scheduled[0] if scheduled else {}
    kernel_entry = kernel_entry or {}
    heartbeat_at = _utc()
    execution_mode = selected.get("execution_mode") or "production"
    artifact_spec = _build_dispatch_artifact_spec(goal, graph, node, selected)
    retry_count = int(node.get("retry_count") or 0)
    retry_summary = str(node.get("last_failure_summary") or "").strip()
    dispatch_prompt = node["prompt"]
    if retry_count and retry_summary:
        dispatch_prompt = (
            f"{node['prompt']}\n\n"
            f"Retry chain: previous attempt failed with {retry_summary}. "
            "Repair the failure, keep the same ToyOS mainline goal moving, and rerun the delivery path before claiming completion."
        )
    payload = {
        "task_id": node.get("task_id") or f"{graph.get('graph_id')}:{node.get('id')}",
        "prompt": dispatch_prompt,
        "title": node.get("title"),
        "goal": goal.get("target"),
        "goal_id": goal.get("goal_id"),
        "graph_id": graph.get("graph_id"),
        "node_id": node.get("id"),
        "scheduled_by": "runtime.scheduler",
        "caller": "brain-loop",
        "repo_path": str(ROOT),
        "task_heartbeat_at": heartbeat_at,
        "auto_approve": auto_approve,
        "allow_resource_scan": True,
        "allow_repo_status": True,
        "capability_request": goal.get("target"),
        "preferred_worker": selected.get("worker"),
        "execution_mode": execution_mode,
        "artifact_spec": artifact_spec,
        "scheduler_hint": {
            "goal_id": goal.get("goal_id"),
            "graph_id": graph.get("graph_id"),
            "node_id": node.get("id"),
            "goal_target": goal.get("target"),
            "node_title": node.get("title"),
            "selection_reason": selected.get("selection_reason"),
            "worker_success_rate": selected.get("worker_success_rate"),
            "skill_matches": selected.get("skill_matches", []),
            "scheduled_by": "runtime.scheduler",
            "required_artifacts": list(artifact_spec.get("required_artifacts") or []),
            "min_fresh_artifacts": artifact_spec.get("min_fresh_artifacts"),
            "artifact_spec": artifact_spec,
            "execution_mode": selected.get("execution_mode"),
            "execution_lane": selected.get("execution_lane"),
            "worker_vm_preferred": selected.get("worker_vm_preferred"),
            "module_focus": selected.get("module_focus", []),
            "owner_teams": selected.get("owner_teams", []),
            "module_ownership": selected.get("module_ownership", {}),
            "patch_required": selected.get("patch_required", False),
            "patch_target_teams": selected.get("patch_target_teams", []),
            "factory_pool": goal.get("factory_pool"),
            "factory_priority": goal.get("factory_priority"),
            "priority_class": goal.get("priority_class"),
            "release_tier": goal.get("release_tier"),
            "assigned_department": goal.get("assigned_department"),
            "task_heartbeat_at": heartbeat_at,
            "timeslice_seconds": kernel_entry.get("timeslice_seconds", 60),
            "effective_priority": kernel_entry.get("effective_priority"),
            "priority_components": kernel_entry.get("priority_components", {}),
            "focus_mode": kernel_entry.get("focus_mode", False),
            "checkpoint_hint": kernel_entry.get("checkpoint_hint", {}),
            "scheduler_reason": kernel_entry.get("reason"),
            "retry_count": retry_count,
            "retry_mode": node.get("retry_mode"),
            "last_failure_task_id": node.get("last_failure_task_id"),
            "last_failure_summary": retry_summary or None,
        },
        "vm_request": (vm_template or {}).get("template_id") if vm_template else None,
    }
    if selected.get("patch_required"):
        patch = create_patch_submission(
            task_id=None,
            node_id=node.get("id"),
            title=f"Patch proposal for {node.get('title')}",
            team=node.get("team"),
            owner_teams=selected.get("patch_target_teams", []),
            module_focus=selected.get("module_focus", []),
            reason="Non-owner engineering team is modifying owned modules; patch submission required.",
            repo_path=goal.get("repo_path"),
        )
        gate = patch_submission_gate(node_id=node.get("id"))
        payload["scheduler_hint"]["patch_submission"] = patch
        actions = payload["scheduler_hint"].setdefault("ownership_actions", [])
        actions.append("patch-submission-required")
        node["patch_submission_id"] = patch.get("patch_id")
        node["patch_submission_status"] = gate.get("status")
        if not gate.get("approved"):
            return {
                "status": "patch-required",
                "patch_submission": patch,
                "approved": False,
            }
    try:
        task = _dispatch_task_direct(payload)
    except Exception as exc:
        node["status"] = "failed"
        node["dispatch_error"] = f"{type(exc).__name__}: {exc}"
        node["dispatch_error_type"] = type(exc).__name__
        node["dispatch_error_at"] = _utc()
        node["execution_mode"] = execution_mode
        node["artifact_spec"] = artifact_spec
        return {
            "status": "dispatch-error",
            "error": str(exc),
            "error_type": type(exc).__name__,
            "artifact_spec": artifact_spec,
        }
    node["task_id"] = task.get("id")
    node["status"] = "running"
    node["worker"] = selected.get("worker")
    node["selection_reason"] = selected.get("selection_reason")
    node["worker_success_rate"] = selected.get("worker_success_rate")
    node["skill_matches"] = selected.get("skill_matches", [])
    node["execution_mode"] = selected.get("execution_mode")
    node["execution_lane"] = selected.get("execution_lane")
    node["worker_vm_preferred"] = selected.get("worker_vm_preferred")
    node["artifact_spec"] = {
        **artifact_spec,
        "artifact_id": task.get("id") or artifact_spec.get("artifact_id"),
    }
    return task


def _run_github_learning_cycle(actions: list[dict], clone_limit: int = 1) -> dict:
    scan = scan_github_repositories(limit=12)
    actions.append(
        {
            "phase": "github-learning-scan",
            "candidate_count": scan.get("candidate_count", 0),
            "top_candidates": [
                item.get("full_name") for item in (scan.get("candidates") or [])[:3]
            ],
        }
    )
    status_before = github_learning_status()
    clone_result = {"status": "skipped", "reason": "no-clone-needed", "operations": []}
    if int(status_before.get("ready_repo_count", 0) or 0) < max(1, clone_limit):
        clone_result = clone_learning_target(limit=clone_limit)
        actions.append(
            {
                "phase": "github-learning-clone",
                "status": clone_result.get("status"),
                "operation_count": clone_result.get("operation_count", 0),
                "repos": [item.get("repo") for item in (clone_result.get("operations") or [])[:3]],
            }
        )
    knowledge = rebuild_knowledge()
    github_status = knowledge.get("github_learning") or {}
    actions.append(
        {
            "phase": "github-learning-refresh",
            "ready_repo_count": github_status.get("ready_repo_count", 0),
            "learned_repository_count": (knowledge.get("repo_learning") or {}).get(
                "learned_repository_count", 0
            ),
            "extracted_capabilities": (knowledge.get("repo_learning") or {}).get(
                "extracted_capabilities", []
            )[:6],
        }
    )
    return {"scan": scan, "clone": clone_result, "knowledge": knowledge, "status": github_status}


def _run_experiment_cycle(actions: list[dict]) -> dict:
    plan = plan_experiments()
    actions.append(
        {
            "phase": "experiment-plan",
            "selected": (plan.get("selected") or {}).get("target"),
            "candidate_count": plan.get("candidate_count", 0),
        }
    )
    run = run_experiment()
    actions.append(
        {
            "phase": "experiment-run",
            "status": run.get("status"),
            "target": (run.get("experiment") or {}).get("target"),
        }
    )
    evaluation = evaluate_experiment()
    actions.append(
        {
            "phase": "experiment-evaluate",
            "status": evaluation.get("status"),
            "score": evaluation.get("score"),
            "adopt": evaluation.get("adopt"),
        }
    )
    distillation = distill_capabilities()
    actions.append(
        {
            "phase": "capability-distillation",
            "status": distillation.get("status"),
            "adopted": distillation.get("adopted"),
            "capability_hints": len(distillation.get("capability_hints", [])),
        }
    )
    library = refresh_github_capability_library()
    actions.append(
        {
            "phase": "github-capability-library",
            "status": library.get("status"),
            "asset_count": library.get("asset_count", 0),
            "synced_registry_count": library.get("synced_registry_count", 0),
        }
    )
    knowledge = rebuild_knowledge()
    actions.append(
        {
            "phase": "knowledge-refresh",
            "decision_patterns": len(knowledge.get("decision_patterns", [])),
            "experiment_patterns": len(knowledge.get("experiment_patterns", [])),
        }
    )
    return {
        "plan": plan,
        "run": run,
        "evaluation": evaluation,
        "distillation": distillation,
        "library": library,
        "knowledge": knowledge,
    }


def _complete_runtime_native_goal(
    goal: dict, actions: list[dict], phase: str, summary: str, extra: dict | None = None
) -> None:
    complete_tasks(goal.get("task_ids", []), summary)
    if goal.get("graph_id"):
        graph = _load_graph(goal["graph_id"])
        if graph:
            _complete_graph(graph)
    payload = {"phase": phase, "goal_id": goal.get("goal_id"), "target": goal.get("target")}
    payload.update(extra or {})
    try:
        reflect_goal(goal["goal_id"], success=True, summary=summary)
        payload["status"] = "completed"
    except KeyError:
        payload["status"] = "goal_missing"
        payload["reason"] = "goal_registry_missing_runtime_native_goal"
    actions.append(payload)



def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _budget_exhausted(started_at: float, budget_ms: int) -> bool:
    return _elapsed_ms(started_at) >= max(1, int(budget_ms or 1))


def _cadence_due(cycle: int, every: int) -> bool:
    every = int(every or 0)
    if every <= 1:
        return True
    if cycle <= 1:
        return True
    return cycle % every == 0


def _cached_loop_section(previous_state: dict, key: str, default):
    value = previous_state.get(key)
    return value if value is not None else default


def brain_step(policy_schedule: dict | None = None) -> dict:
    schedule = dict(policy_schedule or {})
    cycle = int(schedule.get("cycle") or 0)
    started_at = time.perf_counter()
    last_phase_at = started_at
    init_metrics: dict[str, int] = {}
    budget_ms = max(50, int(schedule.get("brain_step_budget_ms") or MAX_STEP_TIME_MS))
    task_limit = max(
        1,
        int(schedule.get("brain_step_task_limit") or schedule.get("runtime_dispatch_limit") or MAX_TASKS_PER_TICK),
    )
    goal_scan_limit = max(task_limit, int(schedule.get("brain_step_goal_scan_limit") or (task_limit * 3)))
    previous_state = _load_json(LOOP_STATE, {})
    task_checkpoints = _load_json(TASK_CHECKPOINTS, {})
    init_metrics["load_previous_state_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    last_phase_at = time.perf_counter()
    approval = previous_state.get("approval_policy") or load_policy()
    init_metrics["load_approval_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    last_phase_at = time.perf_counter()
    control = _load_control_center_state()
    init_metrics["load_control_state_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    last_phase_at = time.perf_counter()
    focus = write_production_focus_status(schedule)
    init_metrics["production_focus_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    last_phase_at = time.perf_counter()
    kernel_mode = schedule.get("kernel_mode") or load_kernel_mode()
    init_metrics["load_kernel_mode_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    governance_enabled = is_component_enabled("governance", kernel_mode) and not focus.get("single_product_mode")
    allow_goal_generation = bool(schedule.get("allow_goal_generation", True)) or focus.get("single_product_mode")
    task_snapshot = None
    toyos_lock_task_snapshot = None
    goal_scan_task_snapshot = None
    last_phase_at = time.perf_counter()
    if focus.get("single_product_mode"):
        runtime_pressure = previous_state.get("runtime_pressure") or {}
        active_task_count_before = int(
            runtime_pressure.get("true_running_task_count")
            or runtime_pressure.get("active_task_count_after")
            or runtime_pressure.get("active_task_count_before")
            or 0
        )
        active_task_count_source = "previous_runtime_pressure"
    else:
        active_task_count_before, active_task_count_source = _load_active_task_count(
            previous_state=previous_state,
            focus=focus,
            task_snapshot=task_snapshot,
        )
    init_metrics["active_task_count_ms"] = max(0, round((time.perf_counter() - last_phase_at) * 1000))
    if focus.get("single_product_mode") and task_snapshot is None and active_task_count_before <= 0:
        task_snapshot = []
    min_active_goals = (
        1 if focus.get("single_product_mode") else int(schedule.get("min_active_goals") or DEFAULT_MIN_ACTIVE_GOALS)
    )
    min_active_tasks = (
        1 if focus.get("single_product_mode") else int(schedule.get("min_active_tasks") or DEFAULT_MIN_ACTIVE_TASKS)
    )
    max_active_tasks = (
        min(2, int(schedule.get("max_active_tasks") or DEFAULT_MAX_ACTIVE_TASKS))
        if focus.get("single_product_mode")
        else int(schedule.get("max_active_tasks") or DEFAULT_MAX_ACTIVE_TASKS)
    )
    dispatch_headroom = max(0, max_active_tasks - active_task_count_before)
    dispatch_budget_remaining = min(task_limit, dispatch_headroom) if dispatch_headroom else 0
    actions: list[dict] = []

    sync_every = int(schedule.get("brain_runtime_sync_every") or DEFAULT_RUNTIME_SYNC_EVERY)
    sync_status = _cached_loop_section(previous_state, "goal_runtime_sync", {"status": "skipped"})
    if not _budget_exhausted(started_at, budget_ms) and (
        cycle <= 1 or _cadence_due(cycle, sync_every)
    ):
        sync_status = sync_goal_runtime()
        actions.append(
            {
                "phase": "goal-runtime-sync",
                "status": sync_status.get("status"),
                "updated": sync_status.get("updated", 0),
                "active_goal_count": sync_status.get("active_goal_count", 0),
            }
        )

    goal_audit = _cached_loop_section(previous_state, "goal_storage", {"status": "cached"})
    if not _budget_exhausted(started_at, budget_ms) and (
        cycle <= 1 or _cadence_due(cycle, sync_every)
    ):
        goal_audit = run_goal_storage_audit()
        actions.append(
            {
                "phase": "goal-storage-audit",
                "status": goal_audit.get("status"),
                "stored_successfully": goal_audit.get("stored_successfully"),
                "issues": goal_audit.get("issues", []),
                "active_task_count": ((goal_audit.get("task_queue") or {}).get("active_task_count", 0)),
            }
        )

    global_policy = _cached_loop_section(
        previous_state,
        "global_policy",
        {"focus_capabilities": [], "worker_bias_policy": {}, "organization_priority": {"departments": []}},
    )
    if (
        governance_enabled
        and bool(schedule.get("run_global_policy", True))
        and not _budget_exhausted(started_at, budget_ms)
        and _cadence_due(cycle, int(schedule.get("global_policy_every") or DEFAULT_GLOBAL_POLICY_EVERY))
    ):
        global_policy = run_global_policy()
        actions.append(
            {
                "phase": "global-policy-refresh",
                "focus_capability_count": len(global_policy.get("focus_capabilities") or []),
                "department_count": len(((global_policy.get("organization_priority") or {}).get("departments") or [])),
            }
        )

    task_engine = _cached_loop_section(previous_state, "task_engine", {"status": "cached"})
    if not _budget_exhausted(started_at, budget_ms) and (
        cycle <= 1
        or _cadence_due(cycle, int(schedule.get("task_engine_every") or DEFAULT_TASK_ENGINE_EVERY))
    ):
        task_engine = run_factory_task_engine(schedule)
        actions.append(
            {
                "phase": "factory-task-engine",
                "status": task_engine.get("status"),
                "seeded_goals": [item.get("target") for item in (task_engine.get("seeded_goals") or [])],
                "repaired_graphs": len(task_engine.get("repaired_graphs") or []),
                "ready_node_count": ((task_engine.get("supply_after_seed") or {}).get("ready_node_count")),
                "active_task_count": ((task_engine.get("supply_after_seed") or {}).get("active_task_count")),
            }
        )
    goal_backlog = _cached_loop_section(previous_state, "goal_backlog", {"status": "cached"})
    if not _budget_exhausted(started_at, budget_ms):
        goal_backlog = build_goal_backlog_plan(schedule)
        actions.append(
            {
                "phase": "goal-backlog-plan",
                "goal_primary": goal_backlog.get("goal_primary"),
                "goal_mode": goal_backlog.get("goal_mode"),
                "goal_health": goal_backlog.get("goal_health"),
                "dispatch_now_count": goal_backlog.get("dispatch_now_count"),
                "pending_candidate_count": goal_backlog.get("pending_candidate_count"),
                "active_candidate_count": goal_backlog.get("active_candidate_count"),
                "compiled_task_types": goal_backlog.get("compiled_task_types") or [],
                "replenishment_block_reason": goal_backlog.get("replenishment_block_reason"),
            }
        )
        if int(goal_backlog.get("dispatch_now_count") or 0) <= 0:
            goal_backlog = record_goal_backlog_result(goal_backlog, dispatched=[])

    active_statuses = {"pending", "planned", "running"}
    goal_refresh_every = max(2, int(schedule.get("goal_refresh_every") or 10))
    goal_snapshot = _cached_loop_section(previous_state, "goal_scan_snapshot", {})
    cached_goals = list(goal_snapshot.get("goals") or [])
    active_goal_count_after = int(goal_snapshot.get("active_goal_count") or len(cached_goals))
    goal_snapshot_refreshed = False
    if cycle <= 1 or _cadence_due(cycle, goal_refresh_every) or not cached_goals:
        goals = rank_goals(statuses=active_statuses, limit=max(goal_scan_limit * 2, task_limit * 2, 8))
        active_goal_count_after = len(rank_goals(statuses=active_statuses))
        goal_snapshot_refreshed = True
    else:
        goals = cached_goals
    if any(_is_toyos_mainline_goal(goal) for goal in goals):
        priority_task_snapshot = task_snapshot if isinstance(task_snapshot, list) else _load_json(TASKS, [])
        goals, toyos_priority_action = _prioritize_toyos_mainline_goals(goals, priority_task_snapshot)
        if toyos_priority_action:
            actions.append(toyos_priority_action)
            if toyos_lock_task_snapshot is None:
                toyos_lock_task_snapshot = priority_task_snapshot
            if goal_scan_task_snapshot is None:
                goal_scan_task_snapshot = priority_task_snapshot
    toyos_backlog_dispatches: list[dict[str, Any]] = []
    backlog_candidates = list((goal_backlog or {}).get("dispatch_candidates") or [])
    backlog_dispatch_budget = max(
        dispatch_budget_remaining,
        int((goal_backlog or {}).get("dispatch_now_count") or 0),
    )
    if backlog_candidates and backlog_dispatch_budget > 0 and not control.get("paused"):
        goal_lookup = {str(goal.get("goal_id") or ""): goal for goal in goals}
        for candidate in backlog_candidates:
            if backlog_dispatch_budget <= 0:
                break
            if not bool(candidate.get("dispatch_now")):
                continue
            payload = candidate.get("payload") or {}
            goal_id = str(payload.get("goal_id") or "").strip()
            graph_id = str(payload.get("graph_id") or "").strip()
            node_id = str(payload.get("node_id") or "").strip()
            goal = goal_lookup.get(goal_id) or {}
            graph = _load_graph(graph_id) if graph_id else {}
            node = next((item for item in (graph.get("nodes", []) or []) if str(item.get("id") or "") == node_id), None) if graph else None
            if node is not None:
                node_status = str(node.get("status") or "").strip().lower()
                if node_status == "completed":
                    continue
                if node_status != "pending" and not bool(candidate.get("dispatch_now")):
                    continue
            try:
                task = _dispatch_task_direct(payload)
            except Exception as exc:
                toyos_backlog_dispatches.append(
                    {
                        "status": "dispatch-error",
                        "goal_id": goal_id,
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    }
                )
                continue
            if graph and node is not None:
                node["task_id"] = task.get("id")
                node["status"] = "running"
                node["updated_at"] = _utc()
                _save_graph(graph)
            if goal_id:
                goal_task_ids = list(goal.get("task_ids") or [])
                if task.get("id") and task.get("id") not in goal_task_ids:
                    goal_task_ids.append(task.get("id"))
                goal_lookup[goal_id] = update_goal(goal_id, task_ids=goal_task_ids, status="running")
            toyos_backlog_dispatches.append(
                {
                    "status": "dispatched",
                    "goal_id": goal_id,
                    "graph_id": graph_id,
                    "node_id": node_id,
                    "task_id": task.get("id"),
                    "task_type": payload.get("task_type"),
                    "queue_name": payload.get("queue_name"),
                }
            )
            backlog_dispatch_budget -= 1
            dispatch_budget_remaining = max(0, dispatch_budget_remaining - 1)
            task_snapshot = _load_json(TASKS, [])
        if toyos_backlog_dispatches and not any(item.get("status") == "dispatched" for item in toyos_backlog_dispatches):
            goal_backlog = record_goal_backlog_result(goal_backlog, dispatched=[], error="dispatch_failed")
        else:
            goal_backlog = record_goal_backlog_result(goal_backlog, dispatched=toyos_backlog_dispatches)
        toyos_lock_task_snapshot = task_snapshot if isinstance(task_snapshot, list) else _load_json(TASKS, [])
        goal_scan_task_snapshot = toyos_lock_task_snapshot
        actions.append(
            {
                "phase": "goal-backlog-dispatch",
                "dispatched_count": len([item for item in toyos_backlog_dispatches if item.get("status") == "dispatched"]),
                "error_count": len([item for item in toyos_backlog_dispatches if item.get("status") != "dispatched"]),
                "task_ids": [item.get("task_id") for item in toyos_backlog_dispatches if item.get("task_id")],
                "goal_health": goal_backlog.get("goal_health"),
                "last_result": goal_backlog.get("last_replenishment_result"),
            }
        )
    dispatch_candidates: list[dict] = []
    blocked_candidates_for_repair: list[dict] = []
    scanned_goals = 0
    toyos_mainline_lock_held = False
    for goal in goals:
        if scanned_goals >= goal_scan_limit or _budget_exhausted(started_at, budget_ms):
            break
        goal = _hydrate_goal_for_scan(goal)
        if goal_scan_task_snapshot is None and str(goal.get("status") or "").strip().lower() == "running":
            goal_scan_task_snapshot = task_snapshot if isinstance(task_snapshot, list) else _load_json(TASKS, [])
        blocked_goal_state = _blocked_running_goal_state(goal, goal_scan_task_snapshot)
        if blocked_goal_state:
            update_goal(
                goal["goal_id"],
                status="on_hold",
                status_reason="blocked-running-goal-auto-hold",
                blockers=["Linked tasks are terminal without active work; auto-held to unblock dispatch."],
                metadata={
                    "runtime_hold": {
                        **blocked_goal_state,
                        "held_at": _utc(),
                    }
                },
            )
            actions.append(
                {
                    "phase": "auto-hold-blocked-goal",
                    "goal_id": goal.get("goal_id"),
                    "target": goal.get("target"),
                    **blocked_goal_state,
                }
            )
            continue
        if focus.get("single_product_mode") and not goal_matches_focus(goal, focus):
            continue
        scanned_goals += 1
        target_lower = str(goal.get("target") or "").strip().lower()
        if (
            goal.get("platform_generated")
            and _healthy_platform(goal.get("platform_id"))
            and (
                goal.get("type") == "build_platform"
                or target_lower.startswith("build ")
                or target_lower.endswith("factory")
            )
        ):
            complete_tasks(
                goal.get("task_ids", []),
                "Goal auto-completed because the generated platform is present and healthy.",
            )
            if goal.get("graph_id"):
                graph = _load_graph(goal["graph_id"])
                if graph:
                    _complete_graph(graph)
            update_goal(goal["goal_id"], status="completed")
            actions.append({"phase": "complete-generated-platform", "goal_id": goal["goal_id"]})
            continue
        if target_lower == "expand capability routing patterns" and _capability_count() >= 6:
            _complete_runtime_native_goal(
                goal,
                actions,
                "complete-capability-routing",
                "Goal auto-completed because capability routing patterns are already expanded and registered.",
                {"capability_count": _capability_count()},
            )
            update_goal(goal["goal_id"], status="completed")
            continue
        if not goal.get("graph_id"):
            graph = compile_goal(goal)
            update_goal(goal["goal_id"], graph_id=graph["graph_id"], status="planned")
            actions.append({"phase": "compile-goal", "goal_id": goal["goal_id"], "graph_id": graph["graph_id"]})
            goal = {**goal, "graph_id": graph["graph_id"], "status": "planned"}
            if _budget_exhausted(started_at, budget_ms):
                break
        graph = _load_graph(goal.get("graph_id"))
        if not graph:
            continue
        graph_changed = _refresh_node_statuses(goal, graph, task_checkpoints)
        graph_changed = _record_first_artifact(goal, graph, actions) or graph_changed
        graph_changed = _auto_progress_engineering_graph(goal, graph, actions) or graph_changed
        graph_changed = _enforce_first_artifact_policy(goal, graph, actions) or graph_changed
        if graph_changed:
            _save_graph(graph)
        if graph.get("status") == "completed":
            reflect_goal(
                goal["goal_id"],
                success=True,
                summary=f"Goal {goal.get('target')} completed after graph execution reached terminal success.",
            )
            actions.append({"phase": "complete-goal", "goal_id": goal["goal_id"]})
            continue
        if control.get("paused"):
            actions.append({"phase": "paused", "reason": "control-center-paused"})
            break
        ready_nodes = _ready_nodes(graph)
        if ready_nodes:
            if _is_toyos_mainline_goal(goal):
                if toyos_lock_task_snapshot is None:
                    toyos_lock_task_snapshot = task_snapshot if isinstance(task_snapshot, list) else _load_json(TASKS, [])
                active_toyos_task = _active_toyos_mainline_task(toyos_lock_task_snapshot)
                if active_toyos_task or toyos_mainline_lock_held:
                    actions.append({
                        "phase": "project-mainline-lock",
                        "goal_id": goal.get("goal_id"),
                        "target": goal.get("target"),
                        "reason": "active-mainline-task" if active_toyos_task else "dispatch-slot-held",
                        "active_task_id": (active_toyos_task or {}).get("id"),
                    })
                    continue
                ready_nodes = _select_project_ready_nodes(goal, ready_nodes)
                toyos_mainline_lock_held = bool(ready_nodes)
            if ready_nodes:
                dispatch_candidates.append({"goal": goal, "graph": graph, "ready_nodes": ready_nodes})
        else:
            blocked_nodes = [
                node for node in graph.get("nodes", []) if str(node.get("status") or "").strip().lower() == "blocked"
            ]
            if blocked_nodes:
                top_blocked_node = max(blocked_nodes, key=_delivery_node_priority)
                blocked_candidates_for_repair.append(
                    {
                        "goal": goal,
                        "graph": graph,
                        "node": top_blocked_node,
                        "reason": "graph-blocked-without-ready-node",
                    }
                )
        if any(node.get("task_id") for node in graph.get("nodes", [])):
            update_goal(
                goal["goal_id"],
                task_ids=[node.get("task_id") for node in graph.get("nodes", []) if node.get("task_id")],
                status="running" if graph.get("status") != "completed" else "completed",
            )
        if len(dispatch_candidates) >= task_limit and dispatch_budget_remaining > 0:
            break

    if (
        not control.get("paused")
        and not dispatch_candidates
        and blocked_candidates_for_repair
        and dispatch_budget_remaining > 0
        and not _budget_exhausted(started_at, budget_ms)
    ):
        unblock_goal = _ensure_unblock_goal(goals, actions, blocked_candidates_for_repair, True)
        if unblock_goal:
            actions.append(
                {
                    "phase": "unblock-goal-created",
                    "goal_id": unblock_goal.get("goal_id"),
                    "target": unblock_goal.get("target"),
                    "reason": "blocked-work-needs-repair-lane",
                }
            )

    unblock_dispatches: list[dict[str, Any]] = []
    unblock_dispatch_budget = max(1, int(schedule.get("unblock_dispatch_limit") or 1))
    if (
        not control.get("paused")
        and blocked_candidates_for_repair
        and unblock_dispatch_budget > 0
        and not _budget_exhausted(started_at, budget_ms)
    ):
        for candidate in blocked_candidates_for_repair[:unblock_dispatch_budget]:
            if _budget_exhausted(started_at, budget_ms):
                break
            result = _dispatch_unblock_repair_task(
                candidate,
                task_snapshot=task_snapshot if isinstance(task_snapshot, list) else _load_json(TASKS, []),
            )
            unblock_dispatches.append(result)
        if unblock_dispatches:
            actions.append(
                {
                    "phase": "unblock-task-dispatch",
                    "dispatched_count": len([item for item in unblock_dispatches if item.get("status") == "dispatched"]),
                    "skipped_count": len([item for item in unblock_dispatches if item.get("status") == "skipped"]),
                    "task_ids": [item.get("task_id") for item in unblock_dispatches if item.get("task_id")],
                    "reasons": [item.get("reason") for item in unblock_dispatches if item.get("reason")],
                }
            )

    dispatch_count = 0
    if (
        not control.get("paused")
        and decide("dispatch_low_risk_goal_nodes").approved
        and dispatch_candidates
        and dispatch_budget_remaining > 0
        and not _budget_exhausted(started_at, budget_ms)
    ):
        kernel_snapshot = build_scheduling_snapshot(
            dispatch_candidates, dispatch_budget=dispatch_budget_remaining
        )
        actions.append(
            {
                "phase": "scheduling-kernel",
                "focus_mode": kernel_snapshot.get("focus_mode"),
                "focus_reason": kernel_snapshot.get("focus_reason"),
                "ready_count": ((kernel_snapshot.get("queues") or {}).get("ready", 0)),
                "running_count": ((kernel_snapshot.get("queues") or {}).get("running", 0)),
                "dispatchable_count": ((kernel_snapshot.get("queues") or {}).get("dispatchable", 0)),
            }
        )
        graph_lookup = {
            (entry.get("goal", {}).get("goal_id"), entry.get("graph", {}).get("graph_id")): entry
            for entry in dispatch_candidates
        }
        for entry in kernel_snapshot.get("dispatch_order", []):
            if dispatch_budget_remaining <= 0 or _budget_exhausted(started_at, budget_ms):
                break
            candidate = graph_lookup.get((entry.get("goal_id"), entry.get("graph_id")))
            if not candidate:
                continue
            goal = candidate["goal"]
            graph = candidate["graph"]
            node = next((item for item in graph.get("nodes", []) if item.get("id") == entry.get("node_id")), None)
            if node is None or node.get("status") != "pending":
                continue
            task = _dispatch_node(
                goal,
                graph,
                node,
                selected=entry.get("selection") or {},
                kernel_entry={**entry, "focus_mode": kernel_snapshot.get("focus_mode")},
                auto_approve=should_auto_approve_task(
                    requested=False,
                    execution_mode=((entry.get("selection") or {}).get("execution_mode")),
                    scheduler_hint={
                        "factory_pool": goal.get("factory_pool"),
                        "execution_mode": ((entry.get("selection") or {}).get("execution_mode")),
                        "execution_lane": ((entry.get("selection") or {}).get("execution_lane")),
                        "scheduled_by": "runtime.scheduler",
                    },
                    scheduled_by="runtime.scheduler",
                ),
            )
            if task.get("status") == "patch-required":
                actions.append(
                    {
                        "phase": "patch-submission",
                        "goal_id": goal["goal_id"],
                        "node_id": node["id"],
                        "patch_id": ((task.get("patch_submission") or {}).get("patch_id")),
                    }
                )
                _save_graph(graph)
                continue
            if task.get("status") == "dispatch-error":
                actions.append(
                    {
                        "phase": "dispatch-error",
                        "goal_id": goal["goal_id"],
                        "node_id": node["id"],
                        "error_type": task.get("error_type"),
                        "error": task.get("error"),
                    }
                )
                _save_graph(graph)
                continue
            actions.append(
                {
                    "phase": "dispatch-node",
                    "goal_id": goal["goal_id"],
                    "node_id": node["id"],
                    "task_id": task.get("id"),
                    "effective_priority": entry.get("effective_priority"),
                    "timeslice_seconds": entry.get("timeslice_seconds"),
                    "reason": entry.get("reason"),
                }
            )
            dispatch_count += 1
            dispatch_budget_remaining -= 1
            _save_graph(graph)

    for entry in dispatch_candidates:
        goal = entry.get("goal") or {}
        graph = entry.get("graph") or {}
        task_ids = [node.get("task_id") for node in graph.get("nodes", []) if node.get("task_id")]
        if not task_ids:
            continue
        desired_status = "running" if graph.get("status") != "completed" else "completed"
        existing_task_ids = list(goal.get("task_ids") or [])
        if existing_task_ids == task_ids and goal.get("status") == desired_status:
            continue
        update_goal(
            goal["goal_id"],
            task_ids=task_ids,
            status=desired_status,
        )

    if goal_snapshot_refreshed:
        active_goals_after = rank_goals(statuses=active_statuses, limit=max(goal_scan_limit * 2, task_limit * 2, 8))
    else:
        active_goals_after = list(goals)
    active_task_count_after = active_task_count_before + dispatch_count
    if (
        not focus.get("single_product_mode")
        and not control.get("paused")
        and active_task_count_after < min_active_tasks
        and allow_goal_generation
        and not _budget_exhausted(started_at, budget_ms)
    ):
        decision = decide_next_goal()
        actions.append(
            {
                "phase": "decision-engine",
                "action": decision.get("action"),
                "reason": decision.get("reason"),
                "selected": decision.get("selected"),
                "active_goals": len(active_goals_after),
                "active_tasks": active_task_count_after,
                "min_active_goals": min_active_goals,
                "min_active_tasks": min_active_tasks,
            }
        )

    kernel = _cached_loop_section(previous_state, "context_kernel", {})
    if not _budget_exhausted(started_at, budget_ms) and _cadence_due(
        cycle, int(schedule.get("context_rebuild_every") or DEFAULT_CONTEXT_REBUILD_EVERY)
    ):
        kernel = rebuild()
        actions.append({"phase": "context-kernel-refresh", "status": "rebuilt"})

    memory = _cached_loop_section(previous_state, "memory_kernel", {})
    if not _budget_exhausted(started_at, budget_ms) and _cadence_due(
        cycle, int(schedule.get("memory_rebuild_every") or DEFAULT_MEMORY_REBUILD_EVERY)
    ):
        memory = rebuild_memory(actions)
        actions.append({"phase": "memory-kernel-refresh", "status": "rebuilt"})

    state = {
        "updated_at": _utc(),
        "status": "active",
        "mode": "brain_step",
        "control_center": {"paused": control.get("paused"), "status": control.get("status")},
        "approval_policy": approval,
        "actions": actions,
        "context_kernel": kernel,
        "memory_kernel": memory,
        "global_policy": global_policy,
        "task_engine": task_engine,
        "github_learning": _cached_loop_section(previous_state, "github_learning", {"status": "deferred"}),
        "experiment_cycle": _cached_loop_section(previous_state, "experiment_cycle", {"status": "deferred"}),
        "ai_testing": load_ai_test_status(),
        "goal_storage": goal_audit,
        "goal_runtime_sync": sync_status,
        "goal_scan_snapshot": {
            "refresh_every": goal_refresh_every,
            "refreshed": goal_snapshot_refreshed,
            "active_goal_count": active_goal_count_after,
            "goals": [_compact_goal_for_scan(goal) for goal in active_goals_after],
        },
        "runtime_pressure": {
            "min_active_goals": min_active_goals,
            "min_active_tasks": min_active_tasks,
            "production_focus": focus,
            "max_active_tasks": max_active_tasks,
            "active_task_count_before": active_task_count_before,
            "active_task_count_after": active_task_count_after,
            "active_task_count_source": active_task_count_source,
            "active_goal_count_after": len(active_goals_after),
            "dispatch_budget": task_limit,
            "dispatch_headroom": dispatch_headroom,
        },
        "step_metrics": {
            "budget_ms": budget_ms,
            "duration_ms": _elapsed_ms(started_at),
            "task_limit": task_limit,
            "goal_scan_limit": goal_scan_limit,
            "scanned_goal_count": scanned_goals,
            "dispatch_count": dispatch_count,
            "budget_exhausted": _budget_exhausted(started_at, budget_ms),
            "init_metrics": init_metrics,
        },
    }
    _save_json(LOOP_STATE, state)
    _save_json(_brain_loop_latest_path(), state)
    _write_soak_state(actions)
    return state

def run_once(policy_schedule: dict | None = None) -> dict:
    approval = load_policy()
    kernel = rebuild()
    control = _load_control_center_state()
    actions = []
    goal_backlog: dict[str, Any] = {"status": "cached"}
    sync_status = sync_goal_runtime()
    actions.append(
        {
            "phase": "goal-runtime-sync",
            "status": sync_status.get("status"),
            "updated": sync_status.get("updated", 0),
            "active_goal_count": sync_status.get("active_goal_count", 0),
        }
    )
    goal_audit = run_goal_storage_audit()
    actions.append(
        {
            "phase": "goal-storage-audit",
            "status": goal_audit.get("status"),
            "stored_successfully": goal_audit.get("stored_successfully"),
            "issues": goal_audit.get("issues", []),
            "active_task_count": ((goal_audit.get("task_queue") or {}).get("active_task_count", 0)),
        }
    )
    goals = list_goals()
    schedule = policy_schedule or {}
    focus = write_production_focus_status(schedule)
    kernel_mode = schedule.get("kernel_mode") or load_kernel_mode()
    governance_enabled = is_component_enabled("governance", kernel_mode) and not focus.get(
        "single_product_mode"
    )
    experiment_enabled = (
        bool(schedule.get("run_experiments", True))
        and is_component_enabled("experiments", kernel_mode)
        and not focus.get("single_product_mode")
    )
    capability_building_enabled = (
        bool(schedule.get("run_capability_building", True))
        and is_component_enabled("platform_generation", kernel_mode)
        and not focus.get("single_product_mode")
    )
    allow_goal_generation = bool(schedule.get("allow_goal_generation", True)) or focus.get(
        "single_product_mode"
    )
    global_policy = (
        run_global_policy()
        if governance_enabled and bool(schedule.get("run_global_policy", True))
        else {
            "focus_capabilities": [],
            "worker_bias_policy": {},
            "organization_priority": {"departments": []},
        }
    )
    task_snapshot = [] if focus.get("single_product_mode") else _load_json(TASKS, [])
    if focus.get("single_product_mode"):
        focus_goal_ids_before = {
            str(goal.get("goal_id") or "")
            for goal in goals
            if goal.get("status") in {"pending", "planned", "running"}
            and goal_matches_focus(goal, focus)
        }
        scoped_task_snapshot = [
            task
            for task in task_snapshot
            if str(task.get("goal_id") or "") in focus_goal_ids_before
        ]
        active_task_count_before = _active_task_count(scoped_task_snapshot)
    else:
        active_task_count_before = _active_task_count(task_snapshot)
    min_active_goals = (
        1
        if focus.get("single_product_mode")
        else int(schedule.get("min_active_goals") or DEFAULT_MIN_ACTIVE_GOALS)
    )
    min_active_tasks = (
        1
        if focus.get("single_product_mode")
        else int(schedule.get("min_active_tasks") or DEFAULT_MIN_ACTIVE_TASKS)
    )
    max_active_tasks = (
        min(2, int(schedule.get("max_active_tasks") or DEFAULT_MAX_ACTIVE_TASKS))
        if focus.get("single_product_mode")
        else int(schedule.get("max_active_tasks") or DEFAULT_MAX_ACTIVE_TASKS)
    )
    dispatch_headroom = max(0, max_active_tasks - active_task_count_before)
    pressure_gap = max(0, min_active_tasks - active_task_count_before)
    runtime_dispatch_limit = (
        1 if focus.get("single_product_mode") else int(schedule.get("runtime_dispatch_limit") or 3)
    )
    runtime_dispatch_limit = max(runtime_dispatch_limit, pressure_gap)
    runtime_dispatch_limit = (
        min(runtime_dispatch_limit, dispatch_headroom) if dispatch_headroom else 0
    )
    ai_testing = load_ai_test_status()
    merge_ready = merge_ready_patch_ids()
    if merge_ready:
        merged = auto_merge_ready_submissions()
        actions.append(
            {
                "phase": "auto-merge-ready-patches",
                "merged_count": merged.get("merged_count", 0),
                "merged": merged.get("merged", []),
            }
        )
    coordination = (
        _ensure_cross_project_goal(goals, actions, allow_goal_generation)
        if governance_enabled
        else None
    )
    if coordination is not None:
        actions.append(
            {
                "phase": "cross-project-coordination-sweep",
                "candidate_count": coordination.get("candidate_count", 0),
                "selected_targets": [
                    item.get("target") for item in (coordination.get("selected") or [])[:3]
                ],
            }
        )
    pressure_seed = (
        {"created": 0, "attempted": 0, "reason": "single-product-mode"}
        if focus.get("single_product_mode")
        else _seed_goal_pressure(
            actions,
            allow_goal_generation=allow_goal_generation,
            min_active_goals=min_active_goals,
            max_iterations=max(1, min_active_goals),
        )
    )
    if pressure_seed.get("attempted"):
        actions.append(
            {
                "phase": "task-pressure-summary",
                "created": pressure_seed.get("created"),
                "attempted": pressure_seed.get("attempted"),
                "reason": pressure_seed.get("reason"),
                "final_active_goals": pressure_seed.get("final_active_goals"),
            }
        )
    task_engine = run_factory_task_engine(schedule)
    actions.append(
        {
            "phase": "production-focus",
            "enabled": focus.get("enabled"),
            "single_product_mode": focus.get("single_product_mode"),
            "primary_target": focus.get("primary_target"),
            "primary_artifact_id": focus.get("primary_artifact_id"),
            "reason": focus.get("reason"),
        }
    )
    actions.append(
        {
            "phase": "factory-task-engine",
            "status": task_engine.get("status"),
            "seeded_goals": [
                item.get("target") for item in (task_engine.get("seeded_goals") or [])
            ],
            "repaired_graphs": len(task_engine.get("repaired_graphs") or []),
            "ready_node_count": (
                (task_engine.get("supply_after_seed") or {}).get("ready_node_count")
            ),
            "active_task_count": (
                (task_engine.get("supply_after_seed") or {}).get("active_task_count")
            ),
        }
    )
    github_cycle = (
        _run_github_learning_cycle(actions)
        if bool(schedule.get("run_github_learning", True))
        and is_component_enabled("github_learning", kernel_mode)
        and not focus.get("single_product_mode")
        else {"status": "skipped", "reason": "lean_execution"}
    )
    github_status_payload = (
        github_cycle.get("status") if isinstance(github_cycle.get("status"), dict) else {}
    )
    experiment_cycle = (
        _run_experiment_cycle(actions)
        if experiment_enabled
        else {"status": "skipped", "reason": "resource-budget"}
    )
    if ai_testing.get("status") in {"degraded", "attention"}:
        actions.append(
            {
                "phase": "ai-testing-attention",
                "status": ai_testing.get("status"),
                "pass_rate": ai_testing.get("pass_rate"),
                "error_count": ai_testing.get("error_count"),
                "failing_case_ids": (ai_testing.get("failing_case_ids") or [])[:5],
            }
        )
    if not experiment_enabled:
        actions.append({"phase": "experiment-budget-hold", "reason": "resource-budget"})

    platform_generation_allowed, platform_reason = allow_platform_generation()
    generated_platforms = (
        generate_pending_platforms()
        if platform_generation_allowed and capability_building_enabled
        else []
    )
    if not platform_generation_allowed:
        actions.append(
            {"phase": "guard-throttle", "reason": platform_reason, "target": "platform-generation"}
        )
    elif not capability_building_enabled:
        actions.append(
            {
                "phase": "policy-throttle",
                "reason": "resource-budget",
                "target": "platform-generation",
            }
        )
    for platform in generated_platforms:
        goal_id = platform.get("goal_id")
        if not goal_id:
            continue
        update_goal(
            goal_id,
            platform_generated=True,
            platform_id=platform.get("platform_id"),
            platform_workspace=platform.get("workspace"),
            platform_status=platform.get("status"),
        )
        actions.append(
            {
                "phase": "generate-platform",
                "goal_id": goal_id,
                "platform_id": platform.get("platform_id"),
                "workspace": platform.get("workspace"),
                "capabilities": [
                    item.get("capability_id") for item in platform.get("capabilities", [])
                ],
            }
        )

    goals = rank_goals()
    dispatch_budget_remaining = runtime_dispatch_limit
    dispatch_candidates: list[dict] = []
    for goal in goals:
        if focus.get("single_product_mode") and not goal_matches_focus(goal, focus):
            continue
        target_lower = (goal.get("target") or "").strip().lower()
        if (
            goal.get("platform_generated")
            and _healthy_platform(goal.get("platform_id"))
            and (
                goal.get("type") == "build_platform"
                or target_lower.startswith("build ")
                or target_lower.endswith("factory")
            )
        ):
            complete_tasks(
                goal.get("task_ids", []),
                "Goal auto-completed because the generated platform is present and healthy.",
            )
            if goal.get("graph_id"):
                graph = _load_graph(goal["graph_id"])
                if graph:
                    _complete_graph(graph)
            update_goal(
                goal["goal_id"],
                status="completed",
                notes=(
                    (goal.get("notes") or "") + " Auto-completed after healthy platform generation."
                ).strip(),
            )
            actions.append(
                {
                    "phase": "complete-generated-platform",
                    "goal_id": goal["goal_id"],
                    "platform_id": goal.get("platform_id"),
                    "platform_workspace": goal.get("platform_workspace"),
                }
            )
            continue
        if target_lower == "expand capability routing patterns" and _capability_count() >= 6:
            _complete_runtime_native_goal(
                goal,
                actions,
                "complete-capability-routing",
                "Goal auto-completed because capability routing patterns are already expanded and registered.",
                {"capability_count": _capability_count()},
            )
            update_goal(
                goal["goal_id"],
                notes=(
                    (goal.get("notes") or "")
                    + " Auto-completed after capability routing registry validation."
                ).strip(),
            )
            continue
        if goal.get("type") == "verify_platforms":
            sweep = run_sweep()
            _complete_runtime_native_goal(
                goal,
                actions,
                "verify-platforms",
                "Platform verification sweep completed by runtime-native sweep.",
                {
                    "quality_score": (sweep.get("control_layer") or {}).get("quality_score"),
                    "healthy_platforms": (sweep.get("summary") or {}).get("healthy_platforms"),
                    "platform_count": (sweep.get("summary") or {}).get("platform_count"),
                },
            )
            continue
        if target_lower == "repair abnormal toolchain health":
            maintenance = run_maintenance(mode="full")
            verification = run_verification()
            tool_health = run_tool_health_audit()
            if tool_health.get("status") == "pass":
                _complete_runtime_native_goal(
                    goal,
                    actions,
                    "repair-toolchain-health",
                    "Toolchain health repair completed by runtime-native maintenance and verification sweep.",
                    {
                        "maintenance_mode": maintenance.get("mode"),
                        "reconciled_tasks": (maintenance.get("tasks") or {}).get("reconciled", []),
                        "verification_status": verification.get("status"),
                        "tool_health_status": tool_health.get("status"),
                        "tool_health_issue_count": len(tool_health.get("issues", [])),
                    },
                )
            else:
                actions.append(
                    {
                        "phase": "repair-toolchain-health",
                        "goal_id": goal.get("goal_id"),
                        "target": goal.get("target"),
                        "verification_status": verification.get("status"),
                        "tool_health_status": tool_health.get("status"),
                        "tool_health_issues": tool_health.get("issues", []),
                    }
                )
            continue
        if target_lower == "experiment adopted-pattern rollout":
            run = run_experiment()
            evaluation = evaluate_experiment()
            distillation = distill_capabilities()
            refresh_github_capability_library()
            knowledge = rebuild_knowledge()
            _complete_runtime_native_goal(
                goal,
                actions,
                "experiment-pattern-rollout",
                "Goal auto-completed after adopted-pattern rollout experiment succeeded.",
                {
                    "run_status": run.get("status"),
                    "evaluation_score": evaluation.get("score"),
                    "adopt": evaluation.get("adopt"),
                    "distillation_status": distillation.get("status"),
                    "knowledge_patterns": len(knowledge.get("experiment_patterns", [])),
                },
            )
            continue
        if target_lower == "review patch queue and verification gates":
            verification_snapshot = _load_json(DATA / "verification_status.json", {})
            triage = auto_triage_patch_submissions(
                verification_passed=verification_snapshot.get("status") == "pass",
                verification_status=verification_snapshot.get("status", "attention"),
            )
            _complete_runtime_native_goal(
                goal,
                actions,
                "patch-queue-review",
                "Patch queue review and verification gate sweep completed by runtime-native ownership triage.",
                {
                    "auto_approved": len(triage.get("auto_approved", [])),
                    "ready_for_merge": len(triage.get("ready_for_merge", [])),
                    "proposed_count": (triage.get("summary") or {}).get("proposed_count", 0),
                    "approved_count": (triage.get("summary") or {}).get("approved_count", 0),
                },
            )
            continue

        if target_lower == "advance release train operations":
            release_ops = run_release_operations_status()
            release_train = run_release_train(
                runtime_ok=(release_ops.get("operations_readiness") or {}).get("runtime_ok", False),
                verification_ok=(release_ops.get("operations_readiness") or {}).get(
                    "verification_ok", False
                ),
                control_ok=(release_ops.get("operations_readiness") or {}).get("control_ok", False),
                blocked_patch_count=(release_ops.get("release_train") or {}).get(
                    "blocked_patch_count", 0
                ),
                experimental_ok=(
                    (release_ops.get("release_tiers") or {}).get("experimental") or {}
                ).get("status")
                == "ready",
            )
            _complete_runtime_native_goal(
                goal,
                actions,
                "release-train-advance",
                "Release train operations advanced by runtime-native release workflow.",
                {
                    "release_status": release_train.get("status"),
                    "ready_count": release_train.get("ready_count"),
                    "candidate_count": release_train.get("candidate_count"),
                    "promoted_to_ready": release_train.get("promoted_to_ready", []),
                },
            )
            continue

        if (
            target_lower == "coordinate cross-project integration surfaces"
            or target_lower.startswith("coordinate ")
        ):
            coordination_result = run_coordination(
                (coordination or {}).get("selected") or [], target=goal.get("target")
            )
            _complete_runtime_native_goal(
                goal,
                actions,
                "cross-project-coordination",
                "Cross-project coordination work packages completed by runtime-native coordination workflow.",
                {
                    "coordination_status": coordination_result.get("status"),
                    "completed_count": coordination_result.get("completed_count"),
                    "task_count": coordination_result.get("task_count"),
                },
            )
            continue

        if target_lower == "merge ready patch queue":
            merged = auto_merge_ready_submissions()
            _complete_runtime_native_goal(
                goal,
                actions,
                "patch-queue-merge",
                "Merge-ready patch queue completed by runtime-native merge closure.",
                {
                    "merged_count": merged.get("merged_count", 0),
                    "merged": merged.get("merged", []),
                    "ready_count": (merged.get("summary") or {}).get("ready_count", 0),
                },
            )
            continue
        if target_lower == "optimize task scheduler from agent experience":
            sweep = run_scheduler_optimization_sweep()
            _complete_runtime_native_goal(
                goal,
                actions,
                "optimize-scheduler",
                "Scheduler optimization sweep completed by runtime-native optimization pass.",
                {
                    "worker_count": sweep.get("worker_count"),
                    "recommendation": sweep.get("recommendation"),
                },
            )
            continue
        if target_lower == "improve cheap agent prompts":
            sweep = run_prompt_improvement_sweep()
            _complete_runtime_native_goal(
                goal,
                actions,
                "improve-cheap-prompts",
                "Prompt improvement sweep completed by runtime-native optimization pass.",
                {
                    "skill_count": sweep.get("skill_count"),
                    "replay_count": sweep.get("replay_count"),
                    "decision_pattern_count": sweep.get("decision_pattern_count"),
                },
            )
            continue
        if target_lower == "experiment capability routing heuristics":
            evaluation = experiment_cycle.get("evaluation") or {}
            _complete_runtime_native_goal(
                goal,
                actions,
                "experiment-routing-heuristics",
                "Capability routing heuristic experiment completed by runtime-native experiment cycle.",
                {"experiment_score": evaluation.get("score"), "adopt": evaluation.get("adopt")},
            )
            continue
        if target_lower == "experiment progress-first goal seeding":
            evaluation = experiment_cycle.get("evaluation") or {}
            _complete_runtime_native_goal(
                goal,
                actions,
                "experiment-goal-seeding",
                "Progress-first goal seeding experiment completed by runtime-native experiment cycle.",
                {"experiment_score": evaluation.get("score"), "adopt": evaluation.get("adopt")},
            )
            continue
        if target_lower == "experiment reviewer prompt specialization":
            evaluation = experiment_cycle.get("evaluation") or {}
            _complete_runtime_native_goal(
                goal,
                actions,
                "experiment-reviewer-specialization",
                "Reviewer prompt specialization experiment completed by runtime-native experiment cycle.",
                {"experiment_score": evaluation.get("score"), "adopt": evaluation.get("adopt")},
            )
            continue
        if target_lower == "experiment github repo capability extraction":
            evaluation = experiment_cycle.get("evaluation") or {}
            _complete_runtime_native_goal(
                goal,
                actions,
                "experiment-github-capability-extraction",
                "GitHub repository capability extraction completed by runtime-native learning cycle.",
                {
                    "experiment_score": evaluation.get("score"),
                    "adopt": evaluation.get("adopt"),
                    "ready_repo_count": github_status_payload.get("ready_repo_count", 0),
                    "learned_repository_count": (
                        (github_cycle.get("knowledge") or {}).get("repo_learning") or {}
                    ).get("learned_repository_count", 0),
                },
            )
            continue
        if not goal.get("graph_id"):
            graph = compile_goal(goal)
            update_goal(goal["goal_id"], graph_id=graph["graph_id"], status="planned")
            actions.append(
                {"phase": "compile-goal", "goal_id": goal["goal_id"], "graph_id": graph["graph_id"]}
            )
            goal = {**goal, "graph_id": graph["graph_id"], "status": "planned"}
        graph = _load_graph(goal["graph_id"])
        if not graph:
            continue
        graph_changed = _refresh_node_statuses(goal, graph)
        graph_changed = _auto_progress_engineering_graph(goal, graph, actions) or graph_changed
        if graph_changed:
            _save_graph(graph)
        if graph.get("status") == "completed":
            reflect_goal(
                goal["goal_id"],
                success=True,
                summary=f"Goal {goal.get('target')} completed after graph execution reached terminal success.",
            )
            actions.append({"phase": "complete-goal", "goal_id": goal["goal_id"]})
            continue
        if control.get("paused"):
            actions.append({"phase": "paused", "reason": "control-center-paused"})
            continue
        ready_nodes = _ready_nodes(graph)
        if ready_nodes:
            if _is_toyos_mainline_goal(goal):
                toyos_snapshot = _load_json(TASKS, [])
                active_toyos_task = _active_toyos_mainline_task(toyos_snapshot)
                if active_toyos_task:
                    actions.append({
                        "phase": "project-mainline-lock",
                        "goal_id": goal.get("goal_id"),
                        "target": goal.get("target"),
                        "reason": "active-mainline-task",
                        "active_task_id": active_toyos_task.get("id"),
                    })
                    continue
                ready_nodes = _select_project_ready_nodes(goal, ready_nodes)
            dispatch_candidates.append(
                {"goal": goal, "graph": graph, "ready_nodes": ready_nodes}
            )
        if any(node.get("task_id") for node in graph.get("nodes", [])):
            update_goal(
                goal["goal_id"],
                task_ids=[
                    node.get("task_id") for node in graph.get("nodes", []) if node.get("task_id")
                ],
                status="running" if graph.get("status") != "completed" else "completed",
            )

    if (
        not control.get("paused")
        and decide("dispatch_low_risk_goal_nodes").approved
        and dispatch_candidates
    ):
        kernel_snapshot = build_scheduling_snapshot(
            dispatch_candidates, dispatch_budget=dispatch_budget_remaining
        )
        actions.append(
            {
                "phase": "scheduling-kernel",
                "focus_mode": kernel_snapshot.get("focus_mode"),
                "focus_reason": kernel_snapshot.get("focus_reason"),
                "ready_count": ((kernel_snapshot.get("queues") or {}).get("ready", 0)),
                "running_count": ((kernel_snapshot.get("queues") or {}).get("running", 0)),
                "dispatchable_count": (
                    (kernel_snapshot.get("queues") or {}).get("dispatchable", 0)
                ),
            }
        )
        for item in kernel_snapshot.get("preemptions", []):
            actions.append(
                {
                    "phase": "preemption-recommended",
                    "running_task_id": item.get("running_task_id"),
                    "running_goal_id": item.get("running_goal_id"),
                    "incoming_goal_id": item.get("incoming_goal_id"),
                    "incoming_node_id": item.get("incoming_node_id"),
                    "reason": item.get("reason"),
                    "checkpoint_dir": item.get("checkpoint_dir"),
                }
            )

        graph_lookup = {
            (entry.get("goal", {}).get("goal_id"), entry.get("graph", {}).get("graph_id")): entry
            for entry in dispatch_candidates
        }
        for entry in kernel_snapshot.get("dispatch_order", []):
            if dispatch_budget_remaining <= 0:
                actions.append(
                    {
                        "phase": "dispatch-budget-hold",
                        "reason": "runtime-task-budget",
                        "goal_id": entry.get("goal_id"),
                    }
                )
                break
            candidate = graph_lookup.get((entry.get("goal_id"), entry.get("graph_id")))
            if not candidate:
                continue
            goal = candidate["goal"]
            graph = candidate["graph"]
            node = next(
                (item for item in graph.get("nodes", []) if item.get("id") == entry.get("node_id")),
                None,
            )
            if node is None or node.get("status") != "pending":
                continue
            task = _dispatch_node(
                goal,
                graph,
                node,
                selected=entry.get("selection") or {},
                kernel_entry={**entry, "focus_mode": kernel_snapshot.get("focus_mode")},
                auto_approve=should_auto_approve_task(
                    requested=False,
                    execution_mode=((entry.get("selection") or {}).get("execution_mode")),
                    scheduler_hint={
                        "factory_pool": goal.get("factory_pool"),
                        "execution_mode": ((entry.get("selection") or {}).get("execution_mode")),
                        "execution_lane": ((entry.get("selection") or {}).get("execution_lane")),
                        "scheduled_by": "runtime.scheduler",
                    },
                    scheduled_by="runtime.scheduler",
                ),
            )
            if task.get("status") == "patch-required":
                actions.append(
                    {
                        "phase": "patch-submission",
                        "goal_id": goal["goal_id"],
                        "node_id": node["id"],
                        "patch_id": ((task.get("patch_submission") or {}).get("patch_id")),
                    }
                )
                _save_graph(graph)
                continue
            if task.get("status") == "dispatch-error":
                actions.append(
                    {
                        "phase": "dispatch-error",
                        "goal_id": goal["goal_id"],
                        "node_id": node["id"],
                        "error_type": task.get("error_type"),
                        "error": task.get("error"),
                    }
                )
                _save_graph(graph)
                continue
            actions.append(
                {
                    "phase": "dispatch-node",
                    "goal_id": goal["goal_id"],
                    "node_id": node["id"],
                    "task_id": task.get("id"),
                    "effective_priority": entry.get("effective_priority"),
                    "timeslice_seconds": entry.get("timeslice_seconds"),
                    "reason": entry.get("reason"),
                }
            )
            dispatch_budget_remaining -= 1
            _save_graph(graph)

    for entry in dispatch_candidates:
        goal = entry.get("goal") or {}
        graph = entry.get("graph") or {}
        if any(node.get("task_id") for node in graph.get("nodes", [])):
            update_goal(
                goal["goal_id"],
                task_ids=[
                    node.get("task_id") for node in graph.get("nodes", []) if node.get("task_id")
                ],
                status="running" if graph.get("status") != "completed" else "completed",
            )

    active_goals_after = [
        item for item in list_goals() if item.get("status") in {"pending", "planned", "running"}
    ]
    task_snapshot_after = _load_json(TASKS, [])
    active_task_count_after = _active_task_count(task_snapshot_after)
    task_state_counts_after = _task_state_counts(task_snapshot_after)
    if (
        not focus.get("single_product_mode")
        and not control.get("paused")
        and (
            len(active_goals_after) < min_active_goals or active_task_count_after < min_active_tasks
        )
        and allow_goal_generation
    ):
        decision = decide_next_goal()
        actions.append(
            {
                "phase": "decision-engine",
                "action": decision.get("action"),
                "reason": decision.get("reason"),
                "selected": decision.get("selected"),
                "active_goals": len(active_goals_after),
                "active_tasks": active_task_count_after,
                "min_active_goals": min_active_goals,
                "min_active_tasks": min_active_tasks,
            }
        )
    elif (
        not focus.get("single_product_mode")
        and not control.get("paused")
        and (
            len(active_goals_after) < min_active_goals or active_task_count_after < min_active_tasks
        )
        and not allow_goal_generation
    ):
        actions.append({"phase": "goal-generation-budget-hold", "reason": "runtime-task-budget"})

    core_messages = _load_json(DATA / "core_messages.json", [])
    if decide("resolve_warning_escalations").approved:
        changed_messages = False
        for message in core_messages:
            if message.get("status", "open") != "open" or message.get("severity") != "warning":
                continue
            message["status"] = "auto-resolved"
            message["resolved_at"] = _utc()
            message["resolution"] = (
                "Auto-resolved by brain loop under resolve_warning_escalations policy."
            )
            changed_messages = True
            actions.append(
                {
                    "phase": "auto-resolve-escalation",
                    "message_id": message.get("id"),
                    "severity": message.get("severity"),
                }
            )
        if changed_messages:
            _save_json(DATA / "core_messages.json", core_messages)

    memory = rebuild_memory(actions)
    state = {
        "updated_at": _utc(),
        "control_center": {"paused": control.get("paused"), "status": control.get("status")},
        "approval_policy": approval,
        "actions": actions,
        "context_kernel": kernel,
        "memory_kernel": memory,
        "global_policy": global_policy,
        "task_engine": task_engine,
        "goal_backlog": goal_backlog,
        "github_learning": {
            "candidate_count": (github_cycle.get("scan") or {}).get("candidate_count"),
            "clone_status": (github_cycle.get("clone") or {}).get("status"),
            "ready_repo_count": github_status_payload.get("ready_repo_count"),
            "learned_repository_count": (
                (github_cycle.get("knowledge") or {}).get("repo_learning") or {}
            ).get("learned_repository_count"),
        },
        "experiment_cycle": {
            "selected": ((experiment_cycle.get("plan") or {}).get("selected") or {}).get("target"),
            "run_status": (experiment_cycle.get("run") or {}).get("status"),
            "evaluation_score": (experiment_cycle.get("evaluation") or {}).get("score"),
            "adopt": (experiment_cycle.get("evaluation") or {}).get("adopt"),
        },
        "ai_testing": ai_testing,
        "goal_storage": goal_audit,
        "runtime_pressure": {
            "min_active_goals": min_active_goals,
            "min_active_tasks": min_active_tasks,
            "production_focus": focus,
            "max_active_tasks": max_active_tasks,
            "active_task_count_before": active_task_count_before,
            "active_task_count_after": active_task_count_after,
            "active_task_count_including_finishing": task_state_counts_after.get("true_running", 0) + task_state_counts_after.get("execution_finishing", 0),
            "active_goal_count_after": len(active_goals_after),
            "dispatch_budget": runtime_dispatch_limit,
            "dispatch_headroom": dispatch_headroom,
            "true_running_task_count": task_state_counts_after.get("true_running", 0),
            "execution_finishing_task_count": task_state_counts_after.get("execution_finishing", 0),
            "recovery_running_task_count": task_state_counts_after.get("recovery_running", 0),
            "mainline_running_task_count": task_state_counts_after.get("mainline_running", 0),
            "blocked_task_count": task_state_counts_after.get("blocked", 0),
        },
    }
    _save_json(LOOP_STATE, state)
    _save_json(_brain_loop_latest_path(), state)
    _write_soak_state(actions)
    return state


if __name__ == "__main__":
    print(json.dumps(run_once(), ensure_ascii=False, indent=2))
