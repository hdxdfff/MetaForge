from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from tools.control_plane_policy import project_session_policy
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SESSION_FILE = DATA / "control_session.json"
SESSIONS_FILE = DATA / "control_sessions.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def policy() -> dict:
    return project_session_policy()


def current_session() -> dict:
    return _load_json(SESSION_FILE, {"active": False, "role": "observer", "owner": None, "token": None, "scope": "global"})


def _sessions_payload() -> dict:
    legacy = current_session()
    payload = _load_json(SESSIONS_FILE, {"active_token": None, "sessions": []})
    if payload.get("sessions"):
        return payload
    if legacy.get("active") and legacy.get("token"):
        session = {
            "active": True,
            "owner": legacy.get("owner"),
            "role": legacy.get("role", "observer"),
            "token": legacy.get("token"),
            "scope": legacy.get("scope", "global"),
            "opened_at": legacy.get("opened_at", _utc()),
            "updated_at": legacy.get("updated_at", _utc()),
        }
        payload = {"active_token": legacy.get("token"), "sessions": [session]}
        atomic_write_json(SESSIONS_FILE, payload)
        return payload
    return payload


def _write_sessions(payload: dict) -> None:
    atomic_write_json(SESSIONS_FILE, payload)


def list_sessions() -> list[dict]:
    return _sessions_payload().get("sessions", [])


def active_session() -> dict:
    payload = _sessions_payload()
    active_token = payload.get("active_token")
    if not active_token:
        return current_session()
    return next((item for item in payload.get("sessions", []) if item.get("token") == active_token), current_session())


def open_session(owner: str, role: str = "operator", scope: str = "global") -> dict:
    payload = _sessions_payload()
    cfg = policy()
    sessions = payload.get("sessions", [])
    if cfg.get("single_control_session", True) and any(item.get("active") for item in sessions):
        raise RuntimeError("A control session is already active.")
    token = secrets.token_hex(16)
    session = {
        "active": True,
        "owner": owner,
        "role": role,
        "token": token,
        "scope": scope,
        "opened_at": _utc(),
        "updated_at": _utc(),
    }
    sessions.append(session)
    next_payload = {
        "active_token": payload.get("active_token") or token,
        "sessions": sessions,
    }
    _write_sessions(next_payload)
    if next_payload.get("active_token") == token:
        atomic_write_json(SESSION_FILE, session)
    return session


def close_session(token: str) -> dict:
    payload = _sessions_payload()
    sessions = payload.get("sessions", [])
    current = next((item for item in sessions if item.get("token") == token and item.get("active")), None)
    if current is None:
        raise RuntimeError("Invalid control session token.")
    closed = {
        "active": False,
        "owner": current.get("owner"),
        "role": current.get("role"),
        "token": None,
        "scope": current.get("scope", "global"),
        "closed_at": _utc(),
        "updated_at": _utc(),
    }
    remaining = [item for item in sessions if item.get("token") != token]
    next_active = payload.get("active_token")
    if next_active == token:
        next_active = next((item.get("token") for item in remaining if item.get("active")), None)
    next_payload = {
        "active_token": next_active,
        "sessions": remaining,
    }
    _write_sessions(next_payload)
    latest = active_session()
    atomic_write_json(SESSION_FILE, latest if latest.get("active") else closed)
    return closed


def authorize(command: str, token: str | None) -> tuple[bool, str, dict]:
    cfg = policy()
    payload = _sessions_payload()
    sessions = payload.get("sessions", [])
    matched = next((item for item in sessions if token and item.get("active") and token == item.get("token")), None)
    if matched:
        role = matched.get("role", "observer")
    else:
        role = cfg.get("default_role_without_token", "observer")
    allowed = cfg.get("roles", {}).get(role, [])
    ok = "*" in allowed or command in allowed
    reason = "" if ok else f"Command {command} requires a higher-privilege control session."
    return ok, reason, {
        "role": role,
        "matched_session": matched,
        "active_session": active_session(),
        "session_count": len(sessions),
    }
