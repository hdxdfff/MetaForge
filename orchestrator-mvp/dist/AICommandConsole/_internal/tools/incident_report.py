from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.risk_engine import INCIDENT_LEDGER_PATH, RISK_STATUS_PATH


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def build_incident_report(limit: int = 10) -> dict[str, Any]:
    status = _load_json(RISK_STATUS_PATH, {})
    ledger = _load_json(INCIDENT_LEDGER_PATH, [])
    if not isinstance(ledger, list):
        ledger = []
    open_incidents = [item for item in ledger if item.get("status") != "closed"]
    closed_incidents = [item for item in ledger if item.get("status") == "closed"]
    by_risk: dict[str, int] = {}
    for item in ledger:
        risk_id = str(item.get("risk_id") or "unknown")
        by_risk[risk_id] = by_risk.get(risk_id, 0) + 1
    recent = ledger[-max(1, limit):]
    return {
        "updated_at": status.get("updated_at"),
        "risk_status": status,
        "incident_count": len(ledger),
        "open_incident_count": len(open_incidents),
        "closed_incident_count": len(closed_incidents),
        "by_risk": by_risk,
        "recent": recent,
        "ledger_path": str(INCIDENT_LEDGER_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize incident ledger state.")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = build_incident_report(limit=args.limit)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"incidents: {payload['incident_count']} open={payload['open_incident_count']} closed={payload['closed_incident_count']}")
        print(f"ledger: {payload['ledger_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

