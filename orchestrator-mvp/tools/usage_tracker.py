from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
TELEMETRY = DATA / "telemetry_events.json"
OUT = DATA / "usage_tracker.json"
POLICY = ROOT / "runtime" / "policy" / "upgrade_policy.json"
RECENT_WINDOW_HOURS = 1
MIN_RATIO_SAMPLE_CALLS = 5


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _window_metrics(events: list[dict[str, Any]], cutoff: datetime) -> dict[str, float | int | list[dict[str, Any]]]:
    kept = []
    for event in events:
        try:
            at = datetime.fromisoformat(str(event.get("at", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if at >= cutoff:
            kept.append(event)
    cheap_calls = sum(1 for event in kept if event.get("provider") == "cheap")
    reasoning_calls = sum(1 for event in kept if event.get("provider") == "reasoning")
    strong_calls = sum(1 for event in kept if event.get("provider") == "openai")
    total_calls = cheap_calls + reasoning_calls + strong_calls
    total = max(1, total_calls)
    has_fallback_signal = any("used_fallback" in event for event in kept)
    successful_calls = sum(1 for event in kept if not bool(event.get("used_fallback", False)))
    non_fallback_ratio = round((successful_calls / total), 4) if has_fallback_signal else (1.0 if total_calls else 0.0)
    has_char_signal = any(("input_chars" in event) or ("output_chars" in event) for event in kept)
    total_input_chars = sum(int(event.get("input_chars", 0) or 0) for event in kept)
    total_output_chars = sum(int(event.get("output_chars", 0) or 0) for event in kept)
    if has_char_signal and total_input_chars > 0:
        output_input_ratio = round(total_output_chars / max(1, total_input_chars), 4)
    else:
        output_input_ratio = 0.25 if total_calls else 0.0
    return {
        "events": kept,
        "cheap_calls": cheap_calls,
        "reasoning_calls": reasoning_calls,
        "strong_calls": strong_calls,
        "total_calls": total_calls,
        "successful_calls": successful_calls if has_fallback_signal else total_calls,
        "non_fallback_ratio": non_fallback_ratio,
        "total_input_chars": total_input_chars,
        "total_output_chars": total_output_chars,
        "output_input_ratio": output_input_ratio,
        "reasoning_ratio": round(reasoning_calls / total, 4),
        "strong_ratio": round(strong_calls / total, 4),
    }


def _ratio_allowed(ratio: float, total_calls: int, limit: float, min_calls: int) -> bool:
    # Treat the exact minimum sample size as still too small to hard-block the loop.
    return total_calls <= min_calls or ratio <= limit


def main() -> int:
    telemetry = _load_json(TELEMETRY, {})
    existing = _load_json(OUT, {})
    policy = _load_json(POLICY, {"max_strong_model_ratio": 0.2, "max_reasoning_model_ratio": 0.6})
    now = datetime.now(timezone.utc)
    window_hours = int(existing.get("window_hours", 24) or 24)
    recent_events = existing.get("recent_events", [])
    primary = _window_metrics(recent_events, now - timedelta(hours=window_hours))
    kept = list(primary["events"])
    cheap_calls = int(primary["cheap_calls"])
    reasoning_calls = int(primary["reasoning_calls"])
    strong_calls = int(primary["strong_calls"])
    total_calls = int(primary["total_calls"])
    if not kept:
        cheap_calls = int(telemetry.get("cheap_calls_total", 0) or 0)
        reasoning_calls = int(telemetry.get("reasoning_calls_total", 0) or 0)
        strong_calls = int(telemetry.get("core_escalations_total", 0) or 0)
        total_calls = cheap_calls + reasoning_calls + strong_calls
    total = max(1, total_calls)
    reasoning_ratio = round(reasoning_calls / total, 4)
    strong_ratio = round(strong_calls / total, 4)
    recent_window = _window_metrics(kept, now - timedelta(hours=RECENT_WINDOW_HOURS))
    recent_total_calls = int(recent_window["total_calls"])
    min_ratio_sample_calls = int(policy.get("min_ratio_sample_calls", MIN_RATIO_SAMPLE_CALLS) or MIN_RATIO_SAMPLE_CALLS)
    use_recent_window = recent_total_calls >= min_ratio_sample_calls
    effective_reasoning_ratio = float(recent_window["reasoning_ratio"] if use_recent_window else reasoning_ratio)
    effective_strong_ratio = float(recent_window["strong_ratio"] if use_recent_window else strong_ratio)
    max_reasoning_ratio = float(policy.get("max_reasoning_model_ratio", 0.6))
    max_strong_ratio = float(policy.get("max_strong_model_ratio", 0.2))
    payload = {
        "updated_at": _utc(),
        "window_hours": window_hours,
        "recent_events": kept[-500:],
        "cheap_calls": cheap_calls,
        "reasoning_calls": reasoning_calls,
        "strong_calls": strong_calls,
        "total_calls": total_calls,
        "successful_calls": int(primary["successful_calls"]),
        "non_fallback_ratio": float(primary["non_fallback_ratio"]),
        "total_input_chars": int(primary["total_input_chars"]),
        "total_output_chars": int(primary["total_output_chars"]),
        "output_input_ratio": float(primary["output_input_ratio"]),
        "reasoning_ratio": reasoning_ratio,
        "strong_ratio": strong_ratio,
        "recent_window": {
            "hours": RECENT_WINDOW_HOURS,
            "cheap_calls": int(recent_window["cheap_calls"]),
            "reasoning_calls": int(recent_window["reasoning_calls"]),
            "strong_calls": int(recent_window["strong_calls"]),
            "total_calls": recent_total_calls,
            "successful_calls": int(recent_window["successful_calls"]),
            "non_fallback_ratio": float(recent_window["non_fallback_ratio"]),
            "total_input_chars": int(recent_window["total_input_chars"]),
            "total_output_chars": int(recent_window["total_output_chars"]),
            "output_input_ratio": float(recent_window["output_input_ratio"]),
            "reasoning_ratio": float(recent_window["reasoning_ratio"]),
            "strong_ratio": float(recent_window["strong_ratio"]),
        },
        "ratio_sample_min_calls": min_ratio_sample_calls,
        "recent_window_sample_sufficient": use_recent_window,
        "effective_ratio_source": "recent_window" if use_recent_window else "full_window",
        "effective_reasoning_ratio": effective_reasoning_ratio,
        "effective_strong_ratio": effective_strong_ratio,
        "max_reasoning_model_ratio": max_reasoning_ratio,
        "reasoning_allowed": _ratio_allowed(effective_reasoning_ratio, recent_total_calls if use_recent_window else total_calls, max_reasoning_ratio, min_ratio_sample_calls),
        "max_strong_model_ratio": max_strong_ratio,
        "strong_allowed": _ratio_allowed(effective_strong_ratio, recent_total_calls if use_recent_window else total_calls, max_strong_ratio, min_ratio_sample_calls),
    }
    atomic_write_json(OUT, payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
