from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from tools.io_utils import atomic_write_json


class CodeAgent(Protocol):
    def execute(self, contract_path: Path, run_dir: Path) -> dict:
        ...


class BaselineToyOSCodeAgent:
    """Low-intrusion baseline agent for an already-present ToyOS atomic feature."""

    def execute(self, contract_path: Path, run_dir: Path) -> dict:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        target_root = Path(r"D:\codex\generated\toy-os-demo")
        changed_files: list[str] = []
        note_path = target_root / "docs" / "harness" / f"{contract['feature_name']}_baseline_note.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_text = (
            f"# Harness Baseline: {contract['feature_name']}\n\n"
            f"- run_id: {contract['run_id']}\n"
            f"- goal_id: {contract['goal_id']}\n"
            f"- source_goal: {contract['source_goal']}\n"
            f"- created_at: {datetime.now(UTC).isoformat()}\n"
            "- note: baseline candidate prepared for independent evaluation.\n"
        )
        note_path.write_text(note_text, encoding="utf-8")
        changed_files.append(str(note_path))
        return {
            "run_id": contract["run_id"],
            "changed_files": changed_files,
            "commands_executed": [],
            "build_result": "not_run_by_generator",
            "self_claim": "candidate_ready_for_evaluation",
            "known_risks": [
                "Generator is baseline-only; runtime truth must come from evaluator rerun.",
            ],
        }


class Generator:
    def __init__(self, agent: CodeAgent) -> None:
        self.agent = agent

    def run(self, contract_path: Path, run_dir: Path) -> Path:
        result = self.agent.execute(contract_path=contract_path, run_dir=run_dir)
        report = {
            "generator_status": "completed_with_candidate",
            **result,
        }
        report_path = run_dir / "generator_report.json"
        atomic_write_json(report_path, report)
        (run_dir / "logs" / "generator.log").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report_path

