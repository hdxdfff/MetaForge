from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


def atomic_write_text(path: Path, content: str, *, encoding: str = 'utf-8') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f'{path.name}.{uuid4().hex}.tmp')
    last_error: OSError | None = None
    try:
        tmp_path.write_text(content, encoding=encoding)
        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError as exc:
                last_error = exc
                time.sleep(0.1 * (attempt + 1))
        path.write_text(content, encoding=encoding)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
    if last_error is not None:
        return


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')



