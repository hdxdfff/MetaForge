from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.artifact_audit import summarize_verified_completed_tasks
from tools.execution_trace import append_trace
from tools.io_utils import atomic_write_json

TASKS_PATH = DATA / "tasks.json"
TASK_HISTORY_PATH = DATA / "task_history.json"
TASK_ARCHIVE_PATH = DATA / "task_archive.json"
CONTINUITY_PATH = DATA / "continuity_metrics.json"
STAGE5_PATH = DATA / "stage5_dashboard.json"
INDUSTRIAL_READINESS_PATH = DATA / "industrial_readiness.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
AUTONOMY_PATH = DATA / "autonomy_score.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
INCIDENT_SUMMARY_PATH = DATA / "incident_ledger_summary.json"
QUEUE_PRESSURE_PATH = DATA / "queue_pressure_analysis.json"
ROLLBACK_DRILL_PATH = DATA / "release_rollback_drill.json"
EVO_LEDGER_PATH = DATA / "evolution_ledger.json"
BLOCKED_TO_DONE_PATH = DATA / "blocked_to_done_transitions.json"
GOAL_BACKLOG_STATUS_PATH = DATA / "goal_backlog_status.json"
ARTIFACT_GROWTH_STATUS_PATH = DATA / "artifact_growth_status.json"
CAPABILITY_BUILDER_STATUS_PATH = DATA / "capability_builder_status.json"
FAILURE_BACKLOG_REPORT_PATH = DATA / "task_backlog_automation.json"
OUTPUT_PATH = DATA / "industrial_operations.json"
TAXONOMY_PATH = DATA / "industrial_failure_taxonomy.json"

WINDOWS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}
DEFAULT_BUDGETS = {
    "self_repair_daily": 5,
    "artifact_growth_daily": 2,
    "capability_expansion_daily": 1,
    "sandbox_p2_daily": 1,
    "research_daily": 1,
}
DEFAULT_POOL_LIMITS = {"P0": 4, "P1": 2, "P2": 1, "P3": 1}
FAILURE_STRATEGIES = {
    "dispatch_failure": {
        "priority": "P1",
        "repair_kind": "dispatch_repair",
        "action": "repair admission, queue, or scheduler routing and rerun a dispatch smoke",
        "verification": ["dispatch smoke", "queue sanity", "status refresh"],
    },
    "execution_failure": {
        "priority": "P0",
        "repair_kind": "execution_repair",
        "action": "repair the failing execution path with the smallest bounded patch and rerun local execution",
        "verification": ["local execution", "py_compile", "status refresh"],
    },
    "verification_failure": {
        "priority": "P1",
        "repair_kind": "verification_repair",
        "action": "add a minimal repro plus the missing validator or assertion and rerun verification",
        "verification": ["validator smoke", "regression check", "status refresh"],
    },
    "artifact_audit_failure": {
        "priority": "P1",
        "repair_kind": "artifact_repair",
        "action": "restore evidence, manifest, or reproducibility assets and rerun artifact audit",
        "verification": ["artifact audit", "manifest check", "evidence check"],
    },
    "rollback_failure": {
        "priority": "P1",
        "repair_kind": "rollback_repair",
        "action": "fix rollback wiring, then rerun rollback drill before any expansion",
        "verification": ["rollback drill", "release readiness", "status refresh"],
    },
    "environment_failure": {
        "priority": "P1",
        "repair_kind": "environment_repair",
        "action": "repair the runtime environment, paths, dependencies, or sandbox assumptions",
        "verification": ["environment smoke", "path check", "status refresh"],
    },
    "policy_gate_failure": {
        "priority": "P1",
        "repair_kind": "policy_repair",
        "action": "adjust the policy or gate inputs with a minimal safe change and rerun the gate",
        "verification": ["gate refresh", "release readiness", "status refresh"],
    },
    "permission_failure": {
        "priority": "P1",
        "repair_kind": "permission_repair",
        "action": "repair path access, execution policy, or privilege boundary and rerun the task",
        "verification": ["permission smoke", "workspace write check", "status refresh"],
    },
    "provider_failure": {
        "priority": "P2",
        "repair_kind": "fallback_repair",
        "action": "switch to fallback provider, cheap-first routing, or cached evidence path",
        "verification": ["fallback smoke", "provider probe", "status refresh"],
    },
    "flaky_failure": {
        "priority": "P1",
        "repair_kind": "stability_repair",
        "action": "stabilize retries, isolate nondeterminism, and rerun the failing path repeatedly",
        "verification": ["repeat smoke", "flake repro", "status refresh"],
    },
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        stamp = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(stamp)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _task_timestamp(item: dict[str, Any]) -> datetime | None:
    return _parse_time(item.get("updated_at") or item.get("completed_at") or item.get("created_at") or item.get("heartbeat_at"))


def _latest_records(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    for source in sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or item.get("task_id") or "").strip()
            if not item_id:
                anonymous.append(item)
                continue
            existing = merged.get(item_id)
            existing_time = _task_timestamp(existing) if existing else None
            item_time = _task_timestamp(item)
            if existing is None or (item_time or min_time) >= (existing_time or min_time):
                merged[item_id] = item
    return list(merged.values()) + anonymous


def _task_corpus(task: dict[str, Any]) -> str:
    result = task.get("result") or {}
    scheduler_hint = task.get("scheduler_hint") or {}
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("prompt"),
        task.get("repo_path"),
        task.get("task_type"),
        task.get("queue_name"),
        result.get("error") if isinstance(result, dict) else None,
        result.get("summary") if isinstance(result, dict) else None,
        scheduler_hint.get("template_id"),
        scheduler_hint.get("goal_primary"),
        scheduler_hint.get("goal_target"),
    ]
    return " ".join(_normalize(part) for part in parts if _normalize(part))


def _is_terminal_success(task: dict[str, Any]) -> bool:
    status = _normalize(task.get("status"))
    if status not in {"completed", "delivery_ready", "released"}:
        return False
    result = task.get("result") or {}
    if isinstance(result, dict):
        production_evidence = result.get("production_evidence")
        if isinstance(production_evidence, dict) and _normalize(production_evidence.get("status")) == "verified":
            return True
        if bool(result.get("verified")):
            return True
    return True


def _is_terminal_failure(task: dict[str, Any]) -> bool:
    return _normalize(task.get("status")) in {"failed", "timed_out", "cancelled", "verification_failed"}


def _classify_failure(task: dict[str, Any]) -> str:
    corpus = _task_corpus(task)
    if not _is_terminal_failure(task):
        return "other"
    if any(marker in corpus for marker in ("permission denied", "access is denied", "[winerror 5]", "access denied")):
        return "permission_failure"
    if any(marker in corpus for marker in ("rollback", "revert", "rollback drill")):
        return "rollback_failure"
    if any(marker in corpus for marker in ("artifact", "manifest", "evidence", "audit")):
        return "artifact_audit_failure"
    if any(marker in corpus for marker in ("verification", "validation", "smoke", "test", "assert")):
        return "verification_failure"
    if any(marker in corpus for marker in ("gate", "policy", "release gate")):
        return "policy_gate_failure"
    if any(marker in corpus for marker in ("dispatch", "scheduler", "queue", "admission")):
        return "dispatch_failure"
    if any(marker in corpus for marker in ("environment", "filesystem", "path", "docker", "container", "dependency")):
        return "environment_failure"
    if any(marker in corpus for marker in ("provider", "network", "connection", "auth", "rate limit", "timeout")):
        return "provider_failure"
    if any(marker in corpus for marker in ("flaky", "intermittent", "unstable")):
        return "flaky_failure"
    return "execution_failure"


def _task_cycle_minutes(task: dict[str, Any]) -> float | None:
    created = _parse_time(task.get("created_at"))
    updated = _task_timestamp(task)
    if created is None or updated is None or updated < created:
        return None
    return round((updated - created).total_seconds() / 60.0, 2)


def _artifact_latest_time(artifact: dict[str, Any]) -> datetime | None:
    checks = artifact.get("checks") or {}
    values = [
        _parse_time(artifact.get("updated_at")),
        _parse_time(checks.get("latest_evidence_at")),
        _parse_time(checks.get("build_timestamp")),
        _parse_time(checks.get("test_timestamp")),
        _parse_time(checks.get("execution_timestamp")),
        _parse_time(checks.get("qemu_timestamp")),
    ]
    candidates = [item for item in values if item is not None]
    return max(candidates) if candidates else None


def _window_summary(records: list[dict[str, Any]], artifacts: list[dict[str, Any]], window_hours: int, continuity: dict[str, Any] | None = None) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    window_tasks = [item for item in records if (_task_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    completed = [item for item in window_tasks if _is_terminal_success(item)]
    failed = [item for item in window_tasks if _is_terminal_failure(item)]
    cycle_samples = [cycle for cycle in (_task_cycle_minutes(item) for item in completed) if cycle is not None]
    window_artifacts = [item for item in artifacts if (_artifact_latest_time(item) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    real_artifacts = [item for item in window_artifacts if bool(item.get("real"))]
    real_pass_rate = round(len(real_artifacts) / max(1, len(window_artifacts)), 4) if window_artifacts else None
    verified_completed = len(completed)
    unverified_completed = 0
    if window_hours == 24:
        verified_summary = summarize_verified_completed_tasks(records, records, hours=window_hours)
        continuity_tasks = (((continuity or {}).get("windows") or {}).get("24") or {}).get("tasks") or {}
        continuity_artifacts = (((continuity or {}).get("windows") or {}).get("24") or {}).get("artifacts") or {}
        verified_completed = int(continuity_tasks.get("verified_completed_tasks") or verified_summary.get("verified_completed_tasks_last_24h", 0) or len(completed))
        unverified_completed = int(continuity_tasks.get("unverified_completed_tasks") or verified_summary.get("unverified_completed_tasks_last_24h", 0) or 0)
        if continuity_tasks:
            completed = [*completed]
            failed = [*failed]
            real_artifacts = [item for item in real_artifacts]
            window_artifacts = [item for item in window_artifacts]
            if continuity_tasks.get("completed_tasks") is not None:
                completed_count = int(continuity_tasks.get("completed_tasks") or 0)
            else:
                completed_count = len(completed)
            if continuity_tasks.get("verified_completed_tasks") is not None:
                verified_completed = int(continuity_tasks.get("verified_completed_tasks") or 0)
            task_success_rate = round(verified_completed / max(1, completed_count), 4) if completed_count else None
            real_total = int(continuity_artifacts.get("real_artifacts") or len(real_artifacts))
            artifact_total = int(continuity_artifacts.get("artifacts_total") or len(window_artifacts))
            real_pass_rate = round(real_total / max(1, artifact_total), 4) if artifact_total else None
            return {
                "hours": window_hours,
                "completed_tasks": completed_count,
                "verified_completed_tasks": verified_completed,
                "unverified_completed_tasks": unverified_completed,
                "failed_tasks": max(0, completed_count - verified_completed),
                "task_success_rate": task_success_rate,
                "median_task_cycle_minutes": continuity_tasks.get("median_task_cycle_minutes") or (round(sorted(cycle_samples)[len(cycle_samples) // 2], 2) if cycle_samples else None),
                "real_artifacts": real_total,
                "artifacts_total": artifact_total,
                "real_artifact_pass_rate": real_pass_rate,
                "artifact_lane_diversity": len({str(item.get("type") or "").strip().lower() for item in real_artifacts if str(item.get("type") or "").strip()}),
            }
    return {
        "hours": window_hours,
        "completed_tasks": len(completed),
        "verified_completed_tasks": verified_completed,
        "unverified_completed_tasks": unverified_completed,
        "failed_tasks": len(failed),
        "task_success_rate": round(len(completed) / max(1, len(completed) + len(failed)), 4) if (completed or failed) else None,
        "median_task_cycle_minutes": round(sorted(cycle_samples)[len(cycle_samples) // 2], 2) if cycle_samples else None,
        "real_artifacts": len(real_artifacts),
        "artifacts_total": len(window_artifacts),
        "real_artifact_pass_rate": real_pass_rate,
        "artifact_lane_diversity": len({str(item.get("type") or "").strip().lower() for item in real_artifacts if str(item.get("type") or "").strip()}),
    }


def _failure_taxonomy(records: list[dict[str, Any]]) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOWS["30d"])
    classified: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        ts = _task_timestamp(item)
        if ts is None or ts < cutoff:
            continue
        category = _classify_failure(item)
        if category == "other":
            continue
        classified.setdefault(category, []).append(item)
    categories: dict[str, Any] = {}
    for category, items in sorted(classified.items(), key=lambda pair: len(pair[1]), reverse=True):
        categories[category] = {
            "count_30d": len(items),
            "last_seen_at": _iso(max((_task_timestamp(item) for item in items if _task_timestamp(item) is not None), default=None)),
            "default_strategy": FAILURE_STRATEGIES.get(category, {}),
            "sample_task_ids": [str(item.get("id") or item.get("task_id") or "") for item in items[:5] if item.get("id") or item.get("task_id")],
        }
    return {
        "updated_at": _utc(),
        "status": "pass",
        "window_hours": WINDOWS["30d"],
        "total_classified_failures_30d": sum(item["count_30d"] for item in categories.values()),
        "categories": categories,
        "default_strategies": FAILURE_STRATEGIES,
    }


def _blocked_to_done_summary() -> dict[str, Any]:
    ledger = _load_json(BLOCKED_TO_DONE_PATH, {})
    entries = ledger.get("entries") if isinstance(ledger, dict) else []
    if not isinstance(entries, list):
        entries = []
    successes = [item for item in entries if isinstance(item, dict) and _normalize(item.get("result")) == "success"]
    first_created = min((_parse_time(item.get("created_at")) for item in entries if isinstance(item, dict) and _parse_time(item.get("created_at")) is not None), default=None)
    last_completed = max((_parse_time(item.get("completed_at")) for item in successes if _parse_time(item.get("completed_at")) is not None), default=None)
    return {
        "status": "pass" if successes else "pending",
        "count": len(successes),
        "ledger_path": str(BLOCKED_TO_DONE_PATH),
        "first_created_at": _iso(first_created),
        "last_reduced_at": _iso(last_completed),
        "burndown_rate": round(len(successes) / max(1, len(entries)), 4) if entries else 0.0,
    }


def _compute_repair_progress(ledger: list[dict[str, Any]], kind: str, window_hours: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    return sum(
        1
        for item in ledger
        if isinstance(item, dict)
        and _normalize(item.get("type")) == kind
        and _normalize(item.get("result")) == "success"
        and (_parse_time(item.get("completed_at")) or _parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    )


def _task_kind(task: dict[str, Any]) -> str:
    scheduler_hint = task.get("scheduler_hint") or {}
    sandbox_lane = _normalize(scheduler_hint.get("sandbox_lane"))
    if sandbox_lane == "p2_low_risk":
        return "sandbox_p2"
    return _normalize(
        task.get("task_type")
        or task.get("queue_name")
        or scheduler_hint.get("lane")
        or scheduler_hint.get("queue_name")
        or ""
    )


def _count_window_tasks(records: list[dict[str, Any]], window_hours: int, *, kind: str | None = None) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    count = 0
    for item in records:
        ts = _task_timestamp(item)
        if ts is None or ts < cutoff:
            continue
        if kind is not None and _task_kind(item) != kind:
            continue
        count += 1
    return count


def _window_budget_state(records: list[dict[str, Any]], window_hours: int, kind: str, limit: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    window_items = [
        item
        for item in records
        if (_task_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
        and _task_kind(item) == kind
    ]
    used = len(window_items)
    remaining = max(0, int(limit) - used)
    oldest = min((_task_timestamp(item) for item in window_items if _task_timestamp(item) is not None), default=None)
    next_replenishment = _iso(oldest + timedelta(hours=window_hours)) if oldest is not None and remaining <= 0 else None
    return {
        "limit": int(limit),
        "used_24h": used,
        "remaining_24h": remaining,
        "headroom_ratio": round(remaining / max(1, int(limit)), 4),
        "burn_rate": round(used / max(1, int(limit)), 4),
        "window_basis": "rolling_24h",
        "next_replenishment_at": next_replenishment,
    }


def _ledger_budget_state(success_count: int, window_hours: int, kind: str, limit: int) -> dict[str, Any]:
    used = max(0, int(success_count))
    remaining = max(0, int(limit) - used)
    return {
        "limit": int(limit),
        "used_24h": used,
        "remaining_24h": remaining,
        "headroom_ratio": round(remaining / max(1, int(limit)), 4),
        "burn_rate": round(used / max(1, int(limit)), 4),
        "window_basis": f"rolling_{window_hours}h_ledger",
        "next_replenishment_at": None if remaining > 0 else _utc(),
        "source": f"{kind}_ledger",
    }


def run_industrial_operations() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    tasks = _load_json(TASKS_PATH, [])
    task_history = _load_json(TASK_HISTORY_PATH, [])
    task_archive = _load_json(TASK_ARCHIVE_PATH, [])
    artifact_registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    artifacts = artifact_registry.get("artifacts") if isinstance(artifact_registry, dict) else []
    if not isinstance(tasks, list):
        tasks = []
    if not isinstance(task_history, list):
        task_history = []
    if not isinstance(task_archive, list):
        task_archive = []
    if not isinstance(artifacts, list):
        artifacts = []
    latest_records = _latest_records(task_history, task_archive, tasks)
    stage5 = _load_json(STAGE5_PATH, {})
    industrial_readiness = _load_json(INDUSTRIAL_READINESS_PATH, {})
    release_ops = _load_json(RELEASE_OPS_PATH, {})
    control = _load_json(CONTROL_LAYER_PATH, {})
    autonomy = _load_json(AUTONOMY_PATH, {})
    continuity = _load_json(CONTINUITY_PATH, {})
    queue_pressure = _load_json(QUEUE_PRESSURE_PATH, {})
    incidents = _load_json(INCIDENT_SUMMARY_PATH, {})
    rollback_drill = _load_json(ROLLBACK_DRILL_PATH, {})
    evolution = _load_json(EVO_LEDGER_PATH, {})
    goal_backlog_status = _load_json(GOAL_BACKLOG_STATUS_PATH, {})
    artifact_growth_status = _load_json(ARTIFACT_GROWTH_STATUS_PATH, {})
    capability_builder_status = _load_json(CAPABILITY_BUILDER_STATUS_PATH, {})
    failure_backlog_report = _load_json(FAILURE_BACKLOG_REPORT_PATH, {})
    ledger_entries = evolution.get("entries") if isinstance(evolution, dict) else []
    if not isinstance(ledger_entries, list):
        ledger_entries = []

    windows = {label: _window_summary(latest_records, artifacts, hours, continuity) for label, hours in WINDOWS.items()}
    repair_24h = _compute_repair_progress(ledger_entries, "self_repair", WINDOWS["24h"])
    repair_7d = _compute_repair_progress(ledger_entries, "self_repair", WINDOWS["7d"])
    repair_30d = _compute_repair_progress(ledger_entries, "self_repair", WINDOWS["30d"])
    capability_24h = _compute_repair_progress(ledger_entries, "capability_expansion", WINDOWS["24h"])
    capability_7d = _compute_repair_progress(ledger_entries, "capability_expansion", WINDOWS["7d"])
    capability_30d = _compute_repair_progress(ledger_entries, "capability_expansion", WINDOWS["30d"])

    taxonomy = _failure_taxonomy(latest_records)
    atomic_write_json(TAXONOMY_PATH, taxonomy)

    historical_debt_archive = _load_json(DATA / "historical_failure_debt_archive.json", {})
    current_debt = int((historical_debt_archive or {}).get("failed_task_count") or 0)
    previous_state = _load_json(OUTPUT_PATH, {})
    previous_debt = int((previous_state or {}).get("historical_failure_debt_count") or 0)
    burndown = round(max(0, previous_debt - current_debt) / previous_debt, 4) if previous_debt > 0 else 0.0
    last_reduced_at = previous_state.get("historical_failure_debt_last_reduced_at") if current_debt >= previous_debt else _utc()
    if not last_reduced_at:
        last_reduced_at = _utc()

    release_ops_status = _normalize(release_ops.get("status"))
    readiness_status = _normalize(industrial_readiness.get("status"))
    real_artifact_pass_rate_24h = float(windows["24h"].get("real_artifact_pass_rate") or 0.0)
    task_success_rate_24h = float(windows["24h"].get("task_success_rate") or 0.0)
    current_queue_pressure = _normalize(queue_pressure.get("pressure"))
    control_policy = control.get("control_policy") if isinstance(control, dict) else {}
    incident_severity_counts = incidents.get("severity_counts") if isinstance(incidents, dict) else {}
    open_high_severity_incidents = int(incident_severity_counts.get("high") or 0) + int(incident_severity_counts.get("critical") or 0)
    control_release_status = _normalize(
        (control_policy.get("release") or {}).get("status")
        or (control.get("release") or {}).get("status")
        or control.get("status")
    )
    control_status = _normalize(control.get("status") or control_policy.get("status"))
    critical_conditions = [
        release_ops_status not in {"pass", "ready"},
        readiness_status not in {"pass", "ready"},
        real_artifact_pass_rate_24h < 0.95,
        task_success_rate_24h < 0.95,
        int(queue_pressure.get("active_pressure_score") or 0) >= 8,
        control_release_status not in {"pass", "ready", "advisory_signal", "signal-only"},
        control_status not in {"stable", "pass"},
    ]
    warning_conditions = [
        int(queue_pressure.get("active_pressure_score") or 0) >= 4,
        _normalize(autonomy.get("stage")) != "stage4_confirmed",
        open_high_severity_incidents > 0,
    ]
    freeze_reasons = []
    if not release_ops_status in {"pass", "ready"}:
        freeze_reasons.append("release_operations_not_pass")
    if not readiness_status in {"pass", "ready"}:
        freeze_reasons.append("industrial_readiness_not_pass")
    if real_artifact_pass_rate_24h < 0.95:
        freeze_reasons.append("real_artifact_pass_rate_below_threshold")
    if task_success_rate_24h < 0.95:
        freeze_reasons.append("task_success_rate_below_threshold")
    if int(queue_pressure.get("active_pressure_score") or 0) >= 8:
        freeze_reasons.append("queue_pressure_high")
    if control_release_status not in {"pass", "ready", "advisory_signal", "signal-only"}:
        freeze_reasons.append("control_release_not_pass")
    freeze_triggered = sum(1 for item in critical_conditions if item) >= 2
    operating_state = "freeze" if freeze_triggered else "degraded" if any(warning_conditions) or any(critical_conditions) else "normal"

    pool_limits = dict(DEFAULT_POOL_LIMITS)
    if operating_state == "freeze":
        pool_limits["P2"] = 0
        pool_limits["P3"] = 0
    elif operating_state == "degraded":
        pool_limits["P3"] = 0

    budget_usage = {
        "self_repair_daily": _ledger_budget_state(repair_24h, WINDOWS["24h"], "self_repair", DEFAULT_BUDGETS["self_repair_daily"]),
        "artifact_growth_daily": _window_budget_state(latest_records, WINDOWS["24h"], "artifact_growth", DEFAULT_BUDGETS["artifact_growth_daily"]),
        "capability_expansion_daily": _ledger_budget_state(capability_24h, WINDOWS["24h"], "capability_expansion", DEFAULT_BUDGETS["capability_expansion_daily"]),
        "sandbox_p2_daily": _window_budget_state(latest_records, WINDOWS["24h"], "sandbox_p2", DEFAULT_BUDGETS["sandbox_p2_daily"]),
        "research_daily": _window_budget_state(latest_records, WINDOWS["24h"], "research", DEFAULT_BUDGETS["research_daily"]),
    }
    budget_replenishment = {
        key: {
            "window_basis": value["window_basis"],
            "next_replenishment_at": value["next_replenishment_at"],
            "hours_until_replenishment": round(
                max(
                    0.0,
                    (
                        _parse_time(value["next_replenishment_at"]) - datetime.now(timezone.utc)
                    ).total_seconds() / 3600.0,
                ),
                2,
            ) if value["next_replenishment_at"] else None,
            "headroom_ratio": value["headroom_ratio"],
            "burn_rate": value["burn_rate"],
            "budget_exhausted": value["remaining_24h"] <= 0,
        }
        for key, value in budget_usage.items()
    }
    budget_suppression = {
        "goal_backlog": {
            "budget_suppressed_candidate_count": int(goal_backlog_status.get("budget_suppressed_candidate_count") or 0),
            "budget_gate_closed": int(goal_backlog_status.get("budget_suppressed_candidate_count") or 0) > 0,
            "goal_health": str(goal_backlog_status.get("goal_health") or ""),
            "last_replenishment_result": str(goal_backlog_status.get("last_replenishment_result") or ""),
        },
        "artifact_growth": {
            "status": str(artifact_growth_status.get("status") or ""),
            "created_items": int(artifact_growth_status.get("created_items") or 0),
            "skipped_due_to_budget": int(artifact_growth_status.get("skipped_due_to_budget") or 0),
            "budget_closed": str(artifact_growth_status.get("status") or "") == "budget_closed",
        },
        "capability_builder": {
            "status": str(capability_builder_status.get("status") or ""),
            "open_items_created": int(capability_builder_status.get("open_items_created") or 0),
            "budget_closed": str(capability_builder_status.get("status") or "") == "budget_closed",
        },
        "p2_sandbox": {
            "status": "open" if int(budget_usage["sandbox_p2_daily"]["remaining_24h"]) > 0 else "budget_closed",
            "created_items": int(budget_usage["sandbox_p2_daily"]["used_24h"] or 0),
            "budget_closed": int(budget_usage["sandbox_p2_daily"]["remaining_24h"] or 0) <= 0,
        },
        "failure_backlog_automation": {
            "created_count": int(failure_backlog_report.get("created_count") or 0),
            "toyos_created_count": len([
                item
                for item in (failure_backlog_report.get("created_tasks") or [])
                if isinstance(item, dict) and str(item.get("handling_mode") or "").strip().lower() == "toyos_replenishment"
            ]),
            "budget_suppressed_candidate_count": int(failure_backlog_report.get("budget_suppressed_candidate_count") or 0),
        },
    }

    daily_actions = {
        "verification_refresh": {
            "required": True,
            "met": bool(_parse_time(industrial_readiness.get("updated_at")) and _parse_time(industrial_readiness.get("updated_at")) >= datetime.now(timezone.utc) - timedelta(hours=24)),
            "source": str(INDUSTRIAL_READINESS_PATH),
        },
        "release_readiness_refresh": {
            "required": True,
            "met": bool(_parse_time(release_ops.get("updated_at")) and _parse_time(release_ops.get("updated_at")) >= datetime.now(timezone.utc) - timedelta(hours=24)),
            "source": str(RELEASE_OPS_PATH),
        },
        "rollback_drill": {
            "required": True,
            "met": bool(_parse_time(rollback_drill.get("finished_at") or rollback_drill.get("updated_at") or rollback_drill.get("measured_at")) and _parse_time(rollback_drill.get("finished_at") or rollback_drill.get("updated_at") or rollback_drill.get("measured_at")) >= datetime.now(timezone.utc) - timedelta(hours=24)),
            "source": str(ROLLBACK_DRILL_PATH),
        },
        "evidence_integrity_check": {
            "required": True,
            "met": bool(_parse_time(artifact_registry.get("updated_at")) and _parse_time(artifact_registry.get("updated_at")) >= datetime.now(timezone.utc) - timedelta(hours=24)),
            "source": str(ARTIFACT_REGISTRY_PATH),
        },
    }
    daily_actions_met = all(item["met"] for item in daily_actions.values())
    seven_day_acceptance = {
        "durability": bool(windows["7d"]["real_artifacts"] >= 3 and windows["7d"]["completed_tasks"] >= 15),
        "throughput": bool((windows["24h"]["task_success_rate"] or 0.0) >= 0.95 and (windows["24h"]["real_artifact_pass_rate"] or 0.0) >= 0.95),
        "conversion": bool(repair_7d >= 1 and capability_7d >= 1),
        "generalization": bool(windows["30d"]["artifact_lane_diversity"] >= 2),
        "daily_actions_met": daily_actions_met,
    }
    acceptance_pass = all(seven_day_acceptance.values())
    productivity_24h = int(windows["24h"]["verified_completed_tasks"] or 0) + int(windows["24h"]["real_artifacts"] or 0) + repair_24h + capability_24h
    productivity_7d = int(windows["7d"]["verified_completed_tasks"] or 0) + int(windows["7d"]["real_artifacts"] or 0) + repair_7d + capability_7d
    productivity_30d = int(windows["30d"]["verified_completed_tasks"] or 0) + int(windows["30d"]["real_artifacts"] or 0) + repair_30d + capability_30d
    trend = "flat"
    if productivity_24h > max(1.0, productivity_7d / 7.0) * 1.1:
        trend = "up"
    elif productivity_24h < max(1.0, productivity_7d / 7.0) * 0.9:
        trend = "down"

    payload = {
        "updated_at": _utc(),
        "status": operating_state,
        "current_state": {
            "control_layer_status": str(control.get("status") or ""),
            "release_operations_status": release_ops_status,
            "industrial_readiness_status": readiness_status,
            "autonomy_stage": str(autonomy.get("stage") or ""),
            "stable_autonomy": bool((autonomy.get("decision") or {}).get("stable_autonomy", autonomy.get("stable_autonomy", False))),
            "queue_pressure": current_queue_pressure,
        },
        "windows": windows,
        "productivity": {
            "trend": trend,
            "24h_score": productivity_24h,
            "7d_score": productivity_7d,
            "30d_score": productivity_30d,
        },
        "task_pools": {
            "limits": pool_limits,
            "priority_order": ["P0", "P1", "P2", "P3"],
            "notes": [
                "P0 stays highest priority for production delivery and regressions.",
                "P1 is repair-first and rollback-first.",
                "P2 is budgeted capability growth.",
                "P2 sandbox is the only low-risk P2 lane and stays narrowly capped.",
                "P3 is research and only runs when the system is healthy.",
            ],
        },
        "budgets": DEFAULT_BUDGETS,
        "budget_control": {
            "mode": "budgeted",
            "policy": {
                "P0": {
                    "limit": pool_limits["P0"],
                    "admission": "always_on",
                    "priority": "production_delivery",
                },
                "P1": {
                    "limit": pool_limits["P1"],
                    "admission": "repair_first",
                    "priority": "self_repair_and_rollback",
                },
            "P2": {
                "limit": pool_limits["P2"],
                "admission": "budgeted_growth",
                "priority": "capability_expansion_and_artifact_growth",
            },
            "P2_sandbox": {
                "limit": int(DEFAULT_BUDGETS["sandbox_p2_daily"]),
                "admission": "sandbox_low_risk",
                "priority": "low_risk_sandbox",
            },
            "P3": {
                "limit": pool_limits["P3"],
                "admission": "healthy_only",
                "priority": "research",
            },
            },
            "daily_budgets": DEFAULT_BUDGETS,
            "usage_24h": budget_usage,
            "replenishment": budget_replenishment,
            "gates": {
                "allow_p0": True,
                "allow_p1": True,
                "allow_p2": operating_state != "freeze" and int(budget_usage["capability_expansion_daily"]["remaining_24h"]) > 0,
                "allow_p2_sandbox": operating_state != "freeze" and int(budget_usage["sandbox_p2_daily"]["remaining_24h"]) > 0,
                "allow_p3": operating_state == "normal" and int(budget_usage["research_daily"]["remaining_24h"]) > 0,
                "repair_first": operating_state in {"degraded", "freeze"},
                "budget_enforced": True,
            },
        },
        "budget_suppression": budget_suppression,
        "daily_actions": daily_actions,
        "seven_day_acceptance": {
            **seven_day_acceptance,
            "status": "pass" if acceptance_pass else "attention",
        },
        "blocked_to_done": _blocked_to_done_summary(),
        "historical_failure_debt_count": current_debt,
        "historical_failure_debt_severity": "high" if current_debt >= 50 else "medium" if current_debt >= 10 else "low",
        "historical_failure_debt_burndown_rate": burndown,
        "historical_failure_debt_last_reduced_at": last_reduced_at,
        "failure_taxonomy_path": str(TAXONOMY_PATH),
        "failure_taxonomy": taxonomy,
        "release_freeze": {
            "status": operating_state,
            "freeze_triggered": freeze_triggered,
            "freeze_reasons": freeze_reasons,
            "allow_p0": True,
            "allow_p1": True,
            "allow_p2": operating_state != "freeze" and int(budget_usage["capability_expansion_daily"]["remaining_24h"]) > 0,
            "allow_p2_sandbox": operating_state != "freeze" and int(budget_usage["sandbox_p2_daily"]["remaining_24h"]) > 0,
            "allow_p3": operating_state == "normal" and int(budget_usage["research_daily"]["remaining_24h"]) > 0,
            "repair_first": operating_state in {"degraded", "freeze"},
            "release_freeze": operating_state == "freeze",
        },
        "recommendations": [
            "Keep P0 and repair-first lanes active while the freeze policy is degraded or frozen.",
            "Budget self-repair and capability growth explicitly before widening concurrency.",
            "Use the failure taxonomy to generate repair tasks rather than hand-adding generic follow-ups.",
            "Track historical failure debt separately from current operating state so normal operation can remain normal.",
            "Treat medium-severity open incidents as debt to clear, not as a reason to degrade the live operating state.",
            "Use rolling 24h replenishment signals to reopen P2/P3 only when headroom actually returns.",
            "Keep the P2 sandbox lane separate from the closed mainline P2 capability-expansion lane.",
        ],
        "source_files": {
            "tasks": str(TASKS_PATH),
            "task_history": str(TASK_HISTORY_PATH),
            "task_archive": str(TASK_ARCHIVE_PATH),
            "artifact_registry": str(ARTIFACT_REGISTRY_PATH),
            "continuity_metrics": str(CONTINUITY_PATH),
            "stage5_dashboard": str(STAGE5_PATH),
            "industrial_readiness": str(INDUSTRIAL_READINESS_PATH),
            "release_operations": str(RELEASE_OPS_PATH),
            "control_layer": str(CONTROL_LAYER_PATH),
            "autonomy_score": str(AUTONOMY_PATH),
            "queue_pressure": str(QUEUE_PRESSURE_PATH),
            "incident_summary": str(INCIDENT_SUMMARY_PATH),
            "rollback_drill": str(ROLLBACK_DRILL_PATH),
            "evolution_ledger": str(EVO_LEDGER_PATH),
            "goal_backlog_status": str(GOAL_BACKLOG_STATUS_PATH),
            "artifact_growth_status": str(ARTIFACT_GROWTH_STATUS_PATH),
            "capability_builder_status": str(CAPABILITY_BUILDER_STATUS_PATH),
            "failure_backlog_report": str(FAILURE_BACKLOG_REPORT_PATH),
        },
        "acceptance": {
            "7d_stability_pass": acceptance_pass,
            "durability_pass": seven_day_acceptance["durability"],
            "throughput_pass": seven_day_acceptance["throughput"],
            "conversion_pass": seven_day_acceptance["conversion"],
            "generalization_pass": seven_day_acceptance["generalization"],
            "daily_actions_met": daily_actions_met,
        },
    }
    atomic_write_json(OUTPUT_PATH, payload)
    append_trace(
        "industrial-readiness",
        "build industrial operations report",
        "run industrial_operations.py",
        f"status={payload['status']} freeze={payload['release_freeze']['freeze_triggered']} daily_actions_met={daily_actions_met}",
        "refresh industrial operations views or repair failing lanes",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={
            "status": payload["status"],
            "trend": trend,
            "real_artifact_pass_rate_24h": windows["24h"].get("real_artifact_pass_rate"),
            "task_success_rate_24h": windows["24h"].get("task_success_rate"),
            "freeze_triggered": freeze_triggered,
        },
    )
    return payload


def main() -> int:
    _ = argparse.ArgumentParser(description="Build an industrial operations dashboard and freeze policy.").parse_args()
    print(json.dumps(run_industrial_operations(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
