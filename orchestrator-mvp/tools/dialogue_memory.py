from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ROOT.parent
DATA = ROOT / "data"
KNOWLEDGE = WORKSPACE_ROOT / "knowledge" / "dialogue-memory"
SESSIONS = KNOWLEDGE / "sessions"
INDEX = KNOWLEDGE / "session_index.json"
SUMMARY = DATA / "dialogue_memory.json"
LOCAL_CODEX_HOME = Path.home() / ".codex"
LOCAL_HISTORY = LOCAL_CODEX_HOME / "history.jsonl"
LOCAL_LOGS = LOCAL_CODEX_HOME / "logs_1.sqlite"
MAX_RECENT_SESSIONS = 12
MAX_EXTERNAL_HISTORY_SESSIONS = 8
MAX_EXTERNAL_MESSAGES = 32


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_from_ts(value: Any) -> str:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return _utc()
    if ts > 1_000_000_000_000:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _latest_source_mtime() -> float:
    latest = 0.0
    sources = [INDEX, LOCAL_HISTORY, LOCAL_LOGS]
    if SESSIONS.exists():
        sources.extend(sorted(SESSIONS.glob("*.json")))
    for path in sources:
        try:
            if not path.exists():
                continue
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _summary_is_stale(payload: dict[str, Any]) -> bool:
    if not payload:
        return True
    if not SUMMARY.exists():
        return True
    try:
        summary_mtime = SUMMARY.stat().st_mtime
    except OSError:
        return True
    return _latest_source_mtime() > summary_mtime


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned or "dialogue"


def _trim(value: str | None, limit: int = 400) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _normalize_list(items: list[str] | None, limit: int = 12, item_limit: int = 240) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        text = _trim(raw, item_limit)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_message(item: dict[str, Any], *, default_role: str = "user") -> dict[str, Any] | None:
    role = _trim(item.get("role") or default_role, 32).lower() or default_role
    content = item.get("content")
    if isinstance(content, list):
        content = "\n".join(str(part) for part in content if str(part).strip())
    if content is None:
        content = item.get("text") or item.get("message") or item.get("body")
    text = _trim(str(content or ""), 4000)
    if not text:
        return None
    created_at = _trim(item.get("created_at") or item.get("timestamp") or item.get("at"), 64) or _utc()
    return {
        "role": role,
        "content": text,
        "created_at": created_at,
    }


def _read_transcript(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Transcript path not found: {path}")
    if file_path.suffix.lower() == ".jsonl":
        messages = []
        for raw in file_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line:
                continue
            item = _normalize_message(json.loads(line))
            if item is not None:
                messages.append(item)
        return messages

    payload = _load_json(file_path, None)
    if payload is None:
        text = _trim(file_path.read_text(encoding="utf-8-sig", errors="replace"), 4000)
        return [{"role": "user", "content": text, "created_at": _utc()}] if text else []

    if isinstance(payload, list):
        return [item for item in (_normalize_message(raw) for raw in payload if isinstance(raw, dict)) if item]

    if isinstance(payload, dict):
        if isinstance(payload.get("messages"), list):
            return [item for item in (_normalize_message(raw) for raw in payload.get("messages", []) if isinstance(raw, dict)) if item]
        item = _normalize_message(payload)
        return [item] if item else []

    return []


def _extract_dialogue_messages_from_blob(blob: str) -> list[dict[str, Any]]:
    if not blob:
        return []
    pattern = re.compile(r'"role":"(user|assistant)".*?"text":"((?:\\.|[^"\\])*)"', re.S)
    messages: list[dict[str, Any]] = []
    for match in pattern.finditer(blob):
        role = match.group(1)
        raw_text = match.group(2)
        try:
            text = json.loads(f'"{raw_text}"')
        except Exception:
            continue
        item = _normalize_message({"role": role, "content": text, "created_at": _utc()})
        if item is not None:
            messages.append(item)
    return messages


def _load_codex_history_sessions() -> list[dict[str, Any]]:
    if not LOCAL_HISTORY.exists():
        return []

    sessions: dict[str, dict[str, Any]] = {}
    for raw in LOCAL_HISTORY.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        session_id = _trim(item.get("session_id"), 120)
        text = _trim(item.get("text"), 4000)
        if not session_id or not text:
            continue

        timestamp = _utc_from_ts(item.get("ts"))
        session = sessions.setdefault(session_id, {
            "session_id": f"codex-history:{session_id}",
            "source": "codex-history",
            "title": text,
            "workspace": "",
            "summary": text,
            "topics": [],
            "constraints": [],
            "decisions": [],
            "tags": [],
            "artifacts": [],
            "messages": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        })
        message = _normalize_message({"role": "user", "content": text, "created_at": timestamp})
        if message is None:
            continue
        session["messages"].append(message)
        session["summary"] = text
        if not session.get("title"):
            session["title"] = text
        session["updated_at"] = timestamp

    ordered = sorted(
        sessions.values(),
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    return ordered[:MAX_EXTERNAL_HISTORY_SESSIONS]


def _load_codex_live_session() -> list[dict[str, Any]]:
    thread_id = _trim(os.environ.get("CODEX_THREAD_ID"), 120)
    if not thread_id or not LOCAL_LOGS.exists():
        return []

    try:
        con = sqlite3.connect(str(LOCAL_LOGS))
    except Exception:
        return []

    try:
        cur = con.cursor()
        rows = cur.execute(
            'select ts, feedback_log_body from logs where thread_id=? and feedback_log_body like ? order by ts desc limit ?',
            (thread_id, '%"input":[%', 5),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        con.close()

    if not rows:
        return []

    messages: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ts, body in reversed(rows):
        for item in _extract_dialogue_messages_from_blob(str(body or "")):
            key = (item.get("role", ""), item.get("content", ""))
            if key in seen:
                continue
            seen.add(key)
            messages.append(item)
            if len(messages) >= MAX_EXTERNAL_MESSAGES:
                break
        if len(messages) >= MAX_EXTERNAL_MESSAGES:
            break

    if not messages:
        return []

    user_messages = [item.get("content", "") for item in messages if item.get("role") == "user"]
    assistant_messages = [item.get("content", "") for item in messages if item.get("role") == "assistant"]
    summary = _trim(user_messages[-1] if user_messages else (assistant_messages[-1] if assistant_messages else ""), 1200)
    title = _trim(user_messages[0] if user_messages else thread_id, 160)
    created_at = _utc_from_ts(rows[-1][0])
    updated_at = _utc_from_ts(rows[0][0])
    return [{
        "session_id": f"codex-thread:{thread_id}",
        "source": "codex-live-log",
        "title": title,
        "workspace": str(WORKSPACE_ROOT),
        "summary": summary,
        "topics": [],
        "constraints": [],
        "decisions": [],
        "tags": [],
        "artifacts": [],
        "messages": messages,
        "created_at": created_at,
        "updated_at": updated_at,
    }]


def _session_path(session_id: str) -> Path:
    return SESSIONS / f"{_slug(session_id)}.json"


def _load_session(session_id: str) -> dict[str, Any]:
    path = _session_path(session_id)
    payload = _load_json(path, {})
    if not payload:
        return {
            "session_id": session_id,
            "source": "codex",
            "title": session_id,
            "workspace": "",
            "summary": "",
            "topics": [],
            "constraints": [],
            "decisions": [],
            "tags": [],
            "artifacts": [],
            "messages": [],
            "created_at": _utc(),
            "updated_at": _utc(),
        }
    return payload


def _save_session(session: dict[str, Any]) -> None:
    _save_json(_session_path(str(session.get("session_id") or "dialogue")), session)


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    messages = session.get("messages") or []
    last_user = next((item.get("content") for item in reversed(messages) if item.get("role") == "user"), "")
    last_assistant = next((item.get("content") for item in reversed(messages) if item.get("role") == "assistant"), "")
    return {
        "session_id": session.get("session_id"),
        "source": session.get("source"),
        "title": session.get("title"),
        "workspace": session.get("workspace"),
        "summary": _trim(session.get("summary"), 320),
        "topics": _normalize_list(session.get("topics"), limit=6),
        "constraints": _normalize_list(session.get("constraints"), limit=6),
        "decisions": _normalize_list(session.get("decisions"), limit=6),
        "tags": _normalize_list(session.get("tags"), limit=8),
        "artifacts": _normalize_list(session.get("artifacts"), limit=8, item_limit=400),
        "message_count": len(messages),
        "last_user_message": _trim(last_user, 240),
        "last_assistant_message": _trim(last_assistant, 240),
        "updated_at": session.get("updated_at"),
        "created_at": session.get("created_at"),
    }


def load_dialogue_memory(*, refresh: bool = False) -> dict[str, Any]:
    payload = _load_json(SUMMARY, {})
    if refresh or _summary_is_stale(payload):
        return rebuild_dialogue_memory()
    return payload


def rebuild_dialogue_memory() -> dict[str, Any]:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    session_map: dict[str, dict[str, Any]] = {}

    def remember(payload: dict[str, Any]) -> None:
        session_id = _trim(payload.get("session_id"), 120)
        if not session_id:
            return
        existing = session_map.get(session_id)
        if existing is None:
            session_map[session_id] = payload
            return
        existing_updated = str(existing.get("updated_at") or "")
        payload_updated = str(payload.get("updated_at") or "")
        existing_messages = len(existing.get("messages") or [])
        payload_messages = len(payload.get("messages") or [])
        if payload_updated > existing_updated or payload_messages > existing_messages:
            session_map[session_id] = payload

    for path in sorted(SESSIONS.glob("*.json")):
        payload = _load_json(path, {})
        if isinstance(payload, dict) and payload.get("session_id"):
            remember(payload)
    for payload in _load_codex_history_sessions():
        if isinstance(payload, dict) and payload.get("session_id"):
            _save_session(payload)
            remember(payload)
    for payload in _load_codex_live_session():
        if isinstance(payload, dict) and payload.get("session_id"):
            _save_session(payload)
            remember(payload)

    session_payloads = list(session_map.values())

    ordered = sorted(
        session_payloads,
        key=lambda item: item.get("updated_at") or item.get("created_at") or "",
        reverse=True,
    )
    recent_sessions = [_session_summary(item) for item in ordered[:MAX_RECENT_SESSIONS]]

    recent_topics = _normalize_list([topic for item in recent_sessions for topic in item.get("topics", [])], limit=12)
    recent_decisions = _normalize_list([decision for item in recent_sessions for decision in item.get("decisions", [])], limit=12)
    shared_constraints = _normalize_list([constraint for item in recent_sessions for constraint in item.get("constraints", [])], limit=12)
    workspace_refs = _normalize_list([item.get("workspace", "") for item in recent_sessions], limit=12, item_limit=400)
    artifact_paths = _normalize_list([artifact for item in recent_sessions for artifact in item.get("artifacts", [])], limit=16, item_limit=400)

    payload = {
        "updated_at": _utc(),
        "session_count": len(ordered),
        "message_count": sum(len(item.get("messages") or []) for item in ordered),
        "recent_sessions": recent_sessions,
        "recent_topics": recent_topics,
        "recent_decisions": recent_decisions,
        "shared_constraints": shared_constraints,
        "workspace_refs": workspace_refs,
        "artifact_paths": artifact_paths,
        "active_handoff": recent_sessions[0] if recent_sessions else {},
    }
    _save_json(INDEX, {
        "updated_at": payload.get("updated_at"),
        "session_count": payload.get("session_count"),
        "recent_sessions": recent_sessions,
    })
    _save_json(SUMMARY, payload)
    return payload


def sync_dialogue(
    *,
    session_id: str,
    source: str = "codex",
    title: str = "",
    workspace: str = "",
    summary: str = "",
    topics: list[str] | None = None,
    constraints: list[str] | None = None,
    decisions: list[str] | None = None,
    tags: list[str] | None = None,
    artifacts: list[str] | None = None,
    user_messages: list[str] | None = None,
    assistant_messages: list[str] | None = None,
    transcript_path: str | None = None,
) -> dict[str, Any]:
    if not _trim(session_id, 120):
        raise ValueError("session_id is required")

    now = _utc()
    session = _load_session(session_id)
    session["session_id"] = session_id
    session["source"] = _trim(source, 80) or session.get("source") or "codex"
    session["title"] = _trim(title, 160) or session.get("title") or session_id
    session["workspace"] = _trim(workspace, 400) or session.get("workspace") or ""
    if summary:
        session["summary"] = _trim(summary, 1200)
    session["topics"] = _normalize_list(list(session.get("topics", [])) + list(topics or []), limit=16)
    session["constraints"] = _normalize_list(list(session.get("constraints", [])) + list(constraints or []), limit=20)
    session["decisions"] = _normalize_list(list(session.get("decisions", [])) + list(decisions or []), limit=20)
    session["tags"] = _normalize_list(list(session.get("tags", [])) + list(tags or []), limit=20)
    session["artifacts"] = _normalize_list(list(session.get("artifacts", [])) + list(artifacts or []), limit=20, item_limit=400)
    session.setdefault("messages", [])
    session.setdefault("created_at", now)
    session["updated_at"] = now

    existing = {
        (item.get("role"), item.get("content"))
        for item in session.get("messages", [])
        if isinstance(item, dict)
    }

    for raw in _read_transcript(transcript_path):
        key = (raw.get("role"), raw.get("content"))
        if key in existing:
            continue
        session["messages"].append(raw)
        existing.add(key)

    for text in user_messages or []:
        item = _normalize_message({"role": "user", "content": text, "created_at": now})
        if item is None:
            continue
        key = (item.get("role"), item.get("content"))
        if key in existing:
            continue
        session["messages"].append(item)
        existing.add(key)

    for text in assistant_messages or []:
        item = _normalize_message({"role": "assistant", "content": text, "created_at": now})
        if item is None:
            continue
        key = (item.get("role"), item.get("content"))
        if key in existing:
            continue
        session["messages"].append(item)
        existing.add(key)

    _save_session(session)
    summary_payload = rebuild_dialogue_memory()
    return {
        "status": "ok",
        "updated_at": now,
        "session": _session_summary(session),
        "dialogue_memory": {
            "session_count": summary_payload.get("session_count", 0),
            "message_count": summary_payload.get("message_count", 0),
            "recent_topics": summary_payload.get("recent_topics", []),
        },
        "session_path": str(_session_path(session_id)),
        "summary_path": str(SUMMARY),
    }


def _repair_session_payload(session: dict[str, Any]) -> bool:
    changed = False
    session_id = str(session.get("session_id") or "")
    if session_id == "codex-shared-memory-20260314":
        replacements = {
            "summary": "Build a local dialogue memory bridge and connect Codex conversations to the shared MetaForge snapshot/context package.",
            "title": "Codex MetaForge shared memory rollout",
        }
        for key, value in replacements.items():
            if session.get(key) != value:
                session[key] = value
                changed = True
        messages = session.get("messages") or []
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            if role == "user":
                cleaned = "Build a local storage memory mechanism so Codex conversations can share state with the MetaForge system."
            elif role == "assistant":
                cleaned = "Use the existing memory/context framework to build a shared dialogue ledger and connect it into the MetaForge snapshot and context package."
            else:
                continue
            if item.get("content") != cleaned:
                item["content"] = cleaned
                changed = True
        if messages != session.get("messages"):
            session["messages"] = messages
            changed = True
    return changed


def repair_dialogue_memory() -> dict[str, Any]:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    repaired = 0
    for path in sorted(SESSIONS.glob("*.json")):
        payload = _load_json(path, {})
        if not isinstance(payload, dict) or not payload.get("session_id"):
            continue
        if _repair_session_payload(payload):
            _save_json(path, payload)
            repaired += 1
    summary_payload = rebuild_dialogue_memory()
    summary_payload["repaired_sessions"] = repaired
    _save_json(SUMMARY, summary_payload)
    return summary_payload


def dialogue_status(*, limit: int = 8, rebuild: bool = False) -> dict[str, Any]:
    payload = load_dialogue_memory(refresh=rebuild)
    if not payload:
        payload = rebuild_dialogue_memory()
    return {
        "updated_at": payload.get("updated_at"),
        "session_count": payload.get("session_count", 0),
        "message_count": payload.get("message_count", 0),
        "recent_topics": payload.get("recent_topics", []),
        "recent_decisions": payload.get("recent_decisions", []),
        "shared_constraints": payload.get("shared_constraints", []),
        "active_handoff": payload.get("active_handoff", {}),
        "recent_sessions": (payload.get("recent_sessions") or [])[: max(1, limit)],
        "summary_path": str(SUMMARY),
        "index_path": str(INDEX),
    }


if __name__ == "__main__":
    rendered = json.dumps(dialogue_status(rebuild=True), ensure_ascii=False, indent=2)
    try:
        print(rendered)
    except UnicodeEncodeError:
        print(rendered.encode("gbk", errors="replace").decode("gbk", errors="replace"))
