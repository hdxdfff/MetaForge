from __future__ import annotations

from typing import Any


def should_use_think(task: dict[str, Any]) -> bool:
    title = task.get("title", "").lower()
    risk = task.get("risk_level", "low")
    if risk == "high":
        return True
    triggers = ["failure", "architecture", "code", "conflict", "analysis"]
    return any(trigger in title for trigger in triggers)


def should_escalate(task: dict[str, Any], proposal: dict[str, Any]) -> bool:
    if task.get("risk_level") == "high":
        return True
    if proposal.get("should_escalate_to_cloud_model"):
        return True
    return any(action.get("risk_level") == "high" for action in proposal.get("proposed_actions", []))
