from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
USAGE_FILE = DATA / "usage_tracker.json"


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _ratio_allowed(ratio: float, total_calls: int, limit: float, min_calls: int) -> bool:
    return total_calls < min_calls or ratio <= limit


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except Exception:
        return default


def load_usage_snapshot() -> dict[str, Any]:
    usage = _load_json(USAGE_FILE, {})
    if not isinstance(usage, dict):
        usage = {}
    recent_window = usage.get("recent_window") or {}
    if not isinstance(recent_window, dict):
        recent_window = {}

    total_calls = _coerce_int(usage.get("total_calls"), 0)
    recent_total_calls = _coerce_int(recent_window.get("total_calls"), 0)
    ratio_sample_min_calls = _coerce_int(
        usage.get("ratio_sample_min_calls"),
        settings.model_usage_ratio_sample_min_calls,
    )
    use_recent_window = recent_total_calls >= ratio_sample_min_calls

    reasoning_ratio = _coerce_float(usage.get("reasoning_ratio"), 0.0)
    strong_ratio = _coerce_float(usage.get("strong_ratio"), 0.0)
    if use_recent_window:
        reasoning_ratio = _coerce_float(recent_window.get("reasoning_ratio"), reasoning_ratio)
        strong_ratio = _coerce_float(recent_window.get("strong_ratio"), strong_ratio)
        total_calls_for_ratio = recent_total_calls
    else:
        total_calls_for_ratio = total_calls

    effective_reasoning_ratio = _coerce_float(
        usage.get("effective_reasoning_ratio"),
        reasoning_ratio,
    )
    effective_strong_ratio = _coerce_float(
        usage.get("effective_strong_ratio"),
        strong_ratio,
    )
    if use_recent_window:
        effective_reasoning_ratio = reasoning_ratio
        effective_strong_ratio = strong_ratio

    max_reasoning_ratio = _coerce_float(
        usage.get("max_reasoning_model_ratio"),
        settings.model_usage_max_reasoning_ratio,
    )
    max_strong_ratio = _coerce_float(
        usage.get("max_strong_model_ratio"),
        settings.model_usage_max_strong_ratio,
    )

    reasoning_allowed = _ratio_allowed(
        effective_reasoning_ratio,
        total_calls_for_ratio,
        max_reasoning_ratio,
        ratio_sample_min_calls,
    )
    strong_allowed = _ratio_allowed(
        effective_strong_ratio,
        total_calls_for_ratio,
        max_strong_ratio,
        ratio_sample_min_calls,
    )

    usage["updated_at"] = usage.get("updated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    usage["window_hours"] = _coerce_int(usage.get("window_hours"), 24)
    usage["recent_window"] = recent_window
    usage["cheap_calls"] = _coerce_int(usage.get("cheap_calls"), 0)
    usage["reasoning_calls"] = _coerce_int(usage.get("reasoning_calls"), 0)
    usage["strong_calls"] = _coerce_int(usage.get("strong_calls"), 0)
    usage["total_calls"] = total_calls
    usage["successful_calls"] = _coerce_int(usage.get("successful_calls"), total_calls)
    usage["non_fallback_ratio"] = _coerce_float(usage.get("non_fallback_ratio"), 1.0 if total_calls else 0.0)
    usage["total_input_chars"] = _coerce_int(usage.get("total_input_chars"), 0)
    usage["total_output_chars"] = _coerce_int(usage.get("total_output_chars"), 0)
    usage["output_input_ratio"] = _coerce_float(usage.get("output_input_ratio"), 0.0)
    usage["reasoning_ratio"] = reasoning_ratio
    usage["strong_ratio"] = strong_ratio
    usage["recent_window_sample_sufficient"] = use_recent_window
    usage["ratio_sample_min_calls"] = ratio_sample_min_calls
    usage["effective_ratio_source"] = "recent_window" if use_recent_window else usage.get("effective_ratio_source", "full_window")
    usage["effective_reasoning_ratio"] = effective_reasoning_ratio
    usage["effective_strong_ratio"] = effective_strong_ratio
    usage["max_reasoning_model_ratio"] = max_reasoning_ratio
    usage["max_strong_model_ratio"] = max_strong_ratio
    usage["reasoning_allowed"] = reasoning_allowed
    usage["strong_allowed"] = strong_allowed
    usage["reasoning_pressure"] = round(effective_reasoning_ratio / max(0.0001, max_reasoning_ratio), 4)
    usage["strong_pressure"] = round(effective_strong_ratio / max(0.0001, max_strong_ratio), 4)
    if not strong_allowed:
        usage["demand_pressure"] = "strong-throttled"
    elif not reasoning_allowed:
        usage["demand_pressure"] = "reasoning-throttled"
    else:
        usage["demand_pressure"] = "balanced"
    return usage
