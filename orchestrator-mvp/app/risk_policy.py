from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.risk_engine import REPAIR_HISTORY_PATH, _load_json


class RiskPolicy:
    policy_version = "v1"

    def decide(self, risk: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        severity = str(risk.get("severity") or "").strip().lower()
        blast_radius = str(risk.get("blast_radius") or "").strip().lower()
        confidence = float(risk.get("confidence") or 0.0)
        allowed_actions = [str(item) for item in (risk.get("allowed_actions") or []) if str(item).strip()]

        if not allowed_actions:
            reasons.append("no_safe_actions")
        if severity == "critical":
            reasons.append("critical_risk_requires_human_review")
        if blast_radius == "system" and not str(risk.get("rollback_plan") or "").strip():
            reasons.append("rollback_missing")
        if confidence < 0.65:
            reasons.append("confidence_too_low")

        repeated = self._recent_same_action(risk)
        if repeated:
            reasons.append(f"cooldown:{repeated}")

        requires_human_review = bool(reasons)
        allowed = not requires_human_review
        auto_repair_allowed = allowed and severity in {"low", "medium", "high"} and severity != "critical"
        tier = "manual" if requires_human_review else "auto"
        if severity in {"high", "critical"} and not auto_repair_allowed:
            tier = "conditioned" if allowed_actions else "manual"

        return {
            "policy_version": self.policy_version,
            "allowed": allowed,
            "auto_repair_allowed": auto_repair_allowed,
            "requires_human_review": requires_human_review,
            "tier": tier,
            "reason": "; ".join(reasons) if reasons else "safe_repair_allowed",
            "allowed_actions": allowed_actions,
            "blocked_actions": [str(item) for item in (risk.get("forbidden_actions") or []) if str(item).strip()],
        }

    def _recent_same_action(self, risk: dict[str, Any]) -> str | None:
        history = _load_json(REPAIR_HISTORY_PATH, [])
        risk_id = str(risk.get("risk_id") or "").strip()
        if not history or not risk_id:
            return None
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        for item in reversed(history):
            if str(item.get("risk_id") or "").strip() != risk_id:
                continue
            finished_at = str(item.get("finished_at") or item.get("updated_at") or "").strip()
            if not finished_at:
                continue
            try:
                parsed = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if parsed >= cutoff:
                return str(item.get("name") or "")
        return None

