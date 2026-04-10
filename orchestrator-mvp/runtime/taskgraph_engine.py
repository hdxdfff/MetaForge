from __future__ import annotations

import json
from pathlib import Path

from tools.taskgraph_compiler import compile_goal

ROOT = Path(__file__).resolve().parent.parent
GRAPHS = ROOT / "factory" / "graphs"


def graph_path(graph_id: str) -> Path:
    return GRAPHS / f"{graph_id}.json"


def load_graph(graph_id: str) -> dict:
    path = graph_path(graph_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ensure_graph(goal: dict) -> dict:
    graph_id = goal.get("graph_id")
    if graph_id:
        graph = load_graph(graph_id)
        if graph:
            return graph
    return compile_goal(goal)


def ready_nodes(graph: dict) -> list[dict]:
    completed = {node["id"] for node in graph.get("nodes", []) if node.get("status") == "completed"}
    nodes = []
    for node in graph.get("nodes", []):
        if node.get("status") != "pending":
            continue
        deps = set(node.get("dependencies") or [])
        if deps.issubset(completed):
            nodes.append(node)
    return nodes
