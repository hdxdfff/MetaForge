from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.fact_gate_convergence as convergence


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(convergence, "DATA", tmp_path)
    monkeypatch.setattr(convergence, "VERIFICATION_STATUS", tmp_path / "verification_status.json")
    monkeypatch.setattr(convergence, "RELEASE_OPERATIONS_STATUS", tmp_path / "release_operations_status.json")
    monkeypatch.setattr(convergence, "CONTROL_LAYER_STATUS", tmp_path / "control_layer_status.json")
    monkeypatch.setattr(convergence, "STATUS_PATH", tmp_path / "fact_gate_convergence_status.json")
    monkeypatch.setattr(convergence, "HISTORY_PATH", tmp_path / "fact_gate_convergence_history.json")


def _write_passing_inputs(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "verification_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "fact_consistency": {"passed": True, "contradictions": []},
            "release_gate": {
                "status": "pass",
                "blocking_sample_failures": [],
                "sample_failures": [],
                "sample_size": 6,
            },
        },
    )
    _write_json(
        tmp_path / "release_operations_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "release_claim_policy": {"passed": True, "blocks_release": False, "blocking_reasons": []},
            "release_tiers": {"mainline": {"status": "ready"}},
            "delivery_ready_state_machine": {"counts": {"delivery_ready": 2}},
        },
    )
    _write_json(
        tmp_path / "control_layer_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "status": "stable",
            "source": "live",
        },
    )


def test_fact_gate_convergence_reaches_stable_after_sustained_pass(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _write_passing_inputs(tmp_path)

    payload = {}
    for _ in range(5):
        payload = convergence.run_fact_gate_convergence(write_outputs=True)

    assert payload["status"] == "pass"
    assert payload["all_passed"] is True
    assert payload["trend"] == "stable"
    assert payload["convergence"]["converged"] is True
    assert payload["convergence"]["consecutive_pass_count"] >= 3
    assert payload["convergence"]["window_pass_count"] >= 5
    assert payload["convergence"]["recommendation"] == "observe-only"
    history = convergence.load_fact_gate_convergence_history(limit=2)
    assert history["sample_count"] == 5
    assert len(history["samples"]) == 2


def test_fact_gate_convergence_reports_attention_when_delivery_blocks(monkeypatch, tmp_path: Path) -> None:
    _configure_paths(monkeypatch, tmp_path)
    _write_json(
        tmp_path / "verification_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "fact_consistency": {"passed": True, "contradictions": []},
            "release_gate": {
                "status": "pass",
                "blocking_sample_failures": [],
                "sample_failures": [],
                "sample_size": 6,
            },
        },
    )
    _write_json(
        tmp_path / "release_operations_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "release_claim_policy": {
                "passed": False,
                "blocks_release": True,
                "blocking_reasons": ["verification_gate", "delivery_gate"],
            },
            "release_tiers": {"mainline": {"status": "blocked"}},
            "delivery_ready_state_machine": {"counts": {"delivery_ready": 0}},
        },
    )
    _write_json(
        tmp_path / "control_layer_status.json",
        {
            "updated_at": "2026-04-10T00:00:00Z",
            "status": "stable",
            "source": "live",
        },
    )

    payload = convergence.run_fact_gate_convergence(write_outputs=True)

    assert payload["status"] == "attention"
    assert payload["all_passed"] is False
    assert payload["convergence"]["converged"] is False
    assert "verification_gate" in payload["blocking_reasons"]
    assert "delivery-ready-count-zero" in payload["blocking_reasons"]
    assert payload["convergence"]["recommendation"] == "refresh-facts-and-release-gates"
