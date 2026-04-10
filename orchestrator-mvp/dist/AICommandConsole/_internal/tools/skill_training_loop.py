from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
SKILL_LIBRARY = DATA / "skill_library.json"
TRAINING_TASKS = DATA / "training_tasks.json"
TASK_REPLAY = DATA / "task_replay.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _infer_pattern(task: dict[str, Any]) -> dict[str, Any] | None:
    goal = (task.get("goal") or task.get("prompt") or "").strip()
    result = task.get("result") or {}
    error = (result.get("error") or "").strip()
    status = task.get("status")
    if not goal:
        return None

    if status == "waiting_approval" and "manual" in error.lower():
        return {
            "skill_id": "manual_approval_gate_handling",
            "category": "debugging",
            "pattern": "Real execution blocked by manual approval mode",
            "solution": "Keep the task paused, emit an escalation, and avoid retrying until approval policy changes.",
            "keywords": ["manual", "approval", "auto-debug", "waiting_approval"],
        }

    if "timeout" in error.lower():
        return {
            "skill_id": "timeout_diagnosis",
            "category": "debugging",
            "pattern": "Request or task timeout",
            "solution": "Reduce scope, verify local runtime first, and replay with bounded validation before escalation.",
            "keywords": ["timeout", "retry", "bounded", "validation"],
        }

    if "invalid_api_key" in error.lower() or "incorrect api key" in error.lower():
        return {
            "skill_id": "invalid_api_key_triage",
            "category": "integration",
            "pattern": "Provider authentication failure",
            "solution": "Stop retries, mark the provider as misconfigured, and route to local or cheap fallback until credentials are fixed.",
            "keywords": ["api key", "401", "provider", "credentials"],
        }

    if status == "completed":
        return {
            "skill_id": f"completed_{abs(hash(goal)) % 10000}",
            "category": "task-playbook",
            "pattern": goal[:120],
            "solution": "Reuse the same local-first execution path and validation sequence for similar tasks.",
            "keywords": [token.lower() for token in goal.split()[:8]],
        }

    return None


def run_training() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    library = _load_json(SKILL_LIBRARY, {"updated_at": None, "skills": []})
    training = _load_json(TRAINING_TASKS, [])
    replay = _load_json(TASK_REPLAY, [])

    existing = {(item.get("skill_id"), item.get("pattern")) for item in library.get("skills", [])}
    added = []

    for task in tasks:
        pattern = _infer_pattern(task)
        if not pattern:
            continue
        key = (pattern.get("skill_id"), pattern.get("pattern"))
        if key in existing:
            continue
        skill = {
            **pattern,
            "derived_from_task": task.get("id"),
            "created_at": _utc(),
        }
        library.setdefault("skills", []).append(skill)
        training.append({
            "task_id": task.get("id"),
            "goal": task.get("goal"),
            "status": task.get("status"),
            "skill_id": skill.get("skill_id"),
            "captured_at": _utc(),
        })
        replay.append({
            "task_id": task.get("id"),
            "skill_id": skill.get("skill_id"),
            "replay_status": "ready",
            "captured_at": _utc(),
        })
        existing.add(key)
        added.append(skill)

    library["updated_at"] = _utc()
    _save_json(SKILL_LIBRARY, library)
    _save_json(TRAINING_TASKS, training[-200:])
    _save_json(TASK_REPLAY, replay[-200:])
    return {
        "updated_at": _utc(),
        "skills_added": len(added),
        "skill_count": len(library.get("skills", [])),
        "recent_skills": added[-8:],
    }


if __name__ == "__main__":
    print(json.dumps(run_training(), ensure_ascii=False, indent=2))
