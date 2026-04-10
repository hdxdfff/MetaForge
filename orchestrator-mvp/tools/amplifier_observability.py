from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OBSERVABILITY_PATH = DATA / "amplifier_observability.json"

DEFAULT_AMPLIFIERS = (
    "self_repair_task_generator",
    "artifact_growth_task_generator",
    "p2_sandbox_task_generator",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _empty_stats() -> dict[str, Any]:
    return {
        "trigger_count": 0,
        "generated_tasks": 0,
        "entered_execution": 0,
        "completed_tasks": 0,
        "success_conversion_rate": 0.0,
        "last_triggered_at": None,
        "last_completed_at": None,
        "last_updated_at": None,
    }


def _normalize(payload: Any) -> dict[str, Any]:
    state = payload if isinstance(payload, dict) else {}
    state.setdefault("version", 1)
    state.setdefault("updated_at", None)
    state.setdefault("events", [])
    amplifiers = state.get("amplifiers")
    if not isinstance(amplifiers, dict):
        amplifiers = {}
    normalized: dict[str, Any] = {}
    for name in DEFAULT_AMPLIFIERS:
        stats = amplifiers.get(name) if isinstance(amplifiers.get(name), dict) else {}
        merged = _empty_stats()
        merged.update({k: stats.get(k, merged[k]) for k in merged})
        merged["success_conversion_rate"] = round(
            float(merged["completed_tasks"]) / max(1, float(merged["generated_tasks"])),
            4,
        ) if merged["generated_tasks"] else 0.0
        normalized[name] = merged
    for name, stats in amplifiers.items():
        if name in normalized or not isinstance(stats, dict):
            continue
        merged = _empty_stats()
        merged.update({k: stats.get(k, merged[k]) for k in merged})
        merged["success_conversion_rate"] = round(
            float(merged["completed_tasks"]) / max(1, float(merged["generated_tasks"])),
            4,
        ) if merged["generated_tasks"] else 0.0
        normalized[name] = merged
    state["amplifiers"] = normalized
    if not isinstance(state["events"], list):
        state["events"] = []
    return state


def load_observability() -> dict[str, Any]:
    return _normalize(_load_json(OBSERVABILITY_PATH, {}))


def record_run(
    amplifier_name: str,
    *,
    generated_tasks: int,
    entered_execution: int = 0,
    completed_tasks: int = 0,
    trigger_count: int = 1,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = load_observability()
    amplifiers = state.setdefault("amplifiers", {})
    stats = amplifiers.get(amplifier_name) if isinstance(amplifiers.get(amplifier_name), dict) else _empty_stats()
    if amplifier_name not in amplifiers:
        amplifiers[amplifier_name] = stats
    now = _utc()
    stats["trigger_count"] = int(stats.get("trigger_count") or 0) + max(0, int(trigger_count))
    stats["generated_tasks"] = int(stats.get("generated_tasks") or 0) + max(0, int(generated_tasks))
    stats["entered_execution"] = int(stats.get("entered_execution") or 0) + max(0, int(entered_execution))
    stats["completed_tasks"] = int(stats.get("completed_tasks") or 0) + max(0, int(completed_tasks))
    stats["last_triggered_at"] = now
    stats["last_updated_at"] = now
    if completed_tasks:
        stats["last_completed_at"] = now
    stats["success_conversion_rate"] = round(
        float(stats["completed_tasks"]) / max(1, float(stats["generated_tasks"])),
        4,
    ) if stats["generated_tasks"] else 0.0
    event = {
        "id": f"amp_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "amplifier": amplifier_name,
        "created_at": now,
        "trigger_count": max(0, int(trigger_count)),
        "generated_tasks": max(0, int(generated_tasks)),
        "entered_execution": max(0, int(entered_execution)),
        "completed_tasks": max(0, int(completed_tasks)),
        "success_conversion_rate": stats["success_conversion_rate"],
        "metadata": metadata or {},
    }
    events = state.setdefault("events", [])
    events.append(event)
    if len(events) > 1000:
        state["events"] = events[-1000:]
    state["updated_at"] = now
    from tools.io_utils import atomic_write_json

    atomic_write_json(OBSERVABILITY_PATH, state)
    return event


def window_summary(window_days: int = 1) -> dict[str, Any]:
    state = load_observability()
    now = datetime.now(timezone.utc)
    threshold = now - timedelta(days=window_days)
    summary: dict[str, Any] = {
        "updated_at": state.get("updated_at"),
        "window_days": window_days,
        "amplifiers": {},
        "aggregate": {
            "trigger_count": 0,
            "generated_tasks": 0,
            "entered_execution": 0,
            "completed_tasks": 0,
        },
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
        created_at = str(event.get("created_at") or "")
        try:
            event_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except Exception:
            continue
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        else:
            event_time = event_time.astimezone(timezone.utc)
        if event_time < threshold:
            continue
        name = str(event.get("amplifier") or "unknown")
        entry = summary["amplifiers"].setdefault(
            name,
            {
                "trigger_count": 0,
                "generated_tasks": 0,
                "entered_execution": 0,
                "completed_tasks": 0,
                "success_conversion_rate": 0.0,
            },
        )
        trigger_count = int(event.get("trigger_count") or 0)
        generated_tasks = int(event.get("generated_tasks") or 0)
        entered_execution = int(event.get("entered_execution") or 0)
        completed_tasks = int(event.get("completed_tasks") or 0)
        entry["trigger_count"] += trigger_count
        entry["generated_tasks"] += generated_tasks
        entry["entered_execution"] += entered_execution
        entry["completed_tasks"] += completed_tasks
        summary["aggregate"]["trigger_count"] += trigger_count
        summary["aggregate"]["generated_tasks"] += generated_tasks
        summary["aggregate"]["entered_execution"] += entered_execution
        summary["aggregate"]["completed_tasks"] += completed_tasks
    for entry in summary["amplifiers"].values():
        generated = int(entry.get("generated_tasks") or 0)
        completed = int(entry.get("completed_tasks") or 0)
        entry["success_conversion_rate"] = round(completed / max(1, generated), 4) if generated else 0.0
    aggregate_generated = int(summary["aggregate"]["generated_tasks"] or 0)
    aggregate_completed = int(summary["aggregate"]["completed_tasks"] or 0)
    summary["aggregate"]["success_conversion_rate"] = round(aggregate_completed / max(1, aggregate_generated), 4) if aggregate_generated else 0.0
    return summary
