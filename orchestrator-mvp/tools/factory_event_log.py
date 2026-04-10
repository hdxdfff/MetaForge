from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EVENT_LOG_PATH = DATA / "factory_events.jsonl"
EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024
EVENT_LOG_ARCHIVE_COUNT = 4
EVENT_LOG_TAIL_LIMIT = 5000


def _event_log_archive_path(index: int) -> Path:
    return EVENT_LOG_PATH.with_name(f"{EVENT_LOG_PATH.name}.{index}")


def _event_log_paths(*, include_archives: bool) -> list[Path]:
    if not include_archives:
        return [EVENT_LOG_PATH]
    paths = [_event_log_archive_path(index) for index in range(EVENT_LOG_ARCHIVE_COUNT, 0, -1)]
    paths.append(EVENT_LOG_PATH)
    return paths


def _tail_lines(path: Path, limit: int) -> list[str]:
    limit = max(1, min(limit, EVENT_LOG_TAIL_LIMIT))
    if not path.exists():
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            if size <= 0:
                return []
            block_size = 8192
            buffer = bytearray()
            lines: deque[str] = deque()
            pos = size
            while pos > 0 and len(lines) < limit:
                read_size = min(block_size, pos)
                pos -= read_size
                handle.seek(pos)
                chunk = handle.read(read_size)
                if not chunk:
                    break
                buffer[:0] = chunk
                while True:
                    newline_index = buffer.rfind(b"\n")
                    if newline_index < 0:
                        break
                    line = bytes(buffer[newline_index + 1 :])
                    del buffer[newline_index:]
                    if line:
                        lines.appendleft(line.decode("utf-8", errors="ignore"))
                    else:
                        lines.appendleft("")
                    if len(lines) >= limit:
                        break
            if buffer and len(lines) < limit:
                lines.appendleft(bytes(buffer).decode("utf-8", errors="ignore"))
            return list(lines)[-limit:]
    except OSError:
        return []


def rotate_event_log() -> None:
    if not EVENT_LOG_PATH.exists():
        return
    try:
        if EVENT_LOG_PATH.stat().st_size < EVENT_LOG_MAX_BYTES:
            return
    except OSError:
        return

    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    oldest = _event_log_archive_path(EVENT_LOG_ARCHIVE_COUNT)
    if oldest.exists():
        oldest.unlink()
    for index in range(EVENT_LOG_ARCHIVE_COUNT - 1, 0, -1):
        src = _event_log_archive_path(index)
        if not src.exists():
            continue
        dst = _event_log_archive_path(index + 1)
        if dst.exists():
            dst.unlink()
        src.replace(dst)
    first_archive = _event_log_archive_path(1)
    if first_archive.exists():
        first_archive.unlink()
    EVENT_LOG_PATH.replace(first_archive)


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
    rotate_event_log()
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def read_events(limit: int | None = None, *, include_archives: bool = False) -> list[dict[str, Any]]:
    paths = [path for path in _event_log_paths(include_archives=include_archives) if path.exists()]
    if not paths:
        return []

    events: list[dict[str, Any]] = []
    if limit is None:
        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        continue
        return events

    tail = deque(maxlen=max(1, min(limit, EVENT_LOG_TAIL_LIMIT)))
    for path in paths:
        for line in _tail_lines(path, tail.maxlen):
            tail.append(line)
    for line in tail:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def read_event_history(limit: int | None = None) -> list[dict[str, Any]]:
    return read_events(limit=limit, include_archives=True)
