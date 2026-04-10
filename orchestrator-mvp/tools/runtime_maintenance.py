from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
ARCHIVE = DATA / "task_archive.json"
MEMORY_KERNEL = DATA / "memory_kernel.json"
DECISION_LOG = DATA / "decision_log.json"
TASK_HISTORY = DATA / "task_history.json"

from tools.io_utils import atomic_write_json

from tools.task_state_tools import (
    reconcile_execution_evidence_steps,
    reconcile_core_messages,
    reconcile_disabled_kernel_tasks,
    reconcile_goal_tasks,
    reconcile_graph_node_tasks,
    reconcile_stale_planning_tasks,
    reconcile_stale_smoke_tasks,
    reconcile_stale_running_tasks,
    reconcile_stale_task_heartbeats,
    reconcile_terminal_task_snapshots,
    reconcile_task_delivery_pipeline,
)
from tools.goal_runtime import sync_goal_runtime
from tools.goal_storage_audit import run_goal_storage_audit
from tools.failure_backlog_automation import run_failure_backlog_automation
from tools.schema_hygiene import run_schema_hygiene

ACTIVE_TIMEOUT_MINUTES = 120
ARCHIVE_AFTER_DAYS = 7
SMOKE_NOISE_ARCHIVE_STATUSES = {"timed_out", "failed", "cancelled"}
MAX_ARCHIVE = 500
MAX_TASK_HISTORY = 120
MAX_DECISION_LOG = 120


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
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


def _reconcile_duplicate_active_tasks(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for task in tasks:
        status = str(task.get('status') or '')
        if status not in {'queued', 'planning', 'running', 'waiting_approval'}:
            continue
        if task.get('goal_id') or task.get('node_id'):
            continue
        repo_path = str(task.get('repo_path') or '').strip().lower()
        goal = str(task.get('goal') or '').strip().lower()
        if not repo_path or not goal:
            continue
        groups.setdefault((repo_path, goal), []).append(task)

    retired: list[str] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ordered = sorted(
            group,
            key=lambda item: (_parse_time(item.get('updated_at') or item.get('created_at')) or datetime.min.replace(tzinfo=timezone.utc), str(item.get('id') or '')),
            reverse=True,
        )
        keeper = ordered[0]
        for stale in ordered[1:]:
            stale['status'] = 'completed'
            stale['updated_at'] = _utc()
            result = stale.setdefault('result', {})
            result['summary'] = f"Superseded by newer active task {keeper.get('id')} for goal {stale.get('goal')}."
            result['superseded_by'] = keeper.get('id')
            result['dedupe_reconciled'] = True
            retired.append(str(stale.get('id') or ''))
    return {
        'completed_duplicate_tasks': len(retired),
        'task_ids': [item for item in retired if item],
    }


def _archive_terminal_smoke_noise(tasks: list[dict[str, Any]], archive: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    kept: list[dict[str, Any]] = []
    archived: list[str] = []
    for task in tasks:
        status = str(task.get("status") or "")
        prompt = str(task.get("prompt") or "").lower()
        title = str(task.get("title") or "").lower()
        if status in SMOKE_NOISE_ARCHIVE_STATUSES and any(marker in prompt or marker in title for marker in ("smoke",)):
            archive.append({
                "task_id": task.get("id"),
                "status": task.get("status"),
                "goal": task.get("goal"),
                "repo_path": task.get("repo_path"),
                "updated_at": task.get("updated_at"),
                "archived_reason": "smoke_noise_cleanup",
            })
            archived.append(str(task.get("id") or ""))
            continue
        kept.append(task)
    return kept, archived


def run_smoke_hygiene(mode: str = "auto") -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    archive = _load_json(ARCHIVE, [])
    reconciled_smoke = reconcile_stale_smoke_tasks()
    tasks, archived_smoke_noise = _archive_terminal_smoke_noise(tasks, archive)
    if archived_smoke_noise:
        _save_json(TASKS, tasks)
        _save_json(ARCHIVE, archive[-MAX_ARCHIVE:])
    return {
        "status": "done",
        "mode": mode,
        "reconciled_smoke": reconciled_smoke,
        "archived_smoke_noise": archived_smoke_noise,
        "smoke_noise_cleanup_count": len(archived_smoke_noise),
    }


def maintain_tasks(mode: str = "full") -> dict[str, Any]:
    terminal_snapshots = reconcile_terminal_task_snapshots()
    evidence_backfill = reconcile_execution_evidence_steps()
    delivery_pipeline = reconcile_task_delivery_pipeline()
    auto_completed = delivery_pipeline["auto_completed"]
    delivery_ready = delivery_pipeline["delivery_ready"]
    heartbeat_recovery = reconcile_stale_task_heartbeats()
    timed_out = []
    archived = []

    if mode == "light":
        smoke_hygiene = run_smoke_hygiene(mode=mode)
        failure_backlog = run_failure_backlog_automation(mode=mode)
        return {
            "terminal_snapshots": terminal_snapshots,
            "evidence_backfill": evidence_backfill,
            "auto_completed": auto_completed,
            "delivery_ready": delivery_ready,
            "heartbeat_recovery": heartbeat_recovery,
            "smoke_hygiene": smoke_hygiene,
            "goal_runtime": {"status": "skipped", "reason": "light_mode"},
            "goal_storage": {"status": "skipped", "reason": "light_mode"},
            "reconciled": {"status": "skipped", "reason": "light_mode"},
            "reconciled_kernel": {"status": "skipped", "reason": "light_mode"},
            "reconciled_graph": {"status": "skipped", "reason": "light_mode"},
            "reconciled_smoke": smoke_hygiene["reconciled_smoke"],
            "reconciled_running": {"status": "skipped", "reason": "light_mode"},
            "reconciled_planning": {"status": "skipped", "reason": "light_mode"},
            "reconciled_messages": {"status": "skipped", "reason": "light_mode"},
            "reconciled_duplicates": {"completed_duplicate_tasks": 0, "task_ids": []},
            "archived_smoke_noise": smoke_hygiene["archived_smoke_noise"],
            "timed_out": timed_out,
            "archived": archived,
            "failure_backlog": failure_backlog,
            "active_timeout_minutes": ACTIVE_TIMEOUT_MINUTES,
        "archive_after_days": ARCHIVE_AFTER_DAYS,
        "mode": mode,
        }

    goal_runtime = sync_goal_runtime()
    goal_storage = run_goal_storage_audit()
    reconciled = reconcile_goal_tasks()
    reconciled_kernel = reconcile_disabled_kernel_tasks()
    reconciled_graph = reconcile_graph_node_tasks()
    smoke_hygiene = run_smoke_hygiene(mode=mode)
    reconciled_smoke = smoke_hygiene["reconciled_smoke"]
    archived_smoke_noise = smoke_hygiene["archived_smoke_noise"]
    reconciled_running = reconcile_stale_running_tasks()
    reconciled_planning = reconcile_stale_planning_tasks()
    reconciled_messages = reconcile_core_messages()
    tasks = _load_json(TASKS, [])
    reconciled_duplicates = _reconcile_duplicate_active_tasks(tasks)
    archive = _load_json(ARCHIVE, [])
    now = datetime.now(timezone.utc)
    kept = []

    for task in tasks:
        status = task.get("status")
        updated = _parse_time(task.get("updated_at") or task.get("created_at"))
        if status in {"queued", "planning", "running"} and updated and now - updated > timedelta(minutes=ACTIVE_TIMEOUT_MINUTES):
            task["status"] = "timed_out"
            task.setdefault("result", {})
            task["result"]["error"] = f"Task timed out after {ACTIVE_TIMEOUT_MINUTES} minutes without progress."
            task["updated_at"] = _utc()
            timed_out.append(task.get("id"))
            status = task["status"]

        if status in {"completed", "failed", "timed_out", "cancelled"} and updated and now - updated > timedelta(days=ARCHIVE_AFTER_DAYS):
            archive.append({
                "task_id": task.get("id"),
                "status": task.get("status"),
                "goal": task.get("goal"),
                "repo_path": task.get("repo_path"),
                "updated_at": task.get("updated_at"),
            })
            archived.append(task.get("id"))
            continue

        kept.append(task)

    if (
        reconciled_duplicates.get("completed_duplicate_tasks")
        or timed_out
        or archived
        or archived_smoke_noise
    ):
        _save_json(TASKS, kept)
    if archived or archived_smoke_noise:
        _save_json(ARCHIVE, archive[-MAX_ARCHIVE:])
    failure_backlog = run_failure_backlog_automation(mode=mode)

    return {
        "mode": mode,
        "terminal_snapshots": terminal_snapshots,
        "evidence_backfill": evidence_backfill,
        "auto_completed": auto_completed,
        "delivery_ready": delivery_ready,
        "heartbeat_recovery": heartbeat_recovery,
        "goal_runtime": goal_runtime,
        "goal_storage": goal_storage,
        "reconciled": reconciled,
        "reconciled_kernel": reconciled_kernel,
        "reconciled_graph": reconciled_graph,
        "reconciled_smoke": reconciled_smoke,
        "reconciled_running": reconciled_running,
        "reconciled_planning": reconciled_planning,
        "reconciled_messages": reconciled_messages,
        "reconciled_duplicates": reconciled_duplicates,
        "smoke_hygiene": smoke_hygiene,
        "archived_smoke_noise": archived_smoke_noise,
        "timed_out": timed_out,
        "archived": archived,
        "failure_backlog": failure_backlog,
        "active_timeout_minutes": ACTIVE_TIMEOUT_MINUTES,
        "archive_after_days": ARCHIVE_AFTER_DAYS,
    }


def compact_memory(mode: str = "full") -> dict[str, Any]:
    decision_log = _load_json(DECISION_LOG, [])
    if mode == "light":
        return {"decision_log_trimmed": 0, "task_history_trimmed": 0, "mode": mode}
    task_history = _load_json(TASK_HISTORY, [])
    kernel = _load_json(MEMORY_KERNEL, {})

    compacted = {
        "decision_log_trimmed": max(0, len(decision_log) - MAX_DECISION_LOG),
        "task_history_trimmed": max(0, len(task_history) - MAX_TASK_HISTORY),
    }

    if len(decision_log) > MAX_DECISION_LOG:
        decision_log = decision_log[-MAX_DECISION_LOG:]
        _save_json(DECISION_LOG, decision_log)
    if len(task_history) > MAX_TASK_HISTORY:
        task_history = task_history[:MAX_TASK_HISTORY]
        _save_json(TASK_HISTORY, task_history)

    kernel["compacted_at"] = _utc()
    kernel["retention"] = {
        "max_decision_log": MAX_DECISION_LOG,
        "max_task_history": MAX_TASK_HISTORY,
        "task_archive_days": ARCHIVE_AFTER_DAYS,
        "task_timeout_minutes": ACTIVE_TIMEOUT_MINUTES,
    }
    _save_json(MEMORY_KERNEL, kernel)
    return compacted


def run_maintenance(mode: str = "full") -> dict[str, Any]:
    task_info = maintain_tasks(mode=mode)
    memory_info = compact_memory(mode=mode)
    schema_hygiene = run_schema_hygiene(mode=mode)
    return {
        "updated_at": _utc(),
        "tasks": task_info,
        "mode": mode,
        "memory": memory_info,
        "schema_hygiene": schema_hygiene,
    }


if __name__ == "__main__":
    print(json.dumps(run_maintenance(), ensure_ascii=False, indent=2))
