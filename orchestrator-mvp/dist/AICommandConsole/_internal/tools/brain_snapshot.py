from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAIN = ROOT / "brain"
DATA = ROOT / "data"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_snapshot() -> dict:
    blueprint = _load_json(BRAIN / "system_blueprint.json", {})
    memory = _load_json(BRAIN / "memory.json", {})
    context_kernel = _load_json(DATA / "context_kernel.json", {})
    hot_context = _load_json(DATA / "hot_context.json", {})
    dialogue_memory = _load_json(DATA / "dialogue_memory.json", {})
    escalations = _load_json(DATA / "escalation_inbox.json", [])
    return {
        "blueprint": blueprint,
        "memory": memory,
        "context_kernel": context_kernel,
        "hot_context": hot_context,
        "dialogue_memory": dialogue_memory,
        "open_escalations": escalations,
        "summary": {
            "mode": blueprint.get("mode", "unknown"),
            "protocol": blueprint.get("protocol", "unknown"),
            "open_escalation_count": len(escalations),
            "active_task_count": hot_context.get("active_task_count", 0),
            "failed_task_count": hot_context.get("failed_task_count", 0),
            "dialogue_session_count": dialogue_memory.get("session_count", 0),
            "dialogue_message_count": dialogue_memory.get("message_count", 0),
        },
    }


if __name__ == "__main__":
    print(json.dumps(build_snapshot(), ensure_ascii=False, indent=2))
