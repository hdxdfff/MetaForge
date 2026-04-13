from __future__ import annotations

import argparse
import json
from typing import Any

from app.risk_engine import DATA
from tools.io_utils import atomic_write_json
from tools.risk_scan import run_risk_branch

DRILL_OUT = DATA / "risk_drills"


def _scenario_snapshot(name: str) -> dict[str, Any]:
    if name == "queue_starvation":
        return {
            "goal_primary": "restore_toyos_delivery",
            "goal_mode": "toyos_priority_mode",
            "daemon_running": True,
            "daemon_heartbeat_fresh": True,
            "queue_depth": 0,
            "active_tasks": 0,
            "completed_tasks_last_60m": 0,
            "worker_idle_ratio": 0.92,
            "verification_pending_checks_count": 0,
            "artifact_updates_last_24h": 0,
            "provider_route_count": 2,
            "provider_failure_count": 0,
            "provider_auth_failure_count": 0,
            "release_train_status": "ready",
            "quality_status": "attention",
            "continuity_mode": "preserved",
            "state_write_error_recent": False,
            "latest_repair_action": None,
            "latest_repair_result": None,
            "raw": {},
        }
    if name == "continuity_distortion":
        return {
            "goal_primary": "restore_toyos_delivery",
            "goal_mode": "toyos_priority_mode",
            "daemon_running": True,
            "daemon_heartbeat_fresh": True,
            "queue_depth": 1,
            "active_tasks": 0,
            "completed_tasks_last_60m": 0,
            "worker_idle_ratio": 0.9,
            "verification_pending_checks_count": 0,
            "artifact_updates_last_24h": 0,
            "provider_route_count": 1,
            "provider_failure_count": 0,
            "provider_auth_failure_count": 0,
            "release_train_status": "ready",
            "quality_status": "attention",
            "continuity_mode": "preserved",
            "state_write_error_recent": True,
            "latest_repair_action": None,
            "latest_repair_result": None,
            "raw": {},
        }
    if name == "provider_401":
        return {
            "goal_primary": "restore_toyos_delivery",
            "goal_mode": "toyos_priority_mode",
            "daemon_running": True,
            "daemon_heartbeat_fresh": True,
            "queue_depth": 1,
            "active_tasks": 1,
            "completed_tasks_last_60m": 0,
            "worker_idle_ratio": 0.25,
            "verification_pending_checks_count": 0,
            "artifact_updates_last_24h": 0,
            "provider_route_count": 2,
            "provider_failure_count": 2,
            "provider_auth_failure_count": 2,
            "release_train_status": "ready",
            "quality_status": "attention",
            "continuity_mode": "preserved",
            "state_write_error_recent": False,
            "latest_repair_action": "switch_provider_fallback",
            "latest_repair_result": "success",
            "raw": {},
        }
    if name == "verification_misalignment":
        return {
            "goal_primary": "restore_toyos_delivery",
            "goal_mode": "toyos_priority_mode",
            "daemon_running": True,
            "daemon_heartbeat_fresh": True,
            "queue_depth": 1,
            "active_tasks": 1,
            "completed_tasks_last_60m": 1,
            "worker_idle_ratio": 0.25,
            "verification_pending_checks_count": 2,
            "artifact_updates_last_24h": 0,
            "provider_route_count": 1,
            "provider_failure_count": 0,
            "provider_auth_failure_count": 0,
            "release_train_status": "ready",
            "quality_status": "attention",
            "continuity_mode": "preserved",
            "state_write_error_recent": False,
            "latest_repair_action": "re_run_verification",
            "latest_repair_result": "success",
            "raw": {},
        }
    raise ValueError(f"Unknown drill scenario: {name}")


def run_drills(*, apply_repairs: bool, scenarios: list[str]) -> dict[str, Any]:
    DRILL_OUT.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    for scenario in scenarios:
        snapshot = _scenario_snapshot(scenario)
        payload = run_risk_branch(snapshot=snapshot, apply_repairs=apply_repairs, source=f"drill:{scenario}")
        out_path = DRILL_OUT / f"{scenario}.json"
        atomic_write_json(out_path, payload)
        results[scenario] = {
            "out_path": str(out_path),
            "risk_count": payload["status"]["risk_count"],
            "scan_status": payload["status"]["scan_status"],
        }
    return {"updated_at": None, "apply_repairs": apply_repairs, "scenarios": results, "out_dir": str(DRILL_OUT)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run risk branch drills.")
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Scenario to run. Repeat to run multiple.")
    parser.add_argument("--apply", action="store_true", help="Apply safe repairs in the drill.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    scenarios = args.scenarios or ["queue_starvation", "continuity_distortion", "provider_401", "verification_misalignment"]
    payload = run_drills(apply_repairs=args.apply, scenarios=scenarios)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"drills written to {payload['out_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
