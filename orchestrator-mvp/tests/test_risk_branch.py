from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.provider_gateway as provider_gateway_module
import tools.factory_daemon as factory_daemon_module
import app.risk_engine as risk_engine_module
import app.incident_state_machine as incident_state_machine_module
import app.safe_repair_executor as safe_repair_executor_module
from app.risk_policy import RiskPolicy
from tools import risk_scan


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _patch_data_roots(monkeypatch, data: Path) -> None:
    monkeypatch.setattr(risk_engine_module, "DATA", data)
    monkeypatch.setattr(risk_engine_module, "TASKS_PATH", data / "tasks.json")
    monkeypatch.setattr(risk_engine_module, "DAEMON_STATE_PATH", data / "factory_daemon_state.json")
    monkeypatch.setattr(risk_engine_module, "FACTORY_STATE_PATH", data / "factory_state.json")
    monkeypatch.setattr(risk_engine_module, "CONTROL_LAYER_PATH", data / "control_layer_status.json")
    monkeypatch.setattr(risk_engine_module, "VERIFICATION_STATUS_PATH", data / "verification_status.json")
    monkeypatch.setattr(risk_engine_module, "ARTIFACT_REGISTRY_PATH", data / "artifact_registry.json")
    monkeypatch.setattr(risk_engine_module, "GOAL_BACKLOG_PATH", data / "goal_backlog_status.json")
    monkeypatch.setattr(risk_engine_module, "QUALITY_STATUS_PATH", data / "quality_status.json")
    monkeypatch.setattr(risk_engine_module, "RELEASE_OPERATIONS_PATH", data / "release_operations_status.json")
    monkeypatch.setattr(risk_engine_module, "REPAIR_HISTORY_PATH", data / "repair_history.json")
    monkeypatch.setattr(risk_engine_module, "SEMANTIC_HEALTH_PATH", data / "semantic_health.json")
    monkeypatch.setattr(risk_engine_module, "RISK_STATUS_PATH", data / "risk_status.json")
    monkeypatch.setattr(risk_engine_module, "INCIDENT_LEDGER_PATH", data / "incident_ledger.json")
    monkeypatch.setattr(risk_engine_module, "RISK_CATALOG_PATH", data / "risk_catalog.json")
    monkeypatch.setattr(provider_gateway_module, "STATE_PATH", data / "provider_gateway_state.json")
    monkeypatch.setattr(incident_state_machine_module, "INCIDENT_LEDGER_PATH", data / "incident_ledger.json")
    monkeypatch.setattr(incident_state_machine_module, "REPAIR_HISTORY_PATH", data / "repair_history.json")
    monkeypatch.setattr(incident_state_machine_module, "RISK_STATUS_PATH", data / "risk_status.json")
    monkeypatch.setattr(incident_state_machine_module, "SEMANTIC_HEALTH_PATH", data / "semantic_health.json")
    monkeypatch.setattr(safe_repair_executor_module, "DATA", data)
    monkeypatch.setattr(safe_repair_executor_module, "RELEASE_OPERATIONS_PATH", data / "release_operations_status.json")
    monkeypatch.setattr(safe_repair_executor_module, "DAEMON_STATE_PATH", data / "factory_daemon_state.json")
    monkeypatch.setattr(safe_repair_executor_module, "PROVIDER_STATE_PATH", data / "provider_gateway_state.json")


def test_risk_branch_detects_queue_starvation_and_writes_ledger(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _patch_data_roots(monkeypatch, data)

    _write_json(data / "tasks.json", [])
    _write_json(
        data / "factory_daemon_state.json",
        {
            "running": True,
            "status": "running",
            "heartbeat_at": "2026-03-29T12:00:00Z",
            "last_tick_at": "2026-03-29T12:00:00Z",
            "last_self_model_goal": "restore_toyos_delivery",
        },
    )
    _write_json(data / "factory_state.json", {"consistency": {"runtime_continuity": "preserved", "findings": []}})
    _write_json(data / "verification_status.json", {"status": "pass", "delayed_verification": {"pending_count": 0, "pending_checks": []}})
    _write_json(data / "artifact_registry.json", {"artifact_count": 0, "real_artifact_count": 0, "valuable_artifact_count": 0, "artifacts": []})
    _write_json(data / "goal_backlog_status.json", {"last_replenished_at": None})
    _write_json(data / "quality_status.json", {"status": "attention"})
    _write_json(data / "release_operations_status.json", {"release_train": {"status": "ready"}})
    _write_json(data / "provider_gateway_state.json", {"updated_at": None, "providers": {}})
    _write_json(data / "risk_catalog.json", risk_engine_module._catalog())

    payload = risk_scan.run_risk_branch(source="test", apply_repairs=False)

    assert payload["status"]["scan_status"] == "attention"
    assert payload["status"]["risk_count"] >= 1
    ledger = json.loads((data / "incident_ledger.json").read_text(encoding="utf-8"))
    assert any(item["risk_id"] == "runtime.queue_starvation" for item in ledger)


def test_safe_executor_can_freeze_release_train(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _patch_data_roots(monkeypatch, data)

    _write_json(data / "factory_daemon_state.json", {"running": True, "status": "running", "restart_requested": False})
    _write_json(data / "provider_gateway_state.json", {"updated_at": None, "providers": {}})
    _write_json(data / "release_operations_status.json", {"status": "pass", "release_train": {"status": "ready"}})
    _write_json(data / "verification_status.json", {"status": "pass", "delayed_verification": {"pending_count": 0, "pending_checks": []}})
    _write_json(data / "artifact_registry.json", {"artifact_count": 0, "real_artifact_count": 0, "valuable_artifact_count": 0, "artifacts": []})

    executor = safe_repair_executor_module.SafeRepairExecutor()
    risk = {
        "risk_id": "release.promotion_mismatch",
        "severity": "critical",
        "blast_radius": "system",
        "rollback_plan": "revoke_release_promotion",
        "allowed_actions": ["freeze_release_train"],
        "forbidden_actions": [],
        "confidence": 0.99,
        "signals": {},
    }
    snapshot = risk_engine_module.build_runtime_snapshot()
    actions = executor.execute(risk, snapshot=snapshot, dry_run=False)

    assert actions[0]["name"] == "freeze_release_train"
    release_ops = json.loads((data / "release_operations_status.json").read_text(encoding="utf-8"))
    assert release_ops["release_train"]["status"] == "blocked"


def test_policy_blocks_critical_without_rollout_plan() -> None:
    policy = RiskPolicy()
    decision = policy.decide(
        {
            "risk_id": "verification.misalignment",
            "severity": "critical",
            "blast_radius": "system",
            "confidence": 0.95,
            "allowed_actions": ["re_run_verification"],
            "forbidden_actions": [],
            "rollback_plan": "",
        }
    )
    assert decision["allowed"] is False
    assert decision["requires_human_review"] is True


def test_daemon_risk_scan_is_due_on_verification_or_cadence() -> None:
    assert factory_daemon_module._risk_scan_due(7, 5, True) is True
    assert factory_daemon_module._risk_scan_due(10, 5, False) is True
    assert factory_daemon_module._risk_scan_due(3, 5, False) is False
