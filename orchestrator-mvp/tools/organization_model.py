from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "organization_model.json"
PROJECT_GRAPH = DATA / "project_graph.json"
OWNERSHIP_GRAPH = DATA / "module_ownership_graph.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"
EXPERIENCE = DATA / "agent_experience.json"

DEFAULT_OFFICES = {
    "strategy_office": {
        "mission": "govern long-term goals, portfolio priorities, and resource allocation",
        "departments": ["architecture_department", "rnd_department", "operations_department"],
    },
    "architecture_office": {
        "mission": "maintain architecture blueprints, ownership rules, and cross-project interfaces",
        "departments": ["architecture_department", "engineering_department", "qa_department"],
    },
}

TEAM_TO_DEPARTMENT = {
    "architecture_team": "architecture_department",
    "backend_team": "engineering_department",
    "infrastructure_team": "operations_department",
    "testing_team": "qa_department",
}

DEPARTMENTS = {
    "architecture_department": {
        "focus": ["architecture_validation", "module_ownership", "cross_project_coordination"],
        "default_worker": "reviewer",
    },
    "engineering_department": {
        "focus": ["agent_orchestration", "webapp_generation", "tool_extension"],
        "default_worker": "coder",
    },
    "operations_department": {
        "focus": ["deploy_scaffold", "runtime_stability", "worker_vm_execution"],
        "default_worker": "docker",
    },
    "qa_department": {
        "focus": ["verification", "runtime_health", "patch_gate"],
        "default_worker": "shell",
    },
    "rnd_department": {
        "focus": ["experiments", "distillation", "knowledge_growth", "productization"],
        "default_worker": "reviewer",
    },
}

FUNCTIONAL_GROUPS = {
    "ai_infrastructure_group": {
        "name": "AI基础架构组",
        "default_worker": "reviewer",
        "focus": ["ai_system_architecture", "multi_agent_runtime", "scheduler", "ai_os"],
    },
    "ai_platform_engineering_group": {
        "name": "AI平台工程组",
        "default_worker": "coder",
        "focus": ["sdk", "api", "tool_platform", "framework"],
    },
    "ai_algorithm_research_group": {
        "name": "AI算法研究组",
        "default_worker": "reviewer",
        "focus": ["model_research", "capability_distillation", "knowledge_growth"],
    },
    "ai_automation_engineering_group": {
        "name": "AI自动化工程组",
        "default_worker": "shell",
        "focus": ["automation", "ai_coding", "ai_testing", "ai_devops"],
    },
    "ai_productization_group": {
        "name": "AI产品化组",
        "default_worker": "docker",
        "focus": ["productization", "service_delivery", "enterprise_ai"],
    },
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


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _project_allocations(project_graph: dict[str, Any], global_policy: dict[str, Any]) -> list[dict[str, Any]]:
    focus_capabilities = {str(item or "").strip().lower() for item in global_policy.get("focus_capabilities", []) if item}
    allocations: list[dict[str, Any]] = []
    for node in project_graph.get("nodes", []):
        project_id = node.get("project_id")
        if not project_id:
            continue
        domains = [str(item or "").strip().lower() for item in node.get("domains", [])]
        owner_department = "engineering_department"
        support_departments = ["qa_department"]
        if "factory" in domains:
            owner_department = "architecture_department"
            support_departments = ["engineering_department", "qa_department", "rnd_department"]
        elif "database" in domains or "network" in domains:
            owner_department = "operations_department"
            support_departments = ["engineering_department", "qa_department"]
        elif "frontend" in domains:
            owner_department = "engineering_department"
            support_departments = ["qa_department", "operations_department"]
        if any(cap in " ".join(domains) for cap in focus_capabilities):
            support_departments = sorted(set(support_departments + ["rnd_department"]))
        allocations.append(
            {
                "project_id": project_id,
                "name": node.get("name"),
                "type": node.get("type"),
                "domains": domains,
                "owner_department": owner_department,
                "support_departments": support_departments,
            }
        )
    return allocations


def _department_metrics(experience: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metrics = {key: {"task_count": 0, "success_rate": 0.0, "workers": set()} for key in DEPARTMENTS.keys()}
    for item in experience:
        worker = str(item.get("worker") or "").strip()
        if not worker:
            continue
        if worker == "reviewer":
            department = "architecture_department"
        elif worker == "coder":
            department = "engineering_department"
        elif worker == "docker":
            department = "operations_department"
        elif worker == "shell":
            department = "qa_department"
        else:
            department = "rnd_department"
        metrics[department]["task_count"] += int(item.get("completed", 0) or 0)
        metrics[department]["success_rate"] = max(
            float(metrics[department]["success_rate"] or 0.0),
            float(item.get("success_rate", 0.0) or 0.0),
        )
        metrics[department]["workers"].add(worker)
    for value in metrics.values():
        value["workers"] = sorted(value["workers"])
    return metrics


def _functional_group_state(project_allocations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    group_projects: dict[str, list[dict[str, Any]]] = {key: [] for key in FUNCTIONAL_GROUPS}
    for item in project_allocations:
        domains = set(item.get("domains") or [])
        if "factory" in domains or "kernel" in domains:
            group_projects["ai_infrastructure_group"].append(item)
        if item.get("type") == "platform" or "frontend" in domains:
            group_projects["ai_platform_engineering_group"].append(item)
        if item.get("owner_department") == "architecture_department" or "rnd_department" in (item.get("support_departments") or []):
            group_projects["ai_algorithm_research_group"].append(item)
        if "qa_department" in (item.get("support_departments") or []):
            group_projects["ai_automation_engineering_group"].append(item)
        if "frontend" in domains or "operations_department" in (item.get("support_departments") or []):
            group_projects["ai_productization_group"].append(item)

    payload: dict[str, dict[str, Any]] = {}
    for group_id, cfg in FUNCTIONAL_GROUPS.items():
        projects = group_projects.get(group_id, [])
        payload[group_id] = {
            **cfg,
            "project_count": len(projects),
            "projects": [
                {
                    "project_id": item.get("project_id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                }
                for item in projects[:12]
            ],
            "status": "active" if projects else "building",
        }
    return payload


def build_organization_model() -> dict[str, Any]:
    project_graph = _load_json(PROJECT_GRAPH, {"nodes": [], "edges": []})
    ownership_graph = _load_json(OWNERSHIP_GRAPH, {"teams": {}, "modules": []})
    global_policy = _load_json(GLOBAL_POLICY, {})
    experience = _load_json(EXPERIENCE, [])

    team_map = {}
    for team_name, summary in (ownership_graph.get("teams") or {}).items():
        department = TEAM_TO_DEPARTMENT.get(team_name, "engineering_department")
        team_map[team_name] = {
            "department": department,
            "owner": summary.get("owner"),
            "module_count": summary.get("module_count", 0),
            "critical_modules": summary.get("critical_modules", 0),
            "layers": summary.get("layers", []),
            "default_worker": DEPARTMENTS.get(department, {}).get("default_worker"),
        }

    project_allocations = _project_allocations(project_graph, global_policy)
    metrics = _department_metrics(experience)

    department_state = {}
    for name, cfg in DEPARTMENTS.items():
        assigned_projects = [item["project_id"] for item in project_allocations if item.get("owner_department") == name or name in item.get("support_departments", [])]
        department_state[name] = {
            **cfg,
            "teams": sorted([team for team, item in team_map.items() if item.get("department") == name]),
            "project_count": len(assigned_projects),
            "projects": assigned_projects[:12],
            "metrics": metrics.get(name, {}),
        }

    payload = {
        "updated_at": _utc(),
        "offices": DEFAULT_OFFICES,
        "departments": department_state,
        "functional_groups": _functional_group_state(project_allocations),
        "teams": team_map,
        "project_allocations": project_allocations,
        "focus_capabilities": global_policy.get("focus_capabilities", []),
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_organization_model(), ensure_ascii=False, indent=2))
