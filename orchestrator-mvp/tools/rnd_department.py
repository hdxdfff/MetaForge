from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "rnd_department_status.json"
ORGANIZATION = DATA / "organization_model.json"
WORKBOARD = DATA / "organization_workboard.json"
PROJECT_GRAPH = DATA / "project_graph.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"


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


def _group_definition(group_id: str, name: str, charter: str, keywords: list[str], default_worker: str) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "name": name,
        "charter": charter,
        "keywords": keywords,
        "default_worker": default_worker,
    }


GROUPS = [
    _group_definition(
        "ai_infrastructure_group",
        "AI基础架构组",
        "负责 AI 系统架构、调度、多 agent 控制和 AI 操作系统底座。",
        ["factory", "kernel", "runtime", "scheduler", "agent", "architecture"],
        "reviewer",
    ),
    _group_definition(
        "ai_platform_engineering_group",
        "AI平台工程组",
        "负责平台框架、工具层、SDK、API 和复用型工程资产。",
        ["platform", "tool", "framework", "sdk", "api", "webapp"],
        "coder",
    ),
    _group_definition(
        "ai_algorithm_research_group",
        "AI算法研究组",
        "负责算法实验、能力蒸馏、知识增长和模型能力提升。",
        ["experiment", "distillation", "knowledge", "model", "research", "learning"],
        "reviewer",
    ),
    _group_definition(
        "ai_automation_engineering_group",
        "AI自动化工程组",
        "负责自动化研发、AI coding、自动测试和自动运维闭环。",
        ["automation", "verification", "testing", "devops", "execution", "workflow"],
        "shell",
    ),
    _group_definition(
        "ai_productization_group",
        "AI产品化组",
        "负责产品实例、交付路径、企业服务和商业化能力承接。",
        ["product", "frontend", "deploy", "release", "service", "saas"],
        "docker",
    ),
]


def _project_keywords(project: dict[str, Any]) -> set[str]:
    text = " ".join([
        str(project.get("name") or ""),
        str(project.get("type") or ""),
        " ".join(str(item or "") for item in (project.get("domains") or [])),
    ]).lower()
    return {part for part in text.replace("-", " ").replace("_", " ").split() if part}


def _match_groups(project: dict[str, Any], allocation: dict[str, Any] | None = None) -> list[str]:
    keywords = _project_keywords(project)
    matched: list[str] = []
    allocation = allocation or {}
    owner_department = str(allocation.get("owner_department") or "")
    support_departments = {str(item or "") for item in (allocation.get("support_departments") or [])}
    domains = {str(item or "") for item in (allocation.get("domains") or project.get("domains") or [])}
    for group in GROUPS:
        if any(token in keywords for token in group["keywords"]):
            matched.append(group["group_id"])
    if owner_department == "architecture_department" or "factory" in domains or "kernel" in domains:
        matched.append("ai_infrastructure_group")
    if project.get("type") == "platform" or "frontend" in domains or "general" in domains:
        matched.append("ai_platform_engineering_group")
    if owner_department == "rnd_department" or "rnd_department" in support_departments:
        matched.append("ai_algorithm_research_group")
    if owner_department == "qa_department" or "qa_department" in support_departments:
        matched.append("ai_automation_engineering_group")
    if owner_department == "operations_department" or "operations_department" in support_departments or "frontend" in domains or "service" in domains:
        matched.append("ai_productization_group")
    if not matched:
        matched.append("ai_platform_engineering_group")
    return sorted(set(matched))


def build_rnd_department_status() -> dict[str, Any]:
    organization = _load_json(ORGANIZATION, {})
    workboard = _load_json(WORKBOARD, {})
    project_graph = _load_json(PROJECT_GRAPH, {})
    global_policy = _load_json(GLOBAL_POLICY, {})

    allocations = organization.get("project_allocations") or []
    projects_by_id = {item.get("project_id"): item for item in (project_graph.get("nodes") or []) if item.get("project_id")}
    focus_capabilities = global_policy.get("focus_capabilities", [])
    top_departments = workboard.get("top_departments", [])

    group_states: dict[str, dict[str, Any]] = {}
    for group in GROUPS:
        matched_projects = []
        domains: set[str] = set()
        for allocation in allocations:
            node = projects_by_id.get(allocation.get("project_id"), allocation)
            if group["group_id"] not in _match_groups(node, allocation):
                continue
            matched_projects.append({
                "project_id": allocation.get("project_id"),
                "name": allocation.get("name"),
                "type": allocation.get("type"),
            })
            domains.update(str(item or "") for item in (allocation.get("domains") or []))
        group_states[group["group_id"]] = {
            "name": group["name"],
            "charter": group["charter"],
            "default_worker": group["default_worker"],
            "project_count": len(matched_projects),
            "projects": matched_projects[:12],
            "domains": sorted(item for item in domains if item),
            "status": "active" if matched_projects else "building",
        }

    staffed_groups = sum(1 for item in group_states.values() if item["project_count"] > 0)
    platform_group_ready = group_states["ai_platform_engineering_group"]["project_count"] > 0
    product_group_ready = group_states["ai_productization_group"]["project_count"] > 0

    payload = {
        "updated_at": _utc(),
        "status": "department",
        "department": {
            "department_id": "rnd_department",
            "name": "AI 研发部",
            "formal_name": "AI R&D Department",
            "mission": "将研究、工程、平台和产品能力整合为可持续交付的 AI 研发体系。",
        },
        "operating_model": {
            "type": "human_ai_hybrid",
            "human_roles": ["架构师", "产品负责人", "工程负责人"],
            "agent_roles": ["AI研究Agent", "AI工程Agent", "AI测试Agent", "AI运维Agent"],
        },
        "functional_groups": group_states,
        "summary": {
            "group_count": len(GROUPS),
            "staffed_group_count": staffed_groups,
            "focus_capability_count": len(focus_capabilities),
            "top_departments": top_departments,
            "project_count": len(allocations),
        },
        "readiness": {
            "organization_ready": staffed_groups >= 4,
            "platform_group_ready": platform_group_ready,
            "product_group_ready": product_group_ready,
            "departmentalized": staffed_groups == len(GROUPS),
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_rnd_department_status(), ensure_ascii=False, indent=2))

