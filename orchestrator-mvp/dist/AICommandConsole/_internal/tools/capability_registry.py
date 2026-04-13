from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.capability_library import list_local_capabilities, match_local_capability
from tools.platform_registry import list_platforms, normalize_workspace_path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
REGISTRY = FACTORY / "capability_registry.json"
GRAPH = FACTORY / "capability_graph.json"
DISTILLATION = DATA / "capability_distillation.json"
REPUTATION = DATA / "capability_reputation.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def load_registry() -> dict[str, Any]:
    registry = _load_json(REGISTRY, {"updated_at": None, "capabilities": []})
    workspace_by_platform = {item.get('platform_id'): item.get('workspace') for item in list_platforms()}
    changed = False
    for item in registry.get("capabilities", []):
        preferred = workspace_by_platform.get(item.get('provider_platform_id')) or item.get('workspace')
        normalized = normalize_workspace_path(preferred)
        if normalized != item.get('workspace'):
            item['workspace'] = normalized
            changed = True
    if changed:
        save_registry(registry)
    return registry


def save_registry(registry: dict[str, Any]) -> None:
    registry["updated_at"] = _utc()
    _save_json(REGISTRY, registry)


def register_capabilities(platform: dict[str, Any], capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = load_registry()
    current = registry.get("capabilities", [])
    for cap in capabilities:
        cap['workspace'] = normalize_workspace_path(platform.get('workspace'))
        current = [item for item in current if not (item.get("capability_id") == cap.get("capability_id") and item.get("provider_platform_id") == cap.get("provider_platform_id"))]
        current.append(cap)
    registry["capabilities"] = sorted(current, key=lambda item: (item.get("capability_id") or "", item.get("provider_platform_id") or ""))
    save_registry(registry)
    rebuild_graph()
    return capabilities


def list_capabilities() -> list[dict[str, Any]]:
    registered = load_registry().get("capabilities", [])
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in list_local_capabilities() + registered:
        key = (str(item.get("capability_id") or ""), str(item.get("provider_platform_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def route_capability(request: str) -> dict[str, Any]:
    local_match = match_local_capability(request)
    request_lower = (request or "").lower()
    distillation = _load_json(DISTILLATION, {})
    reputation = _load_json(REPUTATION, {})
    global_policy = _load_json(GLOBAL_POLICY, {})
    distillation_hints = {
        (item.get("capability_id"), item.get("provider_platform_id")): float(item.get("boost", 0.0) or 0.0)
        for item in distillation.get("capability_hints", [])
    }
    capability_reputation = {
        str(key or "").strip(): float((value or {}).get("score", 0.0) or 0.0)
        for key, value in (reputation.get("capabilities", {}) or {}).items()
        if str(key or "").strip()
    }
    focus_capabilities = {str(item).strip(): 0.05 for item in global_policy.get("focus_capabilities", []) if item}
    matches = []
    for item in list_capabilities():
        keywords = item.get("keywords", [])
        keyword_hits = 0
        for token in keywords:
            token_text = str(token or '').strip().lower()
            if not token_text:
                continue
            if re.search(rf'(?<![a-z0-9]){re.escape(token_text)}(?![a-z0-9])', request_lower):
                keyword_hits += 1
        capability_id = str(item.get("capability_id") or "")
        hint_boost = distillation_hints.get((item.get("capability_id"), item.get("provider_platform_id")), 0.0)
        if keyword_hits <= 0 and hint_boost <= 0.0:
            continue
        score = float(keyword_hits)
        score += hint_boost
        score += capability_reputation.get(capability_id, 0.0)
        score += focus_capabilities.get(capability_id, 0.0)
        if score:
            match = dict(item)
            match["keyword_hits"] = keyword_hits
            match["score"] = round(float(score), 4)
            matches.append(match)
    if not matches:
        if local_match.get("selected"):
            return local_match
        return {"request": request, "selected": None, "matches": []}
    matches.sort(key=lambda item: (item.get("score", 0), item.get("version", 0)), reverse=True)
    top_registered = matches[0]
    local_selected = local_match.get("selected")
    if local_selected and float(local_selected.get("score", 0.0) or 0.0) >= float(top_registered.get("score", 0.0) or 0.0):
        combined = list(local_match.get("matches", []))
        combined.extend(matches[:10])
        return {"request": request, "selected": local_selected, "matches": combined[:10]}
    combined = matches[:10]
    if local_selected:
        combined.append(local_selected)
    return {"request": request, "selected": top_registered, "matches": combined[:10]}


def rebuild_graph() -> dict[str, Any]:
    nodes = []
    edges = []
    seen_nodes = set()
    for item in list_capabilities():
        platform_id = item.get("provider_platform_id")
        capability_id = item.get("capability_id")
        if platform_id and platform_id not in seen_nodes:
            nodes.append({"id": platform_id, "type": "platform", "label": item.get("provider_name") or platform_id})
            seen_nodes.add(platform_id)
        if capability_id and capability_id not in seen_nodes:
            nodes.append({"id": capability_id, "type": "capability", "label": capability_id})
            seen_nodes.add(capability_id)
        if platform_id and capability_id:
            edges.append({"from": platform_id, "to": capability_id, "type": "provides"})
    payload = {"updated_at": _utc(), "nodes": nodes, "edges": edges}
    _save_json(GRAPH, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(load_registry(), ensure_ascii=False, indent=2))
