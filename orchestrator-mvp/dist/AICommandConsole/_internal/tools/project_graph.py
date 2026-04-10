from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PROJECTS = DATA / "projects.json"
KERNELS = DATA / "project_context_kernels.json"
PLATFORMS = ROOT / "factory" / "platform_registry.json"
OUT = DATA / "project_graph.json"

DOMAIN_KEYWORDS = {
    "kernel": {"kernel", "qemu", "syscall", "scheduler", "filesystem"},
    "network": {"network", "http", "protocol", "packet", "wireshark"},
    "database": {"database", "sql", "opengauss", "schema", "query"},
    "frontend": {"frontend", "html", "css", "javascript", "webapp"},
    "math": {"math", "optimization", "matrix", "analysis"},
    "factory": {"agent", "runtime", "platform", "factory", "orchestration", "deploy"},
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _infer_domains(texts: list[str]) -> list[str]:
    joined = " ".join(texts).lower()
    matched = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in joined for keyword in keywords):
            matched.append(domain)
    return matched or ["general"]


def analyze_project_impact(request: str, *, focus_modules: list[str] | None = None) -> dict[str, Any]:
    graph = build_project_graph()
    focus_modules = focus_modules or []
    query_domains = _infer_domains([request] + focus_modules)
    related_nodes = []
    related_ids = set()
    for node in graph.get("nodes", []):
        overlap = sorted(set(node.get("domains", [])) & set(query_domains))
        if not overlap:
            continue
        related_nodes.append({
            "project_id": node.get("project_id"),
            "name": node.get("name"),
            "type": node.get("type"),
            "repo_path": node.get("repo_path"),
            "domains": overlap,
        })
        if node.get("project_id"):
            related_ids.add(node.get("project_id"))
    cross_edges = [
        edge for edge in graph.get("edges", [])
        if edge.get("from") in related_ids and edge.get("to") in related_ids
    ]
    return {
        "updated_at": _utc(),
        "request": request,
        "query_domains": query_domains,
        "related_projects": related_nodes,
        "cross_project_edges": cross_edges,
        "cross_project_count": len(related_nodes),
    }


def build_project_graph() -> dict[str, Any]:
    projects = _load_json(PROJECTS, [])
    kernels = {item.get("project_id"): item for item in _load_json(KERNELS, []) if item.get("project_id")}
    platforms = _load_json(PLATFORMS, {}).get("platforms", [])

    project_nodes = []
    for project in projects:
        project_id = project.get("id")
        kernel = kernels.get(project_id, {})
        texts = [
            project.get("name", ""),
            project.get("summary", ""),
            " ".join(project.get("project_goals", []) or []),
            " ".join(project.get("technical_constraints", []) or []),
            " ".join(project.get("architecture_decisions", []) or []),
            " ".join((kernel.get("kernel") or {}).get("project_goals", []) or []),
        ]
        project_nodes.append({
            "project_id": project_id,
            "name": project.get("name"),
            "repo_path": project.get("repo_path"),
            "domains": _infer_domains(texts),
            "type": "project",
        })

    platform_nodes = []
    for platform in platforms:
        texts = [
            platform.get("name", ""),
            platform.get("target", ""),
            " ".join(item.get("capability_id", "") for item in (platform.get("capabilities") or [])),
        ]
        platform_nodes.append({
            "project_id": platform.get("platform_id"),
            "name": platform.get("name"),
            "repo_path": platform.get("workspace"),
            "domains": _infer_domains(texts),
            "type": "platform",
        })

    all_nodes = project_nodes + platform_nodes
    edges = []
    for left in all_nodes:
        for right in all_nodes:
            if left["project_id"] == right["project_id"]:
                continue
            overlap = sorted(set(left.get("domains", [])) & set(right.get("domains", [])))
            if not overlap:
                continue
            edges.append({
                "from": left["project_id"],
                "to": right["project_id"],
                "kind": "domain-overlap",
                "domains": overlap,
            })

    payload = {
        "updated_at": _utc(),
        "project_count": len(project_nodes),
        "platform_count": len(platform_nodes),
        "nodes": all_nodes,
        "edges": edges,
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_project_graph(), ensure_ascii=False, indent=2))
