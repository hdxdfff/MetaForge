from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.factory_event_log as factory_event_log


def _event_line(event_id: str, timestamp: str) -> str:
    return json.dumps(
        {
            "event_id": event_id,
            "timestamp": timestamp,
            "type": "daemon.tick",
            "source": "factory_daemon",
            "severity": "info",
            "summary": event_id,
            "payload": {},
            "refs": {},
        },
        ensure_ascii=False,
    )


def test_read_events_uses_tail_window_and_skips_invalid_lines(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "factory_events.jsonl"
    log_path.write_text(
        "\n".join(
            [
                _event_line("evt_1", "2026-04-05T15:20:01Z"),
                _event_line("evt_2", "2026-04-05T15:20:02Z"),
                "not-json",
                _event_line("evt_3", "2026-04-05T15:20:03Z"),
                _event_line("evt_4", "2026-04-05T15:20:04Z"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_PATH", log_path)

    events = factory_event_log.read_events(limit=3)

    assert [event["event_id"] for event in events] == ["evt_3", "evt_4"]


def test_append_event_round_trips(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "factory_events.jsonl"
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_PATH", log_path)

    factory_event_log.append_event("daemon.tick", source="factory_daemon", summary="tick=1")

    events = factory_event_log.read_events(limit=1)

    assert len(events) == 1
    assert events[0]["type"] == "daemon.tick"
    assert events[0]["summary"] == "tick=1"


def test_append_event_rotates_when_active_log_exceeds_budget(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "factory_events.jsonl"
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_PATH", log_path)
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_MAX_BYTES", 1)
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_ARCHIVE_COUNT", 2)

    log_path.write_text(_event_line("evt_old", "2026-04-05T15:20:01Z") + "\n", encoding="utf-8")

    factory_event_log.append_event("daemon.tick", source="factory_daemon", summary="tick=2")

    active_events = factory_event_log.read_events(limit=10)
    history_events = factory_event_log.read_events(limit=10, include_archives=True)

    assert active_events[-1]["summary"] == "tick=2"
    assert (tmp_path / "factory_events.jsonl.1").exists()
    assert [event["event_id"] for event in history_events][-2:] == ["evt_old", active_events[-1]["event_id"]]


def test_read_event_history_includes_archived_segments(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "factory_events.jsonl"
    archive_path = tmp_path / "factory_events.jsonl.1"
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_PATH", log_path)
    monkeypatch.setattr(factory_event_log, "EVENT_LOG_ARCHIVE_COUNT", 1)

    archive_path.write_text(_event_line("evt_archived", "2026-04-05T15:20:01Z") + "\n", encoding="utf-8")
    log_path.write_text(_event_line("evt_live", "2026-04-05T15:20:02Z") + "\n", encoding="utf-8")

    events = factory_event_log.read_event_history(limit=10)

    assert [event["event_id"] for event in events] == ["evt_archived", "evt_live"]
