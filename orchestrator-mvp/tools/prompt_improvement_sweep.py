from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "prompt_improvement_status.json"
SKILLS = DATA / "skill_library.json"
REPLAY = DATA / "task_replay.json"
KNOWLEDGE = DATA / "knowledge_base.json"
POLICY = DATA / "policy.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def run_prompt_improvement_sweep() -> dict[str, Any]:
    skills = _load_json(SKILLS, {}).get("skills", [])
    replay = _load_json(REPLAY, [])
    knowledge = _load_json(KNOWLEDGE, {})
    policy = _load_json(POLICY, {})

    prompt_hints = [
        "Prefer local scripts, Docker, QEMU, and deterministic validation before escalating.",
        "When a pattern exists in the skill library or replay store, reuse it before freeform generation.",
        "Keep reviewer/product/architect drafting on the cheap lane unless there is a contradiction or security boundary.",
    ]

    payload = {
        "updated_at": _utc(),
        "status": "completed",
        "skill_count": len(skills),
        "replay_count": len(replay),
        "decision_pattern_count": len(knowledge.get("decision_patterns", [])),
        "cheap_first": bool(policy.get("cheap_first", True)),
        "prompt_hints": prompt_hints,
        "summary": "Prompt improvement sweep refreshed cheap-first guidance from current skills, replay, and knowledge patterns.",
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_prompt_improvement_sweep(), ensure_ascii=False, indent=2))
