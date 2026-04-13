from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import orchestrator as orchestrator_module
from app.models import AgentRole, StepSpec, TaskRecord, TaskStatus, WorkerType


def test_decomposition_spawns_child_tasks_and_tracks_lineage(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_update_checkpoint", lambda *args, **kwargs: None)

    orch = orchestrator_module.Orchestrator()
    orch._tasks = {}

    parent = TaskRecord(
        id="parent-task",
        prompt="Build a nested decomposition flow that splits analysis, implementation, and validation into separate child tasks.",
        title="Parent task",
        status=TaskStatus.planning,
        result={
            "decomposition": {
                "summary": "Split into analysis, implementation, and validation branches.",
                "strategy": "fan out the work into bounded child tasks",
                "subtasks": [
                    {
                        "title": "Analyze current state",
                        "prompt": "Inspect the current workspace and identify the smallest implementation slice.",
                        "goal": "Find the smallest slice",
                        "task_type": "report_refresh",
                        "queue_name": "fastlane",
                        "verification_level": "L1",
                        "preferred_worker": "reviewer",
                        "execution_mode": "governance",
                        "execution_lane": "host-control",
                        "decompose_children": True,
                        "inputs": [],
                        "outputs": ["analysis note"],
                        "dependencies": [],
                        "acceptance_criteria": ["A bounded analysis note exists."],
                        "scheduler_hint": {"branch": "analysis"},
                        "executor_hint": {"surface": "Continue"},
                    },
                    {
                        "title": "Implement bounded change",
                        "prompt": "Apply the smallest safe implementation slice.",
                        "goal": "Implement the slice",
                        "task_type": "build_fix",
                        "queue_name": "build_test",
                        "verification_level": "L2",
                        "preferred_worker": "coder",
                        "execution_mode": "production",
                        "execution_lane": "vm-first",
                        "decompose_children": False,
                        "inputs": ["analysis note"],
                        "outputs": ["bounded patch"],
                        "dependencies": ["Analyze current state"],
                        "acceptance_criteria": ["A bounded patch exists."],
                        "scheduler_hint": {"branch": "implementation"},
                        "executor_hint": {"surface": "OpenHands"},
                    },
                ],
            }
        },
        child_task_ids=[],
    )

    created_payloads: list[object] = []

    async def fake_create_task(payload):
        created_payloads.append(payload)
        task = SimpleNamespace(
            id=f"child-{len(created_payloads)}",
            title=payload.title,
            task_type=payload.task_type,
            execution_mode=payload.execution_mode,
            decomposition_depth=payload.decomposition_depth,
            result={},
            status=TaskStatus.queued,
        )
        orch._tasks[task.id] = task
        return task

    monkeypatch.setattr(orch, "create_task", fake_create_task)

    assert orch._should_decompose_task(parent) is True

    steps = orch._task_decomposition_internal_steps(parent, orch._build_task_decomposition(parent))
    assert [step.command for step in steps] == [
        "internal://decomposition/spawn-subtasks",
        "internal://decomposition/wait-subtasks",
        "internal://decomposition/aggregate-results",
    ]

    step = StepSpec(
        title="Spawn decomposition subtasks",
        worker=WorkerType.planner,
        instructions="Spawn the child tasks.",
        phase="decompose",
        command="internal://decomposition/spawn-subtasks",
        workdir="D:\\codex",
        assigned_role=AgentRole.supervisor,
    )

    result = asyncio.run(orch._internal_decomposition_spawn_subtasks(parent, step, orch._recovery_route()))

    assert result.metadata["child_task_count"] == 2
    assert parent.child_task_ids == ["child-1", "child-2"]
    assert created_payloads[0].parent_task_id == "parent-task"
    assert created_payloads[0].root_task_id == "parent-task"
    assert created_payloads[0].decomposition_depth == 1
    assert created_payloads[0].scheduler_hint["decomposition_allow_children"] is True
    assert created_payloads[1].scheduler_hint["decomposition_allow_children"] is False
    assert orch._tasks["child-1"].decomposition_depth == 1
    assert orch._tasks["child-2"].task_type == "build_fix"


def test_get_task_detail_includes_decomposition_tree(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_refresh_read_state", lambda self: None)
    orch = orchestrator_module.Orchestrator()
    orch._tasks = {}
    parent = TaskRecord(
        id="root-task",
        prompt="Decompose a broad task into child work items.",
        title="Root task",
        status=TaskStatus.running,
        root_task_id="root-task",
        decomposition_depth=0,
        max_decomposition_depth=2,
        result={
            "decomposition": {
                "summary": "Split into analysis and implementation.",
                "strategy": "fan out",
                "child_task_ids": ["child-task"],
            }
        },
        child_task_ids=["child-task"],
    )
    child = TaskRecord(
        id="child-task",
        prompt="Implement the bounded child work.",
        title="Child task",
        status=TaskStatus.queued,
        parent_task_id="root-task",
        root_task_id="root-task",
        decomposition_depth=1,
        max_decomposition_depth=2,
    )
    orch._tasks[parent.id] = parent
    orch._tasks[child.id] = child

    detail = asyncio.run(orch.get_task_detail("root-task"))

    assert detail is not None
    assert detail["decomposition_tree"]["task_id"] == "root-task"
    assert detail["decomposition_tree"]["children"][0]["task_id"] == "child-task"
    assert detail["decomposition_tree"]["children"][0]["parent_task_id"] == "root-task"


def test_should_decompose_complex_production_task(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    orch = orchestrator_module.Orchestrator()
    task = TaskRecord(
        id="complex-task",
        prompt="Build a multi-layer orchestration change that touches routing, planner state, validation, and execution reporting across the controller stack.",
        title="Complex production task",
        goal="Split the work into bounded child tasks and verify the results across the system.",
        status=TaskStatus.planning,
        task_type="analysis",
        execution_mode="production",
        repo_path="D:\\codex\\orchestrator-mvp",
        max_decomposition_depth=2,
    )

    assert orch._should_decompose_task(task) is True


def test_goal_pipeline_compiles_branching_dag(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    orch = orchestrator_module.Orchestrator()
    pipeline = orch._goal_pipeline(
        "Build an integration workflow with a fallback compare path and dependency tracking.",
        strategy="repair-if-needed",
    )

    stages = [item["stage"] for item in pipeline]
    path_kinds = [item["path_kind"] for item in pipeline]
    assert stages[:4] == ["explore", "design", "implement", "verify"]
    assert "optional" in stages
    assert "speculative" in stages
    assert "blocked" in stages
    assert "repair" in stages
    assert "optional" in path_kinds
    assert "speculative" in path_kinds
    assert "blocked" in path_kinds
    assert "repair" in path_kinds


def test_verification_signal_broadcasts_task_updates(monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    orch = orchestrator_module.Orchestrator()
    task = TaskRecord(
        id="signal-task",
        prompt="Track verification signals in real time.",
        title="Signal task",
        status=TaskStatus.running,
    )

    broadcasts: list[str] = []

    async def fake_broadcast(item):
        broadcasts.append(item.id)

    monkeypatch.setattr(orch, "_broadcast", fake_broadcast)

    signal = asyncio.run(
        orch._append_verification_signal(
            task,
            kind="step_started",
            success=True,
            details={"step_id": "step-1"},
        )
    )

    assert signal["kind"] == "step_started"
    assert task.verification_signals[0]["step_id"] == "step-1"
    assert broadcasts == ["signal-task"]


def test_verification_signal_persists_append_only_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_load_state", lambda self: None)
    monkeypatch.setattr(orchestrator_module.Orchestrator, "_persist", lambda self: None)
    orch = orchestrator_module.Orchestrator()
    orch._verification_signal_log = tmp_path / "verification_signal_events.jsonl"

    task = TaskRecord(
        id="signal-task",
        prompt="Persist verification signals to disk.",
        title="Signal task",
        status=TaskStatus.running,
    )

    async def _no_op(*args, **kwargs):
        return None

    monkeypatch.setattr(orch, "_broadcast", _no_op)
    monkeypatch.setattr(orch, "_broadcast_verification_signal", _no_op)

    signal = asyncio.run(
        orch._append_verification_signal(
            task,
            kind="step_completed",
            success=True,
            details={"step_id": "step-1"},
        )
    )

    assert signal["kind"] == "step_completed"
    assert orch._verification_signal_log.exists()

    log_lines = orch._verification_signal_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["task_id"] == "signal-task"

    merged = asyncio.run(orch.list_verification_signals("signal-task"))
    assert len(merged) == 1
    assert merged[0]["step_id"] == "step-1"
