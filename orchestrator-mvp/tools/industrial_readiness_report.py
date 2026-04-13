from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.execution_trace import append_trace, read_tail

SLO_PATH = DATA / "production_slo_registry.json"
INCIDENT_LEDGER_PATH = DATA / "incident_ledger.json"
INCIDENT_SUMMARY_PATH = DATA / "incident_ledger_summary.json"
CONTINUITY_PATH = DATA / "continuity_metrics.json"
STAGE5_PATH = DATA / "stage5_dashboard.json"
ARTIFACT_VALIDATION_PATH = DATA / "artifact_regression_validation.json"
TELEMETRY_PATH = DATA / "telemetry_events.json"
QUEUE_PRESSURE_PATH = DATA / "queue_pressure_analysis.json"
ECONOMICS_PATH = DATA / "economics_engine_status.json"
ROLLBACK_DRILL_PATH = DATA / "release_rollback_drill.json"
INDUSTRIAL_OPERATIONS_PATH = DATA / "industrial_operations.json"
AUTONOMY_CONTROL_PLANE_PATH = DATA / "autonomy_control_plane.json"
OUTPUT_PATH = DATA / "industrial_readiness.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_timestamp(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        stamp = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(stamp)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _trace_control_metrics() -> dict[str, Any]:
    traces = read_tail(limit=500)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    relevant = []
    durations: list[float] = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        ts = _parse_timestamp(trace.get("timestamp"))
        if ts is None or ts < cutoff:
            continue
        if str(trace.get("phase") or "") != "industrial-readiness":
            continue
        relevant.append(trace)
        duration_ms = trace.get("duration_ms")
        if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
            durations.append(float(duration_ms) / 1000.0)
    success_count = 0
    for trace in relevant:
        level = str(trace.get("level") or "").lower()
        result = str(trace.get("result") or "").lower()
        if level != "error" and "fail" not in result and "error" not in result:
            success_count += 1
    p95 = None
    if durations:
        sorted_durations = sorted(durations)
        index = max(0, int(round(0.95 * (len(sorted_durations) - 1))))
        p95 = round(sorted_durations[index], 4)
    return {
        "control_loop_success_rate": round(success_count / max(1, len(relevant)), 4) if relevant else None,
        "control_decision_latency_p95_seconds": p95,
        "control_trace_count": len(relevant),
    }


def _incident_summary() -> dict[str, Any]:
    ledger = _load_json(INCIDENT_LEDGER_PATH, [])
    if not isinstance(ledger, list):
        ledger = []
    open_incidents = [item for item in ledger if isinstance(item, dict) and str(item.get("status") or "").lower() != "closed"]
    closed_incidents = [item for item in ledger if isinstance(item, dict) and str(item.get("status") or "").lower() == "closed"]
    sev_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    mttr_samples: list[float] = []
    for item in closed_incidents:
        sev = str(item.get("severity") or "unknown").lower()
        domain = str(item.get("domain") or "unknown").lower()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        opened = item.get("opened_at")
        closed = item.get("closed_at")
        try:
            if opened and closed:
                opened_dt = datetime.fromisoformat(str(opened).replace("Z", "+00:00"))
                closed_dt = datetime.fromisoformat(str(closed).replace("Z", "+00:00"))
                if opened_dt.tzinfo is None:
                    opened_dt = opened_dt.replace(tzinfo=timezone.utc)
                else:
                    opened_dt = opened_dt.astimezone(timezone.utc)
                if closed_dt.tzinfo is None:
                    closed_dt = closed_dt.replace(tzinfo=timezone.utc)
                else:
                    closed_dt = closed_dt.astimezone(timezone.utc)
                if closed_dt >= opened_dt:
                    mttr_samples.append((closed_dt - opened_dt).total_seconds() / 60.0)
        except Exception:
            continue
    auto_repair_successes = sum(
        1
        for item in closed_incidents
        if isinstance(item, dict)
        and bool((item.get("verification") or {}).get("repair_success"))
    )
    total_incidents = len(ledger)
    auto_recovery_rate = round(auto_repair_successes / max(1, total_incidents), 4) if total_incidents else 0.0
    summary = {
        "updated_at": _utc(),
        "status": "pass",
        "incident_count": total_incidents,
        "open_incident_count": len(open_incidents),
        "closed_incident_count": len(closed_incidents),
        "severity_counts": sev_counts,
        "domain_counts": domain_counts,
        "auto_repair_success_count": auto_repair_successes,
        "auto_recovery_success_rate": auto_recovery_rate,
        "mttr_minutes_p50": round(statistics.median(mttr_samples), 2) if mttr_samples else None,
        "mttr_minutes_p95": round(sorted(mttr_samples)[max(0, int(len(mttr_samples) * 0.95) - 1)], 2) if mttr_samples else None,
        "ledger_path": str(INCIDENT_LEDGER_PATH),
    }
    atomic_write_json(INCIDENT_SUMMARY_PATH, summary)
    return summary


def _measurement(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> dict[str, Any]:
    if value is None:
        return {"status": "unknown", "value": None, "minimum": minimum, "maximum": maximum, "reason": "missing measurement"}
    try:
        numeric = float(value)
    except Exception:
        return {"status": "unknown", "value": value, "minimum": minimum, "maximum": maximum, "reason": "non-numeric measurement"}
    if minimum is not None and numeric < minimum:
        return {"status": "fail", "value": numeric, "minimum": minimum, "maximum": maximum}
    if maximum is not None and numeric > maximum:
        return {"status": "fail", "value": numeric, "minimum": minimum, "maximum": maximum}
    return {"status": "pass", "value": numeric, "minimum": minimum, "maximum": maximum}


def _cost_per_real_artifact(economics: dict[str, Any], artifacts_24h: dict[str, Any]) -> float | None:
    real_artifacts = float(artifacts_24h.get("real_artifacts") or 0)
    if real_artifacts <= 0:
        return None
    currency = economics.get("currency_system") or {}
    usage = currency.get("usage") or {}
    resource_market = economics.get("resource_market") or {}
    resources = {
        str(item.get("resource_id") or ""): item
        for item in (resource_market.get("resources") or [])
        if isinstance(item, dict)
    }
    cost = 0.0
    for resource_id, call_field in (
        ("cheap_model", "cheap_calls"),
        ("reasoning_model", "reasoning_calls"),
        ("strong_model", "strong_calls"),
    ):
        calls = float(usage.get(call_field) or 0)
        unit_price = float((resources.get(resource_id) or {}).get("unit_price_mfc") or 0)
        cost += calls * unit_price
    if cost <= 0:
        return None
    return round(cost / real_artifacts, 4)


def _rollback_measurement() -> dict[str, Any] | None:
    drill = _load_json(ROLLBACK_DRILL_PATH, {})
    value = drill.get("rollback_time_minutes")
    if value is None:
        return None
    try:
        numeric = float(value)
    except Exception:
        return None
    return {
        "value": round(numeric, 4),
        "source": str(drill.get("source") or "drill"),
        "measured_at": drill.get("measured_at"),
    }


def run_industrial_readiness_report() -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    slo = _load_json(SLO_PATH, {})
    stage5 = _load_json(STAGE5_PATH, {})
    continuity = _load_json(CONTINUITY_PATH, {})
    validation = _load_json(ARTIFACT_VALIDATION_PATH, {})
    telemetry = _load_json(TELEMETRY_PATH, {})
    queue_pressure = _load_json(QUEUE_PRESSURE_PATH, {})
    economics = _load_json(ECONOMICS_PATH, {})
    industrial_operations = _load_json(INDUSTRIAL_OPERATIONS_PATH, {})
    autonomy_control_plane = _load_json(AUTONOMY_CONTROL_PLANE_PATH, {})
    incident_summary = _incident_summary()

    task_24h = ((continuity.get("windows") or {}).get("24") or {}).get("tasks") or {}
    artifacts_24h = ((continuity.get("windows") or {}).get("24") or {}).get("artifacts") or {}
    recovery_24h = ((continuity.get("windows") or {}).get("24") or {}).get("recovery") or {}
    control_metrics = _trace_control_metrics()
    rollback_measurement = _rollback_measurement()
    cost_per_real_artifact = _cost_per_real_artifact(economics, artifacts_24h)

    compliance = {
        "control_loop_success_rate": _measurement(
            control_metrics.get("control_loop_success_rate"),
            minimum=float((slo.get("slo_sets") or {}).get("control_plane", {}).get("control_loop_success_rate_min") or 0.995),
        ),
        "control_decision_latency_p95_seconds": _measurement(
            control_metrics.get("control_decision_latency_p95_seconds"),
            maximum=float((slo.get("slo_sets") or {}).get("control_plane", {}).get("control_decision_latency_p95_seconds_max") or 5),
        ),
        "task_start_latency_p95_minutes": _measurement(stage5.get("median_time_to_first_result_minutes"), maximum=float((slo.get("slo_sets") or {}).get("execution_plane", {}).get("task_start_latency_p95_minutes_max") or 15)),
        "task_success_rate_24h": _measurement(
            round((float(task_24h.get("verified_completed_tasks") or 0) / max(1.0, float(task_24h.get("completed_tasks") or 0))), 4) if task_24h else None,
            minimum=float((slo.get("slo_sets") or {}).get("execution_plane", {}).get("task_success_rate_24h_min") or 0.95),
        ),
        "real_artifact_pass_rate": _measurement(
            round((float(artifacts_24h.get("real_artifacts") or 0) / max(1.0, float(artifacts_24h.get("artifacts_total") or 0))), 4) if artifacts_24h else None,
            minimum=float((slo.get("slo_sets") or {}).get("artifact_plane", {}).get("real_artifact_pass_rate_min") or 0.95),
        ),
        "artifact_regression_fail_rate": _measurement(
            validation.get("fail_rate"),
            maximum=float((slo.get("slo_sets") or {}).get("artifact_plane", {}).get("artifact_regression_fail_rate_max") or 0.05),
        ),
        "mttr_minutes": _measurement(
            incident_summary.get("mttr_minutes_p50"),
            maximum=float((slo.get("slo_sets") or {}).get("recovery_plane", {}).get("mttr_minutes_max") or 30),
        ),
        "auto_recovery_success_rate": _measurement(
            incident_summary.get("auto_recovery_success_rate"),
            minimum=float((slo.get("slo_sets") or {}).get("recovery_plane", {}).get("auto_recovery_success_rate_min") or 0.9),
        ),
        "failed_release_rollback_time_minutes": _measurement(
            rollback_measurement.get("value") if rollback_measurement else None,
            maximum=float((slo.get("slo_sets") or {}).get("release_plane", {}).get("failed_release_rollback_time_minutes_max") or 10),
        ),
        "cost_per_real_artifact": _measurement(
            cost_per_real_artifact,
            maximum=(slo.get("slo_sets") or {}).get("economics_plane", {}).get("cost_per_real_artifact_max"),
        ),
    }

    overall_status = "pass"
    if any(item.get("status") == "fail" for item in compliance.values()):
        overall_status = "attention"
    if any(item.get("status") == "unknown" for item in compliance.values()):
        overall_status = "attention"

    payload = {
        "updated_at": _utc(),
        "status": overall_status,
        "slo_registry_path": str(SLO_PATH),
        "incident_summary_path": str(INCIDENT_SUMMARY_PATH),
        "telemetry_path": str(TELEMETRY_PATH),
        "queue_pressure_path": str(QUEUE_PRESSURE_PATH),
        "slo_compliance": compliance,
        "live_context": {
            "stage5_status": str(stage5.get("status") or ""),
            "control_layer_status": str(stage5.get("control_layer_status") or ""),
            "autonomy_stage": str(stage5.get("autonomy_stage") or ""),
            "active_queue_pressure": str(stage5.get("active_queue_pressure") or queue_pressure.get("pressure") or ""),
            "historical_failure_debt_count": int(stage5.get("historical_failure_debt_count") or 0),
            "historical_failure_debt_severity": str(stage5.get("historical_failure_debt_severity") or ""),
            "amplifier_success_conversion_rate": float(stage5.get("amplifier_success_conversion_rate") or 0.0),
            "industrial_operations_status": str(industrial_operations.get("status") or ""),
            "release_freeze": bool((industrial_operations.get("release_freeze") or {}).get("freeze_triggered")),
            "budget_suppression": industrial_operations.get("budget_suppression") if isinstance(industrial_operations, dict) else {},
            "autonomy_control_plane_status": str(autonomy_control_plane.get("status") or ""),
            "autonomy_control_plane_closed_pools": list((autonomy_control_plane.get("summary") or {}).get("closed_pools") or []),
        },
        "telemetry_summary": {
            "event_count": len(telemetry.get("events") or []) if isinstance(telemetry, dict) else 0,
            "task_success_rate": telemetry.get("task_success_rate") if isinstance(telemetry, dict) else None,
            "cheap_calls_total": telemetry.get("cheap_calls_total") if isinstance(telemetry, dict) else None,
            "core_escalations_total": telemetry.get("core_escalations_total") if isinstance(telemetry, dict) else None,
            "control_trace_count": control_metrics.get("control_trace_count"),
        },
        "economics_summary": {
            "source": str(ECONOMICS_PATH),
            "cost_per_real_artifact": cost_per_real_artifact,
            "rollback_measurement": rollback_measurement,
        },
        "incident_summary": incident_summary,
        "coverage_notes": [
            "Unknown measurements are treated as non-compliant for release decisions.",
            "This report is a production governance view, not a replacement for live metrics collection.",
            "SLO thresholds intentionally start conservative until each plane has live measurements.",
            "Rollback is accepted from a dedicated rollback drill when no live failed-release rollback exists yet.",
            "Industrial operations are tracked separately so freeze/degrade policy can tighten without masking readiness state.",
        ],
    }
    atomic_write_json(OUTPUT_PATH, payload)
    append_trace(
        "industrial-readiness",
        "build industrial readiness report",
        "run industrial_readiness_report.py",
        f"status={payload['status']} control_success={payload['slo_compliance']['control_loop_success_rate']['status']}",
        "refresh report bundle or fix failing SLOs",
        worker="supervisor",
        duration_ms=int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        data={
            "status": payload["status"],
            "control_loop_success_rate": payload["slo_compliance"]["control_loop_success_rate"].get("value"),
            "control_decision_latency_p95_seconds": payload["slo_compliance"]["control_decision_latency_p95_seconds"].get("value"),
        },
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an industrial readiness governance report.")
    parser.add_argument("--json", action="store_true", default=True)
    _ = parser.parse_args()
    print(json.dumps(run_industrial_readiness_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
