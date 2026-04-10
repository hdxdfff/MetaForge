from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))
OUT = DATA / "code_knowledge_graph.json"
BLUEPRINT = ROOT / "brain" / "system_blueprint.json"
BAD_PARSE_LOG = DATA / "bad_dynamic_code.log"
GRAPH_CACHE_MAX_AGE_SECONDS = 300

SCAN_ROOTS = [
    ROOT / "app",
    ROOT / "runtime",
    ROOT / "tools",
    ROOT / "agents",
    ROOT / "state",
]

LAYER_PREFIXES = {
    "meta_brain": ["brain."],
    "architecture_engine": [
        "tools.architecture_validator",
        "tools.code_knowledge_graph",
        "tools.taskgraph_compiler",
        "tools.meta_factory_control",
    ],
    "task_graph_planner": [
        "runtime.taskgraph_engine",
        "tools.goal_registry",
        "tools.decision_engine",
        "tools.experiment_planner",
    ],
    "agent_teams": ["agents.", "app.", "runtime.scheduler"],
    "code_graph": ["tools.code_knowledge_graph"],
    "verification": [
        "tools.verification_engine",
        "tools.quality_system",
        "tools.soak_validation",
        "tools.platform_verification_sweep",
    ],
}

DEFAULT_TEAM_PREFIXES = {
    "architecture_team": [
        "brain",
        "tools.taskgraph_compiler",
        "tools.architecture_validator",
        "tools.code_knowledge_graph",
        "tools.decision_engine",
        "tools.experiment_planner",
    ],
    "backend_team": ["app", "runtime", "agents"],
    "infrastructure_team": [
        "tools.vm_orchestrator",
        "tools.platform_registry",
        "tools.verification_engine",
        "tools.meta_factory_control",
        "tools.codex_control",
        "tools.factory_daemon",
        "tools.runtime_maintenance",
        "tools.tool_registry",
        "tools.capability_registry",
        "tools",
    ],
    "testing_team": [
        "tests",
        "tools.quality_system",
        "tools.soak_validation",
        "tools.platform_verification_sweep",
        "tools.experiment_evaluator",
        "tools.experiment_executor",
        "tools.prompt_improvement_sweep",
        "tools.scheduler_optimization_sweep",
    ],
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


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    return ".".join(relative.parts)


def _parse_python(path: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        snippet = "\n".join(text.splitlines()[:600])
        message = "\n".join(
            [
                "==== BAD CODE START ====",
                f"path: {path}",
                f"error: {exc}",
                snippet,
                "==== BAD CODE END ====",
                "",
            ]
        )
        with BAD_PARSE_LOG.open("a", encoding="utf-8") as handle:
            handle.write(message)
        return None
    imports: list[str] = []
    functions: list[str] = []
    classes: list[str] = []
    call_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = "." * node.level
            imports.append(f"{level}{module}".strip("."))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                call_names.append(target.id)
            elif isinstance(target, ast.Attribute):
                call_names.append(target.attr)
    return {
        "imports": sorted({item for item in imports if item}),
        "functions": sorted({item for item in functions if item}),
        "classes": sorted({item for item in classes if item}),
        "calls": sorted({item for item in call_names if item}),
        "line_count": len(text.splitlines()),
        "symbol_count": len(set(functions)) + len(set(classes)),
    }


def _normalize_import(imported: str) -> str:
    return imported.replace("\\", ".").strip(".")


def _match_prefix(value: str, prefixes: list[str]) -> bool:
    return any(value == prefix or value.startswith(prefix + ".") for prefix in prefixes)


def _resolve_internal_edges(modules: dict[str, dict[str, Any]]) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
    names = set(modules.keys())
    edges: list[dict[str, str]] = []
    internal_imports: dict[str, list[str]] = {}
    for module_name, payload in modules.items():
        resolved: list[str] = []
        for imported in payload.get("imports", []):
            normalized = _normalize_import(imported)
            if not normalized:
                continue
            target = None
            if normalized in names:
                target = normalized
            else:
                for candidate in names:
                    if candidate.endswith(normalized):
                        target = candidate
                        break
            if target:
                edges.append({
                    "from": module_name,
                    "to": target,
                    "kind": "import",
                    "from_domain": modules[module_name]["domain"],
                    "to_domain": modules[target]["domain"],
                })
                resolved.append(target)
        internal_imports[module_name] = sorted(set(resolved))
    return edges, internal_imports


def _build_team_map(blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    teams = blueprint.get("agent_teams", {}) or {}
    team_map: dict[str, dict[str, Any]] = {}
    for team_name, payload in teams.items():
        blueprint_prefixes = [item for item in (payload.get("modules", []) or []) if isinstance(item, str)]
        default_prefixes = DEFAULT_TEAM_PREFIXES.get(team_name, [])
        prefixes: list[str] = []
        for item in [*blueprint_prefixes, *default_prefixes]:
            if item not in prefixes:
                prefixes.append(item)
        team_map[team_name] = {
            "owner": payload.get("owner"),
            "prefixes": prefixes,
        }
    for team_name, prefixes in DEFAULT_TEAM_PREFIXES.items():
        team_map.setdefault(team_name, {"owner": None, "prefixes": prefixes})
    return team_map


def _assign_layer(module_name: str) -> str:
    for layer, prefixes in LAYER_PREFIXES.items():
        if _match_prefix(module_name, prefixes):
            return layer
    return "unclassified"


def _assign_team(module_name: str, team_map: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    for team_name, payload in team_map.items():
        prefixes = payload.get("prefixes", [])
        for prefix in prefixes:
            if module_name == prefix or module_name.startswith(prefix + "."):
                return team_name, payload.get("owner")
    return None, None


def _load_cached_graph(max_age_seconds: int = GRAPH_CACHE_MAX_AGE_SECONDS) -> dict[str, Any] | None:
    if not OUT.exists():
        return None
    age_seconds = (datetime.now(timezone.utc) - datetime.fromtimestamp(OUT.stat().st_mtime, tz=timezone.utc)).total_seconds()
    if age_seconds > max_age_seconds:
        return None
    payload = _load_json(OUT, None)
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("modules"), list):
        return None
    if not isinstance(payload.get("edges"), list):
        return None
    return payload


def build_code_knowledge_graph(force: bool = False) -> dict[str, Any]:
    if not force:
        cached = _load_cached_graph()
        if cached is not None:
            return cached
    blueprint = _load_json(BLUEPRINT, {})
    team_map = _build_team_map(blueprint)
    modules: dict[str, dict[str, Any]] = {}
    for scan_root in SCAN_ROOTS:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            module_name = _module_name(path)
            parsed = _parse_python(path)
            if parsed is None:
                continue
            owner_team, owner = _assign_team(module_name, team_map)
            layer = _assign_layer(module_name)
            modules[module_name] = {
                "module": module_name,
                "path": str(path),
                "domain": path.relative_to(ROOT).parts[0],
                "layer": layer,
                "owner_team": owner_team,
                "owner": owner,
                "is_test": "test" in path.name.lower() or any(part == "tests" for part in path.parts),
                **parsed,
            }
    edges, internal_imports = _resolve_internal_edges(modules)
    for module_name, resolved in internal_imports.items():
        modules[module_name]["internal_imports"] = resolved
        modules[module_name]["dependency_count"] = len(resolved)
        modules[module_name]["dependents"] = 0
    for edge in edges:
        target = edge["to"]
        modules[target]["dependents"] = modules[target].get("dependents", 0) + 1

    payload = {
        "updated_at": _utc(),
        "module_count": len(modules),
        "edge_count": len(edges),
        "domains": sorted({item["domain"] for item in modules.values()}),
        "layers": sorted({item["layer"] for item in modules.values()}),
        "teams": {
            team_name: {
                "owner": payload.get("owner"),
                "module_count": sum(1 for module in modules.values() if module.get("owner_team") == team_name),
            }
            for team_name, payload in team_map.items()
        },
        "modules": list(modules.values()),
        "edges": edges,
    }
    atomic_write_json(OUT, payload)
    return payload


def _tokenize_request(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {part for part in normalized.split() if len(part) >= 3}


def query_code_knowledge_graph(request: str, *, limit: int = 5) -> dict[str, Any]:
    payload = build_code_knowledge_graph()
    modules = payload.get("modules", [])
    tokens = _tokenize_request(request)
    if not tokens:
        return {
            "module_focus": [],
            "owner_teams": [],
            "layers": [],
            "matched_modules": [],
        }

    scored: list[tuple[int, dict[str, Any]]] = []
    for module in modules:
        haystacks = [
            module.get("module", ""),
            " ".join(module.get("functions", []) or []),
            " ".join(module.get("classes", []) or []),
            module.get("domain", ""),
            module.get("layer", ""),
            module.get("owner_team", "") or "",
        ]
        score = 0
        joined = " ".join(haystacks).lower()
        for token in tokens:
            if token in joined:
                score += 1
            if module.get("module", "").lower().endswith(token):
                score += 2
            if token in (module.get("owner_team", "") or "").lower():
                score += 2
            if token in (module.get("layer", "") or "").lower():
                score += 1
        if score > 0:
            scored.append((score, module))

    scored.sort(key=lambda item: (-item[0], item[1].get("dependency_count", 0), item[1].get("module", "")))
    selected = [item[1] for item in scored[:limit]]
    return {
        "module_focus": [item.get("module") for item in selected],
        "owner_teams": sorted({item.get("owner_team") for item in selected if item.get("owner_team")}),
        "layers": sorted({item.get("layer") for item in selected if item.get("layer")}),
        "matched_modules": [
            {
                "module": item.get("module"),
                "owner_team": item.get("owner_team"),
                "owner": item.get("owner"),
                "layer": item.get("layer"),
                "dependency_count": item.get("dependency_count", 0),
                "dependents": item.get("dependents", 0),
                "internal_imports": item.get("internal_imports", []),
            }
            for item in selected
        ],
    }


if __name__ == "__main__":
    print(json.dumps(build_code_knowledge_graph(), ensure_ascii=False, indent=2))

