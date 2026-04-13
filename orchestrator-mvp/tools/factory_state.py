from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
FACTORY_STATE_PATH = DATA / "factory_state.json"
STATUS_PATH = DATA / "factory_daemon_state.json"
STATUS_CACHE_PATH = DATA / "status_cache.json"
TASKS_PATH = DATA / "tasks.json"
CORE_MESSAGES_PATH = DATA / "core_messages.json"
CONTROL_PATH = DATA / "control_layer_status.json"
AI_TEST_PATH = DATA / "ai_test_status.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"
TRUE_RUNNING_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
EXECUTION_FINISHING_STATUSES = {"execution_finished"}
PENDING_STATUSES = {"queued", "waiting_approval"}
BLOCKED_STATUSES = {"blocked", "failed", "timed_out", "cancelled", "verification_failed"}
RECOVERY_MARKERS = ("recovery", "execution recovery", "recover stable execution output")
MAINLINE_MARKERS = ("toyos", "toy-os", "generated/toy-os-demo")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except PermissionError:
            time.sleep(0.1 * (attempt + 1))
        except Exception:
            return default
    return default


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _task_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    true_running = 0
    execution_finishing = 0
    pending = 0
    blocked = 0
    recovery_running = 0
    mainline_running = 0
    terminal_statuses = {"completed", "failed", "timed_out", "cancelled"}
    active_tasks: list[str] = []
    for item in tasks:
        status = str(item.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        corpus = " ".join(
            str(part or "")
            for part in [
                item.get("title"),
                item.get("goal"),
                item.get("prompt"),
                item.get("repo_path"),
                (item.get("scheduler_hint") or {}).get("goal_target"),
                (item.get("scheduler_hint") or {}).get("node_title"),
                " ".join(str(value) for value in ((item.get("scheduler_hint") or {}).get("required_artifacts") or []) if value),
            ]
        ).lower()
        scheduler_hint = item.get("scheduler_hint") or {}
        if status in TRUE_RUNNING_STATUSES and item.get("id"):
            active_tasks.append(str(item.get("id")))
        if status in TRUE_RUNNING_STATUSES:
            true_running += 1
            if any(marker in corpus for marker in RECOVERY_MARKERS) or bool(scheduler_hint.get("recovery_task")):
                recovery_running += 1
            if any(marker in corpus for marker in MAINLINE_MARKERS) or str(item.get("execution_mode") or "").strip().lower() == "production":
                mainline_running += 1
        elif status in EXECUTION_FINISHING_STATUSES:
            execution_finishing += 1
        if status in PENDING_STATUSES:
            pending += 1
        if status in BLOCKED_STATUSES:
            blocked += 1
    return {
        "total": len(tasks),
        "active": true_running,
        "active_including_finishing": true_running + execution_finishing,
        "true_running": true_running,
        "execution_finishing": execution_finishing,
        "pending": pending,
        "blocked": blocked,
        "recovery_running": recovery_running,
        "mainline_running": mainline_running,
        "terminal": sum(statuses.get(name, 0) for name in terminal_statuses),
        "by_status": statuses,
        "active_task_ids": active_tasks[:20],
    }


def _message_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    open_items = [item for item in messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_items if item.get("severity") == "error"]
    open_warnings = [item for item in open_items if item.get("severity") == "warning"]
    return {
        "open_total": len(open_items),
        "open_errors": len(open_errors),
        "open_warnings": len(open_warnings),
        "open_error_titles": [str(item.get("title") or "") for item in open_errors[:10]],
    }


def _consistency_checks(
    daemon_state: dict[str, Any],
    status_cache: dict[str, Any],
    tasks: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    daemon_status = str(daemon_state.get("status") or "")
    cache_daemon = status_cache.get("daemon") or {}
    cache_control = status_cache.get("control_layer") or {}
    cache_ai = status_cache.get("ai_testing") or {}
    message_summary = _message_summary(messages)
    task_summary = _task_summary(tasks)
    daemon_cycle = int(daemon_state.get("cycle") or 0)
    cache_cycle = int(cache_daemon.get("cycle") or status_cache.get("cycle") or 0)
    if daemon_cycle and cache_cycle and daemon_cycle != cache_cycle:
        findings.append({
            "code": "cycle_mismatch",
            "severity": "warning",
            "detail": f"factory_daemon_state cycle={daemon_cycle} differs from status_cache cycle={cache_cycle}",
        })
    if daemon_status == "running" and message_summary["open_errors"] > 0:
        findings.append({
            "code": "running_with_open_errors",
            "severity": "attention",
            "detail": f"daemon is running while {message_summary['open_errors']} error escalations remain open",
        })
    if str(cache_control.get("status") or "") == "stable" and str(cache_ai.get("status") or "") not in {"pass", ""}:
        findings.append({
            "code": "stable_control_with_ai_attention",
            "severity": "warning",
            "detail": f"control is stable while ai_testing={cache_ai.get('status')}",
        })
    if task_summary["active"] == 0 and daemon_status == "running":
        findings.append({
            "code": "idle_runtime",
            "severity": "info",
            "detail": "daemon is healthy but currently has no active tasks",
        })
    daemon_tick = _parse_ts(daemon_state.get("last_tick_at"))
    cache_tick = _parse_ts(cache_daemon.get("last_tick_at"))
    lag_seconds = None
    if daemon_tick and cache_tick:
        lag_seconds = round(abs((daemon_tick - cache_tick).total_seconds()), 3)
    overall = "consistent"
    if any(item["severity"] == "attention" for item in findings):
        overall = "attention"
    elif any(item["severity"] == "warning" for item in findings):
        overall = "warning"
    return {
        "status": overall,
        "finding_count": len(findings),
        "findings": findings,
        "tick_lag_seconds": lag_seconds,
    }


def build_factory_state(
    *,
    daemon_state: dict[str, Any] | None = None,
    status_cache: dict[str, Any] | None = None,
    last_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    daemon_state = daemon_state or _load_json(STATUS_PATH, {})
    status_cache = status_cache or _load_json(STATUS_CACHE_PATH, {})
    tasks = _load_json(TASKS_PATH, [])
    messages = _load_json(CORE_MESSAGES_PATH, [])
    control_layer = _load_json(CONTROL_PATH, {})
    ai_testing = _load_json(AI_TEST_PATH, {})
    release_ops = _load_json(RELEASE_OPS_PATH, {})
    consistency = _consistency_checks(daemon_state, status_cache, tasks, messages)
    task_runtime = _task_summary(tasks)
    delivery_summary = {
        "completed_tasks": int(task_runtime["by_status"].get("completed") or 0) + int(task_runtime["by_status"].get("released") or 0),
        "delivery_ready_tasks": int(task_runtime["by_status"].get("delivery_ready") or 0),
        "released_tasks": int(task_runtime["by_status"].get("released") or 0),
        "verification_failed_tasks": int(task_runtime["by_status"].get("verification_failed") or 0),
    }
    return {
        "updated_at": _utc(),
        "source_of_truth": "factory_state",
        "sources": {
            "daemon": str(STATUS_PATH),
            "status_cache": str(STATUS_CACHE_PATH),
            "tasks": str(TASKS_PATH),
            "core_messages": str(CORE_MESSAGES_PATH),
        },
        "daemon": {
            "status": daemon_state.get("status"),
            "pid": daemon_state.get("pid"),
            "cycle": daemon_state.get("cycle"),
            "started_at": daemon_state.get("started_at"),
            "last_tick_at": daemon_state.get("last_tick_at"),
            "heartbeat_at": daemon_state.get("heartbeat_at"),
            "last_error": daemon_state.get("last_error"),
        },
        "task_runtime": task_runtime,
        "delivery_summary": delivery_summary,
        "messages": _message_summary(messages),
        "control_layer": {
            "status": (status_cache.get("control_layer") or {}).get("status", control_layer.get("status")),
            "quality_score": (status_cache.get("control_layer") or {}).get("quality_score", control_layer.get("quality_score")),
            "quality_status": (status_cache.get("control_layer") or {}).get("quality_status", ((control_layer.get("quality_system") or {}).get("status"))),
        },
        "engineering_os": status_cache.get("engineering_os") or {},
        "autonomy": status_cache.get("autonomy") or {},
        "tool_health": status_cache.get("tool_health") or {},
        "ai_testing": {
            "status": (status_cache.get("ai_testing") or {}).get("status", ai_testing.get("status")),
            "pass_rate": (status_cache.get("ai_testing") or {}).get("pass_rate", ai_testing.get("pass_rate")),
            "error_count": (status_cache.get("ai_testing") or {}).get("error_count", ai_testing.get("error_count")),
            "failing_case_ids": (status_cache.get("ai_testing") or {}).get("failing_case_ids", ai_testing.get("failing_case_ids", [])),
            "updated_at": (status_cache.get("ai_testing") or {}).get("updated_at", ai_testing.get("updated_at")),
        },
        "release_ops": status_cache.get("release_ops") or {
            "status": release_ops.get("status"),
            "release_train_status": (release_ops.get("release_train") or {}).get("status"),
        },
        "policy_schedule": status_cache.get("policy_schedule") or {},
        "consistency": consistency,
        "last_result_summary": {
            "has_result": bool(last_result or daemon_state.get("last_result")),
            "top_level_keys": sorted(list((last_result or daemon_state.get("last_result") or {}).keys()))[:30],
        },
    }


def publish_factory_state(
    *,
    daemon_state: dict[str, Any] | None = None,
    status_cache: dict[str, Any] | None = None,
    last_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_factory_state(
        daemon_state=daemon_state,
        status_cache=status_cache,
        last_result=last_result,
    )
    atomic_write_json(FACTORY_STATE_PATH, payload)
    return payload
