from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SKILLS = DATA / "skill_library.json"
REPLAY = DATA / "task_replay.json"
FAILURES = DATA / "failure_patterns.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _keywords(*parts: str) -> list[str]:
    text = " ".join(part for part in parts if part).lower()
    tokens = re.findall(r"[a-zA-Z_]{4,}|[一-鿿]{2,}", text)
    seen = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:10]


def distill_task(task: dict[str, Any]) -> dict[str, Any]:
    skills_doc = _load(SKILLS, {"updated_at": _utc(), "skills": []})
    replay_doc = _load(REPLAY, [])
    failures_doc = _load(FAILURES, [])
    status = task.get("status")
    task_id = task.get("id")
    goal = task.get("goal") or task.get("prompt") or ""
    summary = ((task.get("result") or {}).get("summary") or "").strip()
    error = ((task.get("result") or {}).get("error") or "").strip()
    cheap_calls = ((task.get("result") or {}).get("cheap_calls_used") or 0)
    route = "cheap-distilled" if cheap_calls else "local-distilled"
    created = {"skill": None, "replay": None, "failure": None}

    if status == "completed":
        pattern = goal[:180] or f"task-{task_id}"
        skill_id = f"task_{task_id[-8:]}"
        if not any(item.get("skill_id") == skill_id or item.get("pattern") == pattern for item in skills_doc.get("skills", [])):
            skill = {
                "skill_id": skill_id,
                "category": route,
                "pattern": pattern,
                "solution": summary or "Reuse the same cheap-first validation and execution path.",
                "keywords": _keywords(goal, summary),
                "derived_from_task": task_id,
                "created_at": _utc(),
            }
            skills_doc.setdefault("skills", []).append(skill)
            skills_doc["updated_at"] = _utc()
            created["skill"] = skill_id
        if not any(item.get("task_id") == task_id for item in replay_doc):
            replay = {
                "task_id": task_id,
                "skill_id": skill_id,
                "goal": goal,
                "replay_status": "ready",
                "captured_at": _utc(),
            }
            replay_doc.append(replay)
            created["replay"] = task_id
    elif status in {"failed", "waiting_approval"} and error:
        failure_id = f"failure_{task_id[-8:]}"
        if not any(item.get("failure_id") == failure_id for item in failures_doc):
            failure = {
                "failure_id": failure_id,
                "task_id": task_id,
                "pattern": goal[:180] or f"task-{task_id}",
                "error": error[:500],
                "keywords": _keywords(goal, error),
                "recorded_at": _utc(),
            }
            failures_doc.append(failure)
            created["failure"] = failure_id

    _save(SKILLS, skills_doc)
    _save(REPLAY, replay_doc)
    _save(FAILURES, failures_doc)
    return created
