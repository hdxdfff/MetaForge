from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data"

from tools.code_knowledge_graph import build_code_knowledge_graph
BRAIN = ROOT / "brain"
GRAPH = DATA / "code_knowledge_graph.json"
OUT = DATA / "architecture_validation.json"
BLUEPRINT = BRAIN / "system_blueprint.json"

MODULE_ALIASES = {
    "taskgraph_engine": ["runtime.taskgraph_engine", "tools.taskgraph_compiler"],
    "agent_runtime": ["runtime", "app.worker_adapters", "app.orchestrator"],
    "tool_system": ["tools.tool_registry", "tools.capability_registry", "tools.vm_orchestrator"],
    "evolution_engine": ["tools.evolution_control", "tools.experiment_planner", "tools.experiment_executor", "tools.experiment_evaluator"],
    "product_generator": ["runtime.platform_generator", "tools.generate_system_workspace"],
    "context_kernel": ["tools.context_kernel"],
    "resident_core_agent": ["tools.codex_control", "tools.meta_factory_control"],
    "architecture_engine": ["tools.architecture_validator", "tools.code_knowledge_graph"],
    "code_knowledge_graph": ["tools.code_knowledge_graph"],
    "verification_engine": ["tools.verification_engine", "tools.quality_system", "tools.soak_validation"],
}

TRANSPORT_MODULES = {"app.main"}
CONTROL_PLANE_TOOL_BRIDGES = {"tools.brain_loop", "tools.codex_control", "tools.factory_daemon"}
ROUTER_MODULES = ("app.orchestrator", "tools.tool_registry", "tools.capability_registry")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _match_prefix(value: str, prefixes: list[str]) -> bool:
    return any(value == prefix or value.startswith(prefix + ".") for prefix in prefixes)


def _module_exists(graph: dict[str, Any], module_name: str) -> bool:
    modules = [item.get("module", "") for item in graph.get("modules", [])]
    prefixes = MODULE_ALIASES.get(module_name, [module_name])
    return any(_match_prefix(item, prefixes) for item in modules)


def _rule_agents_cannot_import_runtime(graph: dict[str, Any]) -> dict[str, Any]:
    violations = []
    for edge in graph.get("edges", []):
        source = edge.get("from", "")
        target = edge.get("to", "")
        if source.startswith("agents.") and target.startswith("runtime."):
            violations.append(edge)
    return {
        "rule": "agents cannot import runtime",
        "passed": not violations,
        "violations": violations,
    }


def _rule_router_should_be_stateless(graph: dict[str, Any]) -> dict[str, Any]:
    suspects = []
    for module in graph.get("modules", []):
        name = module.get("module", "")
        if not any(name == prefix or name.startswith(prefix + ".") for prefix in ROUTER_MODULES):
            continue
        for imported in module.get("imports", []):
            if any(token in imported for token in ["sqlite", "shelve", "pickle"]):
                suspects.append({"module": name, "import": imported})
    return {
        "rule": "router should avoid embedded persistence",
        "passed": not suspects,
        "violations": suspects,
    }


def _rule_runtime_no_transport_import(graph: dict[str, Any]) -> dict[str, Any]:
    violations = []
    for edge in graph.get("edges", []):
        source = edge.get("from", "")
        target = edge.get("to", "")
        if source.startswith("runtime.") and target in TRANSPORT_MODULES:
            violations.append(edge)
    return {
        "rule": "runtime modules cannot depend on app transport handlers",
        "passed": not violations,
        "violations": violations,
    }


def _rule_tools_not_http(graph: dict[str, Any]) -> dict[str, Any]:
    violations = []
    for edge in graph.get("edges", []):
        source = edge.get("from", "")
        target = edge.get("to", "")
        if source in CONTROL_PLANE_TOOL_BRIDGES:
            continue
        if source.startswith("tools.") and target in TRANSPORT_MODULES:
            violations.append(edge)
    return {
        "rule": "tools may depend on runtime and state, but not app HTTP layer",
        "passed": not violations,
        "violations": violations,
    }


def _rule_verification_gate(graph: dict[str, Any]) -> dict[str, Any]:
    required = {"tools.verification_engine", "tools.meta_factory_control", "tools.factory_daemon"}
    names = {item.get("module", "") for item in graph.get("modules", [])}
    missing = sorted(item for item in required if item not in names)
    violations = [{"missing": item} for item in missing]
    return {
        "rule": "verification must gate promotion of architecture-affecting changes",
        "passed": not violations,
        "violations": violations,
    }


def _rule_team_ownership(graph: dict[str, Any]) -> dict[str, Any]:
    violations = []
    for module in graph.get("modules", []):
        domain = module.get("domain")
        if domain not in {"app", "runtime", "tools", "agents"}:
            continue
        if not module.get("owner_team"):
            violations.append({"module": module.get("module"), "domain": domain})
    return {
        "rule": "engineering modules should have an owner team",
        "passed": not violations,
        "violations": violations,
    }


def run_architecture_validation() -> dict[str, Any]:
    blueprint = _load_json(BLUEPRINT, {})
    graph = _load_json(GRAPH, {})
    if not graph:
        graph = build_code_knowledge_graph()

    module_results = []
    for module_name in blueprint.get("modules", []):
        module_results.append({
            "module": module_name,
            "exists": _module_exists(graph, module_name),
            "aliases": MODULE_ALIASES.get(module_name, [module_name]),
        })

    rule_results = [
        _rule_agents_cannot_import_runtime(graph),
        _rule_router_should_be_stateless(graph),
        _rule_runtime_no_transport_import(graph),
        _rule_tools_not_http(graph),
        _rule_verification_gate(graph),
        _rule_team_ownership(graph),
    ]
    missing_modules = [item for item in module_results if not item.get("exists")]
    payload = {
        "updated_at": _utc(),
        "blueprint_system": blueprint.get("system"),
        "module_results": module_results,
        "missing_modules": missing_modules,
        "rule_results": rule_results,
        "status": "pass" if not missing_modules and all(item.get("passed") for item in rule_results) else "attention",
        "violation_count": sum(len(item.get("violations", [])) for item in rule_results) + len(missing_modules),
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_architecture_validation(), ensure_ascii=False, indent=2))
