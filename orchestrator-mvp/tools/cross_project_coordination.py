from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROJECT_GRAPH = DATA / "project_graph.json"
ORGANIZATION = DATA / "organization_model.json"
OUT = DATA / "cross_project_coordination.json"


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


def run_cross_project_coordination(limit: int = 5) -> dict[str, Any]:
    graph = _load_json(PROJECT_GRAPH, {"nodes": [], "edges": []})
    organization = _load_json(ORGANIZATION, {"project_allocations": []})
    allocations = {item.get("project_id"): item for item in organization.get("project_allocations", []) if item.get("project_id")}
    nodes = {item.get("project_id"): item for item in graph.get("nodes", []) if item.get("project_id")}

    candidates: list[dict[str, Any]] = []
    for edge in graph.get("edges", []):
        left_id = edge.get("from")
        right_id = edge.get("to")
        if not left_id or not right_id or left_id >= right_id:
            continue
        left = nodes.get(left_id, {})
        right = nodes.get(right_id, {})
        left_alloc = allocations.get(left_id, {})
        right_alloc = allocations.get(right_id, {})
        shared_domains = edge.get("domains", [])
        shared_departments = sorted(({left_alloc.get("owner_department"), right_alloc.get("owner_department")} | set(left_alloc.get("support_departments", []) or []) | set(right_alloc.get("support_departments", []) or [])) - {None, ""})
        score = round(0.55 + min(0.25, len(shared_domains) * 0.08) + min(0.15, len(shared_departments) * 0.03), 4)
        work_packages = [
            {
                "project_id": left_id,
                "name": left.get("name"),
                "owner_department": left_alloc.get("owner_department"),
                "support_departments": left_alloc.get("support_departments", []),
                "action": f"Align interfaces, tests, and rollout notes for {left.get('name', left_id)}",
            },
            {
                "project_id": right_id,
                "name": right.get("name"),
                "owner_department": right_alloc.get("owner_department"),
                "support_departments": right_alloc.get("support_departments", []),
                "action": f"Align interfaces, tests, and rollout notes for {right.get('name', right_id)}",
            },
        ]
        candidates.append({
            "coordination_id": f"{left_id}__{right_id}",
            "target": f"Coordinate {left.get('name', left_id)} with {right.get('name', right_id)}",
            "projects": [
                {"project_id": left_id, "name": left.get("name"), "type": left.get("type")},
                {"project_id": right_id, "name": right.get("name"), "type": right.get("type")},
            ],
            "domains": shared_domains,
            "departments": shared_departments,
            "work_packages": work_packages,
            "score": score,
            "notes": f"Cross-project coordination candidate based on shared domains: {', '.join(shared_domains) or 'general'}.",
        })

    candidates.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    payload = {
        "updated_at": _utc(),
        "candidate_count": len(candidates),
        "selected": candidates[:limit],
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_cross_project_coordination(), ensure_ascii=False, indent=2))
