from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.harness_runner import HarnessRunner
from tools.io_utils import atomic_write_json


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RegressionRunner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.status_path = project_root / "data" / "harness_regression_status.json"
        self.harness = HarnessRunner(project_root)

    def run_suite(self, suite_path: Path) -> dict:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
        cases = suite.get("cases") or []
        started_at = datetime.now(UTC)
        results: list[dict] = []
        for case in cases:
            goal_path = Path(case["goal_file"])
            goal = json.loads(goal_path.read_text(encoding="utf-8"))
            result = self.harness.run_once(goal)
            results.append(
                {
                    "case_id": case["case_id"],
                    "name": case["name"],
                    "goal_id": goal["goal_id"],
                    "run_id": goal["run_id"],
                    "status": result["status"],
                    "evaluation_report": result["evaluation_report"],
                }
            )
        finished_at = datetime.now(UTC)
        total = len(results)
        pass_count = sum(1 for item in results if item["status"] == "pass")
        payload = {
            "suite_id": suite["suite_id"],
            "name": suite["name"],
            "started_at": started_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "finished_at": finished_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
            "case_count": total,
            "pass_count": pass_count,
            "fail_count": total - pass_count,
            "pass_rate": round(pass_count / total, 4) if total else 0.0,
            "results": results,
        }
        atomic_write_json(self.status_path, payload)
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Harness regression suite")
    parser.add_argument("--suite-file", required=True)
    args = parser.parse_args()
    runner = RegressionRunner(ROOT)
    result = runner.run_suite(Path(args.suite_file).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("fail_count", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
