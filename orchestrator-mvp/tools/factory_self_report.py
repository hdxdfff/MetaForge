from __future__ import annotations

import json
import os
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from dotenv import load_dotenv
from tools.report_chain import build_report_chain

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT.parent
DATA = ROOT / "data"
JSON_REPORT_PATH = DATA / "factory_self_report.json"
REPORT_SCHEDULE_PATH = DATA / "self_report_schedule.json"
OPENCODE_REPORT_PATH = WORKSPACE_ROOT / "METAFORGE_OS_FACTORY_SELF_REPORT.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _daemon_running(daemon: dict[str, Any]) -> bool:
    running = daemon.get("running")
    if isinstance(running, bool):
        return running
    return str(daemon.get("status") or "").lower() in {"running", "operator_attention"}


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _weekday_index(name: str) -> int:
    mapping = {
        "MON": 0,
        "TUE": 1,
        "WED": 2,
        "THU": 3,
        "FRI": 4,
        "SAT": 5,
        "SUN": 6,
    }
    return mapping.get(name.upper(), 0)


def _format_minutes_label(minutes: int) -> str:
    hours = minutes / 60
    if float(hours).is_integer():
        return f"{int(hours)}h"
    return f"{minutes}m"


def _parse_report_schedule_state(path: Path) -> dict[str, Any]:
    state = _load_json(path, {})
    return state if isinstance(state, dict) else {}


def _next_weekly_report_at(after_at: datetime, *, weekday: str, hour: int, minute: int) -> datetime:
    local_after = after_at.astimezone()
    target_weekday = _weekday_index(weekday)
    candidate = local_after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta_days = (target_weekday - candidate.weekday()) % 7
    candidate = candidate + timedelta(days=delta_days)
    if candidate <= local_after:
        candidate += timedelta(days=7)
    return candidate


def _schedule_state_from_anchor(config: SelfReportConfig, anchor_at: datetime, *, phase_index: int = 0) -> dict[str, Any]:
    cadence_minutes = list(config.cadence_minutes or [240, 480, 720, 1440])
    index = max(0, min(phase_index, max(0, len(cadence_minutes))))
    local_anchor = anchor_at.astimezone()
    if index < len(cadence_minutes):
        next_minutes = cadence_minutes[index]
        next_at = local_anchor + timedelta(minutes=next_minutes)
        next_kind = _format_minutes_label(next_minutes)
    else:
        next_at = _next_weekly_report_at(
            local_anchor,
            weekday=config.weekly_day,
            hour=config.weekly_hour,
            minute=config.weekly_minute,
        )
        next_kind = f"weekly:{config.weekly_day}@{config.weekly_hour:02d}:{config.weekly_minute:02d}"
    return {
        "mode": "scheduled",
        "anchor_at": local_anchor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "phase_index": index,
        "cadence_minutes": cadence_minutes,
        "weekly": {
            "day": config.weekly_day,
            "hour": config.weekly_hour,
            "minute": config.weekly_minute,
        },
        "next_report_at": next_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "next_report_kind": next_kind,
    }


def _advance_schedule_state(config: SelfReportConfig, state: dict[str, Any], *, reported_at: datetime) -> dict[str, Any]:
    cadence_minutes = list(state.get("cadence_minutes") or config.cadence_minutes or [240, 480, 720, 1440])
    phase_index = _safe_int(state.get("phase_index"), 0)
    anchor_at = _parse_utc(state.get("anchor_at")) or reported_at
    if phase_index < len(cadence_minutes) - 1:
        next_state = _schedule_state_from_anchor(config, anchor_at, phase_index=phase_index + 1)
    elif phase_index == len(cadence_minutes) - 1:
        next_state = _schedule_state_from_anchor(config, anchor_at, phase_index=len(cadence_minutes))
    else:
        next_state = _schedule_state_from_anchor(config, reported_at, phase_index=0)
    next_state["last_reported_at"] = reported_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    next_state["last_report_kind"] = state.get("next_report_kind") or "weekly"
    return next_state


@dataclass(frozen=True)
class SelfReportConfig:
    enabled: bool
    on_alert: bool
    cadence_minutes: list[int]
    weekly_day: str
    weekly_hour: int
    weekly_minute: int
    serverchan_sendkey: str
    qq_mail_enabled: bool
    qq_mail_smtp_host: str
    qq_mail_smtp_port: int
    qq_mail_username: str
    qq_mail_password: str
    qq_mail_from: str
    qq_mail_to: list[str]


def load_self_report_config() -> SelfReportConfig:
    load_dotenv(ROOT / ".env", override=False)
    smtp_port_raw = os.getenv("ORCH_QQMAIL_SMTP_PORT", "465").strip() or "465"
    intervals_raw = os.getenv("ORCH_SELF_REPORT_INTERVALS_MINUTES", "").strip()
    legacy_interval_raw = os.getenv("ORCH_SELF_REPORT_INTERVAL_MINUTES", "").strip()
    legacy_every_raw = os.getenv("ORCH_SELF_REPORT_EVERY", "").strip()
    cadence_source = intervals_raw or legacy_interval_raw or legacy_every_raw or "240,480,720,1440"
    cadence_minutes = []
    for item in cadence_source.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            cadence_minutes.append(max(1, int(text)))
        except Exception:
            continue
    cadence_minutes = sorted(dict.fromkeys(cadence_minutes))
    weekly_day = (os.getenv("ORCH_SELF_REPORT_WEEKLY_DAY", "MON") or "MON").strip().upper()
    weekly_hour = max(0, min(23, int(os.getenv("ORCH_SELF_REPORT_WEEKLY_HOUR", "9"))))
    weekly_minute = max(0, min(59, int(os.getenv("ORCH_SELF_REPORT_WEEKLY_MINUTE", "0"))))
    return SelfReportConfig(
        enabled=_as_bool(os.getenv("ORCH_SELF_REPORT_ENABLED"), True),
        on_alert=_as_bool(os.getenv("ORCH_SELF_REPORT_ON_ALERT"), True),
        cadence_minutes=cadence_minutes or [240, 480, 720, 1440],
        weekly_day=weekly_day,
        weekly_hour=weekly_hour,
        weekly_minute=weekly_minute,
        serverchan_sendkey=os.getenv("ORCH_SERVERCHAN_SENDKEY", "").strip(),
        qq_mail_enabled=_as_bool(os.getenv("ORCH_QQMAIL_ENABLED"), True),
        qq_mail_smtp_host=os.getenv("ORCH_QQMAIL_SMTP_HOST", "smtp.qq.com").strip() or "smtp.qq.com",
        qq_mail_smtp_port=max(1, int(smtp_port_raw)),
        qq_mail_username=os.getenv("ORCH_QQMAIL_USERNAME", "").strip(),
        qq_mail_password=os.getenv("ORCH_QQMAIL_PASSWORD", "").strip(),
        qq_mail_from=os.getenv("ORCH_QQMAIL_FROM", "").strip(),
        qq_mail_to=_split_csv(os.getenv("ORCH_QQMAIL_TO", "")),
    )


def should_emit_self_report(
    *,
    cycle: int,
    ai_testing_alert: bool = False,
    control_status: str | None = None,
    force: bool = False,
) -> bool:
    config = load_self_report_config()
    if force:
        return True
    if not config.enabled:
        return False
    daemon = _load_json(DATA / "factory_daemon_state.json", {})
    schedule_state = _parse_report_schedule_state(REPORT_SCHEDULE_PATH)
    if not schedule_state:
        started_at = _parse_utc(daemon.get("started_at")) or _parse_utc(daemon.get("last_cycle_started_at")) or _local_now()
        schedule_state = _schedule_state_from_anchor(config, started_at, phase_index=0)
    next_report_at = _parse_utc(schedule_state.get("next_report_at"))
    if next_report_at is None:
        return True
    return _local_now().astimezone(timezone.utc) >= next_report_at.astimezone(timezone.utc)


def _determine_overall_status(
    daemon: dict[str, Any],
    status_cache: dict[str, Any],
    core_messages: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    blockers: list[str] = []
    open_messages = [item for item in core_messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_messages if item.get("severity") == "error"]
    ai_testing = status_cache.get("ai_testing") or {}
    control_layer = status_cache.get("control_layer") or {}
    engineering = status_cache.get("engineering_os") or {}
    release_ops = status_cache.get("release_ops") or {}

    if not _daemon_running(daemon):
        blockers.append("daemon_not_running")
    if daemon.get("status") in {"error", "stale", "stopped"}:
        blockers.append(f"daemon_{daemon.get('status')}")
    if open_errors:
        blockers.append("open_error_escalations")
    if ai_testing.get("alert"):
        blockers.append("ai_testing_alert")
    if control_layer.get("status") == "operator_attention":
        blockers.append("operator_attention")
    if release_ops.get("release_train_status") == "blocked":
        blockers.append("release_train_blocked")
    if _safe_int(engineering.get("patch_blocked_count")) > 0:
        blockers.append("patches_blocked")

    if any(item.startswith("daemon_") for item in blockers) or "daemon_not_running" in blockers or "open_error_escalations" in blockers:
        return "critical", blockers
    if blockers or control_layer.get("status") in {"constrained", "attention"}:
        return "attention", blockers
    return "healthy", blockers


def _task_window_stats(window_minutes: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_minutes = max(5, window_minutes)
    window_start = now - timedelta(minutes=window_minutes)
    tasks = _load_json(DATA / "tasks.json", [])
    task_history = _load_json(DATA / "task_history.json", [])
    task_archive = _load_json(DATA / "task_archive.json", [])
    control_layer = _load_json(DATA / "control_layer_status.json", {})

    active_statuses = {"queued", "planning", "running", "waiting_approval"}
    success_statuses = {"completed", "succeeded", "resolved", "merged", "done"}
    failed_statuses = {"failed", "timed_out", "rejected"}
    progress_weights = {
        "queued": 0.2,
        "planning": 0.35,
        "running": 0.65,
        "waiting_approval": 0.85,
    }

    active_goals: list[str] = []
    active_weight = 0.0
    active_count = 0
    running_items: list[str] = []
    queued_items: list[str] = []
    latest_done: dict[str, Any] | None = None
    latest_failed: dict[str, Any] | None = None

    def _goal_name(item: dict[str, Any]) -> str:
        return str(item.get("goal") or item.get("prompt") or "").strip()

    def _pick_latest(current: dict[str, Any] | None, candidate: dict[str, Any], stamp: datetime | None) -> dict[str, Any] | None:
        if stamp is None:
            return current
        if current is None:
            return {**candidate, "_stamp": stamp}
        if stamp > current.get("_stamp"):
            return {**candidate, "_stamp": stamp}
        return current

    for item in tasks:
        status = str(item.get("status") or "").lower()
        goal = _goal_name(item)
        if status in active_statuses:
            active_count += 1
            active_weight += progress_weights.get(status, 0.25)
            if goal:
                active_goals.append(goal)
                if status == "running":
                    running_items.append(goal)
                elif status in {"queued", "planning", "waiting_approval"}:
                    queued_items.append(goal)
        elif status in success_statuses:
            latest_done = _pick_latest(latest_done, item, _parse_utc(item.get("updated_at")))
        elif status in failed_statuses:
            latest_failed = _pick_latest(latest_failed, item, _parse_utc(item.get("updated_at")))

    control_state = control_layer.get("state_kernel") or {}
    active_count = max(active_count, _safe_int(control_state.get("active_tasks"), active_count))
    failed_live = _safe_int(control_state.get("failed_tasks"))

    recent_success = 0
    recent_failed = 0
    recent_goals: list[str] = []
    recent_done_goals: list[str] = []
    seen = set()

    def collect_goal(goal: str, target: list[str]) -> None:
        if goal and goal not in seen:
            target.append(goal)
            seen.add(goal)

    for item in task_history:
        stamp = _parse_utc(item.get("updated_at"))
        if stamp is None:
            continue
        status = str(item.get("status") or "").lower()
        goal = _goal_name(item)
        if status in success_statuses:
            latest_done = _pick_latest(latest_done, item, stamp)
            if stamp >= window_start:
                recent_success += 1
                collect_goal(goal, recent_done_goals)
        elif status in failed_statuses:
            latest_failed = _pick_latest(latest_failed, item, stamp)
            if stamp >= window_start:
                recent_failed += 1
                collect_goal(goal, recent_goals)

    for item in task_archive:
        stamp = _parse_utc(item.get("updated_at"))
        if stamp is None:
            continue
        status = str(item.get("status") or "").lower()
        goal = _goal_name(item)
        if status in failed_statuses:
            latest_failed = _pick_latest(latest_failed, item, stamp)
            if stamp >= window_start:
                recent_failed += 1
                collect_goal(goal, recent_goals)
        else:
            latest_done = _pick_latest(latest_done, item, stamp)
            if stamp >= window_start:
                recent_success += 1
                collect_goal(goal, recent_done_goals)

    weighted_total = active_count + recent_success + max(recent_failed, failed_live)
    weighted_done = recent_success + active_weight
    completion_percent = round((weighted_done / weighted_total) * 100) if weighted_total > 0 else 100

    summary_goals = []
    for goal in recent_done_goals[:3]:
        if goal not in summary_goals:
            summary_goals.append(goal)
    for goal in active_goals[:3]:
        if goal not in summary_goals:
            summary_goals.append(goal)
        if len(summary_goals) >= 3:
            break

    def _result_text(item: dict[str, Any] | None) -> str | None:
        if not item:
            return None
        result = item.get("result") or {}
        if isinstance(result, dict):
            return str(result.get("summary") or result.get("error") or "").strip() or None
        return str(result).strip() or None

    return {
        "window_minutes": window_minutes,
        "active_count": active_count,
        "failed_live": failed_live,
        "recent_success": recent_success,
        "recent_failed": recent_failed,
        "completion_percent": completion_percent,
        "recent_goals": summary_goals,
        "recent_done_goals": recent_done_goals[:3],
        "active_goals": active_goals[:3],
        "active_weight": round(active_weight, 2),
        "running_items": running_items[:2],
        "queued_items": queued_items[:2],
        "latest_done_goal": _goal_name(latest_done or {}),
        "latest_done_status": str((latest_done or {}).get("status") or ""),
        "latest_done_result": _result_text(latest_done),
        "latest_failed_goal": _goal_name(latest_failed or {}),
        "latest_failed_status": str((latest_failed or {}).get("status") or ""),
        "latest_failed_result": _result_text(latest_failed),
    }


def _interval_minutes(config: SelfReportConfig, status_cache: dict[str, Any]) -> int:
    interval_seconds = _safe_int(status_cache.get("interval_seconds"), 60)
    cadence_minutes = list(config.cadence_minutes or [240, 480, 720, 1440])
    scheduled_interval = min(cadence_minutes) if cadence_minutes else round((interval_seconds * 10) / 60)
    return max(5, scheduled_interval)


def _capability_scores(metrics: dict[str, Any]) -> dict[str, int]:
    autonomy = round(_safe_float(metrics.get("autonomy_score")) * 100)
    quality = round(_safe_float(metrics.get("quality_score")) * 100)
    health = 100 if str(metrics.get("tool_health_status") or "") == "pass" else max(40, 100 - _safe_int(metrics.get("tool_issue_count")) * 15)
    overall = round((autonomy + quality + health) / 3)
    return {"autonomy": autonomy, "quality": quality, "health": health, "overall": overall}


def _target_chars(window_minutes: int) -> int:
    if window_minutes <= 15:
        return 120
    if window_minutes <= 60:
        return 180
    return 260


def _status_completion(value: Any) -> int:
    mapping = {
        "pass": 100,
        "healthy": 100,
        "stable": 90,
        "running": 80,
        "attention": 40,
        "constrained": 35,
        "operator_attention": 30,
        "blocked": 20,
        "failed": 10,
        "error": 0,
        "critical": 0,
    }
    return mapping.get(str(value or "unknown").strip().lower(), 50)


def _company_dimensions(company_status: dict[str, Any]) -> dict[str, int]:
    layers = company_status.get("layers") or {}

    def layer_score(name: str) -> int:
        return _status_completion((layers.get(name) or {}).get("status"))

    product = round((layer_score("strategy") + layer_score("organization") + layer_score("project")) / 3)
    engineering = round((layer_score("engineering") + layer_score("execution") + layer_score("learning")) / 3)
    testing = layer_score("ai_testing")
    release = layer_score("release_operations")
    return {
        "product": product,
        "engineering": engineering,
        "testing": testing,
        "release": release,
    }


def _company_dimensions_phrase(company: dict[str, Any]) -> str:
    dimensions = company.get("dimensions") or {}
    if not dimensions:
        return ""
    return (
        f"\u5206\u9879\u4ea7{dimensions.get('product', 0)}"
        f"/\u5de5{dimensions.get('engineering', 0)}"
        f"/\u6d4b{dimensions.get('testing', 0)}"
        f"/\u53d1{dimensions.get('release', 0)}%\u3002"
    )


def _trend_phrase(delta: int) -> str:
    if delta > 0:
        return f"\u8f83\u4e0a\u6b21\u63d0\u5347{delta}%"
    if delta < 0:
        return f"\u8f83\u4e0a\u6b21\u4e0b\u964d{abs(delta)}%"
    return "\u8f83\u4e0a\u6b21\u6301\u5e73"


def _fmt_timestamp(value: Any) -> str:
    stamp = _parse_utc(value)
    if stamp is None:
        return str(value or "unknown")
    return stamp.astimezone().strftime("%Y-%m-%d %H:%M")


def _fmt_uptime(started_at: Any, reported_at: Any) -> str:
    start = _parse_utc(started_at)
    end = _parse_utc(reported_at)
    if start is None or end is None or end < start:
        return "unknown"
    delta = end - start
    minutes = int(delta.total_seconds() // 60)
    hours, mins = divmod(minutes, 60)
    if hours <= 0:
        return f"{mins}m"
    return f"{hours}h {mins}m"


def _safe_ratio(numerator: Any, denominator: Any, default: int = 0) -> int:
    try:
        num = float(numerator)
        den = float(denominator)
        if den <= 0:
            return default
        return round((num / den) * 100)
    except Exception:
        return default


def _resource_metrics() -> dict[str, Any]:
    cpu = None
    ram_gb = None
    try:
        import psutil  # type: ignore
        cpu = round(float(psutil.cpu_percent(interval=0.05)))
        ram_gb = round(psutil.virtual_memory().used / (1024 ** 3), 1)
    except Exception:
        pass
    usage = _load_json(DATA / "usage_tracker.json", {})
    telemetry = _load_json(DATA / "telemetry_events.json", {})
    return {
        "cpu_usage": cpu,
        "ram_usage_gb": ram_gb,
        "model_calls": _safe_int(usage.get("cheap_calls")) + _safe_int(usage.get("reasoning_calls")) + _safe_int(usage.get("strong_calls")),
        "api_calls": _safe_int(telemetry.get("cheap_calls_total")) + _safe_int(telemetry.get("reasoning_calls_total")),
    }


def _quality_metrics(summary: dict[str, Any]) -> dict[str, int]:
    metrics = summary.get("metrics") or {}
    tasks = summary.get("tasks") or {}
    recent_success = _safe_int(tasks.get("recent_success"))
    recent_failed = _safe_int(tasks.get("recent_failed"))
    total_recent = recent_success + recent_failed
    regression_rate = round((recent_failed / total_recent) * 100, 1) if total_recent else 0.0
    open_errors = _safe_int(metrics.get("open_error_count"))
    active_count = max(1, _safe_int(tasks.get("active_count"), 1))
    rework_rate = round((open_errors / active_count) * 100, 1)
    return {
        "pass_rate": round(_safe_float(metrics.get("ai_testing_pass_rate")) * 100),
        "regression_rate": regression_rate,
        "rework_rate": rework_rate,
    }


def _ability_breakdown(summary: dict[str, Any]) -> dict[str, int]:
    capability = summary.get("capability") or {}
    company = summary.get("company") or {}
    dimensions = company.get("dimensions") or {}
    autonomy = _safe_int(capability.get("autonomy"))
    quality = _safe_int(capability.get("quality"))
    health = _safe_int(capability.get("health"))
    return {
        "code_generation": round((_safe_int(dimensions.get("engineering")) + quality) / 2),
        "problem_solving": round((autonomy + quality) / 2),
        "system_understanding": round((_safe_int(dimensions.get("product")) + autonomy + health) / 3),
        "self_optimization": round((autonomy + health) / 2),
    }


def _system_health_score(summary: dict[str, Any]) -> int:
    capability = summary.get("capability") or {}
    company = summary.get("company") or {}
    tasks = summary.get("tasks") or {}
    metrics = summary.get("metrics") or {}
    base = round((_safe_int(capability.get("overall")) + _safe_int(company.get("completion_percent")) + _safe_int(tasks.get("completion_percent"))) / 3)
    penalties = min(40, _safe_int(metrics.get("open_error_count")) * 12 + _safe_int(tasks.get("recent_failed")) * 8)
    return max(0, min(100, base - penalties))


def _exception_lines(summary: dict[str, Any]) -> list[str]:
    metrics = summary.get("metrics") or {}
    daemon_state = _load_json(DATA / "factory_daemon_state.json", {})
    issues: list[str] = []
    if daemon_state.get("last_error"):
        issues.append(f"daemon: {daemon_state.get('last_error')}")
    if _safe_int(metrics.get("open_error_count")) > 0:
        issues.append(f"core_messages: open_error={metrics.get('open_error_count')}")
    if metrics.get("ai_testing_alert"):
        issues.append("ai_testing: alert active")
    if str(metrics.get("release_train_status") or "") == "blocked":
        issues.append("release_train: blocked")
    if not issues:
        issues.append("?????")
    return issues


def _avg_task_duration() -> str:
    history = _load_json(DATA / "task_history.json", [])
    durations: list[float] = []
    for item in history[-50:]:
        created = _parse_utc(item.get("created_at"))
        updated = _parse_utc(item.get("updated_at"))
        status = str(item.get("status") or "").lower()
        if created and updated and updated >= created and status in {"completed", "succeeded", "resolved", "merged", "done"}:
            durations.append((updated - created).total_seconds() / 60)
    if not durations:
        return "unknown"
    return f"{sum(durations) / len(durations):.1f} min"


def _build_report_sections(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = summary.get("metrics") or {}
    tasks = summary.get("tasks") or {}
    company = summary.get("company") or {}
    capability = summary.get("capability") or {}
    dimensions = company.get("dimensions") or {}
    resources = _resource_metrics()
    quality = _quality_metrics(summary)
    abilities = _ability_breakdown(summary)
    daemon_state = _load_json(DATA / "factory_daemon_state.json", {})
    control_layer = _load_json(DATA / "control_layer_status.json", {})
    telemetry = _load_json(DATA / "telemetry_events.json", {})
    usage = _load_json(DATA / "usage_tracker.json", {})
    org = _load_json(DATA / "organization_model.json", {})
    queue_depth = _safe_int((control_layer.get("state_kernel") or {}).get("queued_tasks"))
    if not queue_depth:
        queue_depth = _safe_int(telemetry.get("task_waiting"))
    agents = len(_load_json(DATA / "agent_experience.json", []))
    completed_total = _safe_int(telemetry.get("task_completed")) or len(_load_json(DATA / "task_archive.json", []))
    return {
        "timestamp": _fmt_timestamp(summary.get("reported_at")),
        "version": "MetaForge v2",
        "uptime": _fmt_uptime(daemon_state.get("started_at"), summary.get("reported_at")),
        "health_score": _system_health_score(summary),
        "runtime_status": _zh_status(summary.get("overall_status")),
        "stage": _zh_status(metrics.get("autonomy_stage")) or "??",
        "capability_score": _safe_int(capability.get("overall")),
        "task_completion": _safe_int(tasks.get("completion_percent")),
        "company_completion": _safe_int(company.get("completion_percent")),
        "company_delta": _trend_phrase(_safe_int(company.get("completion_delta"), 0)),
        "production_score": _safe_int(dimensions.get("product")),
        "engineering_score": _safe_int(dimensions.get("engineering")),
        "testing_score": _safe_int(dimensions.get("testing")),
        "release_score": _safe_int(dimensions.get("release")),
        "running_tasks": _safe_int(tasks.get("active_count")),
        "queued_tasks": queue_depth,
        "completed_tasks": completed_total,
        "avg_task_duration": _avg_task_duration(),
        "cpu_usage": resources.get("cpu_usage"),
        "ram_usage_gb": resources.get("ram_usage_gb"),
        "model_calls": resources.get("model_calls"),
        "api_calls": resources.get("api_calls"),
        "scheduler_status": _zh_status(metrics.get("control_status")),
        "queue_depth": queue_depth,
        "agents": agents if agents else len((org.get("teams") or {})),
        "daemon_status": _zh_status(metrics.get("daemon_status")),
        "code_generation": abilities.get("code_generation"),
        "problem_solving": abilities.get("problem_solving"),
        "system_understanding": abilities.get("system_understanding"),
        "self_optimization": abilities.get("self_optimization"),
        "pass_rate": quality.get("pass_rate"),
        "regression_rate": quality.get("regression_rate"),
        "rework_rate": quality.get("rework_rate"),
        "exceptions": _exception_lines(summary),
        "recommendations": summary.get("recommendations") or ["????????"],
        "short_summary": _compose_brief(summary, markdown=False),
        "last_provider": usage.get("last_provider"),
        "last_model": usage.get("last_model"),
    }


def _zh_status(value: Any) -> str:
    mapping = {
        "healthy": "健康",
        "attention": "关注",
        "critical": "告警",
        "running": "运行中",
        "operator_attention": "人工关注",
        "error": "异常",
        "stopped": "已停止",
        "stale": "心跳过期",
        "constrained": "受限",
        "pass": "通过",
        "failed": "失败",
        "degraded": "降级",
        "blocked": "阻塞",
        "unknown": "未知",
        "stage4_confirmed": "四阶段确认",
        "developing": "\u5efa\u8bbe\u4e2d",
        "mature": "\u6210\u719f",
    }
    key = str(value or "unknown").strip().lower()
    return mapping.get(key, str(value or "未知"))


def _goal_theme(goal: str) -> str:
    lowered = goal.lower()
    if "repo learning" in lowered or "knowledge routing" in lowered:
        return "仓库学习"
    if "toyos" in lowered or "kernel" in lowered:
        return "内核分支"
    if "verification" in lowered or "regression" in lowered or "test" in lowered:
        return "验证覆盖"
    if "distillation" in lowered:
        return "能力蒸馏"
    if "governance" in lowered or "architecture" in lowered:
        return "架构治理"
    return "交付任务"


def _task_theme_phrase(goals: list[str]) -> str:
    if not goals:
        return "近期无归档任务"
    theme_counts: dict[str, int] = {}
    for goal in goals[:6]:
        theme = _goal_theme(str(goal or ""))
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
    ordered = sorted(theme_counts.items(), key=lambda item: (-item[1], item[0]))[:2]
    parts = []
    for theme, count in ordered:
        parts.append(f"{theme}{count}项")
    return "、".join(parts) if parts else "交付任务"


def _build_summary(
    *,
    cycle: int | None,
    trigger: str,
    daemon: dict[str, Any],
    status_cache: dict[str, Any],
    core_messages: list[dict[str, Any]],
) -> dict[str, Any]:
    open_messages = [item for item in core_messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_messages if item.get("severity") == "error"]
    open_warnings = [item for item in open_messages if item.get("severity") == "warning"]
    overall_status, blockers = _determine_overall_status(daemon, status_cache, core_messages)
    autonomy = status_cache.get("autonomy") or {}
    control_layer = status_cache.get("control_layer") or {}
    engineering = status_cache.get("engineering_os") or {}
    ai_testing = status_cache.get("ai_testing") or {}
    release_ops = status_cache.get("release_ops") or {}
    lab = status_cache.get("lab") or {}
    tool_health = status_cache.get("tool_health") or {}

    facts = [
        f"daemon={daemon.get('status') or 'unknown'}",
        f"control={control_layer.get('status') or 'unknown'}",
        f"autonomy={autonomy.get('stage') or 'unknown'}:{autonomy.get('score')}",
        f"ai_testing={ai_testing.get('status') or 'unknown'}",
        f"open_errors={len(open_errors)}",
        f"open_warnings={len(open_warnings)}",
        f"release={release_ops.get('release_train_status') or release_ops.get('status') or 'unknown'}",
    ]

    recommendations: list[str] = []
    if not _daemon_running(daemon):
        recommendations.append("\u6062\u590d\u5de5\u5382\u5b88\u62a4\u8fdb\u7a0b\u8fd0\u884c")
    if len(open_errors) > 0:
        recommendations.append("\u4f18\u5148\u6e05\u7406\u6838\u5fc3\u9519\u8bef\u6d88\u606f")
    if ai_testing.get("alert"):
        recommendations.append("\u5c3d\u5feb\u5904\u7406AI\u6d4b\u8bd5\u544a\u8b66")
    if _safe_int(engineering.get("patch_blocked_count")) > 0:
        recommendations.append("\u89e3\u9664\u8865\u4e01\u963b\u585e\u5e76\u6062\u590d\u5408\u5165")
    if release_ops.get("release_train_status") == "blocked":
        recommendations.append("\u89e3\u9664\u53d1\u5e03\u5217\u8f66\u963b\u585e")
    if not recommendations:
        recommendations.append("\u7ee7\u7eed\u7a33\u5b9a\u63a8\u8fdb\u4ea4\u4ed8")

    summary_line = (
        f"\u5de5\u5382\u6574\u4f53\u72b6\u6001{_zh_status(overall_status)}\uff0c"
        f"\u5b88\u62a4\u8fdb\u7a0b{_zh_status(daemon.get('status'))}\uff0c"
        f"\u63a7\u5236\u5c42{_zh_status(control_layer.get('status'))}\uff0c"
        f"AI\u6d4b\u8bd5{_zh_status(ai_testing.get('status'))}\uff0c"
        f"\u672a\u5173\u95ed\u9519\u8bef{len(open_errors)}\u9879\u3002"
    )

    metrics = {
        "daemon_status": daemon.get("status"),
        "daemon_running": _daemon_running(daemon),
        "control_status": control_layer.get("status"),
        "quality_score": control_layer.get("quality_score"),
        "autonomy_stage": autonomy.get("stage"),
        "autonomy_score": autonomy.get("score"),
        "lab_status": lab.get("status"),
        "tool_health_status": tool_health.get("status"),
        "tool_issue_count": tool_health.get("tool_issue_count", tool_health.get("issue_count")),
        "engineering_status": engineering.get("status"),
        "patch_blocked_count": engineering.get("patch_blocked_count"),
        "patch_ready_count": engineering.get("patch_ready_count"),
        "ai_testing_status": ai_testing.get("status"),
        "ai_testing_pass_rate": ai_testing.get("pass_rate"),
        "ai_testing_error_count": ai_testing.get("error_count"),
        "ai_testing_alert": ai_testing.get("alert"),
        "open_message_count": len(open_messages),
        "open_error_count": len(open_errors),
        "open_warning_count": len(open_warnings),
        "release_ops_status": release_ops.get("status"),
        "release_train_status": release_ops.get("release_train_status"),
    }

    return {
        "reported_at": _utc_now(),
        "trigger": trigger,
        "cycle": cycle,
        "overall_status": overall_status,
        "blockers": blockers,
        "summary_line": summary_line,
        "facts": facts,
        "recommendations": recommendations,
        "metrics": metrics,
        "sources": {
            "daemon": str(DATA / "factory_daemon_state.json"),
            "status_cache": str(DATA / "status_cache.json"),
            "core_messages": str(DATA / "core_messages.json"),
        },
    }

def _render_markdown(summary: dict[str, Any]) -> str:
    sections = _build_report_sections(summary)
    lines = [
        "【MetaForge Factory Report】",
        "",
        f"时间: {sections.get('timestamp')}",
        f"系统版本: {sections.get('version')}",
        f"运行时: {sections.get('uptime')}",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【总体状态】",
        f"健康度: {sections.get('health_score')}/100",
        f"运行状态: {sections.get('runtime_status')}",
        f"阶段: {sections.get('stage')}",
        f"能力评分: {sections.get('capability_score')}/100",
        "",
        f"任务完成度: {sections.get('task_completion')}%",
        f"公司完成度: {sections.get('company_completion')}% ({sections.get('company_delta')})",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【生产流水线】",
        "",
        f"生产 (Production): {sections.get('production_score')}/100",
        f"工程 (Engineering): {sections.get('engineering_score')}/100",
        f"测试 (Testing): {sections.get('testing_score')}/100",
        f"发布 (Release): {sections.get('release_score')}/100",
        "",
        "当前任务:",
        f"- 运行中: {sections.get('running_tasks')}",
        f"- 排队: {sections.get('queued_tasks')}",
        f"- 完成: {sections.get('completed_tasks')}",
        "",
        f"平均任务时长: {sections.get('avg_task_duration')}",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【系统资源】",
        "",
        f"CPU: {sections.get('cpu_usage') if sections.get('cpu_usage') is not None else 'unknown'}%",
        f"内存: {sections.get('ram_usage_gb') if sections.get('ram_usage_gb') is not None else 'unknown'}GB",
        f"模型调用: {sections.get('model_calls')}",
        f"外部API: {sections.get('api_calls')}",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【控制层】",
        "",
        f"调度器: {sections.get('scheduler_status')}",
        f"队列深度: {sections.get('queue_depth')}",
        f"Agent数量: {sections.get('agents')}",
        "",
        f"Daemon状态: {sections.get('daemon_status')}",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【AI能力】",
        "",
        f"代码生成: {sections.get('code_generation')}/100",
        f"问题解决: {sections.get('problem_solving')}/100",
        f"系统理解: {sections.get('system_understanding')}/100",
        f"自我优化: {sections.get('self_optimization')}/100",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【质量指标】",
        "",
        f"测试通过率: {sections.get('pass_rate')}%",
        f"回归率: {sections.get('regression_rate')}%",
        f"返工率: {sections.get('rework_rate')}%",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【异常】",
        "",
    ]
    for item in sections.get('exceptions') or ["无关键异常"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【建议行动】",
        "",
    ])
    for idx, item in enumerate(sections.get('recommendations') or ["继续稳定推进交付"], start=1):
        lines.append(f"{idx}. {item}")
    lines.extend([
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【总体评估】",
        "",
        sections.get('short_summary') or "",
        "",
        "━━━━━━━━━━━━━━━━",
        "",
        "【补充上下文】",
        "",
        f"最近模型: {sections.get('last_provider') or 'unknown'} / {sections.get('last_model') or 'unknown'}",
        f"摘要行: {summary.get('summary_line') or ''}",
        "",
    ])
    return "\n".join(lines)


def _brief_goal(goal: str, limit: int = 18) -> str:
    goal = str(goal or "").strip()
    if not goal:
        return ""
    return goal if len(goal) <= limit else goal[: max(1, limit - 3)] + "..."


def _brief_result(result: str | None, limit: int = 16) -> str:
    text = str(result or "").strip()
    normalized = text.lower()
    if "timed out" in normalized:
        text = "超时无进展"
    elif "auto-closed" in normalized or "stale runtime task" in normalized:
        text = "超时自动收口"
    elif "superseded" in normalized:
        text = "被新任务替代"
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _task_snapshot_phrase(tasks: dict[str, Any]) -> str:
    running = [_brief_goal(item) for item in (tasks.get("running_items") or []) if item]
    queued = [_brief_goal(item) for item in (tasks.get("queued_items") or []) if item]
    latest_done_goal = _brief_goal(tasks.get("latest_done_goal") or "")
    latest_done_result = _brief_result(tasks.get("latest_done_result"))
    latest_failed_goal = _brief_goal(tasks.get("latest_failed_goal") or "")
    latest_failed_result = _brief_result(tasks.get("latest_failed_result"))

    parts: list[str] = []
    if running:
        parts.append(f"运行:{'、'.join(running)}")
    if queued:
        parts.append(f"排队:{'、'.join(queued)}")
    if latest_done_goal:
        done_text = f"完成:{latest_done_goal}"
        if latest_done_result:
            done_text += f"({latest_done_result})"
        parts.append(done_text)
    if latest_failed_goal:
        failed_text = f"异常:{latest_failed_goal}"
        if latest_failed_result:
            failed_text += f"({latest_failed_result})"
        parts.append(failed_text)
    return "；".join(parts[:3]) if parts else "任务结果平稳"


def _build_notify_subject(summary: dict[str, Any]) -> str:
    capability = summary.get("capability") or {}
    company = summary.get("company") or {}
    return f"工厂汇报[{_zh_status(summary.get('overall_status'))}] 能力{capability.get('overall', 0)}分 公司完成度{company.get('completion_percent', 0)}%"


def _compose_brief(summary: dict[str, Any], *, markdown: bool = False) -> str:
    metrics = summary["metrics"]
    capability = summary["capability"]
    tasks = summary["tasks"]
    company = summary.get("company") or {}
    advice = (summary.get("recommendations") or ["\u7ee7\u7eed\u7a33\u5b9a\u63a8\u8fdb\u4ea4\u4ed8"])[0]
    overall_status = _zh_status(summary["overall_status"])
    control_status = _zh_status(metrics.get("control_status"))
    ai_status = _zh_status(metrics.get("ai_testing_status"))
    release_status = _zh_status(metrics.get("release_train_status") or metrics.get("release_ops_status"))
    company_status = _zh_status(company.get("status"))
    theme = _task_theme_phrase(tasks.get("recent_goals") or [])
    trend = _trend_phrase(_safe_int(company.get("completion_delta"), 0))
    task_snapshot = _task_snapshot_phrase(tasks)
    base = (
        f"\u5de5\u5382\u5f53\u524d{overall_status}\uff0c\u516c\u53f8\u5b8c\u6210\u5ea6{company.get('completion_percent', 0)}%\uff0c{trend}\uff0c"
        f"\u80fd\u529b{capability['overall']}\u5206\uff0c\u4efb\u52a1\u5b8c\u6210\u5ea6{tasks['completion_percent']}%\u3002"
        f"\u4efb\u52a1\u72b6\u6001:{task_snapshot}\u3002"
    )
    detail = (
        f"\u9636\u6bb5{theme}\u3002"
        f"\u603b\u4f53\uff1a\u516c\u53f8{company_status}\uff0c\u63a7\u5236\u5c42{control_status}\uff0cAI\u6d4b\u8bd5{ai_status}\uff0c\u53d1\u5e03{release_status}\uff0c\u5efa\u8bae{advice}\u3002"
    )
    text = base + detail
    target = _target_chars(tasks["window_minutes"])
    if len(text) > target:
        text = (
            f"\u5de5\u5382{overall_status}\uff0c\u516c\u53f8\u5b8c\u6210\u5ea6{company.get('completion_percent', 0)}%\uff0c{trend}\uff0c\u80fd\u529b{capability['overall']}\u5206\u3002"
            f"\u4efb\u52a1:{task_snapshot}\u3002\u603b\u4f53\uff1a\u516c\u53f8{company_status}\uff0c\u63a7\u5236\u5c42{control_status}\uff0cAI\u6d4b\u8bd5{ai_status}\uff0c\u53d1\u5e03{release_status}\u3002"
        )
    if len(text) > 300:
        text = text[:297] + "..."
    elif len(text) < 100:
        extra = f" \u5efa\u8bae{advice}\u3002"
        text = (text + extra)[:300]
    if markdown:
        return f"# {_build_notify_subject(summary)}\n\n{text}\n"
    return text


def _format_list(items: Any, *, bullet: str = "- ") -> list[str]:
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            lines.append(f"{bullet}{text}")
    return lines


def _format_kv_pairs(items: list[tuple[str, Any]], *, markdown: bool) -> list[str]:
    lines: list[str] = []
    for label, value in items:
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value if str(item).strip()) or "none"
        elif isinstance(value, dict):
            rendered = json.dumps(value, ensure_ascii=False)
        elif value is None:
            rendered = "none"
        else:
            rendered = str(value)
        prefix = "- " if not markdown else "- "
        lines.append(f"{prefix}{label}: {rendered}")
    return lines


def _build_detailed_report_text(summary: dict[str, Any], *, markdown: bool = False) -> str:
    report_chain = summary.get("report_chain") or {}
    system_report = report_chain.get("system_report") or {}
    intent = report_chain.get("intent") or {}
    execution = report_chain.get("execution") or {}
    decisions = report_chain.get("decisions") or {}
    evidence = report_chain.get("evidence") or {}
    capability = report_chain.get("capability") or {}
    company = summary.get("company") or {}
    tasks = summary.get("tasks") or {}

    lines: list[str] = []
    header = _build_notify_subject(summary)
    lines.append(f"# {header}" if markdown else header)
    lines.append("")
    lines.append("0. Quick Summary")
    lines.append(_compose_brief(summary, markdown=False))
    lines.append("")
    lines.append("1. Intent Layer")
    lines.extend(_format_kv_pairs(
        [
            ("primary_goal", system_report.get("primary_goal") or intent.get("primary_goal") or "unknown"),
            ("goal_mode", system_report.get("goal_mode") or intent.get("goal_mode") or "unknown"),
            ("priority_reason", intent.get("priority_reason") or "unknown"),
            ("operator_override", intent.get("operator_override")),
            ("expected_next_delivery", intent.get("expected_next_delivery") or "unknown"),
        ],
        markdown=markdown,
    ))
    lines.append("")
    lines.append("2. Execution Layer")
    lines.extend(_format_kv_pairs(
        [
            ("system_state", system_report.get("system_state") or summary.get("overall_status")),
            ("current_action", system_report.get("current_action") or "unknown"),
            ("active_task_count", execution.get("active_task_count", tasks.get("active_count", 0))),
            ("pending_tasks", execution.get("pending_tasks", tasks.get("pending_tasks", 0))),
            ("running_tasks", execution.get("running_tasks") or []),
            ("queue_health", execution.get("queue_health") or "unknown"),
            ("blocked_on", execution.get("blocked_on") or system_report.get("top_blocker") or "none"),
            ("current_worker_allocation", execution.get("current_worker_allocation") or {}),
        ],
        markdown=markdown,
    ))
    lines.append("")
    lines.append("3. Decision Layer")
    latest_decisions = decisions.get("latest_decisions") if isinstance(decisions.get("latest_decisions"), list) else []
    for item in latest_decisions[:5]:
        if not isinstance(item, dict):
            continue
        stamp = item.get("time") or item.get("ts") or "unknown"
        decision_type = item.get("type") or item.get("decision_type") or "decision"
        decision = item.get("decision") or "unknown"
        reason = item.get("reason") or "no reason"
        impact = item.get("impact")
        if impact:
            lines.append(f"- {stamp} | {decision_type} | {decision} | {reason} | impact={impact}")
        else:
            lines.append(f"- {stamp} | {decision_type} | {decision} | {reason}")
    if not latest_decisions:
        lines.append("- none")
    lines.append("")
    lines.append("4. Evidence Layer")
    lines.extend(_format_kv_pairs(
        [
            ("latest_artifact", evidence.get("latest_artifact") or "unknown"),
            ("latest_artifact_status", evidence.get("latest_artifact_status") or "unknown"),
            ("verification_status", evidence.get("verification_status") or "unknown"),
            ("release_readiness", evidence.get("release_readiness") or "unknown"),
            ("artifacts_last_24h", evidence.get("artifacts_last_24h", 0)),
            ("valuable_artifacts_last_24h", evidence.get("valuable_artifacts_last_24h", 0)),
            ("block_reason", evidence.get("block_reason") or "none"),
        ],
        markdown=markdown,
    ))
    lines.append("")
    lines.append("5. Capability Matrix")
    for name, item in capability.items():
        if not isinstance(item, dict):
            continue
        details = item.get("status")
        if item.get("reason"):
            details = f"{details} ({item.get('reason')})"
        lines.append(f"- {name}: {details}")
    lines.append("")
    lines.append("6. Summary Sentences")
    lines.extend(_format_list(system_report.get("summary_sentences") or []))
    lines.append("")
    lines.append("7. Company and Task Snapshot")
    lines.extend(_format_kv_pairs(
        [
            ("company_status", company.get("status") or "unknown"),
            ("company_completion_percent", company.get("completion_percent", 0)),
            ("company_completion_delta", company.get("completion_delta", 0)),
            ("task_completion_percent", tasks.get("completion_percent", 0)),
            ("task_active_count", tasks.get("active_count", 0)),
            ("task_pending_count", tasks.get("pending_tasks", 0)),
            ("recent_goals", tasks.get("recent_goals") or []),
        ],
        markdown=markdown,
    ))
    lines.append("")
    lines.append("8. Recommended Next Action")
    lines.append(f"- {system_report.get('recommended_next_action') or (summary.get('recommendations') or ['继续稳定推进交付'])[0]}")

    text = "\n".join(lines).strip() + "\n"
    if markdown:
        return text
    return text


def _build_notify_text(summary: dict[str, Any]) -> str:
    return _build_detailed_report_text(summary, markdown=False)


def _build_notify_markdown(summary: dict[str, Any]) -> str:
    return _build_detailed_report_text(summary, markdown=True)


def _send_serverchan(sendkey: str, title: str, desp: str) -> dict[str, Any]:
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=12) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body) if body else {}
    except Exception:
        parsed = {"raw": body}
    delivered = parsed.get("code") == 0 if isinstance(parsed, dict) else True
    return {"attempted": True, "delivered": delivered, "response": parsed}


def _send_qq_mail(config: SelfReportConfig, subject: str, text: str) -> dict[str, Any]:
    sender = config.qq_mail_from or config.qq_mail_username
    recipients = config.qq_mail_to
    message = MIMEText(text, "plain", "utf-8")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = sender
    message["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL(config.qq_mail_smtp_host, config.qq_mail_smtp_port, timeout=15) as server:
        server.login(config.qq_mail_username, config.qq_mail_password)
        server.sendmail(sender, recipients, message.as_string())

    return {
        "attempted": True,
        "delivered": True,
        "smtp_host": config.qq_mail_smtp_host,
        "smtp_port": config.qq_mail_smtp_port,
        "recipients": recipients,
    }


def send_factory_notification(
    subject: str,
    text: str,
    *,
    markdown: str | None = None,
    send_serverchan: bool = True,
    send_qq_mail: bool = True,
) -> dict[str, Any]:
    config = load_self_report_config()
    notify_markdown = markdown or text
    delivery: dict[str, Any] = {
        "serverchan": {"attempted": False, "delivered": False, "reason": "disabled"},
        "qq_mail": {"attempted": False, "delivered": False, "reason": "disabled"},
    }
    if send_serverchan:
        delivery["serverchan"]["attempted"] = True
        if config.serverchan_sendkey:
            try:
                delivery["serverchan"] = _send_serverchan(config.serverchan_sendkey, subject, notify_markdown)
            except urllib.error.HTTPError as exc:
                delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": f"http_error:{exc.code}"}
            except Exception as exc:
                delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": str(exc)}
        else:
            delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": "missing ORCH_SERVERCHAN_SENDKEY"}
    if send_qq_mail:
        delivery["qq_mail"]["attempted"] = True
        qq_ready = bool(config.qq_mail_enabled and config.qq_mail_username and config.qq_mail_password and config.qq_mail_to)
        if qq_ready:
            try:
                delivery["qq_mail"] = _send_qq_mail(config, subject, text)
            except Exception as exc:
                delivery["qq_mail"] = {"attempted": True, "delivered": False, "reason": str(exc)}
        else:
            delivery["qq_mail"] = {"attempted": True, "delivered": False, "reason": "missing QQ mail config"}
    return {
        "reported_at": _utc_now(),
        "subject": subject,
        "text": text,
        "markdown": notify_markdown,
        "delivery": delivery,
    }


def run_factory_self_report(
    *,
    trigger: str = "manual",
    cycle: int | None = None,
    send_notifications: bool = True,
    write_opencode: bool = True,
) -> dict[str, Any]:
    config = load_self_report_config()
    daemon = _load_json(DATA / "factory_daemon_state.json", {})
    status_cache = _load_json(DATA / "status_cache.json", {})
    core_messages = _load_json(DATA / "core_messages.json", [])
    summary = _build_summary(
        cycle=cycle,
        trigger=trigger,
        daemon=daemon,
        status_cache=status_cache,
        core_messages=core_messages,
    )
    interval_minutes = _interval_minutes(config, status_cache)
    summary["tasks"] = _task_window_stats(interval_minutes)
    summary["capability"] = _capability_scores(summary["metrics"])
    company_status = _load_json(DATA / "company_os_status.json", {})
    previous_report = _load_json(JSON_REPORT_PATH, {})
    previous_company = previous_report.get("company") or {}
    current_completion = round(float(company_status.get("score", 0.0) or 0.0) * 100)
    current_dimensions = _company_dimensions(company_status)
    previous_dimensions = previous_company.get("dimensions") or {}
    summary["company"] = {
        "status": company_status.get("status"),
        "score": company_status.get("score"),
        "completion_percent": current_completion,
        "completion_delta": current_completion - _safe_int(previous_company.get("completion_percent"), current_completion),
        "project_count": (company_status.get("summary") or {}).get("project_count", 0),
        "platform_count": (company_status.get("summary") or {}).get("platform_count", 0),
        "department_count": (company_status.get("summary") or {}).get("department_count", 0),
        "dimensions": current_dimensions,
        "dimension_deltas": {
            "product": current_dimensions.get("product", 0) - _safe_int(previous_dimensions.get("product"), current_dimensions.get("product", 0)),
            "engineering": current_dimensions.get("engineering", 0) - _safe_int(previous_dimensions.get("engineering"), current_dimensions.get("engineering", 0)),
            "testing": current_dimensions.get("testing", 0) - _safe_int(previous_dimensions.get("testing"), current_dimensions.get("testing", 0)),
            "release": current_dimensions.get("release", 0) - _safe_int(previous_dimensions.get("release"), current_dimensions.get("release", 0)),
        },
    }
    report_chain = build_report_chain(write_outputs=True)
    summary["report_chain"] = {
        "intent": report_chain.get("intent") or {},
        "execution": report_chain.get("execution") or {},
        "decisions": report_chain.get("decisions") or {},
        "evidence": report_chain.get("evidence") or {},
        "capability": report_chain.get("capability") or {},
        "system_report": report_chain.get("system_report") or {},
        "delivery": report_chain.get("delivery") or {},
    }
    summary["report_chain_outputs"] = report_chain.get("delivery") or {}
    schedule_state = _parse_report_schedule_state(REPORT_SCHEDULE_PATH)
    if not schedule_state:
        started_at = _parse_utc(daemon.get("started_at")) or _parse_utc(daemon.get("last_cycle_started_at")) or _local_now()
        schedule_state = _schedule_state_from_anchor(config, started_at, phase_index=0)
    reported_at = datetime.now(timezone.utc)
    next_schedule_state = _advance_schedule_state(config, schedule_state, reported_at=reported_at)
    report_schedule = {
        **schedule_state,
        "mode": "scheduled",
        "interval_minutes": interval_minutes,
        "reported_at": reported_at.isoformat().replace("+00:00", "Z"),
        "fired_report_at": schedule_state.get("next_report_at"),
        "fired_report_kind": schedule_state.get("next_report_kind"),
        "next_report_at": next_schedule_state.get("next_report_at"),
        "next_report_kind": next_schedule_state.get("next_report_kind"),
        "next_phase_index": next_schedule_state.get("phase_index"),
    }
    if send_notifications or write_opencode:
        atomic_write_json(REPORT_SCHEDULE_PATH, next_schedule_state)

    subject = _build_notify_subject(summary)
    notify_text = _build_notify_text(summary)
    notify_markdown = _build_notify_markdown(summary)

    delivery: dict[str, Any] = {
        "opencode": {"written": False, "path": str(OPENCODE_REPORT_PATH)},
        "serverchan": {"attempted": False, "delivered": False, "reason": "disabled"},
        "qq_mail": {"attempted": False, "delivered": False, "reason": "disabled"},
    }

    if write_opencode:
        OPENCODE_REPORT_PATH.write_text(_render_markdown(summary), encoding="utf-8")
        delivery["opencode"] = {"written": True, "path": str(OPENCODE_REPORT_PATH)}

    if send_notifications:
        delivery["serverchan"]["attempted"] = True
        if config.serverchan_sendkey:
            try:
                delivery["serverchan"] = _send_serverchan(config.serverchan_sendkey, subject, notify_markdown)
            except urllib.error.HTTPError as exc:
                delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": f"http_error:{exc.code}"}
            except Exception as exc:
                delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": str(exc)}
        else:
            delivery["serverchan"] = {"attempted": True, "delivered": False, "reason": "missing ORCH_SERVERCHAN_SENDKEY"}

        delivery["qq_mail"]["attempted"] = True
        qq_ready = bool(config.qq_mail_enabled and config.qq_mail_username and config.qq_mail_password and config.qq_mail_to)
        if qq_ready:
            try:
                delivery["qq_mail"] = _send_qq_mail(config, subject, notify_text)
            except Exception as exc:
                delivery["qq_mail"] = {"attempted": True, "delivered": False, "reason": str(exc)}
        else:
            delivery["qq_mail"] = {"attempted": True, "delivered": False, "reason": "missing QQ mail config"}

    payload = {
        **summary,
        "report_chain": report_chain["system_report"],
        "report_chain_outputs": report_chain["delivery"],
        "report_schedule": report_schedule,
        "delivery": delivery,
        "config": {
            "enabled": config.enabled,
            "on_alert": config.on_alert,
            "interval_minutes": interval_minutes,
            "cadence_minutes": list(config.cadence_minutes),
            "weekly_day": config.weekly_day,
            "weekly_hour": config.weekly_hour,
            "weekly_minute": config.weekly_minute,
            "serverchan_configured": bool(config.serverchan_sendkey),
            "qq_mail_configured": bool(config.qq_mail_enabled and config.qq_mail_username and config.qq_mail_password and config.qq_mail_to),
        },
        "notification_preview": {
            "subject": subject,
            "text": notify_text,
            "markdown": notify_markdown,
            "report_text": notify_text,
            "report_markdown": notify_markdown,
        },
    }
    atomic_write_json(JSON_REPORT_PATH, payload)
    return payload
