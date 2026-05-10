from __future__ import annotations

from collections import Counter
from typing import Any

from json_store import read_json, read_jsonl_tail, write_json
from local_mind_paths import ROOT
from memory_manager import now_iso


def run_consolidation(limit: int = 200) -> dict[str, Any]:
    events = read_jsonl_tail(ROOT / "data" / "event_log.jsonl", limit)
    counter = Counter(event.get("event_type", "unknown") for event in events)
    failures = [event for event in events if not event.get("verified", True) or "fail" in event.get("event_type", "")]
    report = ROOT / "reports" / "daily_summary.md"
    lines = [
        "# Local Mind Daily Summary",
        "",
        f"- Generated at: {now_iso()}",
        f"- Events scanned: {len(events)}",
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
    return {"status": "success", "report": str(report), "events_scanned": len(events)}


if __name__ == "__main__":
    print(run_consolidation())
