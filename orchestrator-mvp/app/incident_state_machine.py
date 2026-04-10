from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.risk_engine import INCIDENT_LEDGER_PATH, REPAIR_HISTORY_PATH, RISK_STATUS_PATH, SEMANTIC_HEALTH_PATH
from tools.io_utils import atomic_write_json


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


class IncidentStateMachine:
    def __init__(self) -> None:
        self.ledger_path = INCIDENT_LEDGER_PATH
        self.repair_history_path = REPAIR_HISTORY_PATH
        self.status_path = RISK_STATUS_PATH
        self.semantic_health_path = SEMANTIC_HEALTH_PATH

    def load_ledger(self) -> list[dict[str, Any]]:
        payload = _load_json(self.ledger_path, [])
        return payload if isinstance(payload, list) else []

    def upsert_incident(self, risk: dict[str, Any], *, source: str, snapshot: dict[str, Any], policy_decision: dict[str, Any]) -> dict[str, Any]:
        ledger = self.load_ledger()
        existing = next(
            (
                item
                for item in ledger
                if str(item.get("risk_id") or "").strip() == str(risk.get("risk_id") or "").strip()
                and not item.get("closed_at")
            ),
            None,
        )
        now = _utc()
        signals_snapshot = dict(risk.get("signals") or {})
        snapshot_fingerprint = _fingerprint(
            {
                "risk_id": risk.get("risk_id"),
                "signals": signals_snapshot,
                "goal_primary": snapshot.get("goal_primary"),
                "daemon_cycle": snapshot.get("daemon_cycle"),
            }
        )
        if existing is None:
            incident_id = f"inc-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{str(risk.get('risk_id') or 'risk').replace('.', '-')}"
            incident = {
                "incident_id": incident_id,
                "risk_id": risk.get("risk_id"),
                "title": risk.get("title"),
                "domain": risk.get("domain"),
                "severity": risk.get("severity"),
                "kind": risk.get("kind"),
                "status": "open",
                "opened_at": now,
                "last_seen_at": now,
                "source": source,
                "signals_snapshot": signals_snapshot,
                "snapshot_fingerprint": snapshot_fingerprint,
                "policy_decision": policy_decision,
                "actions": [],
                "verification": {},
                "closed_at": None,
                "semantic_status": "pending",
            }
            ledger.append(incident)
            atomic_write_json(self.ledger_path, ledger)
            return incident
        existing["last_seen_at"] = now
        existing["signals_snapshot"] = signals_snapshot
        existing["snapshot_fingerprint"] = snapshot_fingerprint
        existing["policy_decision"] = policy_decision
        atomic_write_json(self.ledger_path, ledger)
        return existing

    def record_actions(self, incident_id: str, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
        ledger = self.load_ledger()
        for incident in ledger:
            if incident.get("incident_id") != incident_id:
                continue
            incident.setdefault("actions", [])
            incident["actions"].extend(actions)
            incident["last_seen_at"] = _utc()
            atomic_write_json(self.ledger_path, ledger)
            return incident
        return None

    def finalize(self, incident_id: str, verification: dict[str, Any], semantic_status: str) -> dict[str, Any] | None:
        ledger = self.load_ledger()
        for incident in ledger:
            if incident.get("incident_id") != incident_id:
                continue
            incident["verification"] = verification
            incident["semantic_status"] = semantic_status
            incident["status"] = "closed" if semantic_status == "recovered" else "verifying"
            incident["closed_at"] = _utc() if semantic_status == "recovered" else incident.get("closed_at")
            incident["last_seen_at"] = _utc()
            atomic_write_json(self.ledger_path, ledger)
            return incident
        return None

    def record_repair_action(self, *, incident_id: str, risk_id: str, action: dict[str, Any], source: str) -> dict[str, Any]:
        history = _load_json(self.repair_history_path, [])
        if not isinstance(history, list):
            history = []
        now = _utc()
        entry = {
            "incident_id": incident_id,
            "risk_id": risk_id,
            "name": action.get("name"),
            "result": action.get("result"),
            "mode": action.get("mode") or "bounded",
            "detail": action.get("detail") or {},
            "source": source,
            "started_at": action.get("started_at") or now,
            "finished_at": action.get("finished_at") or now,
            "updated_at": now,
        }
        history.append(entry)
        atomic_write_json(self.repair_history_path, history[-500:])
        return entry

    def write_semantic_health(self, payload: dict[str, Any]) -> dict[str, Any]:
        atomic_write_json(self.semantic_health_path, payload)
        return payload

    def write_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        atomic_write_json(self.status_path, payload)
        return payload

