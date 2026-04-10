from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load_json(name: str, default):
    path = DATA / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_state() -> dict:
    return {
        "context_kernel": load_json("context_kernel.json", {}),
        "hot_context": load_json("hot_context.json", {}),
        "memory_kernel": load_json("memory_kernel.json", {}),
        "brain_loop_state": load_json("brain_loop_state.json", {}),
        "tasks": load_json("tasks.json", []),
    }
