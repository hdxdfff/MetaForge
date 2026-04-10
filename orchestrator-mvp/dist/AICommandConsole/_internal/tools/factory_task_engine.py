from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.ai_testing_compat import load_ai_test_status
from tools.goal_registry import create_goal, list_goals, update_goal
from tools.io_utils import atomic_write_json
from tools.release_operations import run_release_operations_status
from tools.taskgraph_compiler import SYSTEM_BUILD_GOAL_TYPES, compile_goal
from tools.tool_health_audit import run_tool_health_audit
from tools.kernel_mode import is_component_enabled, load_kernel_mode
from tools.production_focus import build_production_focus, goal_matches_focus

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
GOAL_REGISTRY = FACTORY / "goals" / "goal_registry.json"
GRAPHS = FACTORY / "graphs"
STATUS = DATA / "factory_task_engine_status.json"
TASKS = DATA / "tasks.json"

ACTIVE_GOAL_STATUSES = {"pending", "planned", "running"}
ACTIVE_TASK_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
EXECUTION_FINISHING_TASK_STATUSES = {"execution_finished"}
POOL_TARGETS = {
    "production": 0.6,
    "research": 0.3,
    "ops": 0.1,
}
GRAPH_DEPENDENCY_ALIASES = {
    "verification": "verification_gate",
}
GOAL_COOLDOWN_HOURS = 6


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


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _classify_goal_pool(goal: dict[str, Any]) -> str:
    explicit = str(goal.get("factory_pool") or "").strip().lower()
    if explicit in POOL_TARGETS:
        return explicit
    assigned_department = str(goal.get("assigned_department") or "").strip().lower()
    target = str(goal.get("target") or "").strip().lower()
    goal_type = str(goal.get("type") or "").strip().lower()
    priority_class = str(goal.get("priority_class") or "").strip().lower()
    if assigned_department == "rnd_department" or goal_type == "experiment" or target.startswith("experiment "):
        return "research"
    if assigned_department in {"operations_department", "qa_department"}:
        return "ops"
    if priority_class in {"release", "verification", "merge", "stability"}:
        return "ops"
    if any(token in target for token in ("release", "repair", "merge ready", "verification", "stabilize ai reliability", "toolchain health")):
        return "ops"
    return "production"


def _infer_priority_class(goal: dict[str, Any], pool: str) -> str:
    explicit = str(goal.get("priority_class") or "").strip().lower()
    if explicit:
        return explicit
    target = str(goal.get("target") or "").strip().lower()
    goal_type = str(goal.get("type") or "").strip().lower()
    if goal_type == "experiment" or pool == "research":
        return "research"
    if "reliability" in target or "verification" in target or "test lane" in target:
        return "verification"
    if "repair" in target or "toolchain health" in target:
        return "stability"
    if "release" in target or "merge" in target:
        return "release"
    if "orchestration" in target or "mainline" in target:
        return "runtime"
    if "tool extension" in target or "capability" in target:
        return "capability-building"
    return "runtime" if pool == "production" else "stability" if pool == "ops" else "research"


def _infer_assigned_department(goal: dict[str, Any], pool: str, priority_class: str) -> str:
    explicit = str(goal.get("assigned_department") or "").strip()
    if explicit:
        return explicit
    if pool == "research":
        return "rnd_department"
    if priority_class == "verification":
        return "qa_department"
    if pool == "ops":
        return "operations_department"
    return "engineering_department"


def _infer_release_tier(goal: dict[str, Any], pool: str, priority_class: str) -> str:
    explicit = str(goal.get("release_tier") or "").strip().lower()
    if explicit:
        return explicit
    if pool == "research":
        return "experimental"
    if priority_class in {"release", "stability", "runtime"}:
        return "mainline"
    return "normal"


def _infer_factory_priority(goal: dict[str, Any], pool: str, priority_class: str) -> str:
    explicit = str(goal.get("factory_priority") or "").strip().upper()
    if explicit in {"P0", "P1", "P2", "P3"}:
        return explicit
    if pool == "research":
        return "P3"
    if pool == "ops":
        return "P1"
    if priority_class == "runtime":
        return "P0"
    return "P2"


def _goal_metadata(goal: dict[str, Any]) -> dict[str, str]:
    pool = _classify_goal_pool(goal)
    priority_class = _infer_priority_class(goal, pool)
    return {
        "factory_pool": pool,
        "priority_class": priority_class,
        "assigned_department": _infer_assigned_department(goal, pool, priority_class),
        "release_tier": _infer_release_tier(goal, pool, priority_class),
        "factory_priority": _infer_factory_priority(goal, pool, priority_class),
    }


def _backfill_goal_metadata(goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    changed = False
    for goal in goals:
        if goal.get("status") not in ACTIVE_GOAL_STATUSES:
            continue
        inferred = _goal_metadata(goal)
        missing = [key for key, value in inferred.items() if not str(goal.get(key) or "").strip()]
        if not missing:
            continue
        for key in missing:
            goal[key] = inferred[key]
        goal["updated_at"] = _utc()
        updated.append({
            "goal_id": goal.get("goal_id"),
            "target": goal.get("target"),
            "fields": {key: goal.get(key) for key in missing},
        })
        changed = True
    if changed:
        _save_json(GOAL_REGISTRY, goals)
    return updated


def _ready_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    completed = {node.get("id") for node in graph.get("nodes", []) if node.get("status") == "completed"}
    ready = []
    for node in graph.get("nodes", []) or []:
        if node.get("status") != "pending":
            continue
        deps = set(node.get("dependencies") or [])
        if deps.issubset(completed):
            ready.append(node)
    return ready


def _recent_targets(goals: list[dict[str, Any]]) -> set[str]:
    now = datetime.now(timezone.utc)
    recent: set[str] = set()
    for goal in goals:
        target = str(goal.get("target") or "").strip().lower()
        if not target:
            continue
        ts = _parse_time(goal.get("updated_at") or goal.get("created_at"))
        if ts is None:
            continue
        if now - ts <= timedelta(hours=GOAL_COOLDOWN_HOURS):
            recent.add(target)
    return recent


def _repair_graph_dependencies(goal: dict[str, Any]) -> dict[str, Any] | None:
    graph_id = goal.get("graph_id")
    if not graph_id:
        return None
    path = GRAPHS / f"{graph_id}.json"
    graph = _load_json(path, {})
    if not graph:
        return None
    node_ids = {str(node.get("id") or "") for node in graph.get("nodes", [])}
    repairs: list[dict[str, Any]] = []
    changed = False
    for node in graph.get("nodes", []) or []:
        deps = list(node.get("dependencies") or [])
        updated = []
        for dep in deps:
            dep_name = str(dep or "")
            alias = GRAPH_DEPENDENCY_ALIASES.get(dep_name)
            if alias and dep_name not in node_ids and alias in node_ids:
                updated.append(alias)
                repairs.append({"node_id": node.get("id"), "from": dep_name, "to": alias})
                changed = True
            else:
                updated.append(dep_name)
        if updated != deps:
            node["dependencies"] = updated
    if changed:
        graph["updated_at"] = _utc()
        _save_json(path, graph)
        return {
            "graph_id": graph_id,
            "goal_id": goal.get("goal_id"),
            "target": goal.get("target"),
            "repair_count": len(repairs),
            "repairs": repairs,
            "ready_nodes": [node.get("id") for node in _ready_nodes(graph)],
        }
    return None


def _goal_requires_artifact_first(goal: dict[str, Any]) -> bool:
    goal_type = str(goal.get("type") or "").strip().lower()
    return goal_type in SYSTEM_BUILD_GOAL_TYPES


def _graph_needs_contract_upgrade(goal: dict[str, Any], graph: dict[str, Any]) -> bool:
    if not _goal_requires_artifact_first(goal):
        return False
    if not graph:
        return False
    meta = graph.get("meta") or {}
    if str(meta.get("route_strategy") or "") != "artifact-first":
        return True
    bootstrap = next((node for node in (graph.get("nodes") or []) if str(node.get("id") or "") == "bootstrap_build"), None)
    if bootstrap is None:
        return True
    if bool(bootstrap.get("patch_required")):
        return True
    bootstrap_artifacts = set((bootstrap.get("artifact_spec") or {}).get("required_artifacts") or [])
    toyos_bootstrap = any("generated/toy-os-demo" in item for item in bootstrap_artifacts)
    if not toyos_bootstrap and "reports/bootstrap-build-report.json" not in bootstrap_artifacts:
        return True
    bootstrap_test = next((node for node in (graph.get("nodes") or []) if str(node.get("id") or "") == "bootstrap_test"), None)
    if bootstrap_test is None:
        return True
    test_artifacts = set((bootstrap_test.get("artifact_spec") or {}).get("required_artifacts") or [])
    toyos_test = any("generated/toy-os-demo" in item for item in test_artifacts)
    if not toyos_test and "reports/bootstrap-validation.json" not in test_artifacts:
        return True
    return False


def _repair_graph_contract(goal: dict[str, Any]) -> dict[str, Any] | None:
    graph_id = str(goal.get("graph_id") or "").strip()
    if not graph_id:
        return None
    path = GRAPHS / f"{graph_id}.json"
    graph = _load_json(path, {})
    if not _graph_needs_contract_upgrade(goal, graph):
        return None
    compiled = compile_goal({**goal, "graph_id": graph_id})
    update_goal(
        goal["goal_id"],
        status="planned",
        task_ids=[],
        metadata={
            "runtime_contract_upgrade": {
                "upgraded_at": _utc(),
                "graph_id": graph_id,
                "route_strategy": ((compiled.get("meta") or {}).get("route_strategy")),
                "preserved_graph_id": True,
                "previous_graph_updated_at": graph.get("updated_at"),
            }
        },
        status_reason="artifact-first-contract-upgrade",
    )
    return {
        "graph_id": graph_id,
        "goal_id": goal.get("goal_id"),
        "target": goal.get("target"),
        "route_strategy": ((compiled.get("meta") or {}).get("route_strategy")),
        "ready_nodes": [node.get("id") for node in _ready_nodes(compiled)],
    }


def _summarize_supply(goals: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    active_goals = [goal for goal in goals if goal.get("status") in ACTIVE_GOAL_STATUSES]
    goal_by_id = {str(goal.get("goal_id") or ""): goal for goal in active_goals}
    pools: dict[str, dict[str, Any]] = {
        pool: {
            "target_share": target_share,
            "active_goal_count": 0,
            "active_task_count": 0,
            "ready_node_count": 0,
            "goal_targets": [],
        }
        for pool, target_share in POOL_TARGETS.items()
    }
    for goal in active_goals:
        pool = _classify_goal_pool(goal)
        pools[pool]["active_goal_count"] += 1
        pools[pool]["goal_targets"].append(goal.get("target"))
        graph_id = goal.get("graph_id")
        if not graph_id:
            continue
        graph = _load_json(GRAPHS / f"{graph_id}.json", {})
        pools[pool]["ready_node_count"] += len(_ready_nodes(graph))
    for task in tasks:
        if str(task.get("status") or "") not in ACTIVE_TASK_STATUSES:
            continue
        goal = goal_by_id.get(str(task.get("goal_id") or ""))
        pool = _classify_goal_pool(goal or {})
        pools[pool]["active_task_count"] += 1
    return {
        "active_goal_count": len(active_goals),
        "active_task_count": sum(1 for task in tasks if str(task.get("status") or "") in ACTIVE_TASK_STATUSES),
        "execution_finishing_task_count": sum(1 for task in tasks if str(task.get("status") or "") in EXECUTION_FINISHING_TASK_STATUSES),
        "ready_node_count": sum(int(payload.get("ready_node_count", 0) or 0) for payload in pools.values()),
        "pools": pools,
    }


def _goal_templates(ai_testing: dict[str, Any], release_ops: dict[str, Any], tool_health: dict[str, Any], focus: dict[str, Any]) -> list[dict[str, Any]]:
    if focus.get("single_product_mode"):
        return [dict(focus.get("goal_template") or {})]
    templates: list[dict[str, Any]] = []
    release_train = release_ops.get("release_train") or {}
    if str(ai_testing.get("status") or "") in {"degraded", "attention", "missing"}:
        templates.append({
            "target": "Stabilize AI reliability test lane",
            "goal_type": "verification_upgrade",
            "pool": "ops",
            "priority": "P1",
            "release_tier": "normal",
            "assigned_department": "qa_department",
            "priority_class": "verification",
            "goal_class": "operational",
            "notes": "Seeded by AI Factory task engine to restore the reliability lane and keep production unblocked.",
        })
    if str(release_train.get("status") or "") == "blocked":
        templates.append({
            "target": "Ship deployable release artifact bundle",
            "goal_type": "build_product",
            "pool": "ops",
            "priority": "P0",
            "release_tier": "mainline",
            "assigned_department": "operations_department",
            "priority_class": "release",
            "goal_class": "operational",
            "force_seed": True,
            "notes": "Seeded by AI Factory task engine to produce a deployable release bundle with docker-compose, deploy template, and machine-verifiable release evidence when mainline is blocked.",
        })
    if str(tool_health.get("status") or "") == "attention":
        templates.append({
            "target": "Repair abnormal toolchain health",
            "goal_type": "build_product",
            "pool": "ops",
            "priority": "P1",
            "release_tier": "mainline",
            "assigned_department": "operations_department",
            "priority_class": "stability",
            "goal_class": "operational",
            "notes": "Seeded by AI Factory task engine to keep SRE-style repairs flowing instead of waiting for manual intervention.",
        })
    templates.extend([
        {
            "target": "Strengthen agent orchestration capability",
            "goal_type": "build_product",
            "pool": "production",
            "priority": "P0",
            "release_tier": "mainline",
            "assigned_department": "engineering_department",
            "priority_class": "runtime",
            "goal_class": "strategic",
            "notes": "Seeded by AI Factory task engine as the mainline production lane.",
        },
        {
            "target": "Expand tool extension coverage",
            "goal_type": "build_product",
            "pool": "production",
            "priority": "P2",
            "release_tier": "normal",
            "assigned_department": "engineering_department",
            "priority_class": "capability-building",
            "goal_class": "strategic",
            "notes": "Seeded by AI Factory task engine to keep the production backlog non-empty.",
        },
        {
            "target": "Experiment GitHub repo capability extraction",
            "goal_type": "experiment",
            "pool": "research",
            "priority": "P3",
            "release_tier": "experimental",
            "assigned_department": "rnd_department",
            "priority_class": "research",
            "goal_class": "research",
            "notes": "Seeded by AI Factory task engine to keep research running without starving production.",
        },
    ])
    return templates


def _desired_goals_by_pool(min_active_tasks: int, focus: dict[str, Any]) -> dict[str, int]:
    if focus.get("single_product_mode"):
        return {
            "production": 1,
            "research": 0,
            "ops": 0,
        }
    floor = max(1, min_active_tasks)
    return {
        "production": max(2, round(floor * POOL_TARGETS["production"] + 0.4)),
        "research": max(1, round(floor * POOL_TARGETS["research"])),
        "ops": max(1, round(floor * POOL_TARGETS["ops"] + 0.4)),
    }


def run_factory_task_engine(policy_schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    schedule = policy_schedule or {}
    focus = build_production_focus(schedule)
    goals = list_goals()
    tasks = _load_json(TASKS, [])
    ai_testing = load_ai_test_status()
    release_ops = run_release_operations_status()
    tool_health = run_tool_health_audit()

    backfilled_goals = _backfill_goal_metadata(goals)
    if backfilled_goals:
        goals = list_goals()

    active_goals = [goal for goal in goals if goal.get("status") in ACTIVE_GOAL_STATUSES]
    repaired_graphs = [item for item in (_repair_graph_dependencies(goal) for goal in active_goals) if item is not None]
    upgraded_graphs = [item for item in (_repair_graph_contract(goal) for goal in active_goals) if item is not None]
    if repaired_graphs or upgraded_graphs:
        goals = list_goals()
    tasks = _load_json(TASKS, [])

    min_active_tasks = int(schedule.get("min_active_tasks") or 3)
    kernel_mode = schedule.get("kernel_mode") or load_kernel_mode()
    desired_goals = _desired_goals_by_pool(min_active_tasks, focus)
    if not is_component_enabled('experiments', kernel_mode):
        desired_goals['research'] = 0
    scoped_goals = goals
    scoped_tasks = tasks
    if focus.get("single_product_mode"):
        scoped_goals = [goal for goal in goals if goal.get("status") not in ACTIVE_GOAL_STATUSES or goal_matches_focus(goal, focus)]
        focus_goal_ids = {str(goal.get("goal_id") or "") for goal in scoped_goals if goal.get("status") in ACTIVE_GOAL_STATUSES}
        scoped_tasks = [task for task in tasks if str(task.get("goal_id") or "") in focus_goal_ids]
    supply_before_seed = _summarize_supply(scoped_goals, scoped_tasks)

    open_targets = {str(goal.get("target") or "").strip().lower() for goal in scoped_goals if goal.get("status") in ACTIVE_GOAL_STATUSES}
    recent_targets = _recent_targets(scoped_goals)
    active_task_count = int(supply_before_seed.get("active_task_count", 0) or 0)
    ready_node_count = int(supply_before_seed.get("ready_node_count", 0) or 0)
    desired_ready_nodes = max(min_active_tasks, max(1, active_task_count) * 2)
    shortage = max(0, min_active_tasks - active_task_count)
    ready_shortage = max(0, desired_ready_nodes - ready_node_count)
    recovery_mode = active_task_count == 0
    allow_goal_generation = bool(schedule.get("allow_goal_generation", True)) or recovery_mode or ready_shortage > 0
    max_seed = max(0, min(4, max(shortage, ready_shortage, 1 if recovery_mode else 0))) if allow_goal_generation else 0
    seeded_goals: list[dict[str, Any]] = []

    templates = _goal_templates(ai_testing, release_ops, tool_health, focus)
    mandatory_seed_count = sum(1 for item in templates if item.get("force_seed"))
    max_seed = max(max_seed, mandatory_seed_count)
    if not is_component_enabled('experiments', kernel_mode):
        templates = [item for item in templates if item.get('pool') != 'research' and item.get('goal_type') != 'experiment']

    for template in templates:
        if len(seeded_goals) >= max_seed:
            break
        target_lower = template["target"].strip().lower()
        pool = template["pool"]
        force_seed = bool(template.get("force_seed"))
        pool_supply = (supply_before_seed.get("pools") or {}).get(pool, {})
        pool_goal_count = int(pool_supply.get("active_goal_count", 0) or 0)
        pool_ready = int(pool_supply.get("ready_node_count", 0) or 0)
        if target_lower in open_targets or (target_lower in recent_targets and not recovery_mode):
            continue
        if not force_seed and pool_goal_count >= desired_goals.get(pool, 1) and pool_ready > 0:
            continue
        goal = create_goal(
            template["target"],
            goal_type=template["goal_type"],
            notes=template["notes"],
            lane="mainline",
            assigned_department=template["assigned_department"],
            repo_path=template.get("repo_path"),
            primary_artifact_id=template.get("primary_artifact_id"),
            factory_pool=pool,
            factory_priority=template["priority"],
            priority_class=template["priority_class"],
            release_tier=template["release_tier"],
            goal_class=template["goal_class"],
            tags=[template["goal_type"], pool, template["priority"].lower(), template["release_tier"]],
        )
        seeded_goals.append({
            "goal_id": goal.get("goal_id"),
            "target": goal.get("target"),
            "pool": pool,
            "priority": template["priority"],
            "release_tier": template["release_tier"],
            "assigned_department": template["assigned_department"],
            "primary_artifact_id": template.get("primary_artifact_id"),
        })
        open_targets.add(target_lower)

    refreshed_goals = list_goals()
    refreshed_tasks = _load_json(TASKS, [])
    refreshed_scoped_goals = refreshed_goals
    refreshed_scoped_tasks = refreshed_tasks
    if focus.get("single_product_mode"):
        refreshed_scoped_goals = [goal for goal in refreshed_goals if goal.get("status") not in ACTIVE_GOAL_STATUSES or goal_matches_focus(goal, focus)]
        refreshed_focus_goal_ids = {str(goal.get("goal_id") or "") for goal in refreshed_scoped_goals if goal.get("status") in ACTIVE_GOAL_STATUSES}
        refreshed_scoped_tasks = [task for task in refreshed_tasks if str(task.get("goal_id") or "") in refreshed_focus_goal_ids]
    payload = {
        "updated_at": _utc(),
        "status": "active",
        "policy": {
            "pool_targets": POOL_TARGETS,
            "desired_goals": desired_goals,
            "min_active_tasks": min_active_tasks,
            "desired_ready_nodes": desired_ready_nodes,
            "recovery_mode": recovery_mode,
            "graph_dependency_aliases": GRAPH_DEPENDENCY_ALIASES,
            "production_focus": focus,
        },
        "supply_before_seed": supply_before_seed,
        "supply_after_seed": _summarize_supply(refreshed_scoped_goals, refreshed_scoped_tasks),
        "backfilled_goals": backfilled_goals,
        "repaired_graphs": repaired_graphs,
        "upgraded_graphs": upgraded_graphs,
        "seeded_goals": seeded_goals,
        "release_train_status": (release_ops.get("release_train") or {}).get("status"),
        "ready_shortage": ready_shortage,
        "ai_testing_status": ai_testing.get("status"),
    }
    _save_json(STATUS, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_factory_task_engine(), ensure_ascii=False, indent=2))



