from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
MEMORY = ROOT / "data" / "agent_experience.json"
SKILLS = ROOT / "data" / "skill_library.json"
BLUEPRINT = ROOT / "brain" / "system_blueprint.json"
DISTILLATION = ROOT / "data" / "capability_distillation.json"
REPUTATION = ROOT / "data" / "capability_reputation.json"
GLOBAL_POLICY = ROOT / "data" / "global_policy_state.json"
ORGANIZATION = ROOT / "data" / "organization_model.json"
sys.path.insert(0, str(ROOT))

from tools.context_builder import build_context_package
ROLE_DEFAULTS = {
    "product": "planner",
    "architect": "planner",
    "coder": "coder",
    "tester": "shell",
    "ops": "docker",
    "reviewer": "reviewer",
    "supervisor": "planner",
}

RESEARCH_TOKENS = {
    "research",
    "rfc",
    "design",
    "analysis",
    "prototype",
    "experiment",
    "roadmap",
    "proposal",
    "investigate",
    "document",
}

PRODUCTION_TOKENS = {
    "implement",
    "fix",
    "build",
    "patch",
    "test",
    "validate",
    "artifact",
    "regression",
    "release",
    "ship",
}

GOVERNANCE_TOKENS = {
    "coordinate",
    "alignment",
    "align",
    "review patch queue",
    "approval",
    "policy",
    "governance",
    "merge ready patch queue",
}



def _load_blueprint() -> dict:
    if not BLUEPRINT.exists():
        return {}
    return json.loads(BLUEPRINT.read_text(encoding="utf-8-sig"))


def _load_memory() -> list[dict]:
    if not MEMORY.exists():
        return []
    return json.loads(MEMORY.read_text(encoding="utf-8-sig"))


def _load_skills() -> list[dict]:
    if not SKILLS.exists():
        return []
    return json.loads(SKILLS.read_text(encoding="utf-8-sig")).get("skills", [])


def _load_distillation() -> dict:
    if not DISTILLATION.exists():
        return {}
    return json.loads(DISTILLATION.read_text(encoding="utf-8-sig"))


def _load_reputation() -> dict:
    if not REPUTATION.exists():
        return {}
    return json.loads(REPUTATION.read_text(encoding="utf-8-sig"))


def _load_global_policy() -> dict:
    if not GLOBAL_POLICY.exists():
        return {}
    return json.loads(GLOBAL_POLICY.read_text(encoding="utf-8-sig"))


def _load_organization() -> dict:
    if not ORGANIZATION.exists():
        return {}
    return json.loads(ORGANIZATION.read_text(encoding="utf-8-sig"))


def match_skills(text: str) -> list[dict]:
    lowered = (text or "").lower()
    matches = []
    for skill in _load_skills():
        keywords = skill.get("keywords", [])
        score = sum(1 for token in keywords if token and token in lowered)
        if score:
            item = dict(skill)
            item["score"] = score
            matches.append(item)
    matches.sort(key=lambda item: item.get("score", 0), reverse=True)
    return matches[:5]




def _department_worker_policy(node: dict | None, organization: dict | None) -> tuple[dict[str, float], str | None]:
    node = node or {}
    organization = organization or {}
    bias: dict[str, float] = {}
    owner_department = node.get("owner_department")
    departments = organization.get("departments") or {}
    if owner_department:
        default_worker = (departments.get(owner_department) or {}).get("default_worker")
        if default_worker:
            bias[default_worker] = round(float(bias.get(default_worker, 0.0) or 0.0) + 0.06, 4)
    for department in node.get("support_departments") or []:
        default_worker = (departments.get(department) or {}).get("default_worker")
        if default_worker:
            bias[default_worker] = round(float(bias.get(default_worker, 0.0) or 0.0) + 0.02, 4)
    dept_workers = node.get("department_workers") or {}
    for default_worker in dept_workers.values():
        if default_worker:
            bias[default_worker] = round(float(bias.get(default_worker, 0.0) or 0.0) + 0.01, 4)
    return bias, owner_department
def _specialize_target(
    role: str,
    capability_route: dict | None = None,
    vm_template: dict | None = None,
    text: str = "",
    worker_vm_policy: dict | None = None,
) -> tuple[str, str]:
    target = ROLE_DEFAULTS.get(role, "planner")
    reason = f"role-default:{role}->{target}"
    selected = (capability_route or {}).get("selected") or {}
    capability_id = (selected.get("capability_id") or "").lower()
    backend = (vm_template or {}).get("backend") or ""
    lowered = text.lower()
    if role == "tester" and (backend == "qemu-test" or "qemu" in lowered or "regression" in lowered):
        return "shell", "tester-routed:qemu-shell"
    if role == "ops" and ("deploy" in capability_id or "docker" in lowered):
        return "docker", "ops-routed:docker"
    if role == "coder" and "agent_orchestration" in capability_id:
        return "coder", "coder-routed:agent_orchestration"
    if (worker_vm_policy or {}).get("worker_vm_preferred") and role in {"coder", "tester", "ops"}:
        return target, f"{reason}+worker-vm"
    return target, reason


def choose_worker(
    role: str,
    *,
    capability_route: dict | None = None,
    vm_template: dict | None = None,
    task_text: str = "",
    worker_vm_policy: dict | None = None,
    node: dict | None = None,
) -> tuple[str, str, float]:
    candidates = _load_memory()
    blueprint = _load_blueprint()
    teams = blueprint.get("agent_teams", {})
    team = (node or {}).get("team")
    team_owner = ((teams.get(team) or {}).get("owner")) if team else None
    target, route_reason = _specialize_target(
        role,
        capability_route,
        vm_template,
        task_text,
        worker_vm_policy,
    )
    if team_owner:
        target = ROLE_DEFAULTS.get(team_owner, target)
        route_reason = f"{route_reason}+team-owner:{team}->{target}"
    distillation = _load_distillation()
    reputation = _load_reputation()
    global_policy = _load_global_policy()
    organization = _load_organization()
    worker_bias = {str(key or "").strip(): float(value or 0.0) for key, value in (distillation.get("worker_bias") or {}).items()}
    worker_reputation = {
        str(key or "").strip(): float((value or {}).get("score", 0.0) or 0.0)
        for key, value in (reputation.get("workers", {}) or {}).items()
        if str(key or "").strip()
    }
    policy_worker_bias = {str(key or "").strip(): float(value or 0.0) for key, value in (global_policy.get("worker_bias_policy") or {}).items()}
    org_team_map = organization.get("teams") or {}

    if team and team in org_team_map:
        org_default_worker = (org_team_map.get(team) or {}).get("default_worker")
        if org_default_worker == target:
            policy_worker_bias[target] = round(float(policy_worker_bias.get(target, 0.0) or 0.0) + 0.03, 4)
    org_priority = global_policy.get("organization_priority", {}) or {}
    department_bias, owner_department = _department_worker_policy(node, organization)
    for item in org_priority.get("departments", []) or []:
        dept_worker = item.get("default_worker")
        if not dept_worker:
            continue
        project_count = float(item.get("project_count", 0) or 0)
        if dept_worker == target:
            policy_worker_bias[target] = round(float(policy_worker_bias.get(target, 0.0) or 0.0) + min(0.06, project_count * 0.005), 4)
    matching = [item for item in candidates if item.get("worker") == target]
    if matching:
        matching.sort(
            key=lambda item: (
                (item.get("success_rate", 0.0) or 0.0)
                + worker_bias.get(item.get("worker"), 0.0)
                + worker_reputation.get(item.get("worker"), 0.0)
                + policy_worker_bias.get(item.get("worker"), 0.0)
                + department_bias.get(item.get("worker"), 0.0),
                item.get("completed", 0),
            ),
            reverse=True,
        )
        best = matching[0]
        success = (
            float(best.get("success_rate", 0.0) or 0.0)
            + worker_bias.get(best.get("worker"), 0.0)
            + worker_reputation.get(best.get("worker"), 0.0)
            + policy_worker_bias.get(best.get("worker"), 0.0)
            + department_bias.get(best.get("worker"), 0.0)
        )
        return best["worker"], route_reason, round(success, 4)
    return target, route_reason, round(worker_bias.get(target, 0.0) + worker_reputation.get(target, 0.0) + policy_worker_bias.get(target, 0.0) + department_bias.get(target, 0.0), 4)


def infer_execution_mode(node: dict) -> str:
    corpus = " ".join(
        str(part or "")
        for part in [
            node.get("title"),
            node.get("prompt"),
            node.get("kind"),
            node.get("role"),
        ]
    ).lower()
    if any(token in corpus for token in GOVERNANCE_TOKENS):
        return "governance"
    if any(token in corpus for token in PRODUCTION_TOKENS):
        return "production"
    if any(token in corpus for token in RESEARCH_TOKENS):
        return "research"
    if str(node.get("kind") or "").lower() in {"implementation", "verification"}:
        return "production"
    return "research"


def schedule_nodes(
    nodes: list[dict],
    *,
    capability_route: dict | None = None,
    vm_template: dict | None = None,
    worker_vm_policy: dict | None = None,
    repo_path: str | None = None,
) -> list[dict]:
    scheduled = []
    for node in nodes:
        prompt = (node.get("prompt") or "") + " " + (node.get("title") or "")
        skill_matches = match_skills(prompt)
        worker, selection_reason, success_rate = choose_worker(
            node.get("role") or "planner",
            capability_route=capability_route,
            vm_template=vm_template,
            task_text=prompt,
            worker_vm_policy=worker_vm_policy,
            node=node,
        )
        scheduled.append({
            "node_id": node.get("id"),
            "title": node.get("title"),
            "role": node.get("role"),
            "worker": worker,
            "prompt": node.get("prompt"),
            "dependencies": node.get("dependencies", []),
            "team": node.get("team"),
            "owned_modules": node.get("owned_modules", []),
            "module_focus": node.get("module_focus", []),
            "owner_teams": node.get("owner_teams", []),
            "module_ownership": node.get("module_ownership", {}),
            "patch_required": bool(node.get("patch_required", False)),
            "patch_target_teams": node.get("owner_teams", []),
            "kind": node.get("kind"),
            "skill_matches": [item.get("skill_id") for item in skill_matches],
            "selection_reason": selection_reason,
            "worker_success_rate": success_rate,
            "execution_mode": infer_execution_mode(node),
            "execution_lane": "worker-vm" if (worker_vm_policy or {}).get("worker_vm_preferred") else "host-control",
            "worker_vm_preferred": bool((worker_vm_policy or {}).get("worker_vm_preferred")),
            "context_package": build_context_package(
                prompt=prompt.strip(),
                goal=node.get("title"),
                repo_path=repo_path,
                scheduler_hint={
                    "owner_teams": node.get("owner_teams", []),
                    "layers": node.get("layers", []),
                    "module_focus": node.get("module_focus", []),
                },
            ),
        })
    return scheduled