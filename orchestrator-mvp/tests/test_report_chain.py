from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import report_chain


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_report_chain_writes_unified_snapshot(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()

    monkeypatch.setattr(report_chain, "DATA", data)
    monkeypatch.setattr(report_chain, "INTENT_PATH", data / "report_intent.json")
    monkeypatch.setattr(report_chain, "EXECUTION_PATH", data / "report_execution.json")
    monkeypatch.setattr(report_chain, "DECISIONS_PATH", data / "report_decisions.json")
    monkeypatch.setattr(report_chain, "EVIDENCE_PATH", data / "report_evidence.json")
    monkeypatch.setattr(report_chain, "CAPABILITY_PATH", data / "capability_status.json")
    monkeypatch.setattr(report_chain, "SYSTEM_REPORT_PATH", data / "system_report.json")
    monkeypatch.setattr(report_chain, "DECISION_LEDGER_PATH", data / "decision_ledger.jsonl")

    _write_json(
        data / "self_model_runtime.json",
        {
            "updated_at": "2026-03-29T00:00:00Z",
            "state": {
                "goal": "restore_toyos_delivery",
                "mode": "toyos_priority_mode",
                "tasks": {
                    "active": [
                        {
                            "id": "task-1",
                            "goal": "Restore ToyOS real artifact delivery",
                            "status": "planning",
                            "updated_at": "2026-03-29T00:01:00Z",
                        }
                    ]
                },
            },
        },
    )
    _write_json(
        data / "factory_daemon_state.json",
        {"running": True, "status": "running", "updated_at": "2026-03-29T00:01:10Z"},
    )
    _write_json(
        data / "control_layer_status.json",
        {
            "status": "stable",
            "updated_at": "2026-03-29T00:01:20Z",
            "enabled_components": ["orchestrator", "scheduler", "task_queue"],
            "control_policy": {"mode": "signal_only", "execution": "signal_only"},
        },
    )
    _write_json(
        data / "verification_status.json",
        {
            "updated_at": "2026-03-29T00:01:30Z",
            "status": "pass",
            "release_gate": {"status": "pass", "reason": "ok"},
            "delayed_verification": {"status": "pass", "reason": "ok"},
            "runtime_health": {"status": "pass"},
        },
    )
    _write_json(
        data / "reality_dashboard.json",
        {"updated_at": "2026-03-29T00:01:40Z", "status": "pass", "artifacts_produced_last_24h": 1, "products_real": 1, "top_issues": []},
    )
    _write_json(
        data / "artifact_registry.json",
        {
            "updated_at": "2026-03-29T00:01:50Z",
            "status": "pass",
            "artifacts": [
                {
                    "artifact_id": "toy-os-demo",
                    "status": "real",
                    "delivery_status": "technical_only",
                    "verified": {"buildable": True},
                    "value": {"valuable": True},
                    "checks": {"latest_evidence_at": "2026-03-29T00:01:45Z"},
                }
            ],
        },
    )
    _write_json(
        data / "decision_engine_status.json",
        {
            "updated_at": "2026-03-29T00:02:00Z",
            "decision_engine": {
                "decisions": [
                    {
                        "decision": "observe-ai-testing-signal",
                        "reason": "signal-only",
                        "applies_to": "ai-testing",
                    }
                ]
            },
        },
    )
    _write_json(
        data / "production_focus_status.json",
        {
            "enabled": True,
            "single_product_mode": True,
            "directive_reason": "priority-directive-toyos",
            "primary_artifact_id": "toy-os-demo",
            "primary_target": "Restore ToyOS real artifact delivery",
            "goal_template": {"target": "Restore ToyOS real artifact delivery"},
        },
    )
    _write_json(
        data / "assistant_capabilities.json",
        [
            {
                "summary": "Compile and build local projects in WSL. Run repeated QEMU smoke tests for OS kernels.",
            }
        ],
    )
    _write_json(
        data / "tasks.json",
        [
            {
                "id": "task-1",
                "goal": "Restore ToyOS real artifact delivery",
                "status": "planning",
                "updated_at": "2026-03-29T00:01:00Z",
            }
        ],
    )
    _write_json(
        data / "decision_log.json",
        [{"source": "project_memory", "project": "ToyOS Kernel", "decision": "Use QEMU for runtime verification"}],
    )

    payload = report_chain.build_report_chain(write_outputs=True)

    assert payload["system_report"]["primary_goal"] == "restore_toyos_delivery"
    assert payload["execution"]["execution_status"] == "active_planning"
    assert payload["capability"]["task_dispatch"]["status"] == "available"
    assert (data / "report_intent.json").exists()
    assert (data / "report_execution.json").exists()
    assert (data / "report_decisions.json").exists()
    assert (data / "report_evidence.json").exists()
    assert (data / "capability_status.json").exists()
    assert (data / "system_report.json").exists()
    ledger_lines = (data / "decision_ledger.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(ledger_lines) >= 2
