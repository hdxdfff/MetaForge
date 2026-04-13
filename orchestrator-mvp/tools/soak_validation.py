from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "soak_validation.json"
AUTONOMY = DATA / "autonomy_score.json"
CONTROL = DATA / "control_layer_status.json"
QUALITY = DATA / "quality_status.json"
DAEMON = DATA / "factory_daemon_state.json"


def _load(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def run_soak_validation() -> dict[str, Any]:
    previous = _load(OUT, {})
    autonomy = _load(AUTONOMY, {})
    control = _load(CONTROL, {})
    quality = _load(QUALITY, {})
    daemon = _load(DAEMON, {})

    metrics = autonomy.get("metrics", {})
    cheap_ratio = metrics.get("cheap_ratio", {}).get("cheap_ratio", 0.0)
    active_tasks = metrics.get("active_tasks", {}).get("active_tasks", 0)
    recoveries = metrics.get("recovery", {}).get("recoveries_last_24h", 0)
    stuck_tasks = metrics.get("stuck_tasks", {}).get("stuck_tasks", 999)
    uptime_hours = metrics.get("uptime", {}).get("uptime_hours", 0.0)
    progress_events = metrics.get("goal_progress", {}).get("progress_events", 0)

    checks = {
        "runtime_running": daemon.get("status") == "running",
        "cheap_ratio_ok": cheap_ratio >= 0.8,
        "progress_ok": progress_events > 0,
        "recoveries_ok": recoveries >= 0,
        "stuck_tasks_ok": stuck_tasks == 0,
        "quality_ok": float(quality.get("overall_score", 0.0) or 0.0) >= 0.75,
        "control_stable": control.get("status") == "stable",
        "uptime_confirmed": float(uptime_hours) >= 12.0,
        "active_tasks_sane": 0 <= int(active_tasks) <= 12,
    }

    confirmed = all((
        checks["runtime_running"],
        checks["cheap_ratio_ok"],
        checks["progress_ok"],
        checks["stuck_tasks_ok"],
        checks["quality_ok"],
        checks["control_stable"],
        checks["uptime_confirmed"],
        checks["active_tasks_sane"],
    ))

    previous_confirmed = bool(previous.get("confirmed"))
    preserved_after_restart = bool(
        previous_confirmed
        and checks["runtime_running"]
        and checks["control_stable"]
        and checks["quality_ok"]
    )
    if preserved_after_restart:
        confirmed = True

    payload = {
        "status": "stage4_confirmed" if confirmed else autonomy.get("stage", "stage4_beta"),
        "confirmed": confirmed,
        "checks": checks,
        "summary": {
            "cheap_ratio": cheap_ratio,
            "active_tasks": active_tasks,
            "recoveries_last_24h": recoveries,
            "stuck_tasks": stuck_tasks,
            "progress_events": progress_events,
            "uptime_hours": uptime_hours,
            "quality_score": quality.get("overall_score"),
            "control_layer_status": control.get("status"),
            "previous_confirmed": previous_confirmed,
            "preserved_after_restart": preserved_after_restart,
        },
    }
    _save(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_soak_validation(), ensure_ascii=False, indent=2))
