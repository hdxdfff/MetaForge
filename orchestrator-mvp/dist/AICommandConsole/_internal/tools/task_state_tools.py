from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import time
from pathlib import Path
from typing import Any
from tools.kernel_mode import is_component_enabled, load_kernel_mode
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
TASKS = DATA / "tasks.json"
GOALS = FACTORY / "goals" / "goal_registry.json"
CORE_MESSAGES = DATA / "core_messages.json"
TASK_CHECKPOINTS = DATA / "task_checkpoints.json"
RUNTIME_TASKS = FACTORY / "runtime" / "tasks"
GRAPHS = FACTORY / "graphs"
STALE_ESCALATION_HOURS = 6
STALE_PERMISSION_DENIED_HOURS = 2
HEARTBEAT_TIMEOUT_MINUTES = 5
STALE_SMOKE_MINUTES = 30
STALE_RUNNING_MINUTES = 20
STALE_PLANNING_MINUTES = 20
STALE_REQUEUED_PAUSE_MINUTES = 10
SMOKE_CALLERS = ("caller: codex-smoke", "caller: vm-policy-smoke", "caller: auto-debug", "caller: smoke-test")
PLANNING_CALLERS = ("caller: brain-loop", "caller: codex-control")
ACTIVE_TASK_STATUSES = {"queued", "planning", "running", "waiting_approval"}
TERMINAL_TASK_STATUSES = {"completed", "failed", "timed_out", "cancelled"}
STALE_CONNECTION_ERROR_MINUTES = 5

DISABLED_COMPONENT_MARKERS = {
    "governance": ("governance", "global policy"),
    "coordination": (
        "cross_project_coordination",
        "cross project",
        "coordination_pkg_",
        "project_sync_",
        "coordinate ",
        "alignment",
    ),
    "policy_contract": ("policy contract", "review patch queue", "merge ready patch queue"),
    "approval": ("approval", "approve ", "waiting approval"),
    "security_review": ("security review", "security gate"),
    "release_train": ("release train", "release_prep"),
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _load_task_evidence(task: dict[str, Any]) -> dict[str, Any]:
    evidence_path = str((task.get("result") or {}).get("execution_evidence_path") or "").strip()
    if not evidence_path:
        return {}
    path = Path(evidence_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _task_execution_mode(task: dict[str, Any]) -> str:
    scheduler_hint = task.get("scheduler_hint") or {}
    return str(task.get("execution_mode") or scheduler_hint.get("execution_mode") or "").strip().lower()


def _disabled_component_for_text(text: str, mode: dict[str, Any]) -> str | None:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return None
    for component, markers in DISABLED_COMPONENT_MARKERS.items():
        if is_component_enabled(component, mode):
            continue
        if any(marker in lowered for marker in markers):
            return component
    return None


def _disabled_component_for_task(task: dict[str, Any], mode: dict[str, Any]) -> str | None:
    execution_mode = _task_execution_mode(task)
    if execution_mode == "governance" and not is_component_enabled("governance", mode):
        return "governance"
    corpus = " ".join(
        str(part or "")
        for part in [
            task.get("node_id"),
            task.get("title"),
            task.get("goal"),
            task.get("prompt"),
            task.get("scheduled_by"),
            (task.get("scheduler_hint") or {}).get("node_title"),
        ]
    )
    return _disabled_component_for_text(corpus, mode)


def _disabled_component_for_node(node: dict[str, Any], mode: dict[str, Any]) -> str | None:
    corpus = " ".join(
        str(part or "")
        for part in [
            node.get("id"),
            node.get("kind"),
            node.get("title"),
            node.get("prompt"),
        ]
    )
    return _disabled_component_for_text(corpus, mode)


def _task_heartbeat_at(task: dict[str, Any], checkpoints: dict[str, dict[str, Any]]) -> datetime | None:
    task_id = str(task.get("id") or "")
    checkpoint = checkpoints.get(task_id) or {}
    for raw in (
        checkpoint.get("heartbeat_at"),
        checkpoint.get("updated_at"),
        task.get("task_heartbeat_at"),
        task.get("updated_at"),
        task.get("created_at"),
    ):
        parsed = _parse_time(str(raw) if raw else None)
        if parsed is not None:
            return parsed
    return None


def _load_runtime_task_json(task_id: str, name: str) -> dict[str, Any]:
    if not task_id:
        return {}
    return _load_json(RUNTIME_TASKS / task_id / name, {})


def _execution_evidence_path(task_id: str) -> Path:
    return RUNTIME_TASKS / task_id / "execution-evidence.json"


def _task_artifact_spec(task: dict[str, Any]) -> dict[str, Any] | None:
    spec = task.get("artifact_spec")
    if isinstance(spec, dict) and spec:
        return dict(spec)
    scheduler_hint = task.get("scheduler_hint") or {}
    hint_spec = scheduler_hint.get("artifact_spec") or {}
    payload = dict(hint_spec) if isinstance(hint_spec, dict) else {}
    required = [str(item) for item in (scheduler_hint.get("required_artifacts") or []) if str(item).strip()]
    if required and not payload.get("required_artifacts"):
        payload["required_artifacts"] = required
    if scheduler_hint.get("min_fresh_artifacts") and not payload.get("min_fresh_artifacts"):
        payload["min_fresh_artifacts"] = int(scheduler_hint.get("min_fresh_artifacts") or 1)
    return payload or None


def _task_requires_audit_gate(task: dict[str, Any]) -> bool:
    if _task_execution_mode(task) != "production":
        return False
    spec = _task_artifact_spec(task)
    return bool(spec and (spec.get("required_artifacts") or []))


def _task_has_verified_audit(task: dict[str, Any]) -> bool:
    result = task.get("result") or {}
    production_evidence = result.get("production_evidence") if isinstance(result, dict) else {}
    if isinstance(production_evidence, dict) and str(production_evidence.get("status") or "").strip().lower() == "verified":
        return True
    if not _task_requires_audit_gate(task):
        return True
    repo_path = str(task.get("repo_path") or "").strip()
    created_at = _parse_time(task.get("created_at") or task.get("updated_at"))
    spec = _task_artifact_spec(task)
    if not repo_path or created_at is None or not spec:
        return False
    try:
        from tools.artifact_audit import validate_task_artifact_completion

        validate_task_artifact_completion(
            repo_root=Path(repo_path),
            artifact_spec=spec,
            created_at=created_at,
        )
        return True
    except Exception:
        return False


def _can_mark_task_completed(task: dict[str, Any]) -> bool:
    return _task_has_verified_audit(task)


def _synthesized_execution_steps(task: dict[str, Any]) -> list[dict[str, Any]]:
    task_id = str(task.get("id") or "").strip()
    fallback_at = str(task.get("updated_at") or task.get("created_at") or _utc())
    synthesized: list[dict[str, Any]] = []
    for index, raw_step in enumerate(task.get("plan") or [], start=1):
        if not isinstance(raw_step, dict):
            continue
        status = str(raw_step.get("status") or "").strip().lower()
        if status not in {"completed", "failed", "running", "pending"}:
            continue
        synthesized.append(
            {
                "step_id": raw_step.get("id") or f"synth-step-{index}",
                "step_title": raw_step.get("title") or f"Step {index}",
                "action": f"{raw_step.get('worker') or 'worker'}_step",
                "ok": status == "completed",
                "at": fallback_at,
                "phase": raw_step.get("phase"),
                "worker": raw_step.get("worker"),
                "status": status,
                "output_ref": raw_step.get("output_ref"),
                "output_stats": raw_step.get("output_stats"),
                "synthesized": True,
                "source": "task-plan-backfill",
            }
        )
    if synthesized:
        return synthesized

    result = task.get("result") or {}
    production_evidence = result.get("production_evidence") if isinstance(result, dict) else {}
    return [
        {
            "step_id": f"{task_id or 'task'}-terminal-record",
            "step_title": task.get("title") or task.get("goal") or "Task terminal record",
            "action": "task_terminal_record",
            "ok": str(task.get("status") or "").strip().lower() == "completed",
            "at": fallback_at,
            "status": str(task.get("status") or "").strip().lower(),
            "summary": str(result.get("summary") or "").strip() or None,
            "error": str(result.get("error") or "").strip() or None,
            "production_evidence_status": (
                str((production_evidence or {}).get("status") or "").strip().lower()
                if isinstance(production_evidence, dict)
                else None
            ),
            "synthesized": True,
            "source": "task-result-backfill",
        }
    ]


def _terminal_task_snapshot(task: dict[str, Any], checkpoints: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    task_id = str(task.get("id") or "")
    if not task_id:
        return None
    checkpoint = checkpoints.get(task_id) or {}
    for payload in (
        _load_runtime_task_json(task_id, "execution-evidence.json"),
        _load_runtime_task_json(task_id, "context.json"),
        checkpoint,
    ):
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("task_status") or payload.get("status") or "").strip().lower()
        if status not in TERMINAL_TASK_STATUSES:
            continue
        updated_at = payload.get("updated_at") or payload.get("heartbeat_at") or task.get("updated_at") or task.get("created_at") or _utc()
        heartbeat_at = payload.get("heartbeat_at") or payload.get("updated_at") or updated_at
        snapshot = {
            "status": status,
            "updated_at": str(updated_at),
            "heartbeat_at": str(heartbeat_at),
        }
        result = payload.get("result")
        if isinstance(result, dict) and result:
            snapshot["result"] = result
        return snapshot
    return None


def _refresh_graph_status(graph: dict[str, Any]) -> None:
    statuses = [str(node.get("status") or "") for node in graph.get("nodes", []) or []]
    if any(status in {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge", "blocked"} for status in statuses):
        graph["status"] = "running"
    elif any(status == "pending" for status in statuses):
        graph["status"] = "planned"
    elif statuses and all(status == "completed" for status in statuses):
        graph["status"] = "completed"


def _is_internal_runtime_task(task: dict[str, Any] | None) -> bool:
    task = task or {}
    scheduler_hint = task.get("scheduler_hint") or {}
    scheduled_by = str(task.get("scheduled_by") or scheduler_hint.get("scheduled_by") or "").strip().lower()
    return scheduled_by.startswith("runtime.") or scheduled_by in {"brain-loop", "factory-daemon", "codex-control"}


def _is_permission_denied_escalation(message: dict[str, Any], task: dict[str, Any] | None, task_status: str | None, created_at: datetime | None, now: datetime) -> bool:
    body_lower = str(message.get("body") or "").lower()
    repo_path = str(message.get("repo_path") or "").lower()
    permission_markers = (
        "[winerror 5]",
        "permission denied",
        "action shell_exec is denied",
        "action shell_exec is not granted",
        "real execution requires task auto-approve when orch_approval_mode is manual",
        "????",
        "???",
        "access is denied",
    )
    if not any(marker in body_lower for marker in permission_markers):
        return False
    threshold = timedelta(minutes=1) if _is_internal_runtime_task(task) else timedelta(hours=STALE_PERMISSION_DENIED_HOURS)
    if created_at is None or now - created_at <= threshold:
        return False
    if task_status in {"completed", "delivery_ready", "released", "verification_failed", "failed", "timed_out", "cancelled"} or task_status is None:
        return True
    return "\\vendor\\" in repo_path


def _is_connection_failure_escalation(message: dict[str, Any], task_status: str | None, created_at: datetime | None, now: datetime) -> bool:
    body_lower = str(message.get("body") or "").lower()
    transient_markers = (
        "connection error",
        "request timed out",
        "expecting value: line 1 column 1",
        "api connection error",
    )
    if not any(marker in body_lower for marker in transient_markers):
        return False
    if created_at is None or now - created_at <= timedelta(minutes=STALE_CONNECTION_ERROR_MINUTES):
        return False
    return task_status in {"completed", "delivery_ready", "released", "verification_failed", "failed", "timed_out", "cancelled", "planning", "queued"} or task_status is None

def _is_stale_core_guidance_pause(message: dict[str, Any], task: dict[str, Any] | None, task_status: str | None, created_at: datetime | None, now: datetime) -> bool:
    body_lower = str(message.get("body") or "").lower()
    task_result = (task or {}).get("result") or {}
    result_state = str(task_result.get("state") or "").strip().lower()
    summary = str(task_result.get("summary") or "").strip().lower()
    pause_markers = (
        "no further action will be taken until core guidance arrives",
        "sandbox command failed with code 1",
        "pytest: command not found",
        "paused_pending_core_instruction",
    )
    if not any(marker in body_lower for marker in pause_markers) and result_state != "paused_pending_core_instruction":
        return False
    if created_at is None:
        return False
    threshold = timedelta(minutes=1) if _is_internal_runtime_task(task) else timedelta(hours=STALE_PERMISSION_DENIED_HOURS)
    if now - created_at <= threshold:
        return False
    if task_status in {"completed", "delivery_ready", "released", "verification_failed", "failed", "timed_out", "cancelled"} or task_status is None:
        return True
    return "heartbeat exceeded" in summary or bool(task_result.get("requeue_requested"))

def _is_requeued_pause_escalation(message: dict[str, Any], task: dict[str, Any] | None, task_status: str | None, created_at: datetime | None, now: datetime) -> bool:
    if created_at is None or now - created_at <= timedelta(minutes=STALE_REQUEUED_PAUSE_MINUTES):
        return False
    if str(message.get("source") or "").strip().lower() != "orchestrator-task-failure":
        return False
    if str(message.get("severity") or "").strip().lower() != "error":
        return False
    task_result = (task or {}).get("result") or {}
    if not isinstance(task_result, dict):
        return False
    summary = str(task_result.get("summary") or "").strip().lower()
    requeue_requested = bool(task_result.get("requeue_requested"))
    heartbeat_timeout = bool(task_result.get("heartbeat_timeout")) or "heartbeat exceeded" in summary
    if task_status != "timed_out":
        return False
    return requeue_requested or heartbeat_timeout


def _is_stale_audit_schema_rejection(
    message: dict[str, Any],
    task: dict[str, Any] | None,
    task_status: str | None,
    created_at: datetime | None,
    now: datetime,
) -> bool:
    if created_at is None or now - created_at <= timedelta(hours=STALE_ESCALATION_HOURS):
        return False
    if str(message.get("source") or "").strip().lower() != "orchestrator-task-failure":
        return False
    if str(message.get("severity") or "").strip().lower() != "error":
        return False
    body_lower = str(message.get("body") or "").lower()
    audit_schema_markers = (
        "audit output schema rejected",
        "missing required structured sections",
        "missing required narrative sections",
    )
    if not any(marker in body_lower for marker in audit_schema_markers):
        return False
    task_result = (task or {}).get("result") or {}
    if not isinstance(task_result, dict):
        task_result = {}
    result_state = str(task_result.get("state") or "").strip().lower()
    if task_status in {"completed", "delivery_ready", "released", "verification_failed", "failed", "timed_out", "cancelled"}:
        return True
    if result_state in {"paused_pending_core_instruction", "paused"}:
        return True
    return task is None

def complete_tasks(task_ids: list[str], summary: str) -> int:
    if not task_ids:
        return 0
    tasks = _load_json(TASKS, [])
    updated = 0
    now = _utc()
    for item in tasks:
        if item.get("id") not in task_ids:
            continue
        if not _can_mark_task_completed(item):
            result = item.setdefault("result", {})
            result["completion_blocked_by_audit"] = True
            result.setdefault("summary", "Completion withheld until production evidence passes artifact audit.")
            continue
        item["status"] = "completed"
        item["updated_at"] = now
        result = item.setdefault("result", {})
        result.setdefault("summary", summary)
        updated += 1
    if updated:
        _save_json(TASKS, tasks)
    return updated


def _completed_goals() -> list[dict[str, Any]]:
    goals = _load_json(GOALS, [])
    return [goal for goal in goals if goal.get("status") == "completed"]


def completed_goal_task_ids() -> set[str]:
    task_ids: set[str] = set()
    for goal in _completed_goals():
        for task_id in goal.get("task_ids", []) or []:
            if task_id:
                task_ids.add(task_id)
    return task_ids


def completed_goal_ids() -> set[str]:
    return {str(goal.get("goal_id") or "").strip() for goal in _completed_goals() if goal.get("goal_id")}


def reconcile_goal_tasks() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    completed_goals = _completed_goals()
    completed_ids = completed_goal_task_ids()
    completed_goal_id_set = completed_goal_ids()
    if not completed_goals:
        return {"completed_from_goals": 0, "task_ids": []}
    updated = []
    now = _utc()
    for item in tasks:
        task_id = item.get("id")
        task_goal_id = str(item.get("goal_id") or "").strip()
        if task_id not in completed_ids and task_goal_id not in completed_goal_id_set:
            continue
        if item.get("status") == "completed":
            continue
        if not _can_mark_task_completed(item):
            result = item.setdefault("result", {})
            result["completion_blocked_by_audit"] = True
            result.setdefault("summary", "Goal completion did not auto-close this production task because artifact audit is not verified.")
            continue
        item["status"] = "completed"
        item["updated_at"] = now
        result = item.setdefault("result", {})
        result.setdefault("summary", "Task auto-completed because its parent completed goal explicitly owns this task.")
        updated.append(task_id)
    if updated:
        _save_json(TASKS, tasks)
    return {"completed_from_goals": len(updated), "task_ids": updated}


def reconcile_stale_smoke_tasks() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    now = datetime.now(timezone.utc)
    updated = []
    for item in tasks:
        if item.get("status") not in {"queued", "planning", "running", "waiting_approval", "verification_pending"}:
            continue
        prompt = (item.get("prompt") or "").lower()
        title = (item.get("title") or "").lower()
        evidence = _load_task_evidence(item)
        evidence_status = str(evidence.get("task_status") or "").lower()
        evidence_result = evidence.get("result") or {}
        if evidence_status == "released" or str(evidence_result.get("delivery_state") or "").lower() == "released":
            item["status"] = "released"
            item["updated_at"] = _utc()
            result = item.setdefault("result", {})
            result["summary"] = "Stale smoke task reconciled from execution evidence and marked released."
            result["stale_reconciled"] = True
            result["delivery_state"] = "released"
            updated.append(item.get("id"))
            continue
        updated_at = _parse_time(item.get("updated_at") or item.get("created_at"))
        if updated_at is None or now - updated_at <= timedelta(minutes=STALE_SMOKE_MINUTES):
            continue
        if not any(marker in prompt for marker in SMOKE_CALLERS) and "smoke" not in title and "verification" not in title:
            continue
        if not _can_mark_task_completed(item):
            result = item.setdefault("result", {})
            result["completion_blocked_by_audit"] = True
            result.setdefault("summary", "Stale smoke task was left open because production evidence is still unverified.")
            continue
        item["status"] = "completed"
        item["updated_at"] = _utc()
        result = item.setdefault("result", {})
        result.setdefault("summary", "Stale internal smoke task auto-closed after runtime validation window elapsed.")
        updated.append(item.get("id"))
    if updated:
        _save_json(TASKS, tasks)
    return {"completed_smoke_tasks": len(updated), "task_ids": updated}


def reconcile_stale_running_tasks() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    now = datetime.now(timezone.utc)
    updated = []
    for item in tasks:
        if item.get("status") != "running":
            continue
        updated_at = _parse_time(item.get("updated_at") or item.get("created_at"))
        if updated_at is None or now - updated_at <= timedelta(minutes=STALE_RUNNING_MINUTES):
            continue
        prompt = (item.get("prompt") or "").lower()
        goal = str(item.get("goal") or "").strip().lower()
        execution_lane = str(item.get("execution_lane") or "").strip().lower()
        vm_mode = str((item.get("vm_context") or {}).get("mode") or "").strip().lower()
        if (
            not any(marker in prompt for marker in SMOKE_CALLERS)
            and goal not in {
                'improve scheduler module behavior',
                'experiment adopted-pattern rollout',
            }
            and execution_lane not in {"worker-vm", "vm-first"}
            and vm_mode != "vm-first"
        ):
            continue
        if not _can_mark_task_completed(item):
            result = item.setdefault("result", {})
            result["completion_blocked_by_audit"] = True
            result.setdefault("summary", "Stale runtime task was left open because production evidence is still unverified.")
            continue
        item["status"] = "completed"
        item["updated_at"] = _utc()
        result = item.setdefault("result", {})
        result.setdefault("summary", "Stale runtime task auto-closed after no progress beyond the stale-running window.")
        result.setdefault("stale_reconciled", True)
        updated.append(item.get("id"))
    if updated:
        _save_json(TASKS, tasks)
    return {"completed_stale_running": len(updated), "task_ids": updated}


def reconcile_stale_planning_tasks() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    now = datetime.now(timezone.utc)
    updated = []
    for item in tasks:
        if item.get("status") != "planning":
            continue
        updated_at = _parse_time(item.get("updated_at") or item.get("created_at"))
        if updated_at is None or now - updated_at <= timedelta(minutes=STALE_PLANNING_MINUTES):
            continue
        prompt = (item.get("prompt") or "").lower()
        execution_lane = str(item.get("execution_lane") or "").strip().lower()
        if not any(marker in prompt for marker in PLANNING_CALLERS) and execution_lane not in {"host-control", "worker-vm", "vm-first"}:
            continue
        if not _can_mark_task_completed(item):
            result = item.setdefault("result", {})
            result["completion_blocked_by_audit"] = True
            result.setdefault("summary", "Stale planning task was left open because production evidence is still unverified.")
            continue
        item["status"] = "completed"
        item["updated_at"] = _utc()
        result = item.setdefault("result", {})
        result.setdefault("summary", "Stale planning task auto-closed after no progress beyond the stale-planning window.")
        result.setdefault("stale_reconciled", True)
        updated.append(item.get("id"))
    if updated:
        _save_json(TASKS, tasks)
    return {"completed_stale_planning": len(updated), "task_ids": updated}


def reconcile_terminal_task_snapshots() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    graph_docs: dict[str, dict[str, Any]] = {}
    task_refs: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}
    requeue_refs: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {}

    for graph_path in GRAPHS.glob("*.json"):
        graph = _load_json(graph_path, {})
        graph_id = str(graph.get("graph_id") or graph_path.stem)
        graph_docs[graph_id] = graph
        for node in graph.get("nodes", []) or []:
            node_task_id = str(node.get("task_id") or "")
            if node_task_id:
                task_refs.setdefault(node_task_id, []).append((graph_id, graph, node))
            last_requeued = str(node.get("last_requeued_task_id") or "")
            if last_requeued:
                requeue_refs.setdefault(last_requeued, []).append((graph_id, graph, node))

    updated_task_ids: list[str] = []
    restored_completed_task_ids: list[str] = []
    restored_node_ids: list[str] = []
    requeued_node_ids: list[str] = []
    removed_checkpoints: list[str] = []
    changed_graph_ids: set[str] = set()

    for task in tasks:
        task_id = str(task.get("id") or "")
        if not task_id:
            continue
        current_status = str(task.get("status") or "").strip().lower()
        snapshot = _terminal_task_snapshot(task, checkpoints)
        if snapshot is None:
            continue

        terminal_status = str(snapshot.get("status") or "").strip().lower()
        if (
            current_status == terminal_status
            and current_status in TERMINAL_TASK_STATUSES
            and task_id not in requeue_refs
        ):
            if checkpoints.pop(task_id, None) is not None:
                removed_checkpoints.append(task_id)
            continue

        task["status"] = terminal_status
        task["updated_at"] = snapshot.get("updated_at") or _utc()
        task["task_heartbeat_at"] = snapshot.get("heartbeat_at") or task["updated_at"]
        if isinstance(snapshot.get("result"), dict) and snapshot.get("result"):
            task["result"] = snapshot["result"]
        else:
            result = task.setdefault("result", {})
            if terminal_status == "completed":
                result.setdefault("summary", "Task restored from terminal runtime evidence.")
            else:
                result.setdefault("summary", f"Task restored from terminal runtime evidence with status={terminal_status}.")
        updated_task_ids.append(task_id)

        refs = list(task_refs.get(task_id, []))
        if terminal_status == "completed":
            refs.extend(requeue_refs.get(task_id, []))

        seen: set[tuple[str, str]] = set()
        for graph_id, graph, node in refs:
            node_id = str(node.get("id") or "")
            dedupe_key = (graph_id, node_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if terminal_status == "completed":
                if (
                    node.get("status") != "completed"
                    or node.get("task_id") is not None
                    or str(node.get("last_requeued_task_id") or "") == task_id
                ):
                    node["status"] = "completed"
                    node["updated_at"] = task["updated_at"]
                    node["task_id"] = None
                    node["last_completed_task_id"] = task_id
                    node.pop("last_requeued_task_id", None)
                    changed_graph_ids.add(graph_id)
                    if node_id:
                        restored_node_ids.append(node_id)
            else:
                if str(node.get("task_id") or "") != task_id:
                    continue
                node["task_id"] = None
                node["status"] = "pending"
                node["updated_at"] = task["updated_at"]
                node["last_requeued_task_id"] = task_id
                node["requeue_count"] = int(node.get("requeue_count", 0) or 0) + 1
                node.pop("worker", None)
                node.pop("selection_reason", None)
                node.pop("worker_success_rate", None)
                changed_graph_ids.add(graph_id)
                if node_id:
                    requeued_node_ids.append(node_id)

        if checkpoints.pop(task_id, None) is not None:
            removed_checkpoints.append(task_id)
        if terminal_status == "completed":
            restored_completed_task_ids.append(task_id)

    if updated_task_ids:
        _save_json(TASKS, tasks)
    if updated_task_ids or removed_checkpoints:
        _save_json(TASK_CHECKPOINTS, checkpoints)
    for graph_id in sorted(changed_graph_ids):
        graph = graph_docs.get(graph_id) or {}
        _refresh_graph_status(graph)
        _save_json(GRAPHS / f"{graph_id}.json", graph)
    return {
        "restored_task_count": len(updated_task_ids),
        "restored_completed_task_count": len(restored_completed_task_ids),
        "restored_graph_node_count": len(restored_node_ids),
        "requeued_terminal_task_count": len(requeued_node_ids),
        "task_ids": updated_task_ids,
        "completed_task_ids": restored_completed_task_ids,
        "graph_ids": sorted(changed_graph_ids),
        "removed_checkpoints": removed_checkpoints,
    }


def reconcile_execution_evidence_steps() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    updated_task_ids: list[str] = []
    wrote_evidence: list[str] = []

    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        status = str(task.get("status") or "").strip().lower()
        if not task_id or status not in TERMINAL_TASK_STATUSES:
            continue
        path = _execution_evidence_path(task_id)
        payload = _load_json(path, {})
        if not isinstance(payload, dict):
            payload = {}
        steps = payload.get("steps")
        if isinstance(steps, list) and steps:
            result = task.get("result")
            if isinstance(result, dict) and result.get("execution_evidence_step_count") != len(steps):
                result["execution_evidence_path"] = str(path)
                result["execution_evidence_step_count"] = len(steps)
                updated_task_ids.append(task_id)
            continue
        synthesized = _synthesized_execution_steps(task)
        if not synthesized:
            continue
        payload.update(
            {
                "task_id": task_id,
                "task_title": task.get("title"),
                "task_status": status,
                "started_at": payload.get("started_at") or task.get("created_at") or _utc(),
                "updated_at": task.get("updated_at") or _utc(),
                "completed": status == "completed",
                "steps": synthesized,
                "result": task.get("result") if isinstance(task.get("result"), dict) else {},
            }
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        _save_json(path, payload)
        result = task.setdefault("result", {})
        result["execution_evidence_path"] = str(path)
        result["execution_evidence_step_count"] = len(synthesized)
        wrote_evidence.append(task_id)
        updated_task_ids.append(task_id)

    if updated_task_ids:
        _save_json(TASKS, tasks)
    return {
        "backfilled_execution_evidence_count": len(wrote_evidence),
        "synchronized_task_count": len(updated_task_ids),
        "task_ids": updated_task_ids,
    }


def reconcile_stale_task_heartbeats() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    now = datetime.now(timezone.utc)
    recovered_task_ids: list[str] = []
    recovered_node_ids: list[str] = []
    graph_changes: dict[str, dict[str, Any]] = {}

    for task in tasks:
        status = str(task.get("status") or "")
        if status not in {"planning", "running", "waiting_approval"}:
            continue
        heartbeat_at = _task_heartbeat_at(task, checkpoints)
        if heartbeat_at is None or now - heartbeat_at <= timedelta(minutes=HEARTBEAT_TIMEOUT_MINUTES):
            continue
        task_id = str(task.get("id") or "")
        task["status"] = "timed_out"
        task["updated_at"] = _utc()
        task["task_heartbeat_at"] = task["updated_at"]
        result = task.setdefault("result", {})
        result["summary"] = f"Task heartbeat exceeded {HEARTBEAT_TIMEOUT_MINUTES} minutes; runtime requested requeue."
        result["heartbeat_timeout"] = True
        result["requeue_requested"] = True
        recovered_task_ids.append(task_id)
        checkpoints.pop(task_id, None)

    for graph_path in GRAPHS.glob("*.json"):
        graph = _load_json(graph_path, {})
        changed = False
        for node in graph.get("nodes", []) or []:
            task_id = str(node.get("task_id") or "")
            if not task_id or task_id not in recovered_task_ids:
                continue
            node["task_id"] = None
            node["status"] = "pending"
            node["updated_at"] = _utc()
            node["last_requeued_task_id"] = task_id
            node["requeue_count"] = int(node.get("requeue_count", 0) or 0) + 1
            node.pop("worker", None)
            node.pop("selection_reason", None)
            node.pop("worker_success_rate", None)
            recovered_node_ids.append(str(node.get("id") or ""))
            changed = True
        if changed:
            statuses = [str(node.get("status") or "") for node in graph.get("nodes", []) or []]
            if any(status in {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge", "blocked"} for status in statuses):
                graph["status"] = "running"
            elif any(status == "pending" for status in statuses):
                graph["status"] = "planned"
            graph_changes[str(graph.get("graph_id") or graph_path.stem)] = graph

    if recovered_task_ids:
        _save_json(TASKS, tasks)
    if recovered_task_ids or checkpoints:
        _save_json(TASK_CHECKPOINTS, checkpoints)
    for graph_id, graph in graph_changes.items():
        _save_json(GRAPHS / f"{graph_id}.json", graph)
    return {
        "heartbeat_timeout_minutes": HEARTBEAT_TIMEOUT_MINUTES,
        "requeued_task_count": len(recovered_task_ids),
        "task_ids": recovered_task_ids,
        "node_ids": recovered_node_ids,
    }


def reconcile_disabled_kernel_tasks() -> dict[str, Any]:
    mode = load_kernel_mode()
    if str(mode.get("profile") or "") != "lean_execution":
        return {
            "profile": mode.get("profile"),
            "completed_disabled_tasks": 0,
            "completed_disabled_nodes": 0,
            "task_ids": [],
            "node_ids": [],
            "graph_ids": [],
            "removed_checkpoints": [],
        }

    tasks = _load_json(TASKS, [])
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    task_ids: list[str] = []
    node_ids: list[str] = []
    graph_ids: list[str] = []
    removed_checkpoints: list[str] = []
    tasks_changed = False

    for task in tasks:
        if str(task.get("status") or "") not in ACTIVE_TASK_STATUSES:
            continue
        component = _disabled_component_for_task(task, mode)
        if not component:
            continue
        task["status"] = "completed"
        task["updated_at"] = _utc()
        result = task.setdefault("result", {})
        result["summary"] = f"Task auto-closed because component {component} is disabled under lean_execution."
        result["disabled_component"] = component
        result["disabled_by_kernel_profile"] = mode.get("profile")
        task_id = str(task.get("id") or "")
        if task_id:
            task_ids.append(task_id)
            if checkpoints.pop(task_id, None) is not None:
                removed_checkpoints.append(task_id)
        tasks_changed = True

    graph_changes: dict[str, dict[str, Any]] = {}
    for graph_path in GRAPHS.glob("*.json"):
        graph = _load_json(graph_path, {})
        changed = False
        for node in graph.get("nodes", []) or []:
            component = _disabled_component_for_node(node, mode)
            if not component:
                continue
            node_id = str(node.get("id") or "")
            if node.get("status") != "completed":
                node["status"] = "completed"
                changed = True
            result = node.setdefault("result", {})
            summary = f"Node bypassed because component {component} is disabled under lean_execution."
            if result.get("summary") != summary:
                result["summary"] = summary
                changed = True
            if result.get("disabled_component") != component:
                result["disabled_component"] = component
                changed = True
            if not node.get("completed_at"):
                node["completed_at"] = _utc()
                changed = True
            task_id = str(node.get("task_id") or "")
            if task_id:
                node["last_disabled_task_id"] = task_id
                node["task_id"] = None
                changed = True
            if node_id:
                node_ids.append(node_id)
        if not changed:
            continue
        statuses = [str(node.get("status") or "") for node in graph.get("nodes", []) or []]
        if statuses and all(status == "completed" for status in statuses):
            graph["status"] = "completed"
        elif any(status in {"running", "waiting_patch", "waiting_patch_verification", "ready_for_merge"} for status in statuses):
            graph["status"] = "running"
        elif any(status == "pending" for status in statuses):
            graph["status"] = "planned"
        graph_changes[str(graph.get("graph_id") or graph_path.stem)] = graph
        graph_ids.append(str(graph.get("graph_id") or graph_path.stem))

    if tasks_changed:
        _save_json(TASKS, tasks)
    if tasks_changed or removed_checkpoints:
        _save_json(TASK_CHECKPOINTS, checkpoints)
    for graph_id, graph in graph_changes.items():
        _save_json(GRAPHS / f"{graph_id}.json", graph)

    return {
        "profile": mode.get("profile"),
        "completed_disabled_tasks": len(task_ids),
        "completed_disabled_nodes": len(node_ids),
        "task_ids": task_ids,
        "node_ids": node_ids,
        "graph_ids": graph_ids,
        "removed_checkpoints": removed_checkpoints,
    }


def reconcile_graph_node_tasks() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    task_map = {item.get("id"): item for item in tasks}
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    updated_task_ids: list[str] = []
    removed_checkpoints: list[str] = []
    now = _utc()

    for graph_path in GRAPHS.glob("*.json"):
        graph = _load_json(graph_path, {})
        for node in graph.get("nodes", []):
            task_id = node.get("task_id")
            if not task_id:
                continue
            task = task_map.get(task_id)
            if task is None:
                checkpoints.pop(task_id, None)
                continue
            if node.get("status") == "completed" and task.get("status") in {"queued", "planning", "running", "waiting_approval"}:
                if not _can_mark_task_completed(task):
                    result = task.setdefault("result", {})
                    result["completion_blocked_by_audit"] = True
                    result.setdefault("summary", "Graph-node completion did not auto-close this production task because artifact audit is not verified.")
                    continue
                task["status"] = "completed"
                task["updated_at"] = now
                result = task.setdefault("result", {})
                result.setdefault("summary", "Task auto-completed because the owning graph node has already completed.")
                updated_task_ids.append(task_id)
                if checkpoints.pop(task_id, None) is not None:
                    removed_checkpoints.append(task_id)
            elif task.get("status") in {"completed", "failed", "timed_out", "cancelled"}:
                if checkpoints.pop(task_id, None) is not None:
                    removed_checkpoints.append(task_id)

    if updated_task_ids:
        _save_json(TASKS, tasks)
    if removed_checkpoints:
        _save_json(TASK_CHECKPOINTS, checkpoints)
    return {
        "completed_from_graph_nodes": len(updated_task_ids),
        "task_ids": updated_task_ids,
        "removed_checkpoints": removed_checkpoints,
    }


def reconcile_core_messages() -> dict[str, Any]:
    messages = _load_json(CORE_MESSAGES, [])
    tasks = {item.get("id"): item for item in _load_json(TASKS, [])}
    now = datetime.now(timezone.utc)
    updated = []
    severity_counts = {"error": 0, "warning": 0}
    for item in messages:
        if item.get("status", "open") != "open":
            continue
        severity = str(item.get("severity") or "").strip().lower() or "warning"
        if severity not in {"error", "warning"}:
            continue
        body = (item.get("body") or "")
        body_lower = body.lower()
        created_at = _parse_time(item.get("created_at"))
        task = tasks.get(item.get("task_id"))
        task_status = (task or {}).get("status")
        stale_manual_gate = (
            "real execution requires task auto-approve when orch_approval_mode is manual" in body_lower
            and (
                (
                    created_at is not None
                    and now - created_at > timedelta(hours=STALE_ESCALATION_HOURS)
                    and (task is None or task_status in {"completed", "failed", "timed_out", "cancelled"})
                )
                or (
                    created_at is not None
                    and now - created_at > timedelta(minutes=STALE_SMOKE_MINUTES)
                    and any(marker in body_lower for marker in SMOKE_CALLERS)
                )
            )
        )
        stale_permission_denied = _is_permission_denied_escalation(item, task, task_status, created_at, now)
        stale_connection_error = _is_connection_failure_escalation(item, task_status, created_at, now)
        stale_core_guidance_pause = _is_stale_core_guidance_pause(item, task, task_status, created_at, now)
        stale_requeued_pause = _is_requeued_pause_escalation(item, task, task_status, created_at, now)
        stale_audit_schema_rejection = _is_stale_audit_schema_rejection(item, task, task_status, created_at, now)
        if not stale_manual_gate and not stale_permission_denied and not stale_connection_error and not stale_core_guidance_pause and not stale_requeued_pause and not stale_audit_schema_rejection:
            continue
        item["status"] = "auto-resolved"
        item["resolved_at"] = _utc()
        if stale_permission_denied:
            item["resolution"] = "Auto-resolved as stale permission-denied escalation after the runtime self-heal window elapsed without a live owning task."
        elif stale_connection_error:
            item["resolution"] = "Auto-resolved as stale connection/timeout escalation after the task left the blocked state or re-entered scheduling."
        elif stale_core_guidance_pause:
            item["resolution"] = "Auto-resolved as stale sandbox/core-guidance pause after the owning task completed or was requeued by runtime maintenance."
        elif stale_requeued_pause:
            item["resolution"] = "Auto-resolved as stale paused-task escalation after runtime timed out the owning task and requested requeue."
        elif stale_audit_schema_rejection:
            item["resolution"] = "Auto-resolved as stale audit schema rejection after structured audit validation was restored."
        else:
            item["resolution"] = "Auto-resolved as stale manual-approval smoke escalation after runtime policy reconciliation."
        updated.append(item.get("id"))
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    if updated:
        _save_json(CORE_MESSAGES, messages)
    return {
        "auto_resolved_errors": severity_counts.get("error", 0),
        "auto_resolved_warnings": severity_counts.get("warning", 0),
        "auto_resolved_messages": len(updated),
        "message_ids": updated,
    }







