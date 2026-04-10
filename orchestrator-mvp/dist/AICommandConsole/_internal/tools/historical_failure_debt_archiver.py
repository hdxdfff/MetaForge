from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT / "generated" / "historical-failure-debt-archive"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.execution_trace import append_trace

OUTPUT = DATA / "historical_failure_debt_archive.json"
TASK_HISTORY_PATH = DATA / "task_history.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _failed_tasks(task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for item in task_history:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").lower() == "failed":
            failures.append(item)
    return failures


def _severity(failure_count: int, failure_rate: float) -> str:
    if failure_count >= 75 or failure_rate >= 0.35:
        return "high"
    if failure_count >= 25 or failure_rate >= 0.15:
        return "medium"
    return "low"


def run_historical_failure_debt_archiver() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    task_history = _load_json(TASK_HISTORY_PATH, [])
    if not isinstance(task_history, list):
        task_history = []
    failed = _failed_tasks(task_history)
    status_counts = Counter(str(item.get("status") or "unknown").lower() for item in task_history if isinstance(item, dict))
    goal_counts = Counter(str(item.get("goal") or "unknown") for item in failed)
    samples = failed[:20]
    generated_at = _utc()
    archive_dir = GENERATED / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir.mkdir(parents=True, exist_ok=True)
    previous_archive = _load_json(OUTPUT, {})
    if not isinstance(previous_archive, dict):
        previous_archive = {}
    previous_failed_count = int(previous_archive.get("historical_failure_debt_count") or previous_archive.get("failed_task_count") or 0)
    current_failed_count = len(failed)
    failure_rate = round(current_failed_count / len(task_history), 4) if task_history else 0.0
    burndown_rate = 0.0
    last_reduced_at = previous_archive.get("historical_failure_debt_last_reduced_at")
    if previous_failed_count and current_failed_count < previous_failed_count:
        burndown_rate = round((previous_failed_count - current_failed_count) / max(1, previous_failed_count), 4)
        last_reduced_at = generated_at
    if not last_reduced_at:
        last_reduced_at = None
    payload = {
        "updated_at": generated_at,
        "status": "archived",
        "task_history_count": len(task_history),
        "failed_task_count": current_failed_count,
        "failure_rate": failure_rate,
        "historical_failure_debt_count": current_failed_count,
        "historical_failure_debt_severity": _severity(current_failed_count, failure_rate),
        "historical_failure_debt_burndown_rate": burndown_rate,
        "historical_failure_debt_last_reduced_at": last_reduced_at,
        "status_counts": dict(status_counts),
        "top_failed_goals": goal_counts.most_common(10),
        "failed_samples": samples,
        "archive_dir": str(archive_dir),
        "risk_notes": [
            "This archive separates historical failure debt from live queue pressure.",
            "Use queue_pressure_analysis.json for current operational pressure.",
        ],
    }
    atomic_write_json(OUTPUT, payload)
    atomic_write_json(archive_dir / "historical_failure_debt_archive.json", payload)
    atomic_write_json(
        archive_dir / "archive_manifest.json",
        {
            "bundle_id": archive_dir.name,
            "created_at": generated_at,
            "files": ["historical_failure_debt_archive.json"],
            "status": "archived",
        },
    )
    append_trace(
        "industrial-readiness",
        "archive historical failure debt",
        "run historical_failure_debt_archiver.py",
        f"status=archived debt={current_failed_count}",
        "refresh industrial readiness report",
        worker="cheap-worker",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"archive_dir": str(archive_dir), "historical_failure_debt_count": current_failed_count},
    )
    return payload


def main() -> int:
    _ = argparse.ArgumentParser(description="Archive historical task failure debt into a separate evidence bundle.").parse_args()
    print(json.dumps(run_historical_failure_debt_archiver(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
