from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


ATOMIC_REPLACE_RETRIES = 30
ATOMIC_REPLACE_BACKOFF_SECONDS = 0.1
ATOMIC_REPLACE_BACKOFF_CAP_SECONDS = 0.5
ATOMIC_LOCK_TIMEOUT_SECONDS = 20.0
ATOMIC_LOCK_POLL_SECONDS = 0.05
ATOMIC_LOCK_STALE_SECONDS = 60.0


def _cleanup_stale_lock(lock_path: Path) -> None:
    try:
        age_seconds = time.time() - lock_path.stat().st_mtime
    except OSError:
        return
    if age_seconds < ATOMIC_LOCK_STALE_SECONDS:
        return
    try:
        lock_path.unlink()
    except OSError:
        pass


def _acquire_atomic_lock(lock_path: Path) -> int:
    deadline = time.monotonic() + ATOMIC_LOCK_TIMEOUT_SECONDS
    payload = f"{os.getpid()} {time.time():.6f}\n".encode("utf-8", errors="replace")
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, payload)
            return fd
        except FileExistsError:
            _cleanup_stale_lock(lock_path)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for write lock: {lock_path}")
            time.sleep(ATOMIC_LOCK_POLL_SECONDS)


def _release_atomic_lock(lock_path: Path, lock_fd: int | None) -> None:
    if lock_fd is not None:
        try:
            os.close(lock_fd)
        except OSError:
            pass
    try:
        lock_path.unlink()
    except OSError:
        pass


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    lock_path = path.with_name(f"{path.name}.lock")
    lock_fd: int | None = None
    try:
        lock_fd = _acquire_atomic_lock(lock_path)
        tmp_path.write_text(content, encoding=encoding)
        last_error = None
        for attempt in range(ATOMIC_REPLACE_RETRIES):
            try:
                os.replace(tmp_path, path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt == ATOMIC_REPLACE_RETRIES - 1:
                    raise
                sleep_seconds = min(
                    ATOMIC_REPLACE_BACKOFF_SECONDS * (attempt + 1),
                    ATOMIC_REPLACE_BACKOFF_CAP_SECONDS,
                )
                time.sleep(sleep_seconds)
        if last_error is not None:
            raise last_error
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        _release_atomic_lock(lock_path, lock_fd)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
