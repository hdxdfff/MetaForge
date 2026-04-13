from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "platform_verification_sweep.json"

from tools.platform_registry import platform_health_summary
from tools.quality_system import run_quality
from tools.meta_factory_control import run_control_layer


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_sweep() -> dict:
    run_quality()
    control = run_control_layer()
    platforms = platform_health_summary()
    payload = {
        "updated_at": _utc(),
        "platform_runtime": platforms,
        "control_layer": {
            "status": control.get("status"),
            "quality_status": (control.get("quality_system") or {}).get("status"),
            "quality_score": (control.get("quality_system") or {}).get("overall_score"),
            "safety_status": (control.get("safety_system") or {}).get("status"),
            "evolution_allowed": (control.get("evolution_system") or {}).get("allowed"),
        },
        "summary": {
            "platform_count": platforms.get("platform_count", 0),
            "healthy_platforms": sum(1 for item in platforms.get("platforms", []) if item.get("health") == "healthy"),
            "active_platforms": platforms.get("active_count", 0),
            "unhealthy_platforms": platforms.get("unhealthy_count", 0),
        },
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_sweep(), ensure_ascii=False, indent=2))

