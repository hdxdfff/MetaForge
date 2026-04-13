from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.ai_guard as ai_guard
import tools.queue_pressure_analyzer as queue_pressure_analyzer


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_ai_guard_prefers_managed_queue_over_raw_task_rows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ai_guard, "DATA", tmp_path)
    monkeypatch.setattr(ai_guard, "TASKS", tmp_path / "tasks.json")
    monkeypatch.setattr(ai_guard, "GOAL_STORAGE_AUDIT", tmp_path / "goal_storage_audit.json")
    monkeypatch.setattr(ai_guard, "CORE_MESSAGES", tmp_path / "core_messages.json")
    monkeypatch.setattr(ai_guard, "PLATFORMS", tmp_path / "platform_registry.json")
    monkeypatch.setattr(ai_guard, "USAGE", tmp_path / "usage_tracker.json")
    monkeypatch.setattr(ai_guard, "HEALTH", tmp_path / "health_status.json")
    monkeypatch.setattr(ai_guard, "STATE", tmp_path / "guard_state.json")

    tasks = [
        {
            "id": f"task-{index}",
            "status": "running" if index < 8 else "queued",
            "created_at": "2026-04-11T00:00:00Z",
            "updated_at": "2026-04-11T00:00:00Z",
        }
        for index in range(14)
    ]
    _write_json(tmp_path / "tasks.json", tasks)
    _write_json(
        tmp_path / "goal_storage_audit.json",
        {
            "status": "healthy",
            "task_queue_confirmed": True,
            "task_queue": {
                "active_task_count": 14,
                "managed_active_task_count": 0,
                "managed_active_tasks_with_goal_link": 0,
                "managed_active_tasks_linked_to_existing_goal": 0,
                "managed_active_tasks_broken_goal_link": [],
                "managed_active_tasks_without_goal_link": [],
                "managed_active_tasks_without_node_link": [],
            },
        },
    )
    _write_json(tmp_path / "core_messages.json", [])
    _write_json(tmp_path / "platform_registry.json", {"platforms": []})
    _write_json(tmp_path / "usage_tracker.json", {"reasoning_allowed": True, "strong_allowed": True})

    snapshot = ai_guard.guard_snapshot()

    assert snapshot["status"] == "healthy"
    assert snapshot["allow_brain_loop"] is True
    assert snapshot["reasons"] == []
    assert snapshot["task_pressure"]["raw_active_tasks"] == 14
    assert snapshot["task_pressure"]["managed_active_tasks"] == 0
    assert snapshot["task_pressure"]["effective_active_tasks"] == 0
    assert snapshot["goal_storage_task_queue"]["task_queue_confirmed"] is True


def test_queue_pressure_analyzer_uses_managed_queue_truth(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(queue_pressure_analyzer, "DATA", tmp_path)
    monkeypatch.setattr(queue_pressure_analyzer, "OUTPUT", tmp_path / "queue_pressure_analysis.json")
    monkeypatch.setattr(
        queue_pressure_analyzer,
        "HISTORICAL_DEBT_ARCHIVE_PATH",
        tmp_path / "historical_failure_debt_archive.json",
    )
    monkeypatch.setattr(
        queue_pressure_analyzer,
        "GOAL_STORAGE_AUDIT_PATH",
        tmp_path / "goal_storage_audit.json",
    )

    _write_json(
        tmp_path / "tasks.json",
        [
            {"id": f"task-{index}", "status": "running" if index < 6 else "queued"}
            for index in range(14)
        ],
    )
    _write_json(
        tmp_path / "goal_backlog_status.json",
        {
            "active_goal_count": 0,
            "starvation_seconds": 0,
        },
    )
    _write_json(tmp_path / "task_history.json", [])
    _write_json(tmp_path / "historical_failure_debt_archive.json", {"status": "archived", "failed_task_count": 55})
    _write_json(
        tmp_path / "goal_storage_audit.json",
        {
            "status": "healthy",
            "task_queue_confirmed": True,
            "task_queue": {
                "active_task_count": 14,
                "managed_active_task_count": 0,
                "managed_active_tasks_with_goal_link": 0,
            },
        },
    )

    snapshot = queue_pressure_analyzer.run_queue_pressure_analyzer()

    assert snapshot["pressure"] == "low"
    assert snapshot["active_pressure_score"] == 0
    assert snapshot["goal_storage_task_queue"]["managed_active_task_count"] == 0
    assert snapshot["goal_storage_task_queue"]["task_queue_confirmed"] is True
