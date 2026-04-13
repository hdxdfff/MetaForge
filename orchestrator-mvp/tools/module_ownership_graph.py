from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.organization_model import build_organization_model

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CODE_GRAPH = DATA / "code_knowledge_graph.json"
OUT = DATA / "module_ownership_graph.json"
REVIEW_OUT = DATA / "review_policy_graph.json"
GRAPH_CACHE_MAX_AGE_SECONDS = 300

CRITICAL_PREFIXES = (
    "brain.",
    "runtime.scheduler",
    "tools.factory_daemon",
    "tools.meta_factory_control",
    "tools.verification_engine",
    "tools.architecture_validator",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _load_cached_graph(path: Path) -> dict[str, Any] | None:
    payload = _load_json(path, {})
    updated_at = payload.get("updated_at")
    if not updated_at:
        return None
    try:
        updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except Exception:
        return None
    if datetime.now(timezone.utc) - updated > timedelta(seconds=GRAPH_CACHE_MAX_AGE_SECONDS):
        return None
    return payload


def _review_policy(module_name: str, owner_team: str | None, layer: str | None) -> dict[str, Any]:
    critical = any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in CRITICAL_PREFIXES) or layer in {"meta_brain", "architecture_engine"}
    if critical:
        return {
            "mode": "manual",
            "requires_patch_submission": True,
            "requires_owner_review": True,
            "requires_architecture_validation": True,
        }
    return {
        "mode": "same-team-auto" if owner_team else "open",
        "requires_patch_submission": bool(owner_team),
        "requires_owner_review": bool(owner_team),
        "requires_architecture_validation": layer in {"architecture_engine", "task_graph_planner", "verification"},
    }


def build_module_ownership_graph(force: bool = False) -> dict[str, Any]:
    if not force:
        cached = _load_cached_graph(OUT)
        if cached:
            return cached
    code_graph = _load_json(CODE_GRAPH, {})
    modules = code_graph.get("modules", [])
    ownership_nodes = []
    team_summary: dict[str, dict[str, Any]] = {}
    for module in modules:
        module_name = module.get("module")
        if not module_name:
            continue
        owner_team = module.get("owner_team")
        owner = module.get("owner")
        layer = module.get("layer")
        policy = _review_policy(module_name, owner_team, layer)
        ownership_nodes.append(
            {
                "module": module_name,
                "owner_team": owner_team,
                "owner": owner,
                "layer": layer,
                "path": module.get("path"),
                "review_policy": policy,
                "dependency_count": module.get("dependency_count", 0),
                "dependents": module.get("dependents", 0),
            }
        )
        if owner_team:
            team_summary.setdefault(owner_team, {"owner": owner, "module_count": 0, "critical_modules": 0, "layers": set()})
            team_summary[owner_team]["module_count"] += 1
            if policy["mode"] == "manual":
                team_summary[owner_team]["critical_modules"] += 1
            if layer:
                team_summary[owner_team]["layers"].add(layer)

    payload = {
        "updated_at": _utc(),
        "module_count": len(ownership_nodes),
        "teams": {
            team: {
                "owner": summary["owner"],
                "module_count": summary["module_count"],
                "critical_modules": summary["critical_modules"],
                "layers": sorted(summary["layers"]),
            }
            for team, summary in team_summary.items()
        },
        "modules": ownership_nodes,
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_module_ownership_graph(), ensure_ascii=False, indent=2))


def reviewer_candidates(module_focus: list[str] | None = None, owner_teams: list[str] | None = None) -> list[str]:
    graph = build_module_ownership_graph()
    organization = build_organization_model()
    module_focus = module_focus or []
    if not module_focus:
        return []
    review_teams = set(item for item in (owner_teams or []) if item)
    modules = {item.get("module"): item for item in graph.get("modules", []) if item.get("module")}
    departments = organization.get("departments") or {}
    team_index = organization.get("teams") or {}
    critical = False
    owner_departments = set()
    for team in review_teams:
        department = (team_index.get(team) or {}).get("department")
        if department:
            owner_departments.add(department)
    for module_name in module_focus:
        item = modules.get(module_name, {})
        policy = item.get("review_policy", {})
        if policy.get("requires_architecture_validation") or policy.get("mode") == "manual":
            critical = True
        owner_team = item.get("owner_team")
        if owner_team:
            review_teams.add(owner_team)
            department = (team_index.get(owner_team) or {}).get("department")
            if department:
                owner_departments.add(department)
    for department in sorted(owner_departments):
        dept_cfg = departments.get(department) or {}
        for team in dept_cfg.get("teams", []) or []:
            review_teams.add(team)
    if critical:
        review_teams.add("architecture_team")
    if not review_teams and module_focus:
        review_teams.add("backend_team")
    return sorted(review_teams)


def merge_policy_for_modules(module_focus: list[str] | None = None, owner_teams: list[str] | None = None) -> dict[str, Any]:
    graph = build_module_ownership_graph()
    organization = build_organization_model()
    module_focus = module_focus or []
    if not module_focus:
        return {
            "required_reviewer_teams": [],
            "required_departments": [],
            "requires_owner_review": False,
            "requires_architecture_validation": False,
            "manual_modules": [],
        }
    modules = {item.get("module"): item for item in graph.get("modules", []) if item.get("module")}
    manual_modules = []
    arch_validation = False
    owner_departments = set()
    team_index = organization.get("teams") or {}
    for team in owner_teams or []:
        department = (team_index.get(team) or {}).get("department")
        if department:
            owner_departments.add(department)
    for module_name in module_focus:
        item = modules.get(module_name, {})
        policy = item.get("review_policy", {})
        if policy.get("mode") == "manual":
            manual_modules.append(module_name)
        if policy.get("requires_architecture_validation"):
            arch_validation = True
        owner_team = item.get("owner_team")
        if owner_team:
            department = (team_index.get(owner_team) or {}).get("department")
            if department:
                owner_departments.add(department)
    return {
        "required_reviewer_teams": reviewer_candidates(module_focus, owner_teams),
        "required_departments": sorted(owner_departments),
        "requires_owner_review": bool(owner_teams),
        "requires_architecture_validation": arch_validation,
        "manual_modules": manual_modules,
    }


def build_review_policy_graph(force: bool = False) -> dict[str, Any]:
    if not force:
        cached = _load_cached_graph(REVIEW_OUT)
        if cached:
            return cached
    ownership = build_module_ownership_graph(force=force)
    review_edges = []
    merge_policies = []
    for item in ownership.get("modules", []):
        policy = item.get("review_policy", {})
        team = item.get("owner_team")
        module = item.get("module")
        if team and module:
            review_edges.append({
                "module": module,
                "reviewer_team": team,
                "mode": policy.get("mode"),
                "requires_owner_review": policy.get("requires_owner_review", False),
                "requires_architecture_validation": policy.get("requires_architecture_validation", False),
            })
        merge_policies.append({
            "module": module,
            "owner_team": team,
            "mode": policy.get("mode"),
            "requires_owner_review": policy.get("requires_owner_review", False),
            "requires_architecture_validation": policy.get("requires_architecture_validation", False),
        })
    payload = {
        "updated_at": _utc(),
        "module_count": ownership.get("module_count", 0),
        "review_edge_count": len(review_edges),
        "review_edges": review_edges,
        "merge_policies": merge_policies,
    }
    atomic_write_json(REVIEW_OUT, payload)
    return payload
