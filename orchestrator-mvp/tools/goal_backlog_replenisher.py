from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.goal_registry import create_goal, list_goals, update_goal
from tools.io_utils import atomic_write_json
from tools.production_focus import build_production_focus, goal_matches_focus
from tools.taskgraph_compiler import compile_goal

DATA = ROOT / "data"
GOAL_BACKLOG_STATUS_PATH = DATA / "goal_backlog_status.json"
TOYOS_TEMPLATE_PATH = DATA / "toyos_task_templates.json"
TASKS_PATH = DATA / "tasks.json"
GRAPHS_PATH = ROOT / "factory" / "graphs"
GRAPHS_FALLBACK_PATH = DATA / "graphs"
INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"

TRUE_RUNNING_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
EXECUTION_FINISHING_STATUSES = {"execution_finished"}
ACTIVE_STATUSES = TRUE_RUNNING_STATUSES | EXECUTION_FINISHING_STATUSES
PENDING_STATUSES = {"queued", "waiting_approval"}
TARGET_ACTIVE = 2
TARGET_PENDING = 5
MIN_ACTIVE = 1
MIN_PENDING = 3
P2_TASK_TYPES = {"new_artifact_bootstrap", "new_demo_creation", "architecture_migration", "subsystem_refactor", "technical_artifact"}
P3_TASK_TYPES = {"exploration_intake"}


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


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_toyos_goal(goal: dict[str, Any] | None) -> bool:
    goal = goal or {}
    corpus = " ".join(
        str(part or "")
        for part in [
            goal.get("target"),
            goal.get("notes"),
            goal.get("primary_artifact_id"),
            goal.get("repo_path"),
            " ".join(str(item) for item in (goal.get("tags") or []) if item),
        ]
    ).lower()
    return any(marker in corpus for marker in ("toyos", "toy-os", "generated/toy-os-demo"))


def _is_toyos_task(task: dict[str, Any] | None) -> bool:
    task = task or {}
    hint = task.get("scheduler_hint") or {}
    corpus = " ".join(
        str(part or "")
        for part in [
            task.get("title"),
            task.get("goal"),
            task.get("prompt"),
            task.get("repo_path"),
            hint.get("goal_target"),
            hint.get("node_title"),
        ]
    ).lower()
    return any(marker in corpus for marker in ("toyos", "toy-os", "generated/toy-os-demo"))


def _load_templates() -> dict[str, Any]:
    payload = _load_json(TOYOS_TEMPLATE_PATH, {})
    if isinstance(payload, dict) and payload.get("restore_toyos_delivery"):
        return payload["restore_toyos_delivery"]
    raise FileNotFoundError(f"Missing ToyOS template library: {TOYOS_TEMPLATE_PATH}")


def _industrial_operations_snapshot() -> dict[str, Any]:
    payload = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    return payload if isinstance(payload, dict) else {}


def _budget_gate_allows(pool: str) -> bool:
    pool = str(pool or "").strip().upper()
    if pool not in {"P2", "P3"}:
        return True
    operations = _industrial_operations_snapshot()
    gates = (operations.get("budget_control") or {}).get("gates") or {}
    if pool == "P2" and isinstance(gates, dict) and gates.get("allow_p2") is False:
        return False
    if pool == "P3" and isinstance(gates, dict) and gates.get("allow_p3") is False:
        return False
    return True


def _active_counts(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_goal: dict[str, dict[str, int]] = {}
    active = 0
    active_including_finishing = 0
    execution_finishing = 0
    pending = 0
    blocked = 0
    for task in tasks:
        if not _is_toyos_task(task):
            continue
        goal_id = str(task.get("goal_id") or task.get("scheduler_hint", {}).get("goal_id") or "unknown")
        bucket = by_goal.setdefault(goal_id, {"active": 0, "execution_finishing": 0, "pending": 0, "blocked": 0, "total": 0})
        bucket["total"] += 1
        status = str(task.get("status") or "").strip().lower()
        if status in TRUE_RUNNING_STATUSES:
            bucket["active"] += 1
            active += 1
            active_including_finishing += 1
        elif status in EXECUTION_FINISHING_STATUSES:
            bucket["execution_finishing"] += 1
            execution_finishing += 1
            active_including_finishing += 1
        if status in PENDING_STATUSES:
            bucket["pending"] += 1
            pending += 1
        if status in {"blocked", "failed", "timed_out", "cancelled", "verification_failed"}:
            bucket["blocked"] += 1
            blocked += 1
    return {
        "active": active,
        "active_including_finishing": active_including_finishing,
        "execution_finishing": execution_finishing,
        "pending": pending,
        "blocked": blocked,
        "by_goal": by_goal,
    }


def _live_goal_counts(goal_id: str | None = None) -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    counts = _active_counts(tasks)
    by_goal = counts.get("by_goal") or {}
    goal_key = str(goal_id or "").strip()
    goal_counts = dict(by_goal.get(goal_key) or {"active": 0, "pending": 0, "total": 0})
    if not goal_key and by_goal:
        # When the caller has no explicit goal id, prefer the most active ToyOS goal.
        goal_key = max(
            by_goal.items(),
            key=lambda item: (int(item[1].get("active") or 0), int(item[1].get("pending") or 0), str(item[0] or "")),
        )[0]
        goal_counts = dict(by_goal.get(goal_key) or goal_counts)
    goal_counts["goal_id"] = goal_key or goal_id or ""
    goal_counts["active"] = int(goal_counts.get("active") or 0)
    goal_counts["pending"] = int(goal_counts.get("pending") or 0)
    goal_counts["total"] = int(goal_counts.get("total") or 0)
    goal_counts["by_goal"] = by_goal
    goal_counts["aggregate_active"] = int(counts.get("active") or 0)
    goal_counts["aggregate_active_including_finishing"] = int(counts.get("active_including_finishing") or 0)
    goal_counts["aggregate_execution_finishing"] = int(counts.get("execution_finishing") or 0)
    goal_counts["aggregate_pending"] = int(counts.get("pending") or 0)
    goal_counts["active_including_finishing"] = int(goal_counts.get("active_including_finishing") or 0)
    goal_counts["execution_finishing"] = int(goal_counts.get("execution_finishing") or 0)
    return goal_counts


def _backlog_health(active_count: int, pending_count: int, *, min_active: int, min_pending: int, desired_active: int, desired_pending: int) -> str:
    if active_count <= 0:
        return "starved"
    if active_count >= desired_active and pending_count >= desired_pending:
        return "healthy"
    if active_count >= min_active:
        return "degraded"
    return "starved"


def _ready_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    completed = {
        str(node.get("id") or "")
        for node in graph.get("nodes", []) or []
        if str(node.get("status") or "").strip().lower() == "completed"
    }
    ready: list[dict[str, Any]] = []
    for node in graph.get("nodes", []) or []:
        if str(node.get("status") or "").strip().lower() != "pending":
            continue
        deps = {str(dep or "") for dep in (node.get("dependencies") or [])}
        if deps.issubset(completed):
            ready.append(node)
    return ready


def _goal_graph(goal: dict[str, Any]) -> dict[str, Any]:
    graph_id = str(goal.get("graph_id") or "").strip()
    if graph_id:
        graph = _load_json(GRAPHS_PATH / f"{graph_id}.json", {})
        if graph:
            return graph
        graph = _load_json(GRAPHS_FALLBACK_PATH / f"{graph_id}.json", {})
        if graph:
            return graph
    graph = compile_goal(goal)
    if goal.get("goal_id"):
        update_goal(goal["goal_id"], graph_id=graph.get("graph_id"), status="planned")
    return graph


def _budget_pool_for_task(task_type: str, queue_name: str, *, dispatch_now: bool) -> str:
    if queue_name == "exploration" or task_type in P3_TASK_TYPES:
        return "P3"
    if task_type in P2_TASK_TYPES:
        return "P2"
    if dispatch_now:
        return "P0"
    return "P1"


def _select_goal(goals: list[dict[str, Any]], focus: dict[str, Any]) -> dict[str, Any] | None:
    matches = [
        goal
        for goal in goals
        if str(goal.get("status") or "").strip().lower() in {"pending", "planned", "running"}
        and goal_matches_focus(goal, focus)
    ]
    matches.sort(
        key=lambda item: (_parse_time(item.get("updated_at") or item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), str(item.get("goal_id") or "")),
        reverse=True,
    )
    if matches:
        return matches[0]
    if not focus.get("single_product_mode"):
        return None
    template = dict(focus.get("goal_template") or {})
    if not template:
        return None
    return create_goal(
        template.get("target") or "Restore ToyOS real artifact delivery",
        goal_type=str(template.get("goal_type") or "build_product"),
        notes=str(template.get("notes") or "ToyOS priority replenishment goal."),
        lane="mainline",
        assigned_department=str(template.get("assigned_department") or "engineering_department"),
        repo_path=template.get("repo_path"),
        primary_artifact_id=template.get("primary_artifact_id") or "toy-os-demo",
        factory_pool="production",
        factory_priority="P0",
        priority_class="runtime",
        release_tier="mainline",
        goal_class="artifact-delivery",
        tags=["toyos", "priority", "replenishment"],
    )


def _template_payload(goal: dict[str, Any], graph: dict[str, Any], template: dict[str, Any], *, dispatch_now: bool, node: dict[str, Any] | None = None) -> dict[str, Any]:
    focus = build_production_focus()
    repo_path = goal.get("repo_path") or (focus.get("goal_template") or {}).get("repo_path") or str(ROOT.parent)
    node = node or {}
    queue_name = str(template.get("queue_name") or "fastlane").strip().lower()
    task_type = str(template.get("task_type") or "report_refresh").strip().lower()
    node_kind = str(template.get("node_kind") or node.get("kind") or "").strip().lower()
    prompt = str(node.get("prompt") or template.get("prompt") or goal.get("notes") or goal.get("target") or "Restore ToyOS real artifact delivery")
    title = str(node.get("title") or template.get("title") or template.get("id") or "ToyOS priority task")
    verification_level = str(template.get("verification_level") or "L1").strip().upper()
    max_runtime_seconds = int(template.get("max_runtime_seconds") or 1200)
    retry_limit = int(template.get("retry_limit") or 1)
    rollback_rule = str(template.get("rollback_rule") or "mark_failed_and_requeue_split")
    graph_id = str(graph.get("graph_id") or goal.get("graph_id") or "").strip()
    node_id = str(node.get("id") or template.get("id") or "").strip()
    template_id = str(template.get("id") or node_id or "").strip()
    artifact_id = str(template.get("artifact_id") or "").strip()
    if not artifact_id:
        if graph_id and node_id:
            artifact_id = f"{graph_id}:{node_id}"
        elif goal.get("goal_id") and template_id:
            artifact_id = f"{goal.get('goal_id')}:{template_id}"
        else:
            artifact_id = template_id or goal.get("goal_id") or "toyos-task"
    required_artifacts: list[str]
    if task_type == "build_fix" or node_kind == "artifact-build":
        required_artifacts = [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/artifact_manifest.json",
            "generated/toy-os-demo/artifact.sha256",
        ]
    elif task_type in {"qemu_smoke_run", "harness_regression_run"} or node_kind == "artifact-test":
        required_artifacts = [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/artifact_manifest.json",
            "generated/toy-os-demo/artifact.sha256",
            "generated/toy-os-demo/score-report.json",
        ]
    elif task_type in {"artifact_audit", "report_refresh", "doc_patch", "harness_case_add"}:
        required_artifacts = [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/score-report.json",
            "generated/toy-os-demo/artifact_manifest.json",
            "generated/toy-os-demo/artifact.sha256",
        ]
    else:
        required_artifacts = [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
            "generated/toy-os-demo/artifact_manifest.json",
        ]
    return {
        "prompt": prompt,
        "title": title,
        "repo_path": repo_path,
        "goal": goal.get("target") or "Restore ToyOS real artifact delivery",
        "goal_id": goal.get("goal_id"),
        "graph_id": graph.get("graph_id"),
        "node_id": node_id,
        "scheduled_by": "factory-daemon.replenisher",
        "caller": "goal-backlog-replenisher",
        "auto_approve": bool(dispatch_now),
        "context_mode": "lean",
        "allow_resource_scan": True,
        "allow_repo_status": True,
        "preferred_worker": "docker" if queue_name in {"build_test", "regression", "incubation"} else "coder",
        "scheduler_hint": {
            "goal_primary": "Restore ToyOS real artifact delivery",
            "goal_mode": "toyos_priority_mode",
            "goal_target": goal.get("target") or "Restore ToyOS real artifact delivery",
            "goal_id": goal.get("goal_id"),
            "graph_id": graph.get("graph_id"),
            "node_id": node_id,
            "node_title": title,
            "task_type": task_type,
            "queue_name": queue_name,
            "verification_level": verification_level,
            "max_runtime_seconds": max_runtime_seconds,
            "retry_limit": retry_limit,
            "rollback_rule": rollback_rule,
            "template_id": template_id,
            "admission_mode": template.get("admission_mode") or ("normal" if dispatch_now else "degraded"),
            "budget_pool": _budget_pool_for_task(task_type, queue_name, dispatch_now=dispatch_now),
        },
        "execution_mode": "production" if queue_name != "fastlane" else "governance",
        "execution_lane": "host-control",
        "task_type": task_type,
        "queue_name": queue_name,
        "verification_level": verification_level,
        "max_runtime_seconds": max_runtime_seconds,
        "retry_limit": retry_limit,
        "rollback_rule": rollback_rule,
        "artifact_spec": {
            "artifact_id": artifact_id,
            "artifact_type": "artifact",
            "type": "artifact",
            "output": "generated/toy-os-demo",
            "deliverables": [],
            "expected_outputs": [],
            "required_artifacts": required_artifacts,
            "evidence": [item for item in required_artifacts if item.endswith((".json", ".log", ".txt"))],
            "verification": {},
            "registry": "artifact_registry",
            "min_fresh_artifacts": max(1, min(len(required_artifacts), 3)),
        },
    }


def build_goal_backlog_plan(schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    schedule = schedule or {}
    focus = build_production_focus(schedule)
    goals = list_goals()
    tasks = _load_json(TASKS_PATH, [])
    focus_goal = _select_goal(goals, focus)
    previous = _load_json(GOAL_BACKLOG_STATUS_PATH, {})
    plan: dict[str, Any] = {
        "updated_at": _utc(),
        "goal_primary": str(focus.get("primary_target") or "Restore ToyOS real artifact delivery"),
        "goal_mode": str(focus.get("reason") or "toyos_priority_mode"),
        "goal_health": "idle",
        "compiled_task_types": [],
        "compiled_template_ids": [],
        "pending_tasks_by_goal": {},
        "active_tasks_by_goal": {},
        "execution_finishing_tasks_by_goal": {},
        "last_replenished_at": previous.get("last_replenished_at"),
        "last_replenishment_result": previous.get("last_replenishment_result"),
        "replenishment_block_reason": previous.get("replenishment_block_reason") or "",
        "starvation_seconds": previous.get("starvation_seconds"),
        "goal_id": None,
        "graph_id": None,
        "dispatch_candidates": [],
        "dispatch_now_count": 0,
        "pending_candidate_count": 0,
        "active_candidate_count": 0,
        "desired_active_tasks": int(previous.get("desired_active_tasks") or TARGET_ACTIVE),
        "desired_pending_tasks": int(previous.get("desired_pending_tasks") or TARGET_PENDING),
        "minimum_active_tasks": int(previous.get("minimum_active_tasks") or MIN_ACTIVE),
        "minimum_pending_tasks": int(previous.get("minimum_pending_tasks") or MIN_PENDING),
        "failure_streak": int(previous.get("failure_streak") or 0),
        "control_alert_required": bool(previous.get("control_alert_required")),
    }
    if not focus_goal:
        plan["goal_health"] = "missing_goal"
        plan["last_replenishment_result"] = "replenishment_failed"
        plan["replenishment_block_reason"] = "no_focus_goal_available"
        _save_json(GOAL_BACKLOG_STATUS_PATH, plan)
        return plan
    graph = _goal_graph(focus_goal)
    counts = _active_counts(tasks)
    active_count = int(counts.get("active") or 0)
    active_including_finishing = int(counts.get("active_including_finishing") or 0)
    execution_finishing_count = int(counts.get("execution_finishing") or 0)
    pending_count = int(counts.get("pending") or 0)
    ready_nodes = _ready_nodes(graph)
    library = _load_templates()
    normal_templates = list(library.get("templates") or [])
    degraded_templates = list(library.get("degraded_templates") or [])
    desired_active = int(library.get("desired_active_tasks") or TARGET_ACTIVE)
    desired_pending = int(library.get("desired_pending_tasks") or TARGET_PENDING)
    dispatch_now_target = max(0, desired_active - active_count)
    backlog_target = max(0, desired_pending - pending_count)
    candidates: list[dict[str, Any]] = []
    budget_suppressed_candidates = 0
    active_needed = dispatch_now_target
    pending_needed = backlog_target
    recovery_priority = active_count <= MIN_ACTIVE or pending_count < MIN_PENDING

    active_template_pools = [list(normal_templates), list(degraded_templates)]
    pending_template_pools = (
        [list(degraded_templates), list(normal_templates)]
        if recovery_priority
        else [list(normal_templates), list(degraded_templates)]
    )

    used_template_ids: set[str] = set()

    for pool in active_template_pools:
        for index, template in enumerate(pool):
            if active_needed <= 0:
                break
            template_id = str(template.get("id") or "").strip()
            if template_id and template_id in used_template_ids:
                continue
            node = ready_nodes[index] if index < len(ready_nodes) else None
            candidate = _template_payload(focus_goal, graph, template, dispatch_now=True, node=node)
            if not _budget_gate_allows(str(candidate.get("scheduler_hint", {}).get("budget_pool") or "")):
                budget_suppressed_candidates += 1
                continue
            candidate["dispatch_now"] = True
            candidate["admission_mode"] = template.get("admission_mode") or "normal"
            candidates.append(candidate)
            if template_id:
                used_template_ids.add(template_id)
            active_needed -= 1
        if active_needed <= 0:
            break

    if pending_needed > 0:
        for pool in pending_template_pools:
            for template in pool:
                if pending_needed <= 0:
                    break
                template_id = str(template.get("id") or "").strip()
                if template_id and template_id in used_template_ids:
                    continue
                candidate = _template_payload(focus_goal, graph, template, dispatch_now=False)
                if not _budget_gate_allows(str(candidate.get("scheduler_hint", {}).get("budget_pool") or "")):
                    budget_suppressed_candidates += 1
                    continue
                candidate["dispatch_now"] = False
                candidate["admission_mode"] = "degraded"
                candidates.append(candidate)
                if template_id:
                    used_template_ids.add(template_id)
                pending_needed -= 1
            if pending_needed <= 0:
                break
    goal_id = str(focus_goal.get("goal_id") or "")
    plan.update(
        {
            "updated_at": _utc(),
            "goal_health": _backlog_health(
                active_count,
                pending_count,
                min_active=MIN_ACTIVE,
                min_pending=MIN_PENDING,
                desired_active=desired_active,
                desired_pending=desired_pending,
            ),
            "compiled_task_types": [str(item.get("task_type") or "") for item in candidates],
            "compiled_template_ids": [str(item.get("scheduler_hint", {}).get("template_id") or "") for item in candidates],
            "pending_tasks_by_goal": {goal_id: max(0, backlog_target - len([item for item in candidates if not item.get("dispatch_now")]))},
            "active_tasks_by_goal": {goal_id: active_count},
            "execution_finishing_tasks_by_goal": {goal_id: execution_finishing_count},
            "goal_id": goal_id,
            "graph_id": graph.get("graph_id"),
            "dispatch_candidates": candidates,
            "dispatch_now_count": len([item for item in candidates if item.get("dispatch_now")]),
            "pending_candidate_count": max(0, len(candidates) - len([item for item in candidates if item.get("dispatch_now")])),
            "active_candidate_count": len([item for item in candidates if item.get("dispatch_now")]),
            "budget_suppressed_candidate_count": budget_suppressed_candidates,
            "desired_active_tasks": desired_active,
            "desired_pending_tasks": desired_pending,
            "active_including_finishing": active_including_finishing,
            "true_running_tasks": active_count,
            "execution_finishing_tasks": execution_finishing_count,
            "ready_node_count": len(ready_nodes),
            "blocked_node_count": len([node for node in graph.get("nodes", []) or [] if str(node.get("status") or "").strip().lower() == "blocked"]),
        }
    )
    if not candidates:
        plan["goal_health"] = "starved"
        plan["last_replenishment_result"] = "replenishment_failed"
        if not ready_nodes:
            blocked_nodes = [node for node in graph.get("nodes", []) or [] if str(node.get("status") or "").strip().lower() == "blocked"]
            plan["replenishment_block_reason"] = "dispatch_precheck_failed:blocked_graph" if blocked_nodes else "dispatch_precheck_failed:no_ready_nodes"
        elif budget_suppressed_candidates > 0:
            plan["replenishment_block_reason"] = "dispatch_precheck_failed:budget_gate_closed"
        else:
            plan["replenishment_block_reason"] = "no_dispatch_candidates"
        plan["failure_streak"] = int(previous.get("failure_streak") or 0) + 1
        if plan["failure_streak"] >= 3:
            plan["control_alert_required"] = True
    plan["starvation_seconds"] = max(
        0,
        int((datetime.now(timezone.utc) - (_parse_time(previous.get("last_replenished_at")) or _parse_time(focus_goal.get("updated_at")) or _parse_time(focus_goal.get("created_at")) or datetime.now(timezone.utc))).total_seconds()),
    )
    _save_json(GOAL_BACKLOG_STATUS_PATH, plan)
    return plan


def record_goal_backlog_result(plan: dict[str, Any], *, dispatched: list[dict[str, Any]] | None = None, error: str | None = None) -> dict[str, Any]:
    current = _load_json(GOAL_BACKLOG_STATUS_PATH, {})
    merged = dict(current)
    dispatched = list(dispatched or [])
    goal_health = str(plan.get("goal_health") or current.get("goal_health") or "").strip().lower()
    live_counts = _live_goal_counts(str(plan.get("goal_id") or current.get("goal_id") or ""))
    live_active = int(live_counts.get("active") or 0)
    live_active_including_finishing = int(live_counts.get("active_including_finishing") or 0)
    live_execution_finishing = int(live_counts.get("execution_finishing") or 0)
    live_pending = int(live_counts.get("pending") or 0)
    live_goal_health = _backlog_health(
        live_active,
        live_pending,
        min_active=int(plan.get("minimum_active_tasks") or current.get("minimum_active_tasks") or MIN_ACTIVE),
        min_pending=int(plan.get("minimum_pending_tasks") or current.get("minimum_pending_tasks") or MIN_PENDING),
        desired_active=int(plan.get("desired_active_tasks") or current.get("desired_active_tasks") or TARGET_ACTIVE),
        desired_pending=int(plan.get("desired_pending_tasks") or current.get("desired_pending_tasks") or TARGET_PENDING),
    )
    merged.update(
        {
            "updated_at": _utc(),
            "goal_primary": plan.get("goal_primary") or current.get("goal_primary"),
            "goal_mode": plan.get("goal_mode") or current.get("goal_mode"),
            "goal_health": live_goal_health or plan.get("goal_health") or current.get("goal_health"),
            "compiled_task_types": list(plan.get("compiled_task_types") or current.get("compiled_task_types") or []),
            "pending_tasks_by_goal": {live_counts.get("goal_id") or plan.get("goal_id") or current.get("goal_id") or "": live_pending},
            "active_tasks_by_goal": {live_counts.get("goal_id") or plan.get("goal_id") or current.get("goal_id") or "": live_active},
            "execution_finishing_tasks_by_goal": {live_counts.get("goal_id") or plan.get("goal_id") or current.get("goal_id") or "": live_execution_finishing},
            "last_replenished_at": _utc(),
            "goal_id": live_counts.get("goal_id") or plan.get("goal_id") or current.get("goal_id"),
            "graph_id": plan.get("graph_id") or current.get("graph_id"),
            "dispatch_now_count": int(plan.get("dispatch_now_count") or 0),
            "pending_candidate_count": int(plan.get("pending_candidate_count") or 0),
            "active_candidate_count": int(plan.get("active_candidate_count") or 0),
            "desired_active_tasks": int(plan.get("desired_active_tasks") or current.get("desired_active_tasks") or TARGET_ACTIVE),
            "desired_pending_tasks": int(plan.get("desired_pending_tasks") or current.get("desired_pending_tasks") or TARGET_PENDING),
            "minimum_active_tasks": int(plan.get("minimum_active_tasks") or current.get("minimum_active_tasks") or MIN_ACTIVE),
            "minimum_pending_tasks": int(plan.get("minimum_pending_tasks") or current.get("minimum_pending_tasks") or MIN_PENDING),
            "control_alert_required": bool(plan.get("control_alert_required") or current.get("control_alert_required")),
            "active_including_finishing": live_active_including_finishing,
            "true_running_tasks": live_active,
            "execution_finishing_tasks": live_execution_finishing,
        }
    )
    if error:
        merged["last_replenishment_result"] = "replenishment_failed"
        merged["replenishment_block_reason"] = error
        merged["failure_streak"] = int(current.get("failure_streak") or 0) + 1
    elif dispatched:
        merged["last_replenishment_result"] = "success"
        merged["replenishment_block_reason"] = ""
        merged["failure_streak"] = 0
        merged["last_dispatched_task_ids"] = [str(item.get("task_id") or "") for item in dispatched if item.get("task_id")]
        merged["last_dispatched_node_ids"] = [str(item.get("node_id") or "") for item in dispatched if item.get("node_id")]
    else:
        if live_goal_health in {"healthy", "degraded"}:
            merged["last_replenishment_result"] = "planned"
            merged["replenishment_block_reason"] = "backlog_satisfied"
            merged["failure_streak"] = 0
        else:
            merged["last_replenishment_result"] = current.get("last_replenishment_result") or "planned"
            merged["failure_streak"] = int(current.get("failure_streak") or 0)
    if merged.get("last_replenishment_result") in {"planned", "success"} and int(merged.get("failure_streak") or 0) == 0 and live_goal_health != "starved":
        merged["control_alert_required"] = False
    if merged.get("failure_streak", 0) >= 3:
        merged["control_alert_required"] = True
    merged["live_active_tasks"] = live_active
    merged["live_pending_tasks"] = live_pending
    merged["live_goal_health"] = live_goal_health
    merged["live_goal_counts"] = {
        "goal_id": live_counts.get("goal_id") or "",
        "active": live_active,
        "active_including_finishing": live_active_including_finishing,
        "execution_finishing": live_execution_finishing,
        "pending": live_pending,
        "total": int(live_counts.get("total") or 0),
        "aggregate_active": int(live_counts.get("aggregate_active") or 0),
        "aggregate_active_including_finishing": int(live_counts.get("aggregate_active_including_finishing") or 0),
        "aggregate_execution_finishing": int(live_counts.get("aggregate_execution_finishing") or 0),
        "aggregate_pending": int(live_counts.get("aggregate_pending") or 0),
    }
    _save_json(GOAL_BACKLOG_STATUS_PATH, merged)
    return merged
