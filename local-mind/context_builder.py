from __future__ import annotations

import json
from typing import Any

from json_store import read_json
from local_mind_paths import ROOT


OUTPUT_CONTRACT = {
    "state_understanding": "string",
    "memory_used": ["memory_id"],
    "proposed_actions": [
        {
            "type": "read_file | write_file | run_command | create_task | summarize | ask_user",
            "target": "string",
            "args": {},
            "risk_level": "low | medium | high",
            "reason": "string",
            "success_criteria": ["string"],
        }
    ],
    "should_escalate_to_cloud_model": False,
    "memory_write_candidates": [],
    "stop_reason": "string",
}


def build_context_packet(
    task: dict[str, Any],
    state: dict[str, Any],
    recent_events: list[dict[str, Any]],
    memories: list[dict[str, Any]],
) -> str:
    identity = read_json(ROOT / "config" / "identity.json", {})
    policy = read_json(ROOT / "config" / "policy.json", {})
    goals = read_json(ROOT / "data" / "goals.json", {})
    procedural = [memory for memory in memories if memory.get("type") == "procedural"]
    relevant = [memory for memory in memories if memory.get("type") != "procedural"]
    sections = [
        ("IDENTITY", identity),
        ("CURRENT GOALS", goals),
        ("CURRENT STATE", state),
        ("CURRENT TASK", task),
        ("RECENT EVENTS", recent_events),
        ("RELEVANT MEMORIES", relevant),
        ("PROCEDURAL MEMORY", procedural),
        ("POLICY", policy),
        ("OUTPUT CONTRACT", OUTPUT_CONTRACT),
    ]
    return "\n\n".join(f"[{name}]\n{json.dumps(payload, ensure_ascii=False, indent=2)}" for name, payload in sections)
