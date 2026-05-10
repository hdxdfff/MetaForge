from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def resolve_local(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate
