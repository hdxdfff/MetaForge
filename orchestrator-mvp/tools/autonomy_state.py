from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"
AUTONOMY = DATA / "autonomy_score.json"
SOAK = DATA / "soak_validation.json"


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def autonomy_is_confirmed(autonomy: dict[str, Any] | None) -> bool:
    if not autonomy:
        return False
    decision = autonomy.get("decision") or {}
    if decision.get("stable_autonomy") is not None:
        return bool(decision.get("stable_autonomy"))
    if autonomy.get("confirmed") is not None:
        return bool(autonomy.get("confirmed"))
    if autonomy.get("stable_autonomy") is not None:
        return bool(autonomy.get("stable_autonomy"))
    confirmation = autonomy.get("confirmation") or {}
    confirmation_status = str(confirmation.get("status") or "").strip().lower()
    if confirmation_status in {"confirmed", "preserved", "stable"}:
        return True
    if confirmation.get("soak_confirmed") is not None:
        return bool(confirmation.get("soak_confirmed"))
    return False


def load_effective_autonomy() -> dict[str, Any]:
    autonomy = _load_json(AUTONOMY, {})
    soak = _load_json(SOAK, {})
    if autonomy.get("runtime_critical") or float(autonomy.get("score", 1.0) or 1.0) < 0.5:
        return {
            **autonomy,
            "source": "autonomy_score_runtime_override",
            "confirmed": False,
        }
    if soak.get("confirmed"):
        summary = soak.get("summary") or {}
        return {
            **autonomy,
            "stage": soak.get("status", autonomy.get("stage")),
            "score": autonomy.get("score"),
            "source": "soak_validation",
            "confirmed": True,
            "summary": summary,
            "uptime_hours": summary.get("uptime_hours"),
            "cheap_ratio": summary.get("cheap_ratio"),
            "quality_score": summary.get("quality_score", autonomy.get("quality_score")),
            "control_layer_status": summary.get("control_layer_status", autonomy.get("control_layer_status")),
        }
    return {
        **autonomy,
        "source": "autonomy_score",
        "confirmed": autonomy_is_confirmed(autonomy),
    }
