from __future__ import annotations

from typing import Any


class SemanticVerifier:
    def verify(
        self,
        *,
        snapshot_before: dict[str, Any],
        snapshot_after: dict[str, Any],
        risk: dict[str, Any],
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        runtime_alive = bool(snapshot_after.get("daemon_running"))
        service_semantics_restored = bool(
            int(snapshot_after.get("queue_depth") or 0) > 0
            or int(snapshot_after.get("active_tasks") or 0) > 0
            or int(snapshot_after.get("completed_tasks_last_60m") or 0) > 0
        )
        evidence_chain_restored = bool(
            int(snapshot_after.get("verification_pending_checks_count") or 0) == 0
            and int(snapshot_after.get("artifact_updates_last_24h") or 0) > 0
        )
        promotion_unblocked = bool(
            int(snapshot_after.get("verification_pending_checks_count") or 0) == 0
            and str(snapshot_after.get("quality_status") or "").strip().lower() in {"ready", "pass", "promote"}
            and str(snapshot_after.get("release_train_status") or "").strip().lower() != "blocked"
        )
        regressions: list[str] = []
        risk_id = str(risk.get("risk_id") or "")
        if risk_id == "runtime.queue_starvation" and int(snapshot_after.get("queue_depth") or 0) == 0:
            regressions.append("queue_remains_empty")
        if risk_id == "runtime.false_liveness" and not service_semantics_restored:
            regressions.append("service_semantics_not_restored")
        if risk_id == "verification.misalignment" and int(snapshot_after.get("verification_pending_checks_count") or 0) > 0:
            regressions.append("verification_still_pending")
        if risk_id == "routing.model_degradation" and int(snapshot_after.get("provider_auth_failure_count") or 0) > 0:
            regressions.append("provider_route_still_degraded")
        if risk_id == "release.promotion_mismatch" and promotion_unblocked:
            regressions.append("promotion_still_unblocked")
        if risk_id == "continuity.distortion" and bool(snapshot_after.get("state_write_error_recent")):
            regressions.append("state_write_error_persists")

        repair_success = bool(runtime_alive and service_semantics_restored and evidence_chain_restored and not regressions)
        return {
            "repair_success": repair_success,
            "runtime_alive": runtime_alive,
            "service_semantics_restored": service_semantics_restored,
            "evidence_chain_restored": evidence_chain_restored,
            "promotion_unblocked": promotion_unblocked,
            "regressions": regressions,
            "before": {
                "queue_depth": snapshot_before.get("queue_depth"),
                "active_tasks": snapshot_before.get("active_tasks"),
                "verification_pending_checks_count": snapshot_before.get("verification_pending_checks_count"),
                "artifact_updates_last_24h": snapshot_before.get("artifact_updates_last_24h"),
            },
            "after": {
                "queue_depth": snapshot_after.get("queue_depth"),
                "active_tasks": snapshot_after.get("active_tasks"),
                "verification_pending_checks_count": snapshot_after.get("verification_pending_checks_count"),
                "artifact_updates_last_24h": snapshot_after.get("artifact_updates_last_24h"),
            },
            "actions_observed": [str(item.get("name") or "") for item in actions if item.get("name")],
        }

