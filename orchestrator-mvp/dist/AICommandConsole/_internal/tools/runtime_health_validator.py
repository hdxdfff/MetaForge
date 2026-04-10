from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.autonomy_state import autonomy_is_confirmed

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = DATA / "runtime_health_validation.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def run_runtime_health_validator() -> dict[str, Any]:
    daemon = _load_json(DATA / "factory_daemon_state.json", {})
    control = _load_json(DATA / "control_layer_status.json", {})
    autonomy = _load_json(DATA / "autonomy_score.json", {})
    ai_testing = (daemon.get("last_result") or {}).get("ai_testing") or {}
    status = "pass"
    issues = []
    if str(daemon.get("status") or "").lower() != "running":
        status = "attention"
        issues.append("daemon_not_running")
    if str(control.get("status") or "").lower() not in {"stable", "pass"}:
        status = "attention"
        issues.append("control_layer_not_stable")
    if str(ai_testing.get("status") or "").lower() == "degraded":
        status = "attention"
        issues.append("ai_testing_degraded")
    if not boolautonomy_is_confirmed(autonomy):
        status = "attention"
        issues.append("autonomy_not_stable")
    payload = {
        "updated_at": _utc(),
        "status": status,
        "daemon_status": daemon.get("status"),
        "control_layer_status": control.get("status"),
        "autonomy_stage": autonomy.get("stage"),
        "ai_testing_status": ai_testing.get("status"),
        "issues": issues,
    }
    atomic_write_json(OUTPUT, payload)
    return payload


def main() -> int:
    _ = argparse.ArgumentParser(description="Validate runtime health and emit a small report.").parse_args()
    print(json.dumps(run_runtime_health_validator(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
