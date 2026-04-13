from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AGENT_EXPERIENCE = DATA / "agent_experience.json"
OUT = DATA / "scheduler_optimization_status.json"


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


def run_scheduler_optimization_sweep() -> dict[str, Any]:
    experience = _load_json(AGENT_EXPERIENCE, {})
    workers = experience.get("workers", {}) if isinstance(experience, dict) else {}
    ranked = []
    for worker, stats in workers.items():
        success_rate = float(stats.get("success_rate", 0.0) or 0.0)
        attempts = int(stats.get("attempts", 0) or 0)
        score = round(success_rate * min(1.0, attempts / 5), 4)
        ranked.append({
            "worker": worker,
            "attempts": attempts,
            "success_rate": success_rate,
            "score": score,
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    payload = {
        "updated_at": _utc(),
        "worker_count": len(ranked),
        "top_workers": ranked[:5],
        "recommendation": ranked[0]["worker"] if ranked else None,
        "status": "completed",
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_scheduler_optimization_sweep(), ensure_ascii=False, indent=2))
