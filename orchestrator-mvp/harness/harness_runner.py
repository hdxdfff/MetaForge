from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.contract_schema import SprintContract
from harness.evaluator import Evaluator
from harness.generator import BaselineToyOSCodeAgent, Generator
from harness.planner import Planner
from tools.io_utils import atomic_write_json


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class HarnessRunner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.runs_root = project_root / "factory" / "runtime" / "harness_runs"
        self.status_path = project_root / "data" / "harness_status.json"
        self.metrics_path = project_root / "data" / "harness_metrics.json"
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.planner = Planner(project_root)
        self.generator = Generator(BaselineToyOSCodeAgent())
        self.evaluator = Evaluator(project_root)

    def _make_run_dir(self, run_id: str) -> Path:
        run_dir = self.runs_root / run_id
        (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        return run_dir

    def _update_status(self, result: dict) -> None:
        current = {}
        if self.status_path.exists():
            current = json.loads(self.status_path.read_text(encoding="utf-8"))
        history = list(current.get("history") or [])
        history.append(result)
        history = history[-50:]
        payload = {
            **current,
            "updated_at": utc_now(),
            "supported_task_types": ["harness_atomic_feature", "harness_fix"],
            "last_run": result,
            "history": history,
        }
        atomic_write_json(self.status_path, payload)

    def _update_metrics(
        self,
        goal: dict,
        run_dir: Path,
        evaluation: dict,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        current = {}
        if self.metrics_path.exists():
            current = json.loads(self.metrics_path.read_text(encoding="utf-8"))
        history = list(current.get("history") or [])
        evidence = evaluation.get("evidence_integrity") or {}
        required_count = len(goal.get("required_evidence") or [])
        missing_count = len(evidence.get("missing_files") or [])
        completeness = 1.0 if required_count == 0 else max(0.0, (required_count - missing_count) / required_count)
        duration_seconds = max(0.0, (finished_at - started_at).total_seconds())
        history.append(
            {
                "run_id": goal["run_id"],
                "goal_id": goal["goal_id"],
                "feature_name": goal["feature_name"],
                "status": evaluation.get("verdict"),
                "time_to_verdict_seconds": round(duration_seconds, 3),
                "evidence_completeness": round(completeness, 4),
                "recorded_at": utc_now(),
            }
        )
        history = history[-200:]
        total = len(history)
        pass_count = sum(1 for item in history if item.get("status") == "pass")
        pass_rate = 0.0 if total == 0 else pass_count / total
        transition_count = 0
        if total > 1:
            for index in range(1, total):
                if history[index - 1].get("status") != history[index].get("status"):
                    transition_count += 1
        flakiness = 0.0 if total <= 1 else transition_count / (total - 1)
        avg_ttv = 0.0 if total == 0 else sum(float(item.get("time_to_verdict_seconds") or 0.0) for item in history) / total
        avg_evidence = 0.0 if total == 0 else sum(float(item.get("evidence_completeness") or 0.0) for item in history) / total
        by_goal: dict[str, dict] = {}
        for item in history:
            goal_id = str(item.get("goal_id"))
            bucket = by_goal.setdefault(
                goal_id,
                {
                    "runs": 0,
                    "pass_count": 0,
                    "transitions": 0,
                    "last_status": None,
                    "time_sum": 0.0,
                    "evidence_sum": 0.0,
                },
            )
            bucket["runs"] += 1
            if item.get("status") == "pass":
                bucket["pass_count"] += 1
            if bucket["last_status"] is not None and bucket["last_status"] != item.get("status"):
                bucket["transitions"] += 1
            bucket["last_status"] = item.get("status")
            bucket["time_sum"] += float(item.get("time_to_verdict_seconds") or 0.0)
            bucket["evidence_sum"] += float(item.get("evidence_completeness") or 0.0)
        per_goal = {}
        for goal_id, bucket in by_goal.items():
            runs = int(bucket["runs"])
            per_goal[goal_id] = {
                "runs": runs,
                "pass_rate": round(bucket["pass_count"] / runs, 4) if runs else 0.0,
                "flakiness": round(bucket["transitions"] / (runs - 1), 4) if runs > 1 else 0.0,
                "avg_time_to_verdict_seconds": round(bucket["time_sum"] / runs, 3) if runs else 0.0,
                "avg_evidence_completeness": round(bucket["evidence_sum"] / runs, 4) if runs else 0.0,
                "last_status": bucket["last_status"],
            }
        payload = {
            "updated_at": utc_now(),
            "metric_definitions": {
                "pass_rate": "passed_runs / total_runs",
                "flakiness": "status_transitions / adjacent_run_pairs",
                "time_to_verdict_seconds": "finished_at - started_at",
                "evidence_completeness": "(required_evidence - missing_evidence) / required_evidence",
            },
            "overall": {
                "runs": total,
                "pass_rate": round(pass_rate, 4),
                "flakiness": round(flakiness, 4),
                "avg_time_to_verdict_seconds": round(avg_ttv, 3),
                "avg_evidence_completeness": round(avg_evidence, 4),
            },
            "per_goal": per_goal,
            "history": history,
        }
        atomic_write_json(self.metrics_path, payload)

    def _register_artifact(self, goal: dict, run_dir: Path, evaluation: dict) -> None:
        if evaluation.get("verdict") != "pass":
            return
        registry_path = self.project_root / "data" / "artifact_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        artifacts = registry.get("artifacts") or []
        artifact_id = goal["goal_id"]
        entry = {
            "artifact_id": artifact_id,
            "type": "kernel_feature",
            "version": "0.1",
            "artifact_path": str(run_dir),
            "entrypoint": "evaluation_report.json",
            "manifest_present": False,
            "real": True,
            "status": "real",
            "delivery_status": "technical_only",
            "declared": {
                "buildable": True,
                "runnable": True,
                "test_passed": True,
                "reproducible": True,
            },
            "verified": {
                "buildable": True,
                "runnable": True,
                "test_passed": True,
                "reproducible": True,
            },
            "value": {
                "valuable": False,
                "value_sources": ["harness_atomic_feature"],
                "focus_match": True,
                "delivery_contract": True,
                "release_linked": False,
                "target_user": None,
                "job_to_be_done": None,
                "delivery_target": None,
                "internal_only": False,
            },
            "checks": {
                "entrypoint_exists": True,
                "entrypoint_path": str(run_dir / "evaluation_report.json"),
                "existing_evidence": goal["required_evidence"],
                "missing_evidence": [],
                "build_report_exists": True,
                "build_success": True,
                "qemu_report_exists": True,
                "qemu_all_passed": True,
            },
            "issues": [],
            "product": goal["product"],
            "source_run_id": goal["run_id"],
            "verification_mode": "independent_evaluator",
            "reality_status": "real",
            "evidence_files": [str(run_dir / rel) for rel in goal["required_evidence"]],
            "registered_at": utc_now(),
        }
        artifacts = [item for item in artifacts if item.get("artifact_id") != artifact_id]
        artifacts.append(entry)
        registry["artifacts"] = artifacts
        registry["artifact_count"] = len(artifacts)
        registry["real_artifact_count"] = sum(1 for item in artifacts if item.get("real"))
        registry["valuable_artifact_count"] = sum(1 for item in artifacts if ((item.get("value") or {}).get("valuable")))
        registry["prototype_artifact_count"] = sum(1 for item in artifacts if str(item.get("status") or "") == "prototype")
        registry["updated_at"] = utc_now()
        atomic_write_json(registry_path, registry)

    def run_once(self, goal: dict) -> dict:
        started_at = datetime.now(UTC)
        run_dir = self._make_run_dir(goal["run_id"])
        atomic_write_json(run_dir / "input_goal.json", goal)
        contract_path = self.planner.create_contract(goal=goal, run_dir=run_dir)
        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        contract = SprintContract.from_dict(contract_data)
        errors = contract.validate()
        if errors:
            result = {"status": "contract_invalid", "errors": errors, "run_id": goal["run_id"]}
            self._update_status(result)
            return result
        self.generator.run(contract_path=contract_path, run_dir=run_dir)
        evaluation_path = self.evaluator.evaluate(contract=contract_data, run_dir=run_dir)
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
        finished_at = datetime.now(UTC)
        result = {
            "task_type": "harness_atomic_feature",
            "status": evaluation["verdict"],
            "run_id": goal["run_id"],
            "goal_id": goal["goal_id"],
            "feature_name": goal["feature_name"],
            "evaluation_report": str(evaluation_path),
            "finished_at": finished_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }
        self._register_artifact(goal, run_dir, evaluation)
        self._update_metrics(goal, run_dir, evaluation, started_at, finished_at)
        self._update_status(result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one harness_atomic_feature contract")
    parser.add_argument("--goal-file", required=True)
    args = parser.parse_args()
    goal_path = Path(args.goal_file).resolve()
    goal = json.loads(goal_path.read_text(encoding="utf-8"))
    runner = HarnessRunner(ROOT)
    result = runner.run_once(goal)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
