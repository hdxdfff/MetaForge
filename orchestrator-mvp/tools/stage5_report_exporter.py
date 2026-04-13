from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT / "generated" / "stage5-report-exports"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json, atomic_write_text
from tools.execution_trace import append_trace


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def run_stage5_report_exporter() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    dashboard = _load_json(DATA / "stage5_dashboard.json", {})
    history = _load_json(DATA / "stage5_metrics_history.json", {})
    ledger = _load_json(DATA / "evolution_ledger.json", {})
    debt_archive = _load_json(DATA / "historical_failure_debt_archive.json", {})
    queue_pressure = _load_json(DATA / "queue_pressure_analysis.json", {})
    amplifier_observability = _load_json(DATA / "amplifier_observability.json", {})
    industrial_readiness = _load_json(DATA / "industrial_readiness.json", {})
    industrial_operations = _load_json(DATA / "industrial_operations.json", {})
    industrial_failure_taxonomy = _load_json(DATA / "industrial_failure_taxonomy.json", {})
    incident_summary = _load_json(DATA / "incident_ledger_summary.json", {})
    slo_registry = _load_json(DATA / "production_slo_registry.json", {})
    goal_backlog_status = _load_json(DATA / "goal_backlog_status.json", {})
    artifact_growth_status = _load_json(DATA / "artifact_growth_status.json", {})
    capability_builder_status = _load_json(DATA / "capability_builder_status.json", {})
    p2_sandbox_queue = _load_json(DATA / "p2_sandbox_queue.json", {})
    p2_sandbox_status = _load_json(DATA / "p2_sandbox_status.json", {})
    failure_backlog_report = _load_json(DATA / "task_backlog_automation.json", {})
    budget_suppression_report = _load_json(DATA / "budget_suppression_report.json", {})
    autonomy_control_plane = _load_json(DATA / "autonomy_control_plane.json", {})
    autonomy_control_plane_summary = _load_json(DATA / "autonomy_control_plane_summary.json", {})
    autonomy_control_plane_summary_md = (DATA / "autonomy_control_plane_summary.md").read_text(encoding="utf-8") if (DATA / "autonomy_control_plane_summary.md").exists() else ""
    export_dir = GENERATED / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(export_dir / "stage5_dashboard.json", dashboard)
    atomic_write_json(export_dir / "stage5_metrics_history.json", history)
    atomic_write_json(export_dir / "evolution_ledger.json", ledger)
    atomic_write_json(export_dir / "historical_failure_debt_archive.json", debt_archive)
    atomic_write_json(export_dir / "queue_pressure_analysis.json", queue_pressure)
    atomic_write_json(export_dir / "amplifier_observability.json", amplifier_observability)
    atomic_write_json(export_dir / "industrial_readiness.json", industrial_readiness)
    atomic_write_json(export_dir / "industrial_operations.json", industrial_operations)
    atomic_write_json(export_dir / "industrial_failure_taxonomy.json", industrial_failure_taxonomy)
    atomic_write_json(export_dir / "incident_ledger_summary.json", incident_summary)
    atomic_write_json(export_dir / "production_slo_registry.json", slo_registry)
    atomic_write_json(export_dir / "goal_backlog_status.json", goal_backlog_status)
    atomic_write_json(export_dir / "artifact_growth_status.json", artifact_growth_status)
    atomic_write_json(export_dir / "capability_builder_status.json", capability_builder_status)
    atomic_write_json(export_dir / "p2_sandbox_queue.json", p2_sandbox_queue)
    atomic_write_json(export_dir / "p2_sandbox_status.json", p2_sandbox_status)
    atomic_write_json(export_dir / "task_backlog_automation.json", failure_backlog_report)
    atomic_write_json(export_dir / "budget_suppression_report.json", budget_suppression_report)
    atomic_write_json(export_dir / "autonomy_control_plane.json", autonomy_control_plane)
    atomic_write_json(export_dir / "autonomy_control_plane_summary.json", autonomy_control_plane_summary)
    atomic_write_text(export_dir / "autonomy_control_plane_summary.md", autonomy_control_plane_summary_md)
    atomic_write_text(
        export_dir / "README.md",
        "# Stage 5 Report Export\n\nThis bundle captures the latest Stage 5 dashboard, history, evolution ledger, debt archive, queue pressure, amplifier observability, industrial readiness, industrial operations, incident summary, SLO registry, budget suppression views, P2 sandbox view, autonomy control plane, and the one-page control plane summary.\n",
    )
    manifest = {
        "bundle_id": export_dir.name,
        "created_at": _utc(),
        "status": str(dashboard.get("status") or "unknown"),
        "stage5_candidate": bool(dashboard.get("stage5_candidate")),
        "stage5_confirmed": bool(dashboard.get("stage5_confirmed")),
        "files": [
            "stage5_dashboard.json",
            "stage5_metrics_history.json",
            "evolution_ledger.json",
            "historical_failure_debt_archive.json",
            "queue_pressure_analysis.json",
            "amplifier_observability.json",
            "industrial_readiness.json",
            "industrial_operations.json",
            "industrial_failure_taxonomy.json",
            "incident_ledger_summary.json",
            "production_slo_registry.json",
            "goal_backlog_status.json",
            "artifact_growth_status.json",
            "capability_builder_status.json",
            "p2_sandbox_queue.json",
            "p2_sandbox_status.json",
            "task_backlog_automation.json",
            "budget_suppression_report.json",
            "autonomy_control_plane.json",
            "autonomy_control_plane_summary.json",
            "autonomy_control_plane_summary.md",
            "README.md",
        ],
    }
    atomic_write_json(export_dir / "artifact_manifest.json", manifest)
    append_trace(
        "industrial-readiness",
        "export stage5 readiness bundle",
        "run stage5_report_exporter.py",
        f"status={dashboard.get('status')} bundle={export_dir.name}",
        "publish export bundle or refresh readiness views",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={"export_dir": str(export_dir), "files": manifest["files"]},
    )
    return {
        "updated_at": _utc(),
        "status": "pass",
        "export_dir": str(export_dir),
        "bundle_id": export_dir.name,
        "dashboard_status": dashboard.get("status"),
    }


def main() -> int:
    _ = argparse.ArgumentParser(description="Export a Stage 5 evidence bundle.").parse_args()
    print(json.dumps(run_stage5_report_exporter(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
