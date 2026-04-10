from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = DATA / "queue_pressure_analysis.json"
HISTORICAL_DEBT_ARCHIVE_PATH = DATA / "historical_failure_debt_archive.json"

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


def run_queue_pressure_analyzer() -> dict[str, Any]:
    tasks = _load_json(DATA / "tasks.json", [])
    backlog = _load_json(DATA / "goal_backlog_status.json", {})
    task_history = _load_json(DATA / "task_history.json", [])
    if not isinstance(tasks, list):
        tasks = []
    if not isinstance(task_history, list):
        task_history = []
    open_count = sum(1 for item in tasks if isinstance(item, dict) and str(item.get("status") or "").lower() in {"planning", "running", "blocked"})
    failed_count = sum(1 for item in tasks if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed")
    active_goals = int(backlog.get("active_goal_count") or 0)
    starvation = int(backlog.get("starvation_seconds") or 0)
    history_failed_count = sum(1 for item in task_history if isinstance(item, dict) and str(item.get("status") or "").lower() == "failed")
    historical_debt_archive = _load_json(HISTORICAL_DEBT_ARCHIVE_PATH, {})
    debt_archive_status = str(historical_debt_archive.get("status") or "missing").lower()
    active_pressure_score = open_count + max(0, active_goals - open_count) + (1 if starvation >= 60 else 0)
    pressure = "low"
    if active_pressure_score >= 8:
        pressure = "high"
    elif active_pressure_score >= 4:
        pressure = "medium"
    payload = {
        "updated_at": _utc(),
        "status": "pass",
        "pressure": pressure,
        "open_task_count": open_count,
        "failed_task_count": failed_count,
        "historical_failed_task_count": history_failed_count,
        "historical_debt_archive_status": debt_archive_status,
        "historical_debt_archive_count": int(historical_debt_archive.get("failed_task_count") or 0) if isinstance(historical_debt_archive, dict) else 0,
        "active_goal_count": active_goals,
        "starvation_seconds": starvation,
        "retry_clusters": failed_count,
        "blocked_concentration": open_count - active_goals,
        "history_window_count": len(task_history),
        "active_pressure_score": active_pressure_score,
        "risk_notes": [
            "failed_task_count reflects currently open task statuses",
            "historical_failed_task_count reflects accumulated backlog debt",
            "historical debt is additionally captured in historical_failure_debt_archive.json",
        ],
    }
    atomic_write_json(OUTPUT, payload)
    return payload


def main() -> int:
    _ = argparse.ArgumentParser(description="Analyze queue pressure and starvation risk.").parse_args()
    print(json.dumps(run_queue_pressure_analyzer(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
