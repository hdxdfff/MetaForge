from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.branch_context import build_branch_context, get_branch_context
from tools.goal_registry import create_goal, list_goals
from tools.organization_model import build_organization_model
from tools.project_graph import build_project_graph

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
OUT = DATA / "branch_workboard.json"


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


def _department_rank_map() -> dict[str, int]:
    workboard = _load_json(DATA / "organization_workboard.json", {})
    ordered = workboard.get("top_departments") or []
    return {name: index + 1 for index, name in enumerate(ordered)}


def _project_lookup(project_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("project_id")): item for item in project_graph.get("nodes", []) if item.get("project_id")}


def build_branch_workboard() -> dict[str, Any]:
    goals = list_goals()
    tasks = _load_json(TASKS, [])
    organization = build_organization_model()
    project_graph = build_project_graph()
    department_rank = _department_rank_map()
    allocations = {str(item.get("project_id")): item for item in (organization.get("project_allocations") or []) if item.get("project_id")}
    project_lookup = _project_lookup(project_graph)
    lanes: dict[str, dict[str, Any]] = {
        "mainline": {"goal_count": 0, "active_goal_count": 0, "goals": [], "active_goals": [], "task_count": 0, "lane_role": "architecture_mainline"},
    }
    active_lanes: list[str] = []
    for goal in goals:
        lane = str(goal.get("lane") or "mainline")
        if lane == "branch":
            lane = str(goal.get("branch_name") or "branch")
        lanes.setdefault(lane, {"goal_count": 0, "active_goal_count": 0, "goals": [], "active_goals": [], "task_count": 0})
        lane_payload = lanes[lane]
        lane_payload["goal_count"] += 1
        branch_name = goal.get("branch_name")
        branch_context = get_branch_context(branch_name) if branch_name else {}
        project = (branch_context.get("project") or {})
        project_id = str(project.get("project_id") or "")
        allocation = allocations.get(project_id, {})
        project_node = project_lookup.get(project_id, {})
        assigned_department = goal.get("assigned_department") or branch_context.get("department") or allocation.get("owner_department")
        lane_role = goal.get("lane_role") or branch_context.get("lane_role") or ("architecture_mainline" if lane == "mainline" else "capability_branch")
        lane_payload.setdefault("assigned_department", assigned_department)
        lane_payload.setdefault("lane_role", lane_role)
        lane_payload.setdefault("priority_rank", department_rank.get(assigned_department))
        lane_payload.setdefault("project_ids", [])
        lane_payload.setdefault("project_domains", [])
        lane_payload.setdefault("support_departments", [])
        lane_payload.setdefault("branch_context_ref", branch_name)
        lane_payload.setdefault("shares_mainline_context", bool(goal.get("shares_mainline_context", True)))
        lane_payload.setdefault("upstream_context_refs", list(goal.get("upstream_context_refs") or []))
        if project_id and project_id not in lane_payload["project_ids"]:
            lane_payload["project_ids"].append(project_id)
        for domain in project_node.get("domains", []) or []:
            if domain not in lane_payload["project_domains"]:
                lane_payload["project_domains"].append(domain)
        for dept in allocation.get("support_departments", []) or []:
            if dept not in lane_payload["support_departments"]:
                lane_payload["support_departments"].append(dept)
        lane_payload["goals"].append({
            "goal_id": goal.get("goal_id"),
            "target": goal.get("target"),
            "status": goal.get("status"),
            "branch_name": goal.get("branch_name"),
            "lane_role": lane_role,
            "assigned_department": assigned_department,
            "project_id": project_id or None,
            "project_name": project.get("name"),
        })
        if goal.get("status") in {"pending", "planned", "running"}:
            lane_payload["active_goal_count"] += 1
            lane_payload["active_goals"].append(goal.get("target"))
            if lane not in active_lanes:
                active_lanes.append(lane)
    for lane_payload in lanes.values():
        lane_payload["active_goals"] = list(dict.fromkeys(goal for goal in lane_payload.get("active_goals", []) if goal))
        lane_payload["active_goal_count"] = len(lane_payload["active_goals"])
    for task in tasks:
        lane = str(task.get("lane") or "mainline")
        if lane == "branch":
            lane = str(task.get("branch_name") or "branch")
        lanes.setdefault(lane, {"goal_count": 0, "active_goal_count": 0, "goals": [], "active_goals": [], "task_count": 0})
        if task.get("status") in {"queued", "planning", "running", "waiting_approval"}:
            lanes[lane]["task_count"] += 1
            if lane not in active_lanes:
                active_lanes.append(lane)
    payload = {
        "updated_at": _utc(),
        "lane_count": len(lanes),
        "active_lane_count": len(active_lanes),
        "active_lanes": active_lanes,
        "department_priority_map": department_rank,
        "lanes": lanes,
    }
    _save_json(OUT, payload)
    return payload


def create_branch_goal(target: str, branch_name: str, department: str | None = None, goal_type: str = "build_product", notes: str = "", source_session: str | None = None, lane_role: str = "capability_branch") -> dict[str, Any]:
    branch_context = build_branch_context(branch_name, target, department=department, source_session=source_session, lane_role=lane_role, shares_mainline_context=True)
    organization = build_organization_model()
    project = (branch_context.get("project") or {})
    project_id = project.get("project_id")
    allocation = next((item for item in (organization.get("project_allocations") or []) if item.get("project_id") == project_id), {})
    resolved_department = department or branch_context.get("department") or allocation.get("owner_department") or "engineering_department"
    goal = create_goal(
        target,
        goal_type=goal_type,
        notes=notes,
        lane="branch",
        lane_role=lane_role,
        branch_name=branch_name,
        branch_context_ref=branch_name,
        assigned_department=resolved_department,
        source_session=source_session,
        shares_mainline_context=True,
        upstream_context_refs=["mainline", "global_policy", "knowledge_base", "control_layer", "engineering_os", "automation_lab"],
    )
    goal["branch_context"] = branch_context
    goal["assigned_department"] = resolved_department
    build_branch_workboard()
    return goal


def branch_context_summary(branch_name: str) -> dict[str, Any]:
    payload = get_branch_context(branch_name)
    if not payload:
        return {"branch_name": branch_name, "status": "missing"}
    project = payload.get("project", {}) or {}
    policy = payload.get("global_policy", {}) or {}
    context_package = payload.get("context_package", {}) or {}
    mainline_state = payload.get("mainline_state", {}) or {}
    return {
        "branch_name": branch_name,
        "status": "ready",
        "updated_at": payload.get("updated_at"),
        "department": payload.get("department"),
        "source_session": payload.get("source_session"),
        "repo_path": payload.get("repo_path"),
        "project": {
            "project_id": project.get("project_id"),
            "name": project.get("name"),
            "summary": project.get("summary"),
        },
        "focus_capabilities": policy.get("focus_capabilities", []),
        "resource_budget": policy.get("resource_budget", {}),
        "mainline_state": mainline_state,
        "context_package": {
            "task_type": context_package.get("task_type"),
            "module_focus": context_package.get("module_focus", []),
            "dependency_modules": context_package.get("dependency_modules", []),
            "owner_teams": context_package.get("owner_teams", []),
            "layers": context_package.get("layers", []),
            "verification_scope": context_package.get("verification_scope", {}),
            "summary_blocks": context_package.get("summary_blocks", []),
        },
    }


if __name__ == "__main__":
    print(json.dumps(build_branch_workboard(), ensure_ascii=False, indent=2))
