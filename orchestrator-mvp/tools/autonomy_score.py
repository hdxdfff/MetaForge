from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.artifact_audit import summarize_verified_completed_tasks
from tools.signal_policy import summarize_signal_policy

DATA = ROOT / "data"
FACTORY = ROOT / "factory"

OUT = DATA / "autonomy_score.json"
USAGE = DATA / "usage_tracker.json"
DAEMON = DATA / "factory_daemon_state.json"
TASKS = DATA / "tasks.json"
TASK_HISTORY = DATA / "task_history.json"
TASK_CHECKPOINTS = DATA / "task_checkpoints.json"
CORE_MESSAGES = DATA / "core_messages.json"
QUALITY = DATA / "quality_status.json"
CONTROL = DATA / "control_layer_status.json"
GOALS = FACTORY / "goals" / "goal_registry.json"
SOAK = DATA / "soak_validation.json"
REALITY = DATA / "reality_dashboard.json"
ARTIFACTS = DATA / "artifact_registry.json"

WINDOW_HOURS = 24
STUCK_MINUTES = 10
MIN_PRODUCTIVE_RATIO = 0.85
MIN_REASONING_RATIO = 0.20
MAX_REASONING_RATIO = 0.70
TARGET_OUTPUT_INPUT_RATIO = 0.18
MIN_RATIO_SAMPLE_CALLS = 5
MAX_ACTIVE_TASKS = 12
MAX_STUCK_TASKS = 0
MIN_UPTIME_HOURS_FOR_CONFIRMED = 12
TARGET_CONVERSION_RATE = 15.0
RUNTIME_FRESHNESS_MINUTES = 5


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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _window_start(hours: int = WINDOW_HOURS) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def _latest_task_view(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    for source in (task_history, tasks):
        for item in source:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("id") or "").strip()
            if not task_id:
                anonymous.append(item)
                continue
            existing = merged.get(task_id)
            existing_time = _parse_time((existing or {}).get("updated_at")) if existing else None
            item_time = _parse_time(item.get("updated_at"))
            if existing is None or (item_time or min_time) >= (existing_time or min_time):
                merged[task_id] = item
    return list(merged.values()) + anonymous


def _daemon_runtime_state(daemon: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    started = _parse_time(daemon.get("started_at"))
    last_seen = _parse_time(daemon.get("last_tick_at") or daemon.get("updated_at"))
    raw_status = str(daemon.get("status") or "").strip().lower()
    fresh = bool(last_seen and (now - last_seen) <= timedelta(minutes=RUNTIME_FRESHNESS_MINUTES))
    running = raw_status == "running" and fresh
    stale = raw_status == "running" and not fresh
    uptime_hours = 0.0
    if started and last_seen:
        uptime_hours = max(0.0, (last_seen - started).total_seconds() / 3600.0)
    effective_status = "running" if running else "stale" if stale else raw_status or "unknown"
    return {
        "raw_status": raw_status or "unknown",
        "effective_status": effective_status,
        "running": running,
        "fresh": fresh,
        "started_at": started,
        "last_seen_at": last_seen,
        "uptime_hours": uptime_hours,
    }

def _lane_mix_score(usage: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    recent_window = usage.get("recent_window") or {}
    min_ratio_sample_calls = int(usage.get("ratio_sample_min_calls", MIN_RATIO_SAMPLE_CALLS) or MIN_RATIO_SAMPLE_CALLS)
    use_recent_window = int(recent_window.get("total_calls", 0) or 0) >= min_ratio_sample_calls
    source = recent_window if use_recent_window else usage
    cheap_calls = int(source.get("cheap_calls", 0) or 0)
    reasoning_calls = int(source.get("reasoning_calls", 0) or 0)
    strong_calls = int(source.get("strong_calls", 0) or 0)
    total = cheap_calls + reasoning_calls + strong_calls
    productive_ratio = float(source.get("non_fallback_ratio", 1.0 if total else 0.0) or 0.0)
    output_input_ratio = float(source.get("output_input_ratio", 0.25 if total else 0.0) or 0.0)
    reasoning_ratio = float(reasoning_calls / total) if total else 0.0
    productive_score = min(1.0, productive_ratio / MIN_PRODUCTIVE_RATIO) if productive_ratio < MIN_PRODUCTIVE_RATIO else 1.0
    if output_input_ratio <= 0:
        output_score = 0.0
    elif output_input_ratio >= TARGET_OUTPUT_INPUT_RATIO:
        output_score = 1.0
    else:
        output_score = min(1.0, output_input_ratio / TARGET_OUTPUT_INPUT_RATIO)
    efficiency_score = round(productive_score * 0.7 + output_score * 0.3, 4)
    if total == 0:
        reasoning_score = 0.0
    elif MIN_REASONING_RATIO <= reasoning_ratio <= MAX_REASONING_RATIO:
        reasoning_score = 1.0
    elif reasoning_calls > 0:
        reasoning_score = 0.75
    else:
        reasoning_score = 0.35
    score = round((efficiency_score * 0.55) + (reasoning_score * 0.45), 4)
    metrics = {
        "cheap_calls": cheap_calls,
        "reasoning_calls": reasoning_calls,
        "strong_calls": strong_calls,
        "productive_ratio": round(productive_ratio, 4),
        "output_input_ratio": round(output_input_ratio, 4),
        "reasoning_ratio": round(reasoning_ratio, 4),
        "target_min_productive_ratio": MIN_PRODUCTIVE_RATIO,
        "target_output_input_ratio": TARGET_OUTPUT_INPUT_RATIO,
        "target_min_ratio_sample_calls": min_ratio_sample_calls,
        "target_reasoning_ratio_range": [MIN_REASONING_RATIO, MAX_REASONING_RATIO],
        "source_window_hours": int((recent_window if use_recent_window else usage).get("hours", WINDOW_HOURS) or WINDOW_HOURS),
        "source": "recent_window" if use_recent_window else "full_window",
    }
    return score, metrics




def _active_task_score(tasks: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    active = [item for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"}]
    count = len(active)
    if count == 0:
        score = 0.25
    elif count <= MAX_ACTIVE_TASKS:
        score = 1.0
    else:
        overflow = min(1.0, (count - MAX_ACTIVE_TASKS) / MAX_ACTIVE_TASKS)
        score = max(0.0, 1.0 - overflow)
    return score, {
        "active_tasks": count,
        "target_range": [1, MAX_ACTIVE_TASKS],
    }


def _goal_progress_score(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]], goals: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    window_start = _window_start()
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    completion_summary = summarize_verified_completed_tasks(tasks, task_history, hours=WINDOW_HOURS)
    verified_completed_tasks = int(completion_summary.get("verified_completed_tasks_last_24h", 0) or 0)
    completed_goals = [
        item for item in goals
        if item.get("status") == "completed" and (_parse_time(item.get("updated_at")) or min_time) >= window_start
    ]
    progress_events = verified_completed_tasks
    if progress_events >= 4:
        score = 1.0
    elif progress_events == 0:
        score = 0.0
    else:
        score = min(1.0, progress_events / 4.0)
    return score, {
        "completed_tasks_last_24h": verified_completed_tasks,
        "completed_goals_last_24h": len(completed_goals),
        "progress_events": progress_events,
        "unverified_completed_tasks_last_24h": int(completion_summary.get("unverified_completed_tasks_last_24h", 0) or 0),
    }

def _recovery_score(core_messages: list[dict[str, Any]], control_layer: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    window_start = _window_start()
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    auto_resolved = [
        item for item in core_messages
        if item.get("status") == "auto-resolved"
        and (_parse_time(item.get("resolved_at") or item.get("created_at")) or min_time) >= window_start
    ]
    open_errors = int(control_layer.get("state_kernel", {}).get("open_error_escalations", 0) or 0)
    recoveries = len(auto_resolved)
    if open_errors > 0:
        score = 0.2
    elif recoveries == 0:
        score = 0.65
    elif recoveries <= 5:
        score = 1.0
    else:
        score = 0.85
    return score, {
        "recoveries_last_24h": recoveries,
        "open_error_escalations": open_errors,
    }


def _stuck_task_score(tasks: list[dict[str, Any]], checkpoints: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    now = datetime.now(timezone.utc)
    active_lookup = {item.get("id"): item for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"} and item.get("id")}
    stuck_ids: list[str] = []
    for task_id, checkpoint in checkpoints.items():
        if task_id not in active_lookup:
            continue
        updated = _parse_time(checkpoint.get("updated_at")) or _parse_time(active_lookup[task_id].get("updated_at"))
        if not updated:
            continue
        if now - updated > timedelta(minutes=STUCK_MINUTES):
            stuck_ids.append(task_id)
    if len(stuck_ids) <= MAX_STUCK_TASKS:
        score = 1.0
    else:
        score = max(0.0, 1.0 - (len(stuck_ids) * 0.25))
    return score, {
        "stuck_tasks": len(stuck_ids),
        "stuck_task_ids": stuck_ids[:10],
        "stuck_threshold_minutes": STUCK_MINUTES,
    }


def _uptime_score(daemon: dict[str, Any], runtime_state: dict[str, Any] | None = None) -> tuple[float, dict[str, Any]]:
    runtime = runtime_state or _daemon_runtime_state(daemon)
    uptime_hours = float(runtime.get("uptime_hours", 0.0) or 0.0)
    running = bool(runtime.get("running"))
    if not running:
        score = 0.0
    elif uptime_hours >= MIN_UPTIME_HOURS_FOR_CONFIRMED:
        score = 1.0
    else:
        score = min(1.0, uptime_hours / MIN_UPTIME_HOURS_FOR_CONFIRMED)
    return score, {
        "uptime_hours": round(uptime_hours, 2),
        "running": running,
        "fresh": bool(runtime.get("fresh")),
        "raw_status": runtime.get("raw_status"),
        "last_seen_at": runtime.get("last_seen_at").isoformat().replace("+00:00", "Z") if runtime.get("last_seen_at") else None,
        "freshness_threshold_minutes": RUNTIME_FRESHNESS_MINUTES,
        "target_hours_for_confirmed": MIN_UPTIME_HOURS_FOR_CONFIRMED,
        "cycle": int(daemon.get("cycle", 0) or 0),
    }


def _history_score(lane_mix_score: float, progress_score: float, recovery_score: float, stuck_score: float, uptime_score: float) -> float:
    return round(
        lane_mix_score * 0.25
        + progress_score * 0.30
        + recovery_score * 0.20
        + stuck_score * 0.15
        + uptime_score * 0.10,
        4,
    )


def _runtime_score(
    daemon: dict[str, Any],
    active_metrics: dict[str, Any],
    reality_dashboard: dict[str, Any],
    runtime_state: dict[str, Any] | None = None,
) -> tuple[float, dict[str, Any]]:
    runtime = runtime_state or _daemon_runtime_state(daemon)
    daemon_status = str(runtime.get("effective_status") or "unknown")
    if daemon_status == "running":
        daemon_score = 1.0
    elif daemon_status in {"error", "stopped", "stale"}:
        daemon_score = 0.0
    else:
        daemon_score = 0.25
    active_tasks = int(active_metrics.get("active_tasks", 0) or 0)
    if active_tasks == 0:
        active_score = 0.25
    elif active_tasks <= MAX_ACTIVE_TASKS:
        active_score = 1.0
    else:
        active_score = max(0.0, 1.0 - min(1.0, (active_tasks - MAX_ACTIVE_TASKS) / MAX_ACTIVE_TASKS))
    artifact_rate = float(reality_dashboard.get("artifacts_produced_last_24h", 0) or 0.0)
    artifact_rate_score = 1.0 if artifact_rate >= 1.0 else 0.0
    score = round(daemon_score * 0.50 + active_score * 0.25 + artifact_rate_score * 0.25, 4)
    return score, {
        "daemon_status": daemon_status,
        "daemon_raw_status": runtime.get("raw_status"),
        "daemon_fresh": bool(runtime.get("fresh")),
        "daemon_score": daemon_score,
        "active_tasks": active_tasks,
        "active_task_score": round(active_score, 4),
        "artifact_rate": artifact_rate,
        "artifact_rate_score": artifact_rate_score,
    }


def _production_score(reality_dashboard: dict[str, Any], artifact_registry: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    real_artifacts = int(reality_dashboard.get("products_real", artifact_registry.get("real_artifact_count", 0)) or 0)
    conversion_rate = float(
        reality_dashboard.get("technical_conversion_rate", reality_dashboard.get("conversion_rate", 0.0)) or 0.0
    )
    real_artifact_score = 1.0 if real_artifacts > 0 else 0.0
    conversion_score = min(1.0, conversion_rate / TARGET_CONVERSION_RATE)
    score = round(real_artifact_score * 0.60 + conversion_score * 0.40, 4)
    return score, {
        "products_real": real_artifacts,
        "conversion_rate": conversion_rate,
        "conversion_rate_source": "technical_conversion_rate" if "technical_conversion_rate" in reality_dashboard else "conversion_rate",
        "target_conversion_rate": TARGET_CONVERSION_RATE,
        "real_artifact_score": real_artifact_score,
        "conversion_score": round(conversion_score, 4),
    }


def _derive_stage(score: float, metrics: dict[str, Any], control_layer: dict[str, Any], quality: dict[str, Any], *, runtime_critical: bool) -> tuple[str, str]:
    control_status = control_layer.get("status")
    quality_score = float(quality.get("overall_score", 0.0) or 0.0)
    if runtime_critical:
        return "stage3", "Runtime health is degraded; autonomy score is clamped until daemon and production flow recover."
    if (
        score >= 0.8
        and metrics["runtime"]["daemon_status"] == "running"
        and metrics["history"]["uptime"].get("running")
        and float(metrics["history"]["uptime"].get("uptime_hours", 0.0) or 0.0) >= MIN_UPTIME_HOURS_FOR_CONFIRMED
        and metrics["production"]["products_real"] > 0
        and metrics["production"]["conversion_rate"] >= 5.0
        and control_status == "stable"
        and quality_score >= 0.75
    ):
        return "stage4_confirmed", "Stable autonomy confirmed by healthy runtime, sustained uptime, non-zero real production, and verified control signals."
    if (
        score >= 0.65
        and metrics["runtime"]["daemon_status"] in {"running", "operator_attention"}
        and control_status in {"stable", "constrained", "lean_execution"}
    ):
        return "stage4_beta", "Autonomy is partially functioning, but runtime or production indicators are not yet strong enough for confirmed status."
    return "stage3", "Constrained autonomy only; runtime or production evidence is still too weak."


def _preserve_confirmed_stage(
    *,
    stage: str,
    verdict: str,
    soak: dict[str, Any],
    soak_summary: dict[str, Any],
    runtime_state: dict[str, Any],
    runtime_critical: bool,
    control_layer: dict[str, Any],
    quality: dict[str, Any],
) -> tuple[str, str, bool]:
    if runtime_critical:
        return stage, verdict, False
    if not bool(soak.get("confirmed")):
        return stage, verdict, False
    if not bool(runtime_state.get("running")) or not bool(runtime_state.get("fresh")):
        return stage, verdict, False
    if control_layer.get("status") != "stable":
        return stage, verdict, False
    if float(quality.get("overall_score", 0.0) or 0.0) < 0.75:
        return stage, verdict, False
    preserved_verdict = (
        "Historical soak confirmation is preserved across restart; current uptime reset does not revoke confirmed autonomy."
    )
    historical_uptime = float(soak_summary.get("uptime_hours", 0.0) or 0.0)
    if historical_uptime <= 0.0:
        historical_uptime = float((soak.get("summary") or {}).get("uptime_hours", 0.0) or 0.0)
    return "stage4_confirmed", preserved_verdict, True


def _signal_policy(
    *,
    runtime_critical: bool,
    stage: str,
    quality_status: str,
    quality_score: float,
    soak_confirmed: bool,
    production_score: float,
    control_layer: dict[str, Any],
    release_operations_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_blockers: list[str] = []
    if runtime_critical:
        runtime_blockers.append("daemon_unhealthy")

    maturity_signals: list[str] = []
    if stage == "stage3":
        maturity_signals.append("autonomy_stage3")
    if quality_status != "pass" and quality_score < 0.75:
        maturity_signals.append(f"quality:{quality_status}")
    if production_score <= 0.0:
        maturity_signals.append("production_gap")

    release_gate_signals: list[str] = []
    control_policy = control_layer.get("control_policy") or {}
    release_policy = control_policy.get("release") or {}
    release_operations = release_operations_snapshot or control_layer.get("release_operations") or {}
    release_claim_policy = release_operations.get("release_claim_policy") or {}
    release_claim_passed = bool(release_claim_policy.get("passed"))
    release_blocks = bool(
        release_claim_policy.get("blocks_release")
        or (
            not release_claim_passed
            and (
                release_policy.get("blocks_release")
                or release_policy.get("status") == "blocked"
            )
        )
    )
    blocking_reasons = [
        str(item) for item in (release_claim_policy.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    if release_blocks:
        release_gate_signals.extend(blocking_reasons or ["release_gate_not_confirmed"])
    if not soak_confirmed:
        release_gate_signals.append("stage4_confirmation_pending")
    if stage != "stage4_confirmed" and not release_blocks:
        release_gate_signals.append("release_gate_not_confirmed")

    return summarize_signal_policy(
        runtime_blockers=runtime_blockers,
        maturity_signals=maturity_signals,
        release_gate_signals=release_gate_signals,
        advisory_signals=[],
        source="autonomy_score",
    )


def run_autonomy_score(
    *,
    quality_snapshot: dict[str, Any] | None = None,
    release_operations_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    daemon = _load_json(DAEMON, {})
    usage = _load_json(USAGE, {})
    tasks = _load_json(TASKS, [])
    task_history = _load_json(TASK_HISTORY, [])
    checkpoints = _load_json(TASK_CHECKPOINTS, {})
    core_messages = _load_json(CORE_MESSAGES, [])
    quality = quality_snapshot or _load_json(QUALITY, {})
    control_layer = _load_json(CONTROL, {})
    goals = _load_json(GOALS, [])
    soak = _load_json(SOAK, {})
    reality_dashboard = _load_json(REALITY, {})
    artifact_registry = _load_json(ARTIFACTS, {})
    runtime_state = _daemon_runtime_state(daemon)

    lane_mix_score, lane_mix_metrics = _lane_mix_score(usage)
    active_score, active_metrics = _active_task_score(tasks)
    progress_score, progress_metrics = _goal_progress_score(tasks, task_history, goals)
    recovery_score, recovery_metrics = _recovery_score(core_messages, control_layer)
    stuck_score, stuck_metrics = _stuck_task_score(tasks, checkpoints)
    uptime_score, uptime_metrics = _uptime_score(daemon, runtime_state)
    history_score = _history_score(lane_mix_score, progress_score, recovery_score, stuck_score, uptime_score)
    runtime_score, runtime_metrics = _runtime_score(daemon, active_metrics, reality_dashboard, runtime_state)
    production_score, production_metrics = _production_score(reality_dashboard, artifact_registry)

    weights = {
        "history": 0.40,
        "runtime": 0.30,
        "production": 0.30,
    }
    autonomy_score = round(
        history_score * weights["history"]
        + runtime_score * weights["runtime"]
        + production_score * weights["production"],
        4,
    )
    runtime_critical = not bool(runtime_state.get("running"))
    if runtime_critical:
        autonomy_score = min(autonomy_score, 0.49)

    metrics = {
        "history": {
            "score": history_score,
            "lane_mix": lane_mix_metrics,
            "goal_progress": progress_metrics,
            "recovery": recovery_metrics,
            "stuck_tasks": stuck_metrics,
            "uptime": uptime_metrics,
        },
        "runtime": {
            **runtime_metrics,
            "score": runtime_score,
        },
        "production": {
            **production_metrics,
            "score": production_score,
        },
    }
    stage, verdict = _derive_stage(autonomy_score, metrics, control_layer, quality, runtime_critical=runtime_critical)

    soak_summary = soak.get("summary") or {}
    stage, verdict, preserved_confirmed = _preserve_confirmed_stage(
        stage=stage,
        verdict=verdict,
        soak=soak,
        soak_summary=soak_summary,
        runtime_state=runtime_state,
        runtime_critical=runtime_critical,
        control_layer=control_layer,
        quality=quality,
    )
    metrics["history"]["soak_validation"] = {
        "confirmed": bool(soak.get("confirmed")),
        "status": soak.get("status"),
        "historical_uptime_hours": round(float(soak_summary.get("uptime_hours", 0.0) or 0.0), 2),
        "historical_control_layer_status": soak_summary.get("control_layer_status"),
        "preserved_after_restart": preserved_confirmed,
    }

    payload = {
        "updated_at": _utc(),
        "window_hours": WINDOW_HOURS,
        "score": autonomy_score,
        "stage": stage,
        "classification": {
            "stage_domain": "autonomy_maturity",
            "health_domain": "runtime_health",
            "release_domain": "release_readiness",
            "stage_is_not_health": True,
            "release_is_not_health": True,
            "health_is_not_stage": True,
        },
        "verdict": verdict,
        "weights": weights,
        "metrics": metrics,
        "runtime_critical": runtime_critical,
        "control_layer_status": control_layer.get("status"),
        "quality_score": float(quality.get("overall_score", 0.0) or 0.0),
        "quality_status": quality.get("status"),
        "confirmation": {
            "status": "preserved" if preserved_confirmed else "computed",
            "source": "historical_soak" if preserved_confirmed else "live_metrics",
            "soak_confirmed": bool(soak.get("confirmed")),
        },
        "signal_policy": _signal_policy(
            runtime_critical=runtime_critical,
            stage=stage,
            quality_status=str(quality.get("status") or "unknown"),
            quality_score=float(quality.get("overall_score", 0.0) or 0.0),
            soak_confirmed=bool(soak.get("confirmed")),
            production_score=production_score,
            control_layer=control_layer,
            release_operations_snapshot=release_operations_snapshot,
        ),
        "decision": {
            "stable_autonomy": stage == "stage4_confirmed" and not runtime_critical,
            "needs_more_soak": stage != "stage4_confirmed",
            "needs_operator_attention": runtime_critical or stage == "stage3",
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_autonomy_score(), ensure_ascii=False, indent=2))


