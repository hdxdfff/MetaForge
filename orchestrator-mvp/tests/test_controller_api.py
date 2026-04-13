from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

import app.controller_api as controller_api
import app.external_integrations as external_integrations


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _patch_paths(monkeypatch, data: Path) -> None:
    monkeypatch.setattr(controller_api, "DATA", data)
    monkeypatch.setattr(controller_api, "CONTROL_CENTER_STATE_PATH", data / "control_center_state.json")
    monkeypatch.setattr(controller_api, "CONTROLLER_STATE_PATH", data / "controller_state.json")
    monkeypatch.setattr(controller_api, "CONTROLLER_JOURNAL_PATH", data / "controller_journal.jsonl")
    monkeypatch.setattr(controller_api, "TASKS_PATH", data / "tasks.json")
    monkeypatch.setattr(controller_api, "VERIFICATION_STATUS_PATH", data / "verification_status.json")
    monkeypatch.setattr(controller_api, "ARTIFACT_REGISTRY_PATH", data / "artifact_registry.json")
    monkeypatch.setattr(controller_api, "RUNTIME_EPOCH_PATH", data / "runtime_epoch.json")
    monkeypatch.setattr(controller_api, "REPAIR_QUEUE_PATH", data / "controller_repair_queue.json")
    monkeypatch.setattr(controller_api, "RELEASE_QUEUE_PATH", data / "controller_release_queue.json")


def test_controller_api_summaries_and_actions(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _patch_paths(monkeypatch, data)

    _write_json(
        data / "control_center_state.json",
        {"paused": False, "status": "active", "updated_at": "2026-03-29T00:00:00Z", "reason": "", "resident": True},
    )
    _write_json(
        data / "verification_status.json",
        {"updated_at": "2026-03-29T00:00:00Z", "status": "pass", "release_gate": {"status": "pass"}},
    )
    _write_json(
        data / "artifact_registry.json",
        {
            "updated_at": "2026-03-29T00:00:00Z",
            "status": "pass",
            "artifact_count": 1,
            "real_artifact_count": 1,
            "valuable_artifact_count": 1,
            "artifacts": [
                {
                    "artifact_id": "toy-os-demo",
                    "updated_at": "2026-03-29T00:00:00Z",
                    "checks": {"latest_evidence_at": "2026-03-29T00:00:00Z"},
                }
            ],
        },
    )
    _write_json(
        data / "runtime_epoch.json",
        {"state_version": 7, "epoch_id": "epoch-1"},
    )
    _write_json(
        data / "tasks.json",
        [
            {"id": "task-1", "status": "waiting_approval", "result": {}},
            {"id": "task-2", "status": "running", "result": {}},
        ],
    )

    client = TestClient(controller_api.app)

    monkeypatch.setenv("ORCH_OPENWEBUI_BASE_URL", "http://openwebui.local")
    monkeypatch.setenv("ORCH_APPSMITH_BASE_URL", "http://appsmith.local")
    monkeypatch.setenv("ORCH_N8N_BASE_URL", "http://n8n.local")
    monkeypatch.setenv("ORCH_DIFY_BASE_URL", "http://dify.local")
    monkeypatch.setenv("ORCH_OPENHANDS_EXECUTOR_ID", "openhands_executor")
    monkeypatch.setenv("ORCH_INTEGRATION_PROBE_TIMEOUT_SECONDS", "1")

    health = client.get("/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["tasks"]["waiting_approval"] == 1
    assert payload["verification"]["status"] == "pass"

    topology = client.get("/topology")
    assert topology.status_code == 200
    topology_payload = topology.json()
    assert topology_payload["ssot"]["name"] == "Core Controller"
    assert "Appsmith" in topology_payload["role_map"]
    assert "n8n" in topology_payload["layers"][2]["surfaces"]
    assert "/queue/pause" in topology_payload["interfaces"]["controlled_write"]
    assert len(topology_payload["integrations"]["bindings"]) == 5

    monkeypatch.setattr(
        external_integrations,
        "_probe_http",
        lambda url, timeout_seconds: {
            "status": "healthy" if "appsmith" in url else "reachable",
            "reachable": True,
            "healthy": "appsmith" in url,
            "response_code": 200 if "appsmith" in url else 302,
            "detail": "stubbed",
        },
    )

    integrations = client.get("/integrations/status")
    assert integrations.status_code == 200
    integrations_payload = integrations.json()
    assert integrations_payload["summary"]["total"] == 5
    assert any(item["name"] == "OpenHands" and item["health"]["healthy"] for item in integrations_payload["services"])

    pause = client.post("/queue/pause", json={"actor": "tester", "source": "unit-test", "reason": "hold"})
    assert pause.status_code == 200
    control_state = json.loads((data / "control_center_state.json").read_text(encoding="utf-8"))
    assert control_state["paused"] is True
    assert control_state["reason"] == "hold"

    activate = client.post(
        "/goal/activate",
        json={"goal_id": "goal-1", "goal": "Restore ToyOS delivery", "actor": "tester", "source": "unit-test"},
    )
    assert activate.status_code == 200
    controller_state = json.loads((data / "controller_state.json").read_text(encoding="utf-8"))
    assert controller_state["active_goal"]["goal_id"] == "goal-1"

    approve = client.post(
        "/task/approve",
        json={"task_id": "task-1", "actor": "tester", "source": "unit-test", "reason": "approved"},
    )
    assert approve.status_code == 200
    tasks = json.loads((data / "tasks.json").read_text(encoding="utf-8"))
    assert next(task for task in tasks if task["id"] == "task-1")["status"] == "queued"

    repair = client.post(
        "/repair/schedule",
        json={
            "repair_type": "build_fix",
            "title": "Repair build toolchain",
            "actor": "tester",
            "source": "unit-test",
        },
    )
    assert repair.status_code == 200
    repairs = json.loads((data / "controller_repair_queue.json").read_text(encoding="utf-8"))
    assert repairs[0]["repair_type"] == "build_fix"

    resume = client.post("/queue/resume", json={"actor": "tester", "source": "unit-test"})
    assert resume.status_code == 200
    control_state = json.loads((data / "control_center_state.json").read_text(encoding="utf-8"))
    assert control_state["paused"] is False
