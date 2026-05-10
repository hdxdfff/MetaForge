from __future__ import annotations

import json
import shutil
from pathlib import Path

from consolidation import compact_event_log, read_jsonl_all, write_jsonl
from local_mind_paths import ROOT


def make_event(index: int, *, importance: float, verified: bool = True) -> dict[str, object]:
    return {
        "event_id": f"evt_selftest_{index:03d}",
        "timestamp": f"2026-05-10T10:{index:02d}:00+08:00",
        "source": "selftest",
        "event_type": "selftest",
        "summary": f"selftest event {index}",
        "raw_observation": {},
        "importance": importance,
        "verified": verified,
        "memory_candidate": importance >= 0.65,
    }


def main() -> int:
    workspace = ROOT / ".tmp" / "compaction-selftest"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    event_log = workspace / "event_log.jsonl"
    archive = workspace / "event_archive.jsonl"

    events = [
        make_event(0, importance=0.1),
        make_event(1, importance=0.2),
        make_event(2, importance=0.9),
        make_event(3, importance=0.1, verified=False),
        make_event(4, importance=0.1),
        make_event(5, importance=0.1),
    ]
    write_jsonl(event_log, events)

    result = compact_event_log(
        max_events=3,
        keep_recent_events=2,
        min_importance=0.65,
        event_log_path=event_log,
        archive_path=archive,
    )
    remaining = read_jsonl_all(event_log)
    archived = read_jsonl_all(archive)
    remaining_ids = {event["event_id"] for event in remaining}
    archived_ids = {event["event_id"] for event in archived}

    expected_remaining = {"evt_selftest_002", "evt_selftest_003", "evt_selftest_004", "evt_selftest_005"}
    expected_archived = {"evt_selftest_000", "evt_selftest_001"}

    checks = {
        "compacted": result["compacted"] is True,
        "events_before": result["events_before"] == 6,
        "events_after": result["events_after"] == 4,
        "archived": result["archived"] == 2,
        "remaining_ids": remaining_ids == expected_remaining,
        "archived_ids": archived_ids == expected_archived,
    }
    output = {
        "result": result,
        "remaining_ids": sorted(remaining_ids),
        "archived_ids": sorted(archived_ids),
        "checks": checks,
        "passed": all(checks.values()),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
