from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.factory_event_log import read_events
from tools.factory_state import FACTORY_STATE_PATH
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "factory_replay_state.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def build_replay_state(limit: int = 500) -> dict[str, Any]:
    snapshot = _load_json(FACTORY_STATE_PATH, {})
    events = read_events(limit=limit)
    counter = Counter(event.get("type") for event in events)
    last_tick = None
    last_error = None
    last_self_report = None
    for event in events:
        if event.get("type") == "daemon.tick":
            last_tick = event
        elif event.get("type") == "daemon.error":
            last_error = event
        elif event.get("type") == "self_report.emitted":
            last_self_report = event
    return {
        "updated_at": _utc(),
        "snapshot_cycle": ((snapshot.get("daemon") or {}).get("cycle")),
        "snapshot_status": ((snapshot.get("daemon") or {}).get("status")),
        "events_scanned": len(events),
        "event_counts": dict(counter),
        "reconstructed": {
            "last_tick_cycle": ((last_tick or {}).get("payload") or {}).get("cycle"),
            "last_tick_meta": ((last_tick or {}).get("payload") or {}).get("run_meta"),
            "last_tick_evolution": ((last_tick or {}).get("payload") or {}).get("run_evolution"),
            "last_error": (last_error or {}).get("summary"),
            "last_error_at": (last_error or {}).get("timestamp"),
            "last_self_report_status": (((last_self_report or {}).get("payload") or {}).get("overall_status")),
            "last_self_report_at": (last_self_report or {}).get("timestamp"),
        },
        "timeline_tail": events[-20:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay recent factory state from event log")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    payload = build_replay_state(limit=args.limit)
    if args.write:
        atomic_write_json(OUT, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
