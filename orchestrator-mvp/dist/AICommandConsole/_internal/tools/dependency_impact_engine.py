from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.code_knowledge_graph import build_code_knowledge_graph, query_code_knowledge_graph

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "dependency_impact.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _reverse_neighbors(edges: list[dict[str, Any]]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for edge in edges:
        source = edge.get("from")
        target = edge.get("to")
        if not source or not target:
            continue
        mapping.setdefault(target, set()).add(source)
        mapping.setdefault(source, set())
    return mapping


def analyze_dependency_impact(request: str, *, limit: int = 8, max_depth: int = 2) -> dict[str, Any]:
    graph = build_code_knowledge_graph()
    focus = query_code_knowledge_graph(request, limit=limit)
    focus_modules = focus.get("module_focus", [])
    module_index = {item.get("module"): item for item in graph.get("modules", []) if item.get("module")}
    reverse = _reverse_neighbors(graph.get("edges", []))

    impacted: dict[str, int] = {}
    queue = deque((module, 0) for module in focus_modules)
    while queue:
        module, depth = queue.popleft()
        if module in impacted and impacted[module] <= depth:
            continue
        impacted[module] = depth
        if depth >= max_depth:
            continue
        for dependent in reverse.get(module, set()):
            queue.append((dependent, depth + 1))

    impacted_modules = []
    affected_teams = set()
    affected_layers = set()
    verification_scope = []
    for module_name, depth in sorted(impacted.items(), key=lambda item: (item[1], item[0])):
        info = module_index.get(module_name, {})
        team = info.get("owner_team")
        layer = info.get("layer")
        if team:
            affected_teams.add(team)
        if layer:
            affected_layers.add(layer)
        if layer in {"verification", "architecture_engine"} or info.get("dependents", 0) > 0:
            verification_scope.append(module_name)
        impacted_modules.append({
            "module": module_name,
            "depth": depth,
            "owner_team": team,
            "layer": layer,
            "dependents": info.get("dependents", 0),
        })

    payload = {
        "updated_at": _utc(),
        "request": request,
        "focus_modules": focus_modules,
        "impacted_modules": impacted_modules,
        "affected_teams": sorted(affected_teams),
        "affected_layers": sorted(affected_layers),
        "verification_scope": sorted(set(verification_scope)),
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(analyze_dependency_impact("strengthen agent orchestration capability"), ensure_ascii=False, indent=2))
