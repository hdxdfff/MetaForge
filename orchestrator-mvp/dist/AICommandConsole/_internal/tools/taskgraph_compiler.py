from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json
from uuid import uuid4

from tools.code_knowledge_graph import query_code_knowledge_graph
from tools.dependency_impact_engine import analyze_dependency_impact
from tools.module_ownership import patch_required, ownership_summary
from tools.module_ownership_graph import build_module_ownership_graph
from tools.project_graph import build_project_graph, analyze_project_impact
from tools.organization_model import build_organization_model
from tools.cross_project_coordination import run_cross_project_coordination
from tools.capability_library import capability_nodes, match_local_capability
from tools.kernel_mode import is_component_enabled, load_kernel_mode

ROOT = Path(__file__).resolve().parent.parent
FACTORY = ROOT / "factory"
GRAPHS = FACTORY / "graphs"
BRAIN = ROOT / "brain"
BLUEPRINT = BRAIN / "system_blueprint.json"

ROLE_BY_OWNER = {
    "planner": "architect",
    "coder": "coder",
    "tester": "tester",
    "ops": "ops",
    None: "coder",
}

TEAM_ROLE_DEFAULTS = {
    "architecture_team": "architect",
    "backend_team": "coder",
    "infrastructure_team": "ops",
    "testing_team": "tester",
}

SYSTEM_BUILD_GOAL_TYPES = {
    "system_build",
    "build_platform",
    "build_product",
    "engineering_system",
}


def _coordination_candidate(target: str) -> dict:
    coordination = run_cross_project_coordination(limit=20)
    target_lower = (target or "").strip().lower()
    for item in coordination.get("selected", []) or []:
        if str(item.get("target") or "").strip().lower() == target_lower:
            return item
    return {}


def _project_allocation(target: str, organization: dict) -> dict:
    target_lower = (target or "").lower()
    for item in organization.get("project_allocations", []) or []:
        name = str(item.get("name") or "").lower()
        project_id = str(item.get("project_id") or "").lower()
        if name and name in target_lower:
            return item
        if project_id and project_id in target_lower:
            return item
    allocations = list(organization.get("project_allocations", []) or [])
    return allocations[0] if allocations else {}


def _department_default_workers(organization: dict, departments: list[str]) -> dict:
    dept_map = organization.get("departments") or {}
    result = {}
    for department in departments:
        default_worker = (dept_map.get(department) or {}).get("default_worker")
        if default_worker:
            result[department] = default_worker
    return result


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_blueprint() -> dict:
    if not BLUEPRINT.exists():
        return {}
    return json.loads(BLUEPRINT.read_text(encoding="utf-8-sig"))


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _module_node_id(module_name: str) -> str:
    return f"module_{_slug(module_name)}"


def _owner_role(owner: str | None, team: str | None) -> str:
    if owner in ROLE_BY_OWNER:
        return ROLE_BY_OWNER[owner]
    return TEAM_ROLE_DEFAULTS.get(team, "coder")


def _is_system_build_goal_type(goal_type: str | None) -> bool:
    return str(goal_type or "").strip().lower() in SYSTEM_BUILD_GOAL_TYPES


def _module_artifact_paths(module_focus: list[str] | None) -> list[str]:
    paths: list[str] = []
    for item in module_focus or []:
        module_name = str(item or "").strip()
        if not module_name:
            continue
        if module_name.startswith(("app.", "runtime.", "tools.", "agents.", "state.")):
            candidate = f"{module_name.replace('.', '/')}.py"
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _release_artifact_paths(node_kind: str) -> list[str]:
    if node_kind == "artifact-build":
        return [
            "docker-compose.app.yml",
            "deploy-template.yml",
            "Dockerfile",
        ]
    if node_kind == "artifact-test":
        return [
            "tests",
            "reports/release-validation.json",
        ]
    if node_kind == "artifact-evidence":
        return [
            "artifact_manifest.json",
            "reports/release-evidence.json",
        ]
    if node_kind == "artifact-audit":
        return []
    if node_kind == "verification":
        return [
            "docker-compose.app.yml",
            "deploy-template.yml",
            "artifact_manifest.json",
            "reports/release-evidence.json",
        ]
    return [
        "docker-compose.app.yml",
        "deploy-template.yml",
        "Dockerfile",
        "artifact_manifest.json",
        "reports/release-evidence.json",
    ]


def _artifact_required_paths(target: str, node: dict | None = None) -> list[str]:
    node = node or {}
    corpus = " ".join(
        [
            str(target or ""),
            str(node.get("title") or ""),
            str(node.get("prompt") or ""),
        ]
    ).lower()
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    if node_kind in {
        "architecture",
        "planning",
        "artifact-audit",
        "cross-project-coordination",
        "cross-project-work-package",
        "cross-project-coordination-package",
    }:
        return []
    if "generated/toy-os-demo" in corpus or "toyos" in corpus or "toy-os" in corpus:
        if node_kind == "artifact-build":
            return [
                "generated/toy-os-demo/build-report.json",
                "generated/toy-os-demo/build/build.log",
                "generated/toy-os-demo/build/kernel.bin",
            ]
        if node_kind in {"artifact-test", "verification"}:
            return [
                "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
                "generated/toy-os-demo/score-report.json",
            ]
        if node_kind == "artifact-audit":
            return []
        if node_kind == "artifact-evidence":
            return [
                "generated/toy-os-demo/build/artifact.sha256",
                "generated/toy-os-demo/artifact_manifest.json",
                "generated/toy-os-demo/build-report.json",
            ]
        return [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
            "generated/toy-os-demo/build/artifact.sha256",
            "generated/toy-os-demo/artifact_manifest.json",
        ]
    if node_id == "bootstrap_build":
        return [
            "reports/bootstrap-build-report.json",
            "reports/bootstrap-build.log",
            "reports/bootstrap-build-manifest.json",
        ]
    if node_id == "bootstrap_test":
        return [
            "reports/bootstrap-validation.json",
            "reports/bootstrap-validation.log",
        ]
    goal_type = str(node.get("goal_type") or "")
    if goal_type == "build_product":
        combined = _release_artifact_paths(node_kind)
        combined.extend(_module_artifact_paths(node.get("module_focus", [])))
        return list(dict.fromkeys(combined))
    return _module_artifact_paths(node.get("module_focus", []))


def _artifact_outputs(goal_type: str, node: dict | None = None) -> list[str]:
    node = node or {}
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    corpus = " ".join(
        [
            str(node.get("title") or ""),
            str(node.get("prompt") or ""),
        ]
    ).lower()
    if node_id == "bootstrap_build" and not any(marker in corpus for marker in ("toyos", "toy-os", "qemu", "kernel")):
        return ["build_report", "build_log", "artifact_manifest"]
    if node_id == "bootstrap_test" and not any(marker in corpus for marker in ("toyos", "toy-os", "qemu", "kernel")):
        return ["test_report", "runtime_log"]
    if node_kind == "artifact-build":
        return ["source_code", "build_script", "build_log", "binary_artifact", "deploy_bundle"]
    if node_kind == "artifact-test":
        return ["test_suite", "test_report", "runtime_log", "release_validation"]
    if node_kind == "artifact-audit":
        return ["runtime_audit", "patch_decision"]
    if node_kind == "artifact-evidence":
        return ["artifact_manifest", "artifact_sha256", "verification_report", "release_evidence"]
    if node_kind == "verification":
        return [
            "source_code",
            "build_script",
            "test_suite",
            "verification_report",
            "release_evidence",
        ]
    if goal_type == "build_product":
        return ["source_code", "build_script", "test_suite", "deploy_bundle", "release_evidence"]
    return ["source_code", "build_script", "test_suite"]


def _build_artifact_spec(
    target: str, goal_type: str, *, graph_id: str, node: dict | None = None
) -> dict:
    node = {**(node or {}), "goal_type": goal_type}
    expected_outputs = _artifact_outputs(goal_type, node)
    required_artifacts = _artifact_required_paths(target, node)
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    build_required = node_kind not in {
        "architecture",
        "planning",
        "artifact-audit",
        "cross-project-coordination",
        "cross-project-work-package",
        "cross-project-coordination-package",
    }
    if node_id == "bootstrap_build":
        build_required = True
    tests_required = (
        node_kind in {"artifact-test", "artifact-evidence", "verification"} or build_required
    )
    if node_id == "bootstrap_build":
        tests_required = False
    elif node_id == "bootstrap_test":
        tests_required = True
    artifact_type = (
        "software_product"
        if goal_type == "build_product" and not node.get("id")
        else "software_component"
    )
    return {
        "artifact_id": f"{graph_id}:{node.get('id')}"
        if node.get("id")
        else f"{graph_id}:{_slug(target)}",
        "artifact_type": artifact_type,
        "type": artifact_type,
        "deliverables": list(expected_outputs),
        "expected_outputs": list(expected_outputs),
        "required_artifacts": list(required_artifacts),
        "evidence": [
            item for item in required_artifacts if item.endswith((".json", ".log", ".txt"))
        ],
        "verification": {
            "build_required": build_required,
            "tests_required": tests_required,
        },
        "registry": "artifact_registry",
        "test_command": "pytest"
        if "test_suite" in expected_outputs or node_kind == "verification"
        else None,
        "min_fresh_artifacts": max(1, min(len(required_artifacts), 3)) if required_artifacts else 1,
    }


def _build_module_slice_nodes(
    graph_focus: dict, *, default_dependency: str = "engineering_plan"
) -> list[dict]:
    matched = graph_focus.get("matched_modules", []) or []
    module_ids = {
        item.get("module"): _module_node_id(item.get("module", ""))
        for item in matched
        if item.get("module")
    }
    slices: list[dict] = []
    for item in matched:
        module_name = item.get("module")
        if not module_name:
            continue
        owner_team = item.get("owner_team")
        owner = item.get("owner")
        deps = []
        for dep in item.get("internal_imports", []) or []:
            dep_node = module_ids.get(dep)
            if dep_node and dep_node != module_ids[module_name]:
                deps.append(dep_node)
        if not deps:
            deps = [default_dependency]
        deps = sorted(set(deps))
        role = _owner_role(owner, owner_team)
        slices.append(
            {
                "id": module_ids[module_name],
                "title": f"Implement module {module_name}",
                "role": role,
                "prompt": f"Implement or refine module {module_name} for the current engineering goal.",
                "dependencies": deps,
                "status": "pending",
                "task_id": None,
                "team": owner_team,
                "owned_modules": [module_name],
                "kind": "module-implementation",
                "module_focus": [module_name],
                "owner_teams": [owner_team] if owner_team else [],
                "module_ownership": ownership_summary(
                    [module_name], [owner_team] if owner_team else []
                ),
                "patch_required": patch_required(
                    owner_team or "backend_team", [owner_team] if owner_team else []
                ),
                "owner": owner,
                "layer": item.get("layer"),
                "owner_department": None,
                "support_departments": [],
                "review_departments": [],
            }
        )
    return slices


def _group_verification_targets(
    module_slices: list[dict],
) -> tuple[list[str], list[str], list[str]]:
    modules = [mod for node in module_slices for mod in node.get("module_focus", [])]
    owner_teams = sorted(
        {team for node in module_slices for team in node.get("owner_teams", []) if team}
    )
    verification_focus = [
        mod for mod in modules if mod.startswith(("app.", "runtime.", "agents.", "tools."))
    ]
    return modules, owner_teams, verification_focus


def _engineering_nodes(
    target: str,
    blueprint: dict,
    coordination_candidate: dict | None = None,
    mode: dict | None = None,
    goal_type: str = "",
) -> list[dict]:
    coordination_candidate = coordination_candidate or {}
    mode = mode or load_kernel_mode()
    coordination_enabled = is_component_enabled("coordination", mode)
    graph_focus = query_code_knowledge_graph(target, limit=8)
    impact = analyze_dependency_impact(target, limit=8, max_depth=2)
    project_impact = analyze_project_impact(
        target, focus_modules=graph_focus.get("module_focus", [])
    )
    ownership_graph = build_module_ownership_graph()
    artifact_first = _is_system_build_goal_type(goal_type) or any(
        marker in str(target or "").lower() for marker in ("toyos", "toy-os")
    )
    bootstrap_dependency = "bootstrap_audit" if artifact_first else "engineering_plan"
    module_slices = _build_module_slice_nodes(
        graph_focus, default_dependency=bootstrap_dependency
    )
    architecture_ownership = ownership_summary(
        graph_focus.get("module_focus", []), graph_focus.get("owner_teams", [])
    )
    verification_modules, verification_owner_teams, verification_focus = (
        _group_verification_targets(module_slices)
    )
    architecture_dependencies = ["artifact_evidence"] if artifact_first else []
    planning_dependencies = ["artifact_evidence"] if artifact_first else ["architecture_contract"]
    nodes = [
        {
            "id": "architecture_contract",
            "title": f"Define architecture contract for {target}",
            "role": "architect",
            "prompt": f"Define architecture boundaries, interfaces, and ownership for: {target}",
            "dependencies": architecture_dependencies,
            "status": "pending",
            "task_id": None,
            "team": "architecture_team",
            "owned_modules": list(
                dict.fromkeys(
                    (
                        (blueprint.get("agent_teams", {}).get("architecture_team") or {}).get(
                            "modules", []
                        )
                        or []
                    )
                    + (graph_focus.get("module_focus", []) or [])
                )
            ),
            "kind": "architecture",
            "module_focus": graph_focus.get("module_focus", []),
            "owner_teams": graph_focus.get("owner_teams", []),
            "module_ownership": architecture_ownership,
            "dependency_impact": impact,
            "project_impact": project_impact,
            "ownership_graph_summary": {
                "module_count": ownership_graph.get("module_count", 0),
                "team_count": len(ownership_graph.get("teams", {})),
            },
            "patch_required": False,
        },
        {
            "id": "engineering_plan",
            "title": f"Plan engineering task graph for {target}",
            "role": "product",
            "prompt": f"Produce the engineering task graph, interface map, and implementation slices for: {target}",
            "dependencies": planning_dependencies,
            "status": "pending",
            "task_id": None,
            "team": "architecture_team",
            "owned_modules": [
                node["module_focus"][0] for node in module_slices if node.get("module_focus")
            ],
            "kind": "planning",
            "module_focus": graph_focus.get("module_focus", []),
            "owner_teams": graph_focus.get("owner_teams", []),
            "module_ownership": architecture_ownership,
            "dependency_impact": impact,
            "project_impact": project_impact,
            "ownership_graph_summary": {
                "module_count": ownership_graph.get("module_count", 0),
                "team_count": len(ownership_graph.get("teams", {})),
            },
            "patch_required": False,
        },
    ]
    if artifact_first:
        nodes = [
            {
                "id": "bootstrap_build",
                "title": f"Build current runnable baseline for {target}",
                "role": "ops",
                "prompt": f"Run the current build path for {target} first and refresh the earliest runnable build outputs and logs before any architecture review.",
                "dependencies": [],
                "status": "pending",
                "task_id": None,
                "team": "infrastructure_team",
                "owned_modules": verification_modules,
                "kind": "artifact-build",
                "module_focus": verification_focus,
                "owner_teams": sorted(
                    set((verification_owner_teams or []) + ["infrastructure_team"])
                ),
                "module_ownership": ownership_summary(
                    verification_focus,
                    sorted(set((verification_owner_teams or []) + ["infrastructure_team"])),
                ),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": patch_required(
                    "infrastructure_team",
                    sorted(set((verification_owner_teams or []) + ["infrastructure_team"])),
                ),
            },
            {
                "id": "bootstrap_test",
                "title": f"Run baseline runtime test loop for {target}",
                "role": "tester",
                "prompt": f"Run the baseline runtime or QEMU validation path for {target}, capture boot or execution output, and refresh machine-readable reports before patch work starts.",
                "dependencies": ["bootstrap_build"],
                "status": "pending",
                "task_id": None,
                "team": "testing_team",
                "owned_modules": verification_modules,
                "kind": "artifact-test",
                "module_focus": verification_focus,
                "owner_teams": verification_owner_teams,
                "module_ownership": ownership_summary(
                    verification_focus, verification_owner_teams
                ),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": patch_required("testing_team", verification_owner_teams),
            },
            {
                "id": "bootstrap_audit",
                "title": f"Audit baseline runtime evidence for {target}",
                "role": "reviewer",
                "prompt": f"Review the baseline runtime evidence for {target}, consume the refreshed build and runtime reports, and emit a concrete repair decision for the next patch step.",
                "dependencies": ["bootstrap_test"],
                "status": "pending",
                "task_id": None,
                "team": "testing_team",
                "owned_modules": verification_modules,
                "kind": "artifact-audit",
                "module_focus": verification_focus,
                "owner_teams": verification_owner_teams,
                "module_ownership": ownership_summary(
                    verification_focus, verification_owner_teams
                ),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": False,
            },
            *nodes,
        ]
    cross_project_related = [
        item for item in project_impact.get("related_projects", []) if item.get("type") == "project"
    ]
    cross_project_dependencies = []
    if coordination_enabled and len(cross_project_related) > 1:
        nodes.append(
            {
                "id": "cross_project_coordination",
                "title": f"Coordinate cross-project impact for {target}",
                "role": "reviewer",
                "prompt": f"Review cross-project downstream impact, compatibility, and rollout planning for: {target}",
                "dependencies": ["artifact_evidence"] if artifact_first else ["engineering_plan"],
                "status": "pending",
                "task_id": None,
                "team": "architecture_team",
                "owned_modules": [],
                "kind": "cross-project-coordination",
                "module_focus": graph_focus.get("module_focus", []),
                "owner_teams": graph_focus.get("owner_teams", []),
                "module_ownership": architecture_ownership,
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": False,
            }
        )
        for idx, project_item in enumerate(cross_project_related[:4], start=1):
            project_id = project_item.get("project_id") or f"project_{idx}"
            node_id = f"project_sync_{_slug(project_id)}"
            cross_project_dependencies.append(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "title": f"Align project {project_item.get('name', project_id)} for {target}",
                    "role": "reviewer",
                    "prompt": f"Update compatibility plan, interfaces, tests, and rollout steps for project {project_item.get('name', project_id)} in support of: {target}",
                    "dependencies": ["cross_project_coordination"],
                    "status": "pending",
                    "task_id": None,
                    "team": "architecture_team",
                    "owned_modules": [],
                    "kind": "cross-project-work-package",
                    "module_focus": graph_focus.get("module_focus", []),
                    "owner_teams": graph_focus.get("owner_teams", []),
                    "module_ownership": architecture_ownership,
                    "dependency_impact": impact,
                    "project_impact": {"project": project_item, "all": project_impact},
                    "owner_department": project_item.get("owner_department"),
                    "support_departments": project_item.get("support_departments", []),
                    "review_departments": sorted(
                        set(
                            (
                                [project_item.get("owner_department")]
                                if project_item.get("owner_department")
                                else []
                            )
                            + list(project_item.get("support_departments", []) or [])
                        )
                    ),
                    "patch_required": False,
                }
            )
    if (
        coordination_enabled
        and coordination_candidate
        and coordination_candidate.get("work_packages")
    ):
        base_dependency = (
            "cross_project_coordination"
            if len(cross_project_related) > 1
            else ("artifact_evidence" if artifact_first else "engineering_plan")
        )
        for idx, package in enumerate(coordination_candidate.get("work_packages", [])[:6], start=1):
            node_id = f"coordination_pkg_{idx}_{_slug(str(package.get('project_id') or package.get('name') or idx))}"
            nodes.append(
                {
                    "id": node_id,
                    "title": f"Coordinate work package for {package.get('name', package.get('project_id', idx))}",
                    "role": "reviewer",
                    "prompt": package.get("action")
                    or f"Coordinate interfaces, verification, and rollout for {package.get('name', package.get('project_id', idx))}.",
                    "dependencies": [base_dependency],
                    "status": "pending",
                    "task_id": None,
                    "team": "architecture_team",
                    "owned_modules": [],
                    "kind": "cross-project-coordination-package",
                    "module_focus": graph_focus.get("module_focus", []),
                    "owner_teams": graph_focus.get("owner_teams", []),
                    "module_ownership": architecture_ownership,
                    "dependency_impact": impact,
                    "project_impact": {"project": package, "all": project_impact},
                    "owner_department": package.get("owner_department"),
                    "support_departments": package.get("support_departments", []),
                    "review_departments": sorted(
                        set(
                            (
                                [package.get("owner_department")]
                                if package.get("owner_department")
                                else []
                            )
                            + list(package.get("support_departments", []) or [])
                        )
                    ),
                    "patch_required": False,
                }
            )
            cross_project_dependencies.append(node_id)

    if module_slices:
        nodes.extend(module_slices)
        verification_dependencies = [node["id"] for node in module_slices]
        if len(cross_project_related) > 1:
            verification_dependencies.extend(
                ["cross_project_coordination", *cross_project_dependencies]
            )
    else:
        teams = blueprint.get("agent_teams", {})
        backend_modules = list(
            dict.fromkeys(
                ((teams.get("backend_team") or {}).get("modules", []) or [])
                + [
                    m
                    for m in (graph_focus.get("module_focus", []) or [])
                    if str(m).startswith(("app.", "runtime.", "agents."))
                ]
            )
        )
        infra_modules = list(
            dict.fromkeys(
                ((teams.get("infrastructure_team") or {}).get("modules", []) or [])
                + [
                    m
                    for m in (graph_focus.get("module_focus", []) or [])
                    if str(m).startswith("tools.")
                ]
            )
        )
        testing_modules = list(
            dict.fromkeys(
                ((teams.get("testing_team") or {}).get("modules", []) or [])
                + [
                    m.get("module")
                    for m in (graph_focus.get("matched_modules", []) or [])
                    if m.get("layer") == "verification"
                ]
            )
        )
        backend_focus = [
            m
            for m in graph_focus.get("module_focus", [])
            if str(m).startswith(("app.", "runtime.", "agents."))
        ]
        backend_owner_teams = sorted(
            {
                item.get("owner_team")
                for item in (graph_focus.get("matched_modules", []) or [])
                if item.get("module") in backend_focus and item.get("owner_team")
            }
        )
        infra_focus = [
            m for m in graph_focus.get("module_focus", []) if str(m).startswith("tools.")
        ]
        infra_owner_teams = sorted(
            {
                item.get("owner_team")
                for item in (graph_focus.get("matched_modules", []) or [])
                if item.get("module") in infra_focus and item.get("owner_team")
            }
        )
        nodes.extend(
            [
                {
                    "id": "backend_impl",
                    "title": f"Implement backend/runtime modules for {target}",
                    "role": "coder",
                    "prompt": f"Implement backend/runtime modules for: {target}",
                    "dependencies": [bootstrap_dependency],
                    "status": "pending",
                    "task_id": None,
                    "team": "backend_team",
                    "owned_modules": backend_modules,
                    "kind": "implementation",
                    "module_focus": backend_focus,
                    "owner_teams": backend_owner_teams or graph_focus.get("owner_teams", []),
                    "module_ownership": ownership_summary(
                        backend_focus, backend_owner_teams or graph_focus.get("owner_teams", [])
                    ),
                    "dependency_impact": impact,
                    "patch_required": patch_required(
                        "backend_team", backend_owner_teams or graph_focus.get("owner_teams", [])
                    ),
                },
                {
                    "id": "infra_impl",
                    "title": f"Implement infrastructure/tooling modules for {target}",
                    "role": "ops",
                    "prompt": f"Implement infrastructure/tooling modules for: {target}",
                    "dependencies": [bootstrap_dependency],
                    "status": "pending",
                    "task_id": None,
                    "team": "infrastructure_team",
                    "owned_modules": infra_modules,
                    "kind": "infrastructure",
                    "module_focus": infra_focus,
                    "owner_teams": infra_owner_teams or graph_focus.get("owner_teams", []),
                    "module_ownership": ownership_summary(
                        infra_focus, infra_owner_teams or graph_focus.get("owner_teams", [])
                    ),
                    "dependency_impact": impact,
                    "patch_required": patch_required(
                        "infrastructure_team",
                        infra_owner_teams or graph_focus.get("owner_teams", []),
                    ),
                },
            ]
        )
        verification_modules = testing_modules
        verification_owner_teams = graph_focus.get("owner_teams", [])
        verification_focus = [
            m.get("module")
            for m in (graph_focus.get("matched_modules", []) or [])
            if m.get("layer") == "verification"
        ]
        verification_dependencies = ["backend_impl", "infra_impl"]
        if len(cross_project_related) > 1:
            verification_dependencies.extend(
                ["cross_project_coordination", *cross_project_dependencies]
            )

    build_dependencies = list(dict.fromkeys(verification_dependencies)) or [bootstrap_dependency]
    nodes.extend(
        [
            {
                "id": "artifact_build",
                "title": f"Build runnable artifact for {target}",
                "role": "ops",
                "prompt": f"Run the product build for {target}, refresh build scripts if needed, and produce fresh build outputs, logs, and entrypoint artifacts.",
                "dependencies": build_dependencies,
                "status": "pending",
                "task_id": None,
                "team": "infrastructure_team",
                "owned_modules": verification_modules,
                "kind": "artifact-build",
                "module_focus": verification_focus,
                "owner_teams": sorted(
                    set((verification_owner_teams or []) + ["infrastructure_team"])
                ),
                "module_ownership": ownership_summary(
                    verification_focus,
                    sorted(set((verification_owner_teams or []) + ["infrastructure_team"])),
                ),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": patch_required(
                    "infrastructure_team",
                    sorted(set((verification_owner_teams or []) + ["infrastructure_team"])),
                ),
            },
            {
                "id": "artifact_test",
                "title": f"Run runtime and integration tests for {target}",
                "role": "tester",
                "prompt": f"Execute the runnable and integration test path for {target}, capture runtime logs, and refresh machine-readable test reports.",
                "dependencies": ["artifact_build"],
                "status": "pending",
                "task_id": None,
                "team": "testing_team",
                "owned_modules": verification_modules,
                "kind": "artifact-test",
                "module_focus": verification_focus,
                "owner_teams": verification_owner_teams,
                "module_ownership": ownership_summary(verification_focus, verification_owner_teams),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": patch_required("testing_team", verification_owner_teams),
            },
            {
                "id": "artifact_evidence",
                "title": f"Refresh artifact evidence for {target}",
                "role": "tester",
                "prompt": f"Refresh artifact manifests, hashes, and evidence-chain outputs for {target} so the artifact registry can verify delivery.",
                "dependencies": ["artifact_test"],
                "status": "pending",
                "task_id": None,
                "team": "testing_team",
                "owned_modules": verification_modules,
                "kind": "artifact-evidence",
                "module_focus": verification_focus,
                "owner_teams": verification_owner_teams,
                "module_ownership": ownership_summary(verification_focus, verification_owner_teams),
                "dependency_impact": impact,
                "project_impact": project_impact,
                "patch_required": patch_required("testing_team", verification_owner_teams),
            },
        ]
    )
    verification_dependencies = ["artifact_evidence"]
    nodes.append(
        {
            "id": "verification_gate",
            "title": f"Run verification and architecture validation for {target}",
            "role": "tester",
            "prompt": f"Run CI, tests, and architecture validation for: {target}",
            "dependencies": verification_dependencies,
            "status": "pending",
            "task_id": None,
            "team": "testing_team",
            "owned_modules": verification_modules,
            "kind": "verification",
            "module_focus": verification_focus,
            "owner_teams": verification_owner_teams,
            "module_ownership": ownership_summary(verification_focus, verification_owner_teams),
            "dependency_impact": impact,
            "project_impact": project_impact,
            "patch_required": patch_required("testing_team", verification_owner_teams),
        }
    )
    return nodes


def compile_goal(goal: dict) -> dict:
    graph_id = str(goal.get("graph_id") or "").strip() or f"graph_{uuid4().hex[:10]}"
    mode = load_kernel_mode()
    target = goal.get("target", "unnamed goal")
    goal_type = goal.get("type", "build_platform")
    blueprint = _load_blueprint()
    project_graph = build_project_graph()
    organization = build_organization_model()
    capability_match = match_local_capability(target, goal_type=goal_type)
    selected_capability = capability_match.get("selected") or {}
    impact = analyze_dependency_impact(target, limit=8, max_depth=2)
    project_impact = analyze_project_impact(
        target, focus_modules=(query_code_knowledge_graph(target, limit=8).get("module_focus", []))
    )
    allocation = _project_allocation(target, organization)
    coordination_candidate = (
        _coordination_candidate(target) if is_component_enabled("coordination", mode) else {}
    )
    engineering_goal = (
        _is_system_build_goal_type(goal_type)
        or "platform" in target.lower()
        or "factory" in target.lower()
        or bool(coordination_candidate)
    )
    if engineering_goal:
        nodes = _engineering_nodes(
            target,
            blueprint,
            coordination_candidate,
            mode=mode,
            goal_type=goal_type,
        )
        for node in nodes:
            node["capability_context"] = {
                "capability_id": selected_capability.get("capability_id"),
                "recommended_tools": list(selected_capability.get("tools", [])),
                "success_conditions": list(selected_capability.get("success_conditions", [])),
            }
    elif selected_capability:
        nodes = capability_nodes(selected_capability, target)
    else:
        nodes = [
            {
                "id": "product_design",
                "title": f"Design product shape for {target}",
                "role": "product",
                "prompt": f"Create a structured product design for: {target}",
                "dependencies": [],
                "status": "pending",
                "task_id": None,
            },
            {
                "id": "architecture_design",
                "title": f"Design architecture for {target}",
                "role": "architect",
                "prompt": f"Create a practical architecture plan for: {target}",
                "dependencies": ["product_design"],
                "status": "pending",
                "task_id": None,
            },
            {
                "id": "implementation_plan",
                "title": f"Plan and start implementation for {target}",
                "role": "coder",
                "prompt": f"Break down implementation work for: {target}",
                "dependencies": ["architecture_design"],
                "status": "pending",
                "task_id": None,
            },
            {
                "id": "verification",
                "title": f"Validate generated work for {target}",
                "role": "tester",
                "prompt": f"Create validation steps and tests for: {target}",
                "dependencies": ["implementation_plan"],
                "status": "pending",
                "task_id": None,
            },
        ]
    if (
        goal_type in {"build_platform", "build_product"}
        and not engineering_goal
        and is_component_enabled("release_train", mode)
    ):
        nodes.append(
            {
                "id": "release_prep",
                "title": f"Prepare release plan for {target}",
                "role": "ops",
                "prompt": f"Prepare deployment and release checklist for: {target}",
                "dependencies": ["verification_gate"],
                "status": "pending",
                "task_id": None,
            }
        )
    owner_department = allocation.get("owner_department")
    support_departments = allocation.get("support_departments", [])
    reviewer_departments = sorted(
        set(([owner_department] if owner_department else []) + list(support_departments or []))
    )
    department_workers = _department_default_workers(organization, reviewer_departments)
    for node in nodes:
        if owner_department and not node.get("owner_department"):
            node["owner_department"] = owner_department
        if support_departments and not node.get("support_departments"):
            node["support_departments"] = list(support_departments)
        if reviewer_departments and not node.get("review_departments"):
            node["review_departments"] = list(reviewer_departments)
        if department_workers and not node.get("department_workers"):
            node["department_workers"] = dict(department_workers)

    if coordination_candidate:
        selected_work_packages = coordination_candidate.get("work_packages", [])
    else:
        selected_work_packages = []

    goal_artifact_spec = _build_artifact_spec(target, goal_type, graph_id=graph_id)
    for node in nodes:
        node_artifact_spec = _build_artifact_spec(target, goal_type, graph_id=graph_id, node=node)
        node["artifact_spec"] = node_artifact_spec
        if node_artifact_spec.get("required_artifacts") and not node.get("required_artifacts"):
            node["required_artifacts"] = list(node_artifact_spec.get("required_artifacts") or [])
        if node_artifact_spec.get("min_fresh_artifacts") and not node.get("min_fresh_artifacts"):
            node["min_fresh_artifacts"] = int(node_artifact_spec.get("min_fresh_artifacts") or 1)
        if str(node.get("kind") or "") in {"artifact-build", "artifact-test", "artifact-audit", "artifact-evidence", "verification"}:
            node["patch_required"] = False
            node["patch_target_teams"] = []

    graph = {
        "graph_id": graph_id,
        "goal_id": goal.get("goal_id"),
        "target": target,
        "type": goal_type,
        "created_at": _utc(),
        "updated_at": _utc(),
        "status": "ready",
        "meta": {
            "goal_scale": "engineering-os" if engineering_goal else "standard",
            "capability_selection": {
                "selected_capability_id": selected_capability.get("capability_id"),
                "source": capability_match.get("source"),
                "recommended_tools": list(selected_capability.get("tools", [])),
                "success_conditions": list(selected_capability.get("success_conditions", [])),
                "match_count": len(capability_match.get("matches", [])),
            },
            "architecture_rules": blueprint.get("architecture", {}).get("rules", []),
            "agent_teams": list((blueprint.get("agent_teams") or {}).keys()),
            "code_graph_focus": query_code_knowledge_graph(target, limit=8),
            "dependency_impact": impact,
            "project_impact": project_impact,
            "project_graph_summary": {
                "project_count": project_graph.get("project_count", 0),
                "platform_count": project_graph.get("platform_count", 0),
                "edge_count": len(project_graph.get("edges", [])),
            },
            "organization_allocation": allocation,
            "organization_summary": {
                "department_count": len((organization.get("departments") or {})),
                "team_count": len((organization.get("teams") or {})),
            },
            "cross_project_candidate": coordination_candidate,
            "selected_work_packages": selected_work_packages,
            "kernel_profile": mode.get("profile"),
            "disabled_components": mode.get("disabled_components", []),
            "artifact_spec": goal_artifact_spec,
            "route_strategy": "artifact-first" if _is_system_build_goal_type(goal_type) else "default",
            "first_artifact_policy": {
                "required": _is_system_build_goal_type(goal_type),
                "max_wait_ticks": 3,
            },
        },
        "nodes": nodes,
    }
    path = GRAPHS / f"{graph_id}.json"
    atomic_write_json(path, graph)
    return graph


if __name__ == "__main__":
    print("Provide a goal object through import use.")
