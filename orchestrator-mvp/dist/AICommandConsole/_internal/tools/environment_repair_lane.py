from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.runtime_maintenance import run_maintenance
from tools.tool_health_audit import append_tool_health_history, run_tool_health_audit
from tools.verification_engine import run_verification

DATA = ROOT / "data"
OUT = DATA / "environment_repair_status.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _run_json_script(path: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(path), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    payload = {}
    raw = (completed.stdout or "").strip()
    if raw:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw}
    return {
        "returncode": completed.returncode,
        "passed": completed.returncode == 0,
        "payload": payload,
    }


def run_environment_repair_lane(workspace: str | None = None, mode: str = "full") -> dict:
    maintenance = run_maintenance(mode=mode)
    tool_health = run_tool_health_audit()
    tool_health_history = append_tool_health_history(tool_health)
    db_runtime = _run_json_script(ROOT / "tools" / "db_runtime_check.py")
    if workspace:
        deployment = _run_json_script(ROOT / "tools" / "prepare_deployment.py", workspace)
    else:
        deployment = {"skipped": True, "reason": "no-workspace"}
    verification = run_verification()

    payload = {
        "updated_at": _utc(),
        "workspace": workspace,
        "mode": mode,
        "maintenance": maintenance,
        "tool_health": tool_health,
        "tool_health_history": tool_health_history,
        "db_runtime": db_runtime,
        "deployment": deployment,
        "verification": {
            "status": verification.get("status"),
            "patch_gate": (verification.get("patch_gate") or {}).get("status"),
            "runtime_health": (verification.get("runtime_health") or {}).get("status"),
        },
    }
    payload["status"] = (
        "pass"
        if tool_health.get("status") == "pass"
        and payload["verification"]["status"] == "pass"
        and db_runtime.get("passed", False)
        else "attention"
    )
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run environment deploy and repair lane.")
    parser.add_argument("--workspace")
    parser.add_argument("--mode", default="full", choices=["full", "light"])
    args = parser.parse_args()
    print(json.dumps(run_environment_repair_lane(workspace=args.workspace, mode=args.mode), ensure_ascii=False, indent=2))
