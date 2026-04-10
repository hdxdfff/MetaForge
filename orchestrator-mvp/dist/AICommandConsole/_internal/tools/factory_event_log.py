from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVENT_LOG_PATH = DATA / "factory_events.jsonl"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_event(
    event_type: str,
    *,
    source: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    refs: dict[str, Any] | None = None,
    severity: str = "info",
) -> dict[str, Any]:
    event = {
        "event_id": f"evt_{uuid4().hex[:12]}",
        "timestamp": utc_iso(),
        "type": event_type,
        "source": source,
        "severity": severity,
        "summary": summary,
        "payload": payload or {},
        "refs": refs or {},
    }
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    if not EVENT_LOG_PATH.exists():
        return []
    lines = EVENT_LOG_PATH.read_text(encoding="utf-8").splitlines()
    if limit is not None:
        lines = lines[-max(1, min(limit, 5000)):]
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events
