from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_operations import _delivery_ready_state_machine


def test_delivery_ready_state_machine_ignores_historical_completed_tasks() -> None:
    payload = _delivery_ready_state_machine(
        tasks=[
            {
                "id": "legacy-windows-task",
                "title": "Legacy Windows task",
                "status": "completed",
                "execution_mode": "production",
                "repo_path": r"D:\\codex\\orchestrator-mvp",
                "result": {
                    "summary": "Superseded by newer runtime task.",
                },
            },
            {
                "id": "vm-production-task",
                "title": "VM production task",
                "status": "completed",
                "execution_mode": "production",
                "repo_path": "/srv/orchestrator-mvp",
                "result": {
                    "production_evidence": {
                        "status": "verified",
                    }
                },
            },
        ],
        runtime_ok=True,
        control_ok=True,
        artifact_release_ok=True,
        governance_ok=True,
        release_gate={"blocking_reasons": []},
        blocked_patches=[],
    )

    assert payload["status"] == "ready"
    assert payload["counts"]["completed"] == 2
    assert payload["counts"]["historical_completed_ignored"] == 1
    assert payload["counts"]["evidence_ready_completed"] == 1
    assert payload["counts"]["evidence_missing_completed"] == 0
    assert payload["counts"]["promotable_completed"] == 1
    assert payload["promotable_tasks"][0]["task_id"] == "vm-production-task"
    assert payload["evidence_missing_tasks"] == []
    assert payload["historical_completed_tasks"][0]["task_id"] == "legacy-windows-task"
