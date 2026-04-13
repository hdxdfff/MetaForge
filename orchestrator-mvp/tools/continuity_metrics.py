from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.artifact_audit import summarize_verified_completed_tasks
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
OUT = DATA / "continuity_metrics.json"

ARTIFACT_REGISTRY = DATA / "artifact_registry.json"
TASKS = DATA / "tasks.json"
TASK_HISTORY = DATA / "task_history.json"
TASK_ENGINE = DATA / "factory_task_engine_status.json"
CORE_MESSAGES = DATA / "core_messages.json"
REALITY_DASHBOARD = DATA / "reality_dashboard.json"
RELEASE_OPERATIONS = DATA / "release_operations_status.json"
AUTONOMY_SCORE = DATA / "autonomy_score.json"
CONTROL_LAYER = DATA / "control_layer_status.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _latest_task_view(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    for source in (task_history, tasks):
        for item in source:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("task_id") or item.get("id") or "").strip()
            if not task_id:
                anonymous.append(item)
                continue
            existing = merged.get(task_id)
            existing_time = _parse_ts((existing or {}).get("updated_at")) if existing else None
            item_time = _parse_ts(item.get("updated_at"))
            if existing is None or (item_time or min_time) >= (existing_time or min_time):
                merged[task_id] = item
    return list(merged.values()) + anonymous


def _artifact_window_metrics(registry: dict[str, Any], *, hours: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    artifacts = registry.get("artifacts") or []
    recent_real = []
    recent_valuable = []
    for item in artifacts:
        if not isinstance(item, dict) or not item.get("real"):
            continue
        latest = _parse_ts(((item.get("checks") or {}).get("latest_evidence_at")))
        if latest is None or latest < cutoff:
            continue
        recent_real.append(item)
        if (item.get("value") or {}).get("valuable"):
            recent_valuable.append(item)
    total_tasks = int(registry.get("artifact_count", 0) or 0)
    completed_tasks = int(summarize_verified_completed_tasks(_read_json(TASKS, []), _read_json(TASK_HISTORY, []), hours=hours).get("verified_completed_tasks_last_24h", 0) or 0)
    conversion_rate = round((len(recent_real) / completed_tasks) * 100.0, 2) if completed_tasks else 0.0
    value_conversion_rate = round((len(recent_valuable) / completed_tasks) * 100.0, 2) if completed_tasks else 0.0
    return {
        "real_artifacts": len(recent_real),
        "valuable_real_artifacts": len(recent_valuable),
        "artifacts_total": total_tasks,
        "technical_conversion_rate": conversion_rate,
        "value_conversion_rate": value_conversion_rate,
        "artifact_ids": [str(item.get("artifact_id") or "") for item in recent_real if item.get("artifact_id")],
        "technical_artifact_ids": [str(item.get("artifact_id") or "") for item in recent_real if item.get("artifact_id")],
        "valuable_artifact_ids": [str(item.get("artifact_id") or "") for item in recent_valuable if item.get("artifact_id")],
    }


def _task_window_metrics(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]], *, hours: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    completion_summary = summarize_verified_completed_tasks(tasks, task_history, hours=hours)
    verified_completed_task_ids = list(completion_summary.get("verified_completed_task_ids") or [])
    verified_completed_tasks = int(completion_summary.get("verified_completed_tasks_last_24h", 0) or 0)
    unverified_completed_tasks = int(completion_summary.get("unverified_completed_tasks_last_24h", 0) or 0)
    completed_total = 0
    released_total = 0
    delivery_ready_total = 0
    cycle_minutes: list[float] = []
    for item in _latest_task_view(tasks, task_history):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        ts = _parse_ts(item.get("updated_at") or item.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        if status in {"completed", "delivery_ready", "released"}:
            completed_total += 1
        if status == "released":
            released_total += 1
        if status == "delivery_ready":
            delivery_ready_total += 1
        created = _parse_ts(item.get("created_at"))
        updated = _parse_ts(item.get("updated_at"))
        if created and updated and updated >= created and status in {"completed", "delivery_ready", "released"}:
            cycle_minutes.append((updated - created).total_seconds() / 60.0)
    median_cycle_minutes = round(statistics.median(cycle_minutes), 2) if cycle_minutes else None
    auto_completion_ratio = round(verified_completed_tasks / completed_total, 4) if completed_total else None
    return {
        "verified_completed_tasks": verified_completed_tasks,
        "verified_completed_task_ids": verified_completed_task_ids,
        "unverified_completed_tasks": unverified_completed_tasks,
        "completed_tasks": completed_total,
        "released_tasks": released_total,
        "delivery_ready_tasks": delivery_ready_total,
        "median_task_cycle_minutes": median_cycle_minutes,
        "auto_completion_ratio": auto_completion_ratio,
    }


def _recovery_metrics(core_messages: list[dict[str, Any]], *, hours: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    auto_resolved = 0
    open_errors = 0
    for item in core_messages:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "").strip().lower()
        severity = str(item.get("severity") or "").strip().lower()
        ts = _parse_ts(item.get("resolved_at") or item.get("created_at") or item.get("updated_at"))
        if ts is None or ts < cutoff:
            continue
        if status == "auto-resolved":
            auto_resolved += 1
        if status == "open" and severity == "error":
            open_errors += 1
    total = auto_resolved + open_errors
    self_recovery_rate = round(auto_resolved / total, 4) if total else None
    return {
        "auto_resolved_messages": auto_resolved,
        "open_error_escalations": open_errors,
        "self_recovery_rate": self_recovery_rate,
    }


def _backlog_metrics(task_engine: dict[str, Any]) -> dict[str, Any]:
    supply = task_engine.get("supply_after_seed") or {}
    pools = supply.get("pools") or task_engine.get("pools") or {}
    production = pools.get("production") or {}
    ops = pools.get("ops") or {}
    return {
        "active_goal_count": int(supply.get("active_goal_count", 0) or 0),
        "active_task_count": int(supply.get("active_task_count", 0) or 0),
        "ready_node_count": int(supply.get("ready_node_count", task_engine.get("ready_node_count", 0)) or 0),
        "production_active_goal_count": int(production.get("active_goal_count", 0) or 0),
        "ops_active_goal_count": int(ops.get("active_goal_count", 0) or 0),
        "production_goal_targets": list(production.get("goal_targets") or [])[:5],
        "ops_goal_targets": list(ops.get("goal_targets") or [])[:5],
    }


def _window_thresholds(hours: int) -> dict[str, Any]:
    if hours == 24:
        return {
            "real_artifacts_min": 1,
            "verified_completed_tasks_min": 5,
            "median_task_cycle_minutes_max": 60,
            "self_recovery_rate_min": 0.75,
        }
    return {
        "real_artifacts_min": 3,
        "verified_completed_tasks_min": 15,
        "median_task_cycle_minutes_max": 90,
        "self_recovery_rate_min": 0.8,
    }


def build_continuity_metrics(*, write_outputs: bool = True) -> dict[str, Any]:
    registry = _read_json(ARTIFACT_REGISTRY, {})
    tasks = _read_json(TASKS, [])
    task_history = _read_json(TASK_HISTORY, [])
    core_messages = _read_json(CORE_MESSAGES, [])
    task_engine = _read_json(TASK_ENGINE, {})
    reality_dashboard = _read_json(REALITY_DASHBOARD, {})
    release_operations = _read_json(RELEASE_OPERATIONS, {})
    autonomy_score = _read_json(AUTONOMY_SCORE, {})
    control_layer = _read_json(CONTROL_LAYER, {})

    windows: dict[str, Any] = {}
    for hours in (24, 72):
        task_metrics = _task_window_metrics(tasks, task_history, hours=hours)
        artifact_metrics = _artifact_window_metrics(registry, hours=hours)
        recovery_metrics = _recovery_metrics(core_messages, hours=hours)
        windows[str(hours)] = {
            "hours": hours,
            "thresholds": _window_thresholds(hours),
            "tasks": task_metrics,
            "artifacts": artifact_metrics,
            "recovery": recovery_metrics,
            "backlog": _backlog_metrics(task_engine),
        }

    payload = {
        "updated_at": _utc(),
        "status": "active",
        "source_files": {
            "artifact_registry": str(ARTIFACT_REGISTRY),
            "tasks": str(TASKS),
            "task_history": str(TASK_HISTORY),
            "task_engine": str(TASK_ENGINE),
            "core_messages": str(CORE_MESSAGES),
            "reality_dashboard": str(REALITY_DASHBOARD),
            "release_operations": str(RELEASE_OPERATIONS),
            "autonomy_score": str(AUTONOMY_SCORE),
            "control_layer": str(CONTROL_LAYER),
        },
        "current_state": {
            "control_layer_status": str(control_layer.get("status") or ""),
            "autonomy_stage": str(autonomy_score.get("stage") or ""),
            "autonomy_score": float(autonomy_score.get("score", 0.0) or 0.0),
            "release_operations_status": str(release_operations.get("status") or ""),
            "artifact_registry_status": str(registry.get("status") or ""),
            "reality_dashboard_status": str(reality_dashboard.get("status") or ""),
        },
        "windows": windows,
        "coverage_notes": [
            "24h and 72h windows are the default observability bands for sustained output.",
            "Real artifacts are counted only when evidence is real and fresh within the window.",
            "Task cycle time is measured from task creation to final completion status.",
            "Blocked-to-done conversion requires a transition ledger and is intentionally not inferred from snapshot-only history.",
        ],
        "gaps": {
            "blocked_to_done_conversion_rate": {
                "status": "pending_transition_ledger",
                "reason": "task_history is snapshot-style, so blocked-to-done transitions cannot be inferred safely yet.",
            }
        },
    }
    if write_outputs:
        atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_continuity_metrics(write_outputs=True), ensure_ascii=False, indent=2))
