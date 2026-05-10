from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return default
    last_error: Exception | None = None
    for _ in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.05)
    raise last_error or ValueError(f"Unable to read JSON from {path}")


@contextmanager
def file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    for _ in range(200):
        try:
            handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(handle, str(os.getpid()).encode("ascii", errors="ignore"))
            break
        except FileExistsError:
            time.sleep(0.05)
    if handle is None:
        raise TimeoutError(f"Timed out waiting for lock: {lock_path}")
    try:
        yield
    finally:
        os.close(handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with file_lock(path):
        write_json_unlocked(path, payload)


def write_json_unlocked(path: Path, payload: str) -> None:
    tmp_path = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)


def update_json(path: Path, default: Any, updater) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        if not path.exists() or path.stat().st_size == 0:
            data = default
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        result = updater(data)
        payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        write_json_unlocked(path, payload)
        return result


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"event_type": "malformed_jsonl", "raw": line})
    return rows[-limit:]
