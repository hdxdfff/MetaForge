from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from tools.io_utils import atomic_write_json


class Planner:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def create_contract(self, goal: dict, run_dir: Path) -> Path:
        run_id = goal["run_id"]
        contract = {
            "contract_version": "1.0",
            "run_id": run_id,
            "goal_id": goal["goal_id"],
            "product": goal["product"],
            "feature_name": goal["feature_name"],
            "feature_type": goal.get("feature_type", "kernel_feature"),
            "source_goal": goal["source_goal"],
            "scope": {
                "allowed_paths": goal["allowed_paths"],
                "forbidden_paths": goal["forbidden_paths"],
                "max_files_to_change": goal.get("max_files_to_change", 12),
            },
            "deliverables": goal["deliverables"],
            "definition_of_done": goal["definition_of_done"],
            "acceptance_checks": goal["acceptance_checks"],
            "required_evidence": goal["required_evidence"],
            "retry_policy": goal.get(
                "retry_policy",
                {"max_attempts": 2, "on_fail": "create_fix_task"},
            ),
            "budget": goal.get(
                "budget",
                {"max_runtime_minutes": 45, "max_model_calls": 12},
            ),
            "status": "approved_for_execution",
            "created_at": datetime.now(UTC).isoformat(),
        }
        contract_path = run_dir / "sprint_contract.json"
        atomic_write_json(contract_path, contract)
        planner_output = {
            "run_id": run_id,
            "planner_status": "success",
            "selected_feature": goal["feature_name"],
            "why_this_feature": goal.get(
                "why_this_feature",
                "Atomic, testable, and low blast radius.",
            ),
            "deferred_items": goal.get("deferred_items", []),
            "risk_notes": goal.get("risk_notes", []),
        }
        atomic_write_json(run_dir / "planner_output.json", planner_output)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs" / "planner.log").write_text(
            json.dumps(planner_output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return contract_path

