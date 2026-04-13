from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.capability_builder as capability_builder


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _patch_paths(monkeypatch, data: Path) -> None:
    monkeypatch.setattr(capability_builder, "DATA", data)
    monkeypatch.setattr(capability_builder, "QUEUE_PATH", data / "capability_build_queue.json")
    monkeypatch.setattr(capability_builder, "REPORT_PATH", data / "capability_builder_status.json")
    monkeypatch.setattr(capability_builder, "ARTIFACT_REGISTRY_PATH", data / "artifact_registry.json")
    monkeypatch.setattr(capability_builder, "CONTINUITY_METRICS_PATH", data / "continuity_metrics.json")
    monkeypatch.setattr(capability_builder, "STAGE5_HISTORY_PATH", data / "stage5_metrics_history.json")
    monkeypatch.setattr(capability_builder, "INDUSTRIAL_OPERATIONS_PATH", data / "industrial_operations.json")


def test_capability_builder_dedupes_semantic_duplicates_and_is_idempotent(tmp_path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _patch_paths(monkeypatch, data)

    duplicate_ledger_items = [
        {
            "id": "cap_20260403_ledger_a1",
            "category": "transition_ledger",
            "trigger": {
                "source": "stage5_evaluator",
                "signal": "blocked_to_done_conversion_pending_transition_ledger",
            },
            "goal": "Add a durable blocked-to-done transition ledger so productivity trend can be measured without inference.",
            "proposed_action": {
                "type": "new_ledger",
                "target": "D:\\codex\\orchestrator-mvp\\data\\blocked_to_done_transitions.json",
            },
            "budget_pool": "P2",
            "admission_lane": "capability_growth",
            "status": "open",
            "created_at": "2026-04-03T17:30:56Z",
        },
        {
            "id": "cap_20260403_ledger_b2",
            "category": "transition_ledger",
            "trigger": {
                "source": "stage5_evaluator",
                "signal": "blocked_to_done_conversion_pending_transition_ledger",
            },
            "goal": "Add a durable blocked-to-done transition ledger so productivity trend can be measured without inference.",
            "proposed_action": {
                "type": "new_ledger",
                "target": "D:\\codex\\orchestrator-mvp\\data\\blocked_to_done_transitions.json",
            },
            "budget_pool": "P2",
            "admission_lane": "capability_growth",
            "status": "open",
            "created_at": "2026-04-03T17:31:56Z",
        },
    ]
    _write_json(
        data / "capability_build_queue.json",
        {
            "version": 1,
            "open_items": duplicate_ledger_items,
            "in_progress_items": [],
            "done_items": [],
            "failed_items": [],
        },
    )
    _write_json(data / "artifact_registry.json", {"status": "pass", "issue_count": 0})
    _write_json(
        data / "industrial_operations.json",
        {
            "budget_control": {
                "gates": {"allow_p2": True},
                "replenishment": {"capability_expansion_daily": {"budget_exhausted": False}},
            }
        },
    )
    _write_json(data / "continuity_metrics.json", {})
    _write_json(data / "stage5_metrics_history.json", {})

    first = capability_builder.run_capability_builder()
    assert first["status"] == "pass"
    assert first["open_items_created"] == 0

    queue_after_first = json.loads((data / "capability_build_queue.json").read_text(encoding="utf-8"))
    assert len(queue_after_first["open_items"]) == 1

    second = capability_builder.run_capability_builder()
    assert second["status"] == "pass"
    assert second["open_items_created"] == 0

    queue_after_second = json.loads((data / "capability_build_queue.json").read_text(encoding="utf-8"))
    assert len(queue_after_second["open_items"]) == 1
