from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from json_store import append_jsonl, read_json, read_jsonl_tail, write_json
from local_mind_paths import ROOT


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_jsonl_all(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            import json

            rows.append(json.loads(line))
        except Exception:
            rows.append({"event_type": "malformed_jsonl", "summary": line, "verified": False, "importance": 0})
    return rows


def write_jsonl(path, rows: list[dict[str, Any]]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("timestamp", "")), str(event.get("event_id", "")))


def append_unique_jsonl(path, key: str, rows: list[dict[str, Any]]) -> int:
    existing = read_jsonl_all(path)
    seen = {item.get(key) for item in existing}
    written = 0
    for row in rows:
        if row.get(key) in seen:
            continue
        append_jsonl(path, row)
        seen.add(row.get(key))
        written += 1
    return written


def event_to_episodic(event: dict[str, Any]) -> dict[str, Any]:
    event_id = event.get("event_id")
    return {
        "memory_id": f"epi_{event_id}",
        "timestamp": now_iso(),
        "source_event_id": event_id,
        "content": event.get("summary", ""),
        "event_type": event.get("event_type"),
        "importance": event.get("importance", 0),
        "verified": bool(event.get("verified", False)),
        "evidence": event.get("raw_observation", {}),
    }


def compact_event_log(
    *,
    max_events: int,
    keep_recent_events: int,
    min_importance: float,
) -> dict[str, Any]:
    event_log = ROOT / "data" / "event_log.jsonl"
    archive = ROOT / "data" / "event_archive.jsonl"
    events = read_jsonl_all(event_log)
    if len(events) <= max_events:
        return {"compacted": False, "events_before": len(events), "events_after": len(events), "archived": 0}

    ordered = sorted(events, key=event_sort_key)
    recent = ordered[-keep_recent_events:]
    recent_ids = {event.get("event_id") for event in recent}
    keep = []
    archive_rows = []
    for event in ordered:
        if event.get("event_id") in recent_ids:
            keep.append(event)
            continue
        if float(event.get("importance", 0)) >= min_importance or not event.get("verified", True):
            keep.append(event)
        else:
            archive_rows.append(event)
    append_unique_jsonl(archive, "event_id", archive_rows)
    write_jsonl(event_log, sorted(keep, key=event_sort_key))
    return {
        "compacted": True,
        "events_before": len(events),
        "events_after": len(keep),
        "archived": len(archive_rows),
    }


def run_consolidation(limit: int = 200) -> dict[str, Any]:
    events = read_jsonl_tail(ROOT / "data" / "event_log.jsonl", limit)
    counter = Counter(event.get("event_type", "unknown") for event in events)
    failures = [event for event in events if not event.get("verified", True) or "fail" in event.get("event_type", "")]
    important_events = [
        event
        for event in events
        if float(event.get("importance", 0)) >= 0.65 and event.get("event_id")
    ]
    episodic_rows = [event_to_episodic(event) for event in important_events]
    episodic_written = append_unique_jsonl(ROOT / "data" / "episodic_memory.jsonl", "source_event_id", episodic_rows)
    report = ROOT / "reports" / "daily_summary.md"
    lines = [
        "# Local Mind Daily Summary",
        "",
        f"- Generated at: {now_iso()}",
        f"- Events scanned: {len(events)}",
        f"- Episodic memories written: {episodic_written}",
        "",
        "## Event Types",
        "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in sorted(counter.items()))
    lines.extend(["", "## Recent Failures", ""])
    if failures:
        lines.extend(f"- {event.get('timestamp')}: {event.get('summary')}" for event in failures[-20:])
    else:
        lines.append("- None recorded.")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    patterns = read_json(ROOT / "data" / "failure_patterns.json", {"patterns": []})
    if len(failures) >= 3:
        patterns.setdefault("patterns", []).append(
            {
                "pattern_id": f"failure_pattern_{len(patterns.get('patterns', [])) + 1:03d}",
                "detected_at": now_iso(),
                "summary": "Three or more failed or unverified events appeared in the consolidation window.",
                "source_event_ids": [event.get("event_id") for event in failures[-10:]],
            }
        )
        write_json(ROOT / "data" / "failure_patterns.json", patterns)
    import yaml

    with (ROOT / "config" / "local_mind.yaml").open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    memory_config = config.get("memory", {})
    compaction = compact_event_log(
        max_events=int(memory_config.get("event_retention_max_events", 5000)),
        keep_recent_events=int(memory_config.get("event_retention_keep_recent_events", 500)),
        min_importance=float(memory_config.get("event_retention_min_importance", 0.65)),
    )
    return {
        "status": "success",
        "report": str(report),
        "events_scanned": len(events),
        "episodic_written": episodic_written,
        "compaction": compaction,
    }


if __name__ == "__main__":
    print(run_consolidation())
