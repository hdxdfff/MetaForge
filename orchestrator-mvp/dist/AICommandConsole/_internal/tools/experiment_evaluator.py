from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.experiment_ledger import mark_evaluated
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
RUN = DATA / "experiment_run.json"
OUT = DATA / "experiment_evaluation.json"
HISTORY = DATA / "experiment_history.json"


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


def evaluate_experiment() -> dict[str, Any]:
    run = _load_json(RUN, {})
    result = run.get("result") or {}
    experiment = run.get("experiment") or {}
    experiment_id = str(run.get("experiment_id") or "").strip()
    if not result:
        payload = {
            "updated_at": _utc(),
            "status": "idle",
            "adopt": False,
            "reason": "no-experiment-result",
        }
        _save_json(OUT, payload)
        return payload

    score = round(
        float(result.get("success_rate", 0.0)) * 0.4
        + float(result.get("quality_score", 0.0)) * 0.3
        + float(result.get("latency_score", 0.0)) * 0.15
        + float(result.get("cost_score", 0.0)) * 0.15,
        4,
    )
    adopt = score >= 0.84
    decision_bias = result.get("decision_bias") or {}
    recommendation = {
        "bias_router": bool(decision_bias.get("routing_bias")),
        "bias_worker": bool(decision_bias.get("worker_bias")),
        "promote_kind": experiment.get("kind") if adopt else None,
    }
    payload = {
        "updated_at": _utc(),
        "status": "evaluated",
        "experiment_id": experiment_id,
        "score": score,
        "adopt": adopt,
        "experiment": experiment,
        "reason": "score-threshold-pass" if adopt else "score-below-threshold",
        "history_count": len(_load_json(HISTORY, [])),
        "decision_bias": decision_bias,
        "recommendation": recommendation,
    }
    _save_json(OUT, payload)
    if experiment_id:
        mark_evaluated(experiment_id, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(evaluate_experiment(), ensure_ascii=False, indent=2))
