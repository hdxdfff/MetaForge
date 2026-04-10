from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "context_cache.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _digest(*parts: str) -> str:
    raw = "||".join((part or "").strip().lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_context_cache_key(
    *,
    prompt: str,
    goal: str | None,
    repo_path: str | None,
    max_modules: int,
    budget_chars: int,
    strategy_revision: int | None = None,
    memory_revision: str | None = None,
) -> str:
    return _digest(
        prompt,
        goal or "",
        repo_path or "",
        str(max_modules),
        str(budget_chars),
        str(strategy_revision or 0),
        memory_revision or "",
    )


def load_cache() -> dict[str, Any]:
    return _load_json(CACHE, {"updated_at": None, "entries": {}})


def _current_memory_revision() -> str:
    parts: list[str] = []
    for path in [
        ROOT / "tools" / "context_builder.py",
        ROOT / "tools" / "memory_objects.py",
        DATA / "memory_objects.jsonl",
        DATA / "memory_candidates.jsonl",
    ]:
        if not path.exists():
            parts.append(f"{path.name}:missing")
            continue
        stat = path.stat()
        parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
    return "|".join(parts)


def get_cached_context(
    *,
    prompt: str,
    goal: str | None,
    repo_path: str | None,
    max_modules: int,
    budget_chars: int,
    strategy_revision: int | None = None,
    memory_revision: str | None = None,
) -> dict[str, Any] | None:
    payload = load_cache()
    entries = payload.get("entries") or {}
    key = build_context_cache_key(
        prompt=prompt,
        goal=goal,
        repo_path=repo_path,
        max_modules=max_modules,
        budget_chars=budget_chars,
        strategy_revision=strategy_revision,
        memory_revision=memory_revision,
    )
    entry = entries.get(key)
    if not isinstance(entry, dict):
        return None
    return entry.get("context_package")


def put_cached_context(
    *,
    prompt: str,
    goal: str | None,
    repo_path: str | None,
    max_modules: int,
    budget_chars: int,
    context_package: dict[str, Any],
    strategy_revision: int | None = None,
    memory_revision: str | None = None,
) -> dict[str, Any]:
    payload = load_cache()
    entries = payload.setdefault("entries", {})
    key = build_context_cache_key(
        prompt=prompt,
        goal=goal,
        repo_path=repo_path,
        max_modules=max_modules,
        budget_chars=budget_chars,
        strategy_revision=strategy_revision,
        memory_revision=memory_revision,
    )
    entries[key] = {
        "updated_at": _utc(),
        "prompt": prompt,
        "goal": goal,
        "repo_path": repo_path,
        "max_modules": max_modules,
        "budget_chars": budget_chars,
        "strategy_revision": strategy_revision or 0,
        "memory_revision": memory_revision or "",
        "context_package": context_package,
    }
    payload["updated_at"] = _utc()
    _save_json(CACHE, payload)
    return entries[key]


def summarize_cache(*, limit: int = 10) -> dict[str, Any]:
    payload = load_cache()
    entries = payload.get("entries") or {}
    ordered = sorted(
        (
            {"key": key, **(value or {})}
            for key, value in entries.items()
            if isinstance(value, dict)
        ),
        key=lambda item: item.get("updated_at") or "",
        reverse=True,
    )
    recent_entries = []
    for item in ordered[: max(0, limit)]:
        context_package = item.get("context_package") or {}
        recent_entries.append(
            {
                "key": item.get("key"),
                "updated_at": item.get("updated_at"),
                "repo_path": item.get("repo_path"),
                "goal": item.get("goal"),
                "prompt": item.get("prompt"),
                "max_modules": item.get("max_modules"),
                "budget_chars": item.get("budget_chars"),
                "strategy_revision": item.get("strategy_revision", 0),
                "module_focus": context_package.get("module_focus", []),
                "owner_teams": context_package.get("owner_teams", []),
                "layers": context_package.get("layers", []),
            }
        )
    return {
        "updated_at": payload.get("updated_at"),
        "entry_count": len(entries),
        "recent_entries": recent_entries,
    }


def purge_stale_cache_entries(*, memory_revision: str | None = None) -> dict[str, Any]:
    payload = load_cache()
    entries = payload.get("entries") or {}
    current_revision = memory_revision or _current_memory_revision()
    kept: dict[str, Any] = {}
    removed = 0
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            removed += 1
            continue
        entry_revision = str(entry.get("memory_revision") or "")
        if entry_revision != current_revision:
            removed += 1
            continue
        kept[key] = entry
    payload["entries"] = kept
    payload["updated_at"] = _utc()
    _save_json(CACHE, payload)
    return {
        "status": "purged",
        "memory_revision": current_revision,
        "removed": removed,
        "kept": len(kept),
        "cache_path": str(CACHE),
    }
