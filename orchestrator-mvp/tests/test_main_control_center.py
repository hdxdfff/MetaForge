from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import app.main as main_app
import tools.goal_storage_audit as goal_storage_audit


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class _FakePayload:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def model_dump(self, mode: str = "json") -> dict:
        return dict(self._payload)


class _FakePolicy:
    version = "test-policy"


class _FakeOrchestrator:
    async def stats(self) -> _FakePayload:
        return _FakePayload(
            {
                "completed_tasks": 2,
                "delivery_ready_tasks": 1,
                "released_tasks": 1,
                "verification_failed_tasks": 0,
            }
        )

    async def list_core_messages(self) -> list[str]:
        return ["msg-1", "msg-2"]

    async def get_policy(self) -> _FakePolicy:
        return _FakePolicy()

    async def list_projects(self) -> list[dict]:
        return []

    async def list_capabilities(self) -> list[dict]:
        return []

    async def list_resources(self) -> list[dict]:
        return []

    async def list_repos(self) -> list[dict]:
        return []

    async def get_task_detail(self, task_id: str) -> dict:
        return {
            "id": task_id,
            "status": "running",
            "prompt": "Inspect decomposition state",
            "goal_admission": {"kind": "goal", "goal": "Inspect decomposition state", "strategy": "explore-design-build-verify"},
            "admission_lane": "exploration",
            "admission_reason": "artifact_spec_missing",
            "dependency_task_ids": ["task-0"],
            "verification_signals": [{"kind": "step_started", "success": True, "task_id": task_id}],
            "decomposition_tree": {
                "task_id": task_id,
                "title": "Root task",
                "status": "running",
                "decomposition_depth": 0,
                "max_decomposition_depth": 2,
                "admission_lane": "exploration",
                "admission_reason": "artifact_spec_missing",
                "dependency_task_ids": ["task-0"],
                "child_task_ids": ["task-child"],
                "children": [
                    {
                        "task_id": "task-child",
                        "title": "Child task",
                        "status": "queued",
                        "decomposition_depth": 1,
                        "max_decomposition_depth": 2,
                        "dependency_task_ids": ["task-0"],
                        "child_task_ids": [],
                        "children": [],
                    }
                ],
                "dag": {
                    "shared_nodes": ["Shared scope"],
                    "branch_nodes": ["Branch scope"],
                    "repair_nodes": ["Repair scope"],
                    "edges": [{"from": "Shared scope", "to": "Branch scope", "kind": "dependency"}],
                },
            },
        }

    async def admit_goal(self, payload) -> dict:
        return await self.get_task_detail("goal-task")

    async def subscribe_verification_signals(self, task_id: str):
        import asyncio

        return asyncio.Queue()

    async def list_verification_signals(self, task_id: str) -> list[dict]:
        return [
            {"kind": "step_started", "success": True, "task_id": task_id, "timestamp": "2026-03-29T00:00:00Z"},
            {"kind": "signal_replayed", "success": True, "task_id": task_id, "timestamp": "2026-03-29T00:00:01Z"},
        ]

    async def unsubscribe_verification_signals(self, task_id: str, queue) -> None:
        return None


def test_control_center_status_includes_integrations(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    control_center_state = data / "control_center_state.json"
    _write_json(
        control_center_state,
        {"paused": False, "status": "active", "updated_at": "2026-03-29T00:00:00Z", "reason": "", "resident": True},
    )

    monkeypatch.setattr(main_app, "CONTROL_CENTER_STATE_PATH", control_center_state)
    monkeypatch.setattr(main_app, "GOAL_BACKLOG_STATUS_PATH", data / "goal_backlog_status.json")
    monkeypatch.setattr(main_app, "orchestrator", _FakeOrchestrator())
    monkeypatch.setattr(main_app, "_integration_status_bundle", lambda: {"configured": True, "complete": False, "summary": {"total": 4, "healthy": 3}, "updated_at": "2026-03-29T00:00:00Z", "bindings": []})
    monkeypatch.setattr(main_app, "read_risk_status", lambda: {"scan_status": "pass", "risk_count": 0, "open_incident_count": 0, "closed_incident_count": 0, "updated_at": "2026-03-29T00:00:00Z"})
    monkeypatch.setattr(goal_storage_audit, "run_goal_storage_audit", lambda: {"status": "pass"})

    client = TestClient(main_app.app)

    status_response = client.get("/api/control-center/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["integrations"]["configured"] is True
    assert status_payload["integrations"]["complete"] is False
    assert status_payload["integrations"]["summary"]["total"] == 4

    health_response = client.get("/api/health")
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["integrations"]["configured"] is True
    assert health_payload["integrations"]["complete"] is False

    task_response = client.get("/api/tasks/task-1")
    assert task_response.status_code == 200
    task_payload = task_response.json()
    assert task_payload["admission_lane"] == "exploration"
    assert task_payload["verification_signals"][0]["kind"] == "step_started"
    assert task_payload["decomposition_tree"]["dag"]["edges"][0]["from"] == "Shared scope"
    assert task_payload["goal_admission"]["kind"] == "goal"
    assert task_payload["goal_admission"]["pipeline"][0]["stage"] == "explore"

    tree_response = client.get("/api/tasks/task-1/tree")
    assert tree_response.status_code == 200
    tree_payload = tree_response.json()
    assert tree_payload["decomposition_tree"]["children"][0]["task_id"] == "task-child"

    graph_response = client.get("/api/tasks/task-1/graph")
    assert graph_response.status_code == 200
    graph_payload = graph_response.json()
    assert graph_payload["dag"]["edges"][0]["to"] == "Branch scope"

    signals_response = client.get("/api/tasks/task-1/verification-signals")
    assert signals_response.status_code == 200
    signals_payload = signals_response.json()
    assert signals_payload["signal_count"] == 2
    assert signals_payload["signals"][1]["kind"] == "signal_replayed"

    admit_response = client.post("/api/goals/admit", json={"goal": "Improve task autonomy for design and verification", "prompt": "Build a stronger admission path"})
    assert admit_response.status_code == 200

    import asyncio

    stream_response = asyncio.run(main_app.stream_task_verification_signals("task-1"))
    assert stream_response.media_type == "text/event-stream"
    first_chunk = asyncio.run(stream_response.body_iterator.__anext__())
    assert "event: snapshot" in first_chunk or "data:" in first_chunk
    assert "signal_replayed" in first_chunk
