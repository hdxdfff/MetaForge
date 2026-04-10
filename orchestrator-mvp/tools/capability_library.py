from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAPABILITIES = ROOT / "capabilities"

LOCAL_PROVIDER_PLATFORM_ID = "local-capability-library"
LOCAL_PROVIDER_NAME = "MetaForge Capability Library"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _normalize_capability(payload: dict[str, Any], source_path: Path) -> dict[str, Any]:
    capability_id = str(payload.get("capability_id") or source_path.stem).strip()
    return {
        "capability_id": capability_id,
        "provider_platform_id": LOCAL_PROVIDER_PLATFORM_ID,
        "provider_name": LOCAL_PROVIDER_NAME,
        "workspace": str(ROOT),
        "registered_at": payload.get("registered_at"),
        "version": int(payload.get("version", 1) or 1),
        "entrypoint": str(source_path),
        "source": "local_capability_library",
        "domain": payload.get("domain", "general"),
        "summary": payload.get("summary", ""),
        "goal_types": list(payload.get("goal_types", [])),
        "keywords": list(payload.get("keywords", [])),
        "inputs": list(payload.get("inputs", [])),
        "steps": list(payload.get("steps", [])),
        "tools": list(payload.get("tools", [])),
        "success_conditions": list(payload.get("success_conditions", [])),
        "fallbacks": list(payload.get("fallbacks", [])),
        "reusable_for": list(payload.get("reusable_for", [])),
        "metadata": dict(payload.get("metadata", {})),
    }


def list_local_capabilities() -> list[dict[str, Any]]:
    if not CAPABILITIES.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(CAPABILITIES.glob("*.json")):
        try:
            items.append(_normalize_capability(_load_json(path), path))
        except Exception:
            continue
    return items


def match_local_capability(request: str, *, goal_type: str | None = None) -> dict[str, Any]:
    request_lower = str(request or "").strip().lower()
    goal_type = str(goal_type or "").strip().lower()
    matches: list[dict[str, Any]] = []
    for item in list_local_capabilities():
        capability_id = str(item.get("capability_id") or "")
        score = 0.0
        for token in item.get("keywords", []):
            token_text = str(token or "").strip().lower()
            if not token_text:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(token_text)}(?![a-z0-9])", request_lower):
                score += 1.0
        for token in item.get("reusable_for", []):
            token_text = str(token or "").strip().lower()
            if token_text and token_text in request_lower:
                score += 0.5
        if goal_type and goal_type in [str(value).strip().lower() for value in item.get("goal_types", [])]:
            score += 1.5
        if capability_id and capability_id in request_lower:
            score += 2.0
        if score <= 0:
            continue
        match = dict(item)
        match["score"] = round(score, 4)
        matches.append(match)
    matches.sort(key=lambda value: (float(value.get("score", 0.0) or 0.0), int(value.get("version", 0) or 0)), reverse=True)
    return {
        "request": request,
        "selected": matches[0] if matches else None,
        "matches": matches[:10],
        "source": "local_capability_library",
    }


def _infer_step_role(step_id: str, title: str) -> str:
    value = f"{step_id} {title}".lower()
    if any(token in value for token in ("design", "architecture", "contract")):
        return "architect"
    if any(token in value for token in ("verify", "test", "validation", "qa")):
        return "tester"
    if any(token in value for token in ("deploy", "release", "runtime", "ops")):
        return "ops"
    if any(token in value for token in ("plan", "triage", "analyze", "analysis")):
        return "product"
    return "coder"


def capability_nodes(capability: dict[str, Any], target: str) -> list[dict[str, Any]]:
    steps = capability.get("steps", []) or []
    nodes: list[dict[str, Any]] = []
    previous_id: str | None = None
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("id") or _slug(str(step.get("title") or f"step_{index}")) or f"step_{index}")
        title = str(step.get("title") or f"Step {index}")
        prompt = str(step.get("prompt") or f"Execute capability step '{title}' for: {target}")
        role = str(step.get("role") or _infer_step_role(step_id, title))
        dependencies = list(step.get("dependencies", []))
        if not dependencies and previous_id:
            dependencies = [previous_id]
        nodes.append(
            {
                "id": step_id,
                "title": f"{title} for {target}",
                "role": role,
                "prompt": prompt,
                "dependencies": dependencies,
                "status": "pending",
                "task_id": None,
                "kind": "capability-step",
                "capability_id": capability.get("capability_id"),
                "recommended_tools": list(step.get("tools", capability.get("tools", []))),
                "success_conditions": list(step.get("success_conditions", capability.get("success_conditions", []))),
            }
        )
        previous_id = step_id
    return nodes
