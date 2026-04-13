from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any
from tools.autonomy_state import autonomy_is_confirmed

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.artifact_regression_validator import run_artifact_regression_validation
from tools.execution_trace import append_trace

RULES_PATH = DATA / "stage5_rules.json"
DASHBOARD_PATH = DATA / "stage5_dashboard.json"
QUEUE_PATH = DATA / "self_improvement_queue.json"
CAPABILITY_QUEUE_PATH = DATA / "capability_build_queue.json"
ARTIFACT_GROWTH_QUEUE_PATH = DATA / "artifact_growth_queue.json"
LEDGER_PATH = DATA / "evolution_ledger.json"
HISTORY_PATH = DATA / "stage5_metrics_history.json"
TRANSITION_LEDGER_PATH = DATA / "blocked_to_done_transitions.json"
AUTONOMY_PATH = DATA / "autonomy_score.json"
CONTROL_LAYER_PATH = DATA / "control_layer_status.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
REALITY_DASHBOARD_PATH = DATA / "reality_dashboard.json"
RELEASE_OPS_PATH = DATA / "release_operations_status.json"
FACTORY_DAEMON_PATH = DATA / "factory_daemon_state.json"
TASKS_PATH = DATA / "tasks.json"
TASK_HISTORY_PATH = DATA / "task_history.json"
ARTIFACT_VALIDATION_PATH = DATA / "artifact_regression_validation.json"
HISTORICAL_FAILURE_DEBT_ARCHIVE_PATH = DATA / "historical_failure_debt_archive.json"
QUEUE_PRESSURE_PATH = DATA / "queue_pressure_analysis.json"
AMPLIFIER_OBSERVABILITY_PATH = DATA / "amplifier_observability.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_timestamp(value: Any) -> datetime | None:
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


def _within_days(value: Any, days: int, now: datetime | None = None) -> bool:
    ts = _parse_timestamp(value)
    if ts is None:
        return False
    now = now or datetime.now(timezone.utc)
    return ts >= now - timedelta(days=days)


def _queue_stats(queue: dict[str, Any]) -> dict[str, int]:
    return {
        "open": len(queue.get("open_items") or []),
        "in_progress": len(queue.get("in_progress_items") or []),
        "done": len(queue.get("done_items") or []),
        "failed": len(queue.get("failed_items") or []),
    }


def _queue_items_within_window(queue: dict[str, Any], amplifier_name: str, window_days: int, default_amplifier: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for section in ("open_items", "in_progress_items", "done_items", "failed_items"):
        for item in queue.get(section) or []:
            if not isinstance(item, dict):
                continue
            item_amplifier = str(item.get("amplifier") or default_amplifier or "")
            if item_amplifier != amplifier_name:
                continue
            if not _within_days(item.get("created_at") or item.get("updated_at"), window_days):
                continue
            copied = dict(item)
            copied["section"] = section
            items.append(copied)
    return items


def _load_task_records() -> list[dict[str, Any]]:
    records = _load_json(TASKS_PATH, [])
    return records if isinstance(records, list) else []


def _load_task_history_records() -> list[dict[str, Any]]:
    records = _load_json(TASK_HISTORY_PATH, [])
    return records if isinstance(records, list) else []


def _load_artifacts() -> list[dict[str, Any]]:
    registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    artifacts = registry.get("artifacts") or []
    return artifacts if isinstance(artifacts, list) else []


def _count_real_artifacts(window_days: int) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for artifact in _load_artifacts():
        if not isinstance(artifact, dict) or not artifact.get("real"):
            continue
        checks = artifact.get("checks") or {}
        stamp = checks.get("latest_evidence_at") or checks.get("execution_timestamp") or checks.get("test_timestamp") or checks.get("build_timestamp")
        if _within_days(stamp, window_days, now=now):
            count += 1
    return count


def _count_successful_ledger_entries(ledger: dict[str, Any], entry_type: str, window_days: int) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    for entry in ledger.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type") or "") != entry_type:
            continue
        if str(entry.get("result") or "").lower() != "success":
            continue
        stamp = entry.get("completed_at") or entry.get("updated_at") or entry.get("created_at")
        if _within_days(stamp, window_days, now=now):
            count += 1
    return count


def _count_blocked_to_done_transitions(window_days: int) -> int:
    ledger = _load_json(TRANSITION_LEDGER_PATH, {})
    now = datetime.now(timezone.utc)
    count = 0
    for entry in ledger.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("result") or "").lower() != "success":
            continue
        if str(entry.get("from_state") or "").lower() != "blocked":
            continue
        if str(entry.get("to_state") or "").lower() != "done":
            continue
        stamp = entry.get("completed_at") or entry.get("updated_at") or entry.get("created_at")
        if _within_days(stamp, window_days, now=now):
            count += 1
    return count


def _task_window_stats(records: list[dict[str, Any]], window_days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_records = []
    for record in records:
        stamp = record.get("created_at") or record.get("updated_at")
        if _within_days(stamp, window_days, now=now):
            window_records.append(record)
    completed = [record for record in window_records if str(record.get("status") or "").lower() == "completed"]
    done_like = [record for record in window_records if str(record.get("status") or "").lower() in {"completed", "done", "released", "verified"}]
    first_result_minutes = []
    for record in completed:
        created_at = _parse_timestamp(record.get("created_at"))
        updated_at = _parse_timestamp(record.get("updated_at"))
        if created_at and updated_at and updated_at >= created_at:
            first_result_minutes.append((updated_at - created_at).total_seconds() / 60.0)
    total = len(window_records)
    completed_count = len(done_like)
    auto_ratio = completed_count / total if total else 0.0
    return {
        "total": total,
        "completed": completed_count,
        "auto_completed_ratio": round(auto_ratio, 4),
        "median_time_to_first_result_minutes": round(median(first_result_minutes), 2) if first_result_minutes else None,
    }


def _blocked_to_done_conversion() -> float | str:
    transitions = _count_blocked_to_done_transitions(7)
    completed = max(1, _count_successful_ledger_entries(_load_json(LEDGER_PATH, {}), "self_repair", 7) + _count_successful_ledger_entries(_load_json(LEDGER_PATH, {}), "capability_expansion", 7))
    return round(transitions / completed, 4) if transitions else 0.0


def _regression_fail_rate() -> float:
    report = _load_json(ARTIFACT_VALIDATION_PATH, {})
    if isinstance(report, dict) and report.get("artifact_count") is not None:
        failed = int(report.get("failed_count") or 0)
        total = max(1, int(report.get("artifact_count") or 0))
        return round(failed / total, 4)
    registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    status = str(registry.get("status") or "").lower()
    issue_count = int(registry.get("issue_count") or 0)
    if status == "pass":
        return 0.0
    return round(min(1.0, issue_count / max(1, len(_load_artifacts()))), 4)


def _productivity_trend(current: dict[str, Any], previous: dict[str, Any] | None) -> str:
    if not previous:
        return "flat"
    current_signal = (
        float(current.get("new_real_artifacts_7d") or 0)
        + float(current.get("self_repair_success_count_7d") or 0)
        + float(current.get("capability_expansion_count_7d") or 0)
    )
    previous_signal = (
        float(previous.get("new_real_artifacts_7d") or 0)
        + float(previous.get("self_repair_success_count_7d") or 0)
        + float(previous.get("capability_expansion_count_7d") or 0)
    )
    if current_signal > previous_signal:
        return "up"
    if current_signal < previous_signal:
        return "down"
    return "flat"


def _control_layer_status() -> str:
    control = _load_json(CONTROL_LAYER_PATH, {})
    return str(control.get("status") or control.get("control_policy", {}).get("mode") or "unknown")


def _autonomy_stage() -> str:
    autonomy = _load_json(AUTONOMY_PATH, {})
    return str(autonomy.get("stage") or "unknown")


def _stable_autonomy() -> bool:
    autonomy = _load_json(AUTONOMY_PATH, {})
    decision = autonomy.get("decision") or {}
    if isinstance(decision, dict) and "stable_autonomy" in decision:
        return bool(decision.get("stable_autonomy"))
    return bool(autonomy_is_confirmed(autonomy))


def _release_gate_signal_count() -> int | None:
    autonomy = _load_json(AUTONOMY_PATH, {})
    signal_policy = autonomy.get("signal_policy") or {}
    if isinstance(signal_policy, dict) and signal_policy.get("release_gate_signal_count") is not None:
        return int(signal_policy.get("release_gate_signal_count") or 0)
    release_ops = _load_json(RELEASE_OPS_PATH, {})
    readiness = release_ops.get("verification_release_gate") or {}
    sample_failures = readiness.get("sample_failures") or []
    return len(sample_failures) if isinstance(sample_failures, list) else 0


def _continuous_runtime_hours() -> float:
    daemon = _load_json(FACTORY_DAEMON_PATH, {})
    started_at = _parse_timestamp(daemon.get("started_at"))
    if not started_at:
        return 0.0
    return round((datetime.now(timezone.utc) - started_at).total_seconds() / 3600.0, 2)


def _historical_failure_debt() -> dict[str, Any]:
    archive = _load_json(HISTORICAL_FAILURE_DEBT_ARCHIVE_PATH, {})
    if not isinstance(archive, dict):
        archive = {}
    return {
        "historical_failure_debt_count": int(archive.get("historical_failure_debt_count") or archive.get("failed_task_count") or 0),
        "historical_failure_debt_severity": str(archive.get("historical_failure_debt_severity") or "unknown"),
        "historical_failure_debt_burndown_rate": float(archive.get("historical_failure_debt_burndown_rate") or 0.0),
        "historical_failure_debt_last_reduced_at": archive.get("historical_failure_debt_last_reduced_at"),
    }


def _amplifier_observability(window_days: int = 1) -> dict[str, Any]:
    state = _load_json(AMPLIFIER_OBSERVABILITY_PATH, {})
    if not isinstance(state, dict):
        state = {}
    self_repair_queue = _load_json(QUEUE_PATH, {})
    artifact_growth_queue = _load_json(ARTIFACT_GROWTH_QUEUE_PATH, {})
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=window_days)
    summary = {
        "amplifier_trigger_count_24h": 0,
        "amplifier_generated_tasks_24h": 0,
        "amplifier_entered_execution_24h": 0,
        "amplifier_completed_tasks_24h": 0,
        "amplifier_success_conversion_rate": 0.0,
        "amplifiers": {},
    }
    for amplifier_name in state.get("amplifiers") or {}:
        summary["amplifiers"][amplifier_name] = {
            "trigger_count": 0,
            "generated_tasks": 0,
            "entered_execution": 0,
            "completed_tasks": 0,
            "success_conversion_rate": 0.0,
        }
    for event in state.get("events") or []:
        if not isinstance(event, dict):
            continue
        stamp = _parse_timestamp(event.get("created_at"))
        if stamp is None or stamp < threshold:
            continue
        amplifier_name = str(event.get("amplifier") or "unknown")
        bucket = summary["amplifiers"].setdefault(
            amplifier_name,
            {
                "trigger_count": 0,
                "generated_tasks": 0,
                "entered_execution": 0,
                "completed_tasks": 0,
                "success_conversion_rate": 0.0,
            },
        )
        trigger_count = int(event.get("trigger_count") or 0)
        bucket["trigger_count"] += trigger_count
        summary["amplifier_trigger_count_24h"] += trigger_count
    queue_sources = {
        "self_repair_task_generator": (self_repair_queue, "self_repair_task_generator"),
        "artifact_growth_task_generator": (artifact_growth_queue, "artifact_growth_task_generator"),
    }
    for amplifier_name, (queue, default_amplifier) in queue_sources.items():
        items = _queue_items_within_window(queue if isinstance(queue, dict) else {}, amplifier_name, window_days, default_amplifier=default_amplifier)
        bucket = summary["amplifiers"].setdefault(
            amplifier_name,
            {
                "trigger_count": 0,
                "generated_tasks": 0,
                "entered_execution": 0,
                "completed_tasks": 0,
                "success_conversion_rate": 0.0,
            },
        )
        generated_tasks = len(items)
        entered_execution = sum(
            1
            for item in items
            if str(item.get("section") or "") == "in_progress_items"
            or str(item.get("status") or "").lower() in {"planning", "running", "blocked", "in_progress"}
        )
        completed_tasks = sum(
            1
            for item in items
            if str(item.get("section") or "") == "done_items"
            or str(item.get("status") or "").lower() in {"completed", "done", "released", "verified"}
        )
        bucket["generated_tasks"] += generated_tasks
        bucket["entered_execution"] += entered_execution
        bucket["completed_tasks"] += completed_tasks
        summary["amplifier_generated_tasks_24h"] += generated_tasks
        summary["amplifier_entered_execution_24h"] += entered_execution
        summary["amplifier_completed_tasks_24h"] += completed_tasks
    for bucket in summary["amplifiers"].values():
        generated = int(bucket.get("generated_tasks") or 0)
        completed = int(bucket.get("completed_tasks") or 0)
        bucket["success_conversion_rate"] = round(completed / max(1, generated), 4) if generated else 0.0
    generated = int(summary["amplifier_generated_tasks_24h"] or 0)
    completed = int(summary["amplifier_completed_tasks_24h"] or 0)
    summary["amplifier_success_conversion_rate"] = round(completed / max(1, generated), 4) if generated else 0.0
    return summary


def _rules() -> dict[str, Any]:
    return _load_json(RULES_PATH, {})


def _candidate_ready(metrics: dict[str, Any], rules: dict[str, Any]) -> bool:
    candidate = rules.get("candidate_requirements") or {}
    control_layer = str(metrics.get("control_layer_status") or "").lower()
    control_ok = control_layer in {"stable", "standard", "stronger"}
    autonomy_ok = bool(metrics.get("stable_autonomy"))
    release_gate_ok = int(metrics.get("release_gate_signal_count") or 0) == 0
    return (
        int(metrics.get("new_real_artifacts_7d") or 0) >= int(candidate.get("min_new_real_artifacts") or 0)
        and int(metrics.get("self_repair_success_count_7d") or 0) >= int(candidate.get("min_self_repair_successes") or 0)
        and int(metrics.get("capability_expansion_count_7d") or 0) >= int(candidate.get("min_capability_expansions") or 0)
        and (not candidate.get("require_stable_autonomy") or autonomy_ok)
        and (not candidate.get("require_control_layer_standard_or_above") or control_ok)
        and (not candidate.get("require_release_gate_signal_count_zero") or release_gate_ok)
    )


def _confirmed_ready(metrics: dict[str, Any], rules: dict[str, Any], trend: str) -> bool:
    confirmed = rules.get("confirmed_requirements") or {}
    control_layer = str(metrics.get("control_layer_status") or "").lower()
    control_ok = control_layer in {"stable", "standard", "stronger"}
    autonomy_ok = bool(metrics.get("stable_autonomy"))
    release_gate_ok = int(metrics.get("release_gate_signal_count") or 0) == 0
    return (
        int(metrics.get("new_real_artifacts_14d") or 0) >= int(confirmed.get("min_new_real_artifacts") or 0)
        and int(metrics.get("self_repair_success_count_14d") or 0) >= int(confirmed.get("min_self_repair_successes") or 0)
        and int(metrics.get("capability_expansion_count_14d") or 0) >= int(confirmed.get("min_capability_expansions") or 0)
        and (not confirmed.get("require_stable_autonomy") or autonomy_ok)
        and (not confirmed.get("require_control_layer_standard_or_above") or control_ok)
        and (not confirmed.get("require_release_gate_signal_count_zero") or release_gate_ok)
        and (not confirmed.get("require_positive_productivity_trend") or trend == "up")
    )


def _reasons(metrics: dict[str, Any], rules: dict[str, Any], trend: str) -> list[str]:
    reasons: list[str] = []
    candidate = rules.get("candidate_requirements") or {}
    confirmed = rules.get("confirmed_requirements") or {}
    if int(metrics.get("new_real_artifacts_7d") or 0) < int(candidate.get("min_new_real_artifacts") or 0):
        reasons.append("new_real_artifacts_7d below candidate threshold")
    if int(metrics.get("self_repair_success_count_7d") or 0) < int(candidate.get("min_self_repair_successes") or 0):
        reasons.append("self_repair_success_count_7d below candidate threshold")
    if int(metrics.get("capability_expansion_count_7d") or 0) < int(candidate.get("min_capability_expansions") or 0):
        reasons.append("capability_expansion_count_7d below candidate threshold")
    if candidate.get("require_stable_autonomy") and not metrics.get("stable_autonomy"):
        reasons.append("stable_autonomy is false")
    if candidate.get("require_control_layer_standard_or_above"):
        control_layer = str(metrics.get("control_layer_status") or "").lower()
        if control_layer not in {"stable", "standard", "stronger"}:
            reasons.append("control_layer_status below standard")
    if candidate.get("require_release_gate_signal_count_zero") and int(metrics.get("release_gate_signal_count") or 0) != 0:
        reasons.append("release_gate_signal_count is non-zero")
    if confirmed.get("require_positive_productivity_trend") and trend != "up":
        reasons.append(f"productivity_trend is {trend}")
    return reasons


def run_stage5_evaluator(*, refresh_artifact_validation: bool = True) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    if refresh_artifact_validation:
        run_artifact_regression_validation()
    rules = _rules()
    tasks = _load_task_records()
    task_history = _load_task_history_records()
    queue = _load_json(QUEUE_PATH, {})
    capability_queue = _load_json(CAPABILITY_QUEUE_PATH, {})
    ledger = _load_json(LEDGER_PATH, {})
    queue_pressure = _load_json(QUEUE_PRESSURE_PATH, {})
    amplifier_obs = _amplifier_observability(1)
    historical_debt = _historical_failure_debt()

    task_24h = _task_window_stats(tasks, 1)
    task_7d = _task_window_stats(tasks, 7)
    task_14d = _task_window_stats(tasks, 14)
    history_24h = _task_window_stats(task_history, 1)
    history_7d = _task_window_stats(task_history, 7)
    history_14d = _task_window_stats(task_history, 14)

    metrics = {
        "window_days": int(rules.get("candidate_window_days") or 7),
        "continuous_runtime_hours": _continuous_runtime_hours(),
        "new_real_artifacts_24h": _count_real_artifacts(1),
        "new_real_artifacts_7d": _count_real_artifacts(7),
        "new_real_artifacts_14d": _count_real_artifacts(14),
        "self_repair_success_count_7d": _count_successful_ledger_entries(ledger, "self_repair", 7),
        "self_repair_success_count_14d": _count_successful_ledger_entries(ledger, "self_repair", 14),
        "capability_expansion_count_7d": _count_successful_ledger_entries(ledger, "capability_expansion", 7),
        "capability_expansion_count_14d": _count_successful_ledger_entries(ledger, "capability_expansion", 14),
        "auto_completed_ratio_24h": task_24h["auto_completed_ratio"],
        "blocked_to_done_conversion_7d": _blocked_to_done_conversion(),
        "median_time_to_first_result_minutes": task_24h["median_time_to_first_result_minutes"],
        "regression_fail_rate_7d": _regression_fail_rate(),
        "control_layer_status": _control_layer_status(),
        "autonomy_stage": _autonomy_stage(),
        "stable_autonomy": _stable_autonomy(),
        "release_gate_signal_count": _release_gate_signal_count(),
        "active_queue_pressure": str(queue_pressure.get("pressure") or "unknown"),
        **historical_debt,
        **amplifier_obs,
        "queue_summary": {
            "self_improvement_queue": _queue_stats(queue),
            "capability_build_queue": _queue_stats(capability_queue),
        },
        "task_window_summary": {
            "24h": task_24h,
            "7d": task_7d,
            "14d": task_14d,
            "history_24h": history_24h,
            "history_7d": history_7d,
            "history_14d": history_14d,
        },
    }

    previous_history = _load_json(HISTORY_PATH, {})
    snapshots = previous_history.get("snapshots") or []
    previous_snapshot = snapshots[-1] if snapshots else None
    trend = _productivity_trend(metrics, previous_snapshot)
    metrics["productivity_trend"] = trend

    dashboard = {
        "status": "evaluating",
        "stage5_candidate": False,
        "stage5_confirmed": False,
        "window_days": int(rules.get("candidate_window_days") or 7),
        "continuous_runtime_hours": metrics["continuous_runtime_hours"],
        "new_real_artifacts_24h": metrics["new_real_artifacts_24h"],
        "new_real_artifacts_7d": metrics["new_real_artifacts_7d"],
        "new_real_artifacts_14d": metrics["new_real_artifacts_14d"],
        "self_repair_success_count_7d": metrics["self_repair_success_count_7d"],
        "self_repair_success_count_14d": metrics["self_repair_success_count_14d"],
        "capability_expansion_count_7d": metrics["capability_expansion_count_7d"],
        "capability_expansion_count_14d": metrics["capability_expansion_count_14d"],
        "auto_completed_ratio_24h": metrics["auto_completed_ratio_24h"],
        "blocked_to_done_conversion_7d": metrics["blocked_to_done_conversion_7d"],
        "median_time_to_first_result_minutes": metrics["median_time_to_first_result_minutes"],
        "regression_fail_rate_7d": metrics["regression_fail_rate_7d"],
        "productivity_trend": trend,
        "control_layer_status": metrics["control_layer_status"],
        "autonomy_stage": metrics["autonomy_stage"],
        "stable_autonomy": metrics["stable_autonomy"],
        "release_gate_signal_count": metrics["release_gate_signal_count"],
        "active_queue_pressure": metrics["active_queue_pressure"],
        "historical_failure_debt_count": metrics["historical_failure_debt_count"],
        "historical_failure_debt_severity": metrics["historical_failure_debt_severity"],
        "historical_failure_debt_burndown_rate": metrics["historical_failure_debt_burndown_rate"],
        "historical_failure_debt_last_reduced_at": metrics["historical_failure_debt_last_reduced_at"],
        "amplifier_trigger_count_24h": metrics["amplifier_trigger_count_24h"],
        "amplifier_generated_tasks_24h": metrics["amplifier_generated_tasks_24h"],
        "amplifier_entered_execution_24h": metrics["amplifier_entered_execution_24h"],
        "amplifier_completed_tasks_24h": metrics["amplifier_completed_tasks_24h"],
        "amplifier_success_conversion_rate": metrics["amplifier_success_conversion_rate"],
        "amplifier_breakdown": metrics["amplifiers"],
        "last_evaluated_at": _utc(),
        "reasons": [],
    }

    candidate_ready = _candidate_ready(dashboard, rules)
    confirmed_ready = _confirmed_ready(dashboard, rules, trend)
    if confirmed_ready:
        dashboard["status"] = "confirmed"
        dashboard["stage5_candidate"] = True
        dashboard["stage5_confirmed"] = True
    elif candidate_ready:
        dashboard["status"] = "candidate"
        dashboard["stage5_candidate"] = True
    else:
        dashboard["status"] = "evaluating"
    dashboard["reasons"] = _reasons(dashboard, rules, trend)

    atomic_write_json(DASHBOARD_PATH, dashboard)

    snapshot = {
        "captured_at": _utc(),
        "dashboard": dashboard,
        "metrics": metrics,
        "rules_version": int(rules.get("version") or 1),
    }
    snapshots.append(snapshot)
    if len(snapshots) > 365:
        snapshots = snapshots[-365:]
    atomic_write_json(HISTORY_PATH, {"version": 1, "snapshots": snapshots})
    append_trace(
        "industrial-readiness",
        "evaluate stage5 readiness",
        "run stage5_evaluator.py",
        f"status={dashboard['status']} candidate={dashboard['stage5_candidate']} confirmed={dashboard['stage5_confirmed']}",
        "export readiness report or continue monitoring",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={
            "dashboard_status": dashboard["status"],
            "historical_failure_debt_count": dashboard.get("historical_failure_debt_count"),
            "amplifier_success_conversion_rate": dashboard.get("amplifier_success_conversion_rate"),
        },
    )

    return {
        **dashboard,
        "metrics": metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Stage 5 readiness and persist the dashboard.")
    parser.add_argument("--no-refresh-artifact-validation", action="store_true", help="Skip artifact regression validation refresh.")
    args = parser.parse_args()
    payload = run_stage5_evaluator(refresh_artifact_validation=not args.no_refresh_artifact_validation)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
