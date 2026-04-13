from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.experiment_ledger import close_with_distillation
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
FACTORY = ROOT / "factory"
EVALUATION = DATA / "experiment_evaluation.json"
RUN = DATA / "experiment_run.json"
OUT = DATA / "capability_distillation.json"
REPUTATION = DATA / "capability_reputation.json"
REGISTRY = FACTORY / "capability_registry.json"


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


def _build_capability_hints(registry: dict[str, Any], routing_bias: dict[str, float]) -> list[dict[str, Any]]:
    capabilities = registry.get("capabilities", [])
    if not capabilities:
        return []
    hints: list[dict[str, Any]] = []
    normalized_bias = {
        str(key or "").strip().lower(): float(value or 0.0)
        for key, value in (routing_bias or {}).items()
        if str(key or "").strip()
    }
    for item in capabilities:
        capability_id = str(item.get("capability_id") or "")
        capability_key = capability_id.lower()
        score = 0.0
        matched_bias = {}
        for key, value in normalized_bias.items():
            if key and (key in capability_key or capability_key in key):
                score += value
                matched_bias[key] = value
        if score > 0:
            hints.append(
                {
                    "capability_id": capability_id,
                    "provider_platform_id": item.get("provider_platform_id"),
                    "provider_name": item.get("provider_name"),
                    "boost": round(score, 4),
                    "matched_bias": matched_bias,
                }
            )
    hints.sort(key=lambda entry: entry.get("boost", 0.0), reverse=True)
    return hints[:12]


def distill_capabilities() -> dict[str, Any]:
    evaluation = _load_json(EVALUATION, {})
    run = _load_json(RUN, {})
    registry = _load_json(REGISTRY, {"capabilities": []})
    reputation = _load_json(REPUTATION, {"updated_at": None, "capabilities": {}, "workers": {}})
    decision_bias = evaluation.get("decision_bias") or ((run.get("result") or {}).get("decision_bias")) or {}
    routing_bias = decision_bias.get("routing_bias") or {}
    worker_bias = decision_bias.get("worker_bias") or {}
    experiment = evaluation.get("experiment") or (run.get("experiment") or {})
    experiment_id = str(evaluation.get("experiment_id") or run.get("experiment_id") or "").strip()
    adopted = bool(evaluation.get("adopt", False))
    score = float(evaluation.get("score", 0.0) or 0.0)

    capability_hints = _build_capability_hints(registry, routing_bias)
    distillation_artifact_ids: list[str] = []
    if adopted:
        for capability_id, boost in routing_bias.items():
            item = reputation.setdefault("capabilities", {}).setdefault(capability_id, {"score": 0.0, "count": 0})
            item["score"] = round(item.get("score", 0.0) + float(boost or 0.0) * score, 4)
            item["count"] = int(item.get("count", 0)) + 1
            distillation_artifact_ids.append(f"routing-bias:{capability_id}")
        for worker, boost in worker_bias.items():
            item = reputation.setdefault("workers", {}).setdefault(worker, {"score": 0.0, "count": 0})
            item["score"] = round(item.get("score", 0.0) + float(boost or 0.0) * score, 4)
            item["count"] = int(item.get("count", 0)) + 1
            distillation_artifact_ids.append(f"worker-bias:{worker}")
        for hint in capability_hints:
            capability_id = str(hint.get("capability_id") or "").strip()
            if capability_id:
                distillation_artifact_ids.append(f"capability-hint:{capability_id}")
    reputation["updated_at"] = _utc()
    _save_json(REPUTATION, reputation)

    has_distillation_value = bool(adopted and (routing_bias or worker_bias or capability_hints))
    status = "ready" if has_distillation_value else "no_distillation_value"
    verdict = {
        "status": "adopt" if adopted else "reject",
        "reason": "reusable-distillation-artifacts-generated" if has_distillation_value else "no-reusable-distillation-output",
        "score": score,
    }
    payload = {
        "updated_at": _utc(),
        "experiment_id": experiment_id,
        "experiment": experiment,
        "adopted": adopted,
        "routing_bias": routing_bias,
        "worker_bias": worker_bias,
        "capability_hints": capability_hints,
        "reputation": reputation,
        "distillation_artifact_ids": sorted(set(distillation_artifact_ids)),
        "status": status,
        "verdict": verdict,
    }
    _save_json(OUT, payload)
    if experiment_id:
        close_with_distillation(experiment_id, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(distill_capabilities(), ensure_ascii=False, indent=2))
