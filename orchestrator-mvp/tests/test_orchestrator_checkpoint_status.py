from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import orchestrator as orchestrator_module
from app.models import TaskStatus


def test_checkpoint_terminal_status_filters_non_terminal_states() -> None:
    assert orchestrator_module._checkpoint_terminal_status({"task_status": "planning"}) is None
    assert orchestrator_module._checkpoint_terminal_status({"task_status": "running"}) is None
    assert orchestrator_module._checkpoint_terminal_status({"task_status": "verification_running"}) is None


def test_checkpoint_terminal_status_accepts_terminal_and_paused_states() -> None:
    assert orchestrator_module._checkpoint_terminal_status({"task_status": "completed"}) == TaskStatus.completed
    assert orchestrator_module._checkpoint_terminal_status({"task_status": "failed"}) == TaskStatus.failed
    assert (
        orchestrator_module._checkpoint_terminal_status({"task_status": "waiting_approval"})
        == TaskStatus.waiting_approval
    )
