from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.goal_registry import create_goal, list_goals
from tools.knowledge_engine import rebuild_knowledge
from tools.experiment_planner import plan_experiments
from tools.global_policy_engine import run_global_policy
from tools.module_ownership import patch_review_queue
from tools.project_graph import analyze_project_impact
from tools.organization_model import build_organization_model
from tools.cross_project_coordination import run_cross_project_coordination
from tools.organization_workboard import build_organization_workboard
from tools.branch_workboard import build_branch_workboard
from tools.release_operations import run_release_operations_status
from tools.tool_health_audit import run_tool_health_audit, read_tool_health_history
from tools.ai_testing_compat import load_ai_test_status

DATA = ROOT / "data"
OUT = DATA / "decision_engine_status.json"
TASKS = DATA / "tasks.json"
CONTROL = DATA / "control_layer_status.json"
EXPERIMENT_EVALUATION = DATA / "experiment_evaluation.json"
AI_TEST = DATA / "ai_test_status.json"

MIN_ACTIVE_GOALS = 3
MIN_ACTIVE_TASKS = 3
MAX_PENDING_GOALS = 5
GOAL_COOLDOWN_HOURS = 2
AI_TEST_PRIORITY_BONUS = 0.18
TASK_ACTIVE_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
TASK_STARVATION_BLOCKED_SOURCES = {
    "tool-health-policy",
    "cross-project-coordination",
    "project-graph-policy",
    "organization-workboard",
    "organization-policy",
    "branch-workboard-policy",
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


def _active_goal_count(goals: list[dict[str, Any]]) -> int:
    return sum(1 for item in goals if item.get("status") in {"pending", "planned", "running"})


def _active_task_count(tasks: list[dict[str, Any]]) -> int:
    return sum(1 for item in tasks if str(item.get("status") or "") in {"planning", "running", "verification_pending", "verification_running"})


def _recent_goal_targets(goals: list[dict[str, Any]]) -> set[str]:
    recent = set()
    now = datetime.now(timezone.utc)
    for item in goals:
        target = (item.get("target") or "").strip().lower()
        ts = _parse_goal_ts(item.get("updated_at") or item.get("created_at"))
        if not target or ts is None:
            continue
        if now - ts <= timedelta(hours=GOAL_COOLDOWN_HOURS):
            recent.add(target)
    return recent


def _parse_goal_ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _inject_experiment_option(
    options: list[dict[str, Any]],
    experiment_plan: dict[str, Any],
    latest_experiment: dict[str, Any],
) -> None:
    selected_experiment = experiment_plan.get("selected")
    if selected_experiment:
        boost = 0.04 if latest_experiment.get("adopt") else 0.0
        options.append(
            {
                "target": selected_experiment.get("target"),
                "goal_type": selected_experiment.get("goal_type") or "experiment",
                "notes": selected_experiment.get("notes") or "Knowledge-guided experiment.",
                "goal_alignment": 0.76 + boost,
                "progress_gain": 0.72 + boost,
                "risk_cost": 0.18,
                "resource_cost": 0.18,
                "source": "experiment-planner",
                "knowledge_hits": experiment_plan.get("knowledge_hits", []),
            }
        )


def _repo_learning_focus(knowledge: dict[str, Any]) -> dict[str, list[str]]:
    repo_learning = knowledge.get("repo_learning") or {}
    top_modules = repo_learning.get("top_modules") or []
    layers = []
    owner_teams = []
    modules = []
    for item in top_modules[:12]:
        layer = str(item.get("layer") or "").strip()
        owner = str(item.get("owner_team") or "").strip()
        module = str(item.get("module") or "").strip()
        if layer and layer not in layers:
            layers.append(layer)
        if owner and owner not in owner_teams:
            owner_teams.append(owner)
        if module:
            modules.append(module)
    return {
        "layers": layers,
        "owner_teams": owner_teams,
        "modules": modules,
    }


def _candidate_options(
    goals: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    knowledge: dict[str, Any],
    experiment_plan: dict[str, Any],
    latest_experiment: dict[str, Any],
    global_policy: dict[str, Any],
    ai_testing: dict[str, Any],
) -> list[dict[str, Any]]:
    open_targets = {
        (item.get("target") or "").strip().lower()
        for item in goals
        if item.get("status") in {"pending", "planned", "running"}
    }
    recent_targets = _recent_goal_targets(goals)
    failed = [item for item in tasks if item.get("status") in {"failed", "timed_out"}]
    waiting = [item for item in tasks if item.get("status") == "waiting_approval"]
    patterns = knowledge.get("decision_patterns", [])
    failures = knowledge.get("failure_solutions", [])
    experiment_patterns = knowledge.get("experiment_patterns", [])
    decision_hints = knowledge.get("decision_hints", {})
    preferred_goal_types = set(decision_hints.get("preferred_goal_types", []))
    focus_capabilities = [
        str(item).strip().lower() for item in global_policy.get("focus_capabilities", []) if item
    ]
    focus_capability_set = set(focus_capabilities)
    preferred_targets = {
        str(item).strip().lower() for item in decision_hints.get("priority_targets", []) if item
    }
    resource_budget = global_policy.get("resource_budget") or {}
    avoided_targets = {
        str(item).strip().lower() for item in decision_hints.get("avoid_targets", []) if item
    }
    repo_focus = _repo_learning_focus(knowledge)
    project_impact = analyze_project_impact(
        " ".join(sorted(open_targets)) or "active engineering portfolio",
        focus_modules=repo_focus.get("modules", []),
    )
    cross_project = run_cross_project_coordination()
    organization = build_organization_model()
    workboard = build_organization_workboard()
    branch_workboard = build_branch_workboard()
    project_allocations = organization.get("project_allocations") or []
    patch_queue = patch_review_queue()
    release_ops = run_release_operations_status()
    tool_health = run_tool_health_audit()
    tool_health_history = read_tool_health_history(limit=12)
    ai_status = str(ai_testing.get("status") or "missing")
    ai_pass_rate = float(ai_testing.get("pass_rate", 0.0) or 0.0)
    ai_error_count = int(ai_testing.get("error_count", 0) or 0)
    ai_failures = list(ai_testing.get("failing_case_ids", []))
    repo_layers = {str(item).strip().lower() for item in repo_focus.get("layers", []) if item}
    repo_teams = {str(item).strip().lower() for item in repo_focus.get("owner_teams", []) if item}

    options = [
        {
            "target": "Run platform verification sweep",
            "goal_type": "verify_platforms",
            "notes": "Auto-generated low-risk verification sweep for existing platforms.",
            "goal_alignment": 0.9,
            "progress_gain": 0.8,
            "risk_cost": 0.2,
            "resource_cost": 0.3,
            "source": "default-progress-policy",
        },
        {
            "target": "Improve cheap agent prompts",
            "goal_type": "build_product",
            "notes": "Auto-generated prompt optimization pass based on recent task outcomes.",
            "goal_alignment": 0.85,
            "progress_gain": 0.7,
            "risk_cost": 0.15,
            "resource_cost": 0.2,
            "source": "default-progress-policy",
        },
        {
            "target": "Optimize task scheduler from agent experience",
            "goal_type": "build_product",
            "notes": "Auto-generated scheduler optimization based on agent experience.",
            "goal_alignment": 0.8,
            "progress_gain": 0.75,
            "risk_cost": 0.25,
            "resource_cost": 0.25,
            "source": "default-progress-policy",
        },
        {
            "target": "Expand capability routing patterns",
            "goal_type": "build_product",
            "notes": "Auto-generated capability routing improvement based on recent routed tasks.",
            "goal_alignment": 0.78,
            "progress_gain": 0.68,
            "risk_cost": 0.2,
            "resource_cost": 0.2,
            "source": "default-progress-policy",
        },
    ]
    if (
        patch_queue.get("proposed_count", 0)
        or patch_queue.get("approved_count", 0)
        or patch_queue.get("ready_count", 0)
    ):
        options.append(
            {
                "target": "Review patch queue and verification gates",
                "goal_type": "build_product",
                "notes": "Auto-generated patch queue review and verification sweep for ownership-controlled changes.",
                "goal_alignment": 0.88,
                "progress_gain": 0.78,
                "risk_cost": 0.12,
                "resource_cost": 0.12,
                "source": "patch-queue-policy",
                "patch_queue": patch_queue,
            }
        )

    release_train = release_ops.get("release_train") or {}
    if release_train.get("status") == "blocked":
        options.append(
            {
                "target": "Advance release train operations",
                "goal_type": "build_product",
                "notes": "Auto-generated release and operations closure objective based on release train status.",
                "goal_alignment": 0.89,
                "progress_gain": 0.81,
                "risk_cost": 0.1,
                "resource_cost": 0.1,
                "source": "release-operations-policy",
                "priority_class": "release",
                "release_train": release_train,
            }
        )
    repeated_tool_failures = int(tool_health_history.get("recent_failure_count", 0) or 0)
    frequent_tool_issues = list((tool_health_history.get("issue_frequency") or {}).keys())[:4]
    if tool_health.get("status") == "attention":
        options.append(
            {
                "target": "Repair abnormal toolchain health",
                "goal_type": "build_product",
                "notes": "Auto-generated toolchain repair and verification objective based on tool health audit failures.",
                "goal_alignment": 0.93 + min(repeated_tool_failures, 3) * 0.01,
                "progress_gain": 0.86 + min(repeated_tool_failures, 3) * 0.01,
                "risk_cost": 0.08,
                "resource_cost": 0.12,
                "source": "tool-health-policy",
                "priority_class": "stability",
                "tool_health": tool_health,
                "tool_health_history": {
                    "recent_failure_count": repeated_tool_failures,
                    "issue_frequency": frequent_tool_issues,
                    "pass_ratio": tool_health_history.get("pass_ratio"),
                },
            }
        )

    if ai_status in {"degraded", "attention", "missing"} or ai_pass_rate < 0.8:
        options.append(
            {
                "target": "Stabilize AI reliability test lane",
                "goal_type": "verification_upgrade",
                "notes": f"Auto-generated AI reliability remediation objective from ai_testing status={ai_status}, pass_rate={ai_pass_rate:.2f}, error_count={ai_error_count}, failing_cases={ai_failures[:5]}",
                "goal_alignment": 0.94 if ai_error_count else 0.9,
                "progress_gain": 0.88 if ai_status != "pass" else 0.76,
                "risk_cost": 0.18 if ai_error_count else 0.24,
                "resource_cost": 0.27,
                "source": "ai-testing",
                "priority_class": "verification",
                "ai_testing": ai_testing,
            }
        )

    if patch_queue.get("ready_count", 0):
        options.append(
            {
                "target": "Merge ready patch queue",
                "goal_type": "build_product",
                "notes": "Auto-generated merge closure objective for patches that have already passed verification and review gates.",
                "goal_alignment": 0.91,
                "progress_gain": 0.84,
                "risk_cost": 0.08,
                "resource_cost": 0.08,
                "source": "patch-merge-policy",
                "priority_class": "merge",
                "patch_queue": patch_queue,
            }
        )

    if project_impact.get("cross_project_count", 0) > 1:
        options.append(
            {
                "target": "Coordinate cross-project integration surfaces",
                "goal_type": "build_product",
                "notes": "Auto-generated cross-project coordination pass for affected projects, APIs, and rollout dependencies.",
                "goal_alignment": 0.86,
                "progress_gain": 0.76,
                "risk_cost": 0.16,
                "resource_cost": 0.18,
                "source": "project-graph-policy",
                "priority_class": "coordination",
                "project_impact": project_impact,
            }
        )

    for item in (cross_project.get("selected") or [])[:3]:
        options.append(
            {
                "target": item.get("target"),
                "goal_type": "build_product",
                "notes": item.get("notes") or "Cross-project coordination candidate.",
                "goal_alignment": 0.87,
                "progress_gain": 0.77,
                "risk_cost": 0.14,
                "resource_cost": 0.16,
                "source": "cross-project-coordination",
                "priority_class": "coordination",
                "project_impact": {
                    "related_projects": item.get("projects", []),
                    "cross_project_count": len(item.get("projects", [])),
                },
                "coordination_departments": item.get("departments", []),
            }
        )

    active_branch_lanes = branch_workboard.get("active_lanes") or []
    for lane in active_branch_lanes[:3]:
        lane_data = lane if isinstance(lane, dict) else {"lane": lane}
        lane_name = str(lane_data.get("lane") or "branch").strip()
        owner_department = lane_data.get("assigned_department")
        branch_context_ref = lane_data.get("branch_context_ref")
        options.append(
            {
                "target": f"Support {lane_name.replace('-', ' ')} branch delivery",
                "goal_type": "build_product",
                "notes": "Auto-generated branch support objective based on active branch lane pressure and reusable mainline context.",
                "goal_alignment": 0.86,
                "progress_gain": 0.74,
                "risk_cost": 0.12,
                "resource_cost": 0.13,
                "source": "branch-workboard-policy",
                "priority_class": "coordination",
                "branch_lane": lane_name,
                "branch_context_ref": branch_context_ref,
                "owner_department": owner_department,
                "project_ids": lane_data.get("project_ids", []),
            }
        )

    top_org_departments = workboard.get("top_departments") or []
    for department in top_org_departments[:2]:
        options.append(
            {
                "target": f"Advance {department.replace('_', ' ')} workboard priorities",
                "goal_type": "build_product",
                "notes": "Auto-generated organization-layer objective based on department priority and workboard pressure.",
                "goal_alignment": 0.84,
                "progress_gain": 0.74,
                "risk_cost": 0.12,
                "resource_cost": 0.12,
                "source": "organization-workboard",
                "owner_department": department,
                "priority_class": "organization",
            }
        )

    if project_allocations:
        top_allocations = sorted(
            project_allocations,
            key=lambda item: len(item.get("support_departments", [])),
            reverse=True,
        )[:3]
        for item in top_allocations:
            options.append(
                {
                    "target": f"Coordinate {item.get('name')} with organization departments",
                    "goal_type": "build_product",
                    "notes": "Auto-generated organization coordination objective based on project allocations and department responsibilities.",
                    "goal_alignment": 0.83,
                    "progress_gain": 0.73,
                    "risk_cost": 0.14,
                    "resource_cost": 0.14,
                    "source": "organization-policy",
                    "priority_class": "coordination",
                    "owner_department": item.get("owner_department"),
                    "support_departments": item.get("support_departments", []),
                }
            )

    capability_goal_templates = {
        "webapp_generation": {
            "target": "Strengthen webapp generation capability",
            "goal_type": "build_product",
            "notes": "Improve webapp generation templates, routing confidence, and verification coverage.",
        },
        "agent_orchestration": {
            "target": "Strengthen agent orchestration capability",
            "goal_type": "build_product",
            "notes": "Improve orchestration patterns, worker coordination, and ownership-aware execution.",
        },
        "deploy_scaffold": {
            "target": "Improve deployment scaffold automation",
            "goal_type": "build_product",
            "notes": "Improve deployment scaffolds, verification steps, and rollout preparation.",
        },
        "tool_extension": {
            "target": "Expand tool extension coverage",
            "goal_type": "build_product",
            "notes": "Expand tool adapters and improve routing coverage for registered tools.",
        },
    }
    for capability_id in list(focus_capabilities)[:3]:
        template = capability_goal_templates.get(capability_id)
        if not template:
            continue
        options.append(
            {
                **template,
                "goal_alignment": 0.84,
                "progress_gain": 0.74,
                "risk_cost": 0.18,
                "resource_cost": 0.18,
                "source": "global-policy-focus-capability",
                "focus_capability": capability_id,
                "priority_class": "capability-building",
            }
        )
        options.append(
            {
                "target": f"Run verification for {capability_id.replace('_', ' ')}",
                "goal_type": "build_product",
                "notes": f"Verification-first follow-up for strategic capability {capability_id}.",
                "goal_alignment": 0.82,
                "progress_gain": 0.7,
                "risk_cost": 0.14,
                "resource_cost": 0.12,
                "source": "global-policy-verification-capability",
                "focus_capability": capability_id,
                "priority_class": "verification",
            }
        )

    _inject_experiment_option(options, experiment_plan, latest_experiment)

    for option in options:
        lowered = option["target"].strip().lower()
        if lowered in open_targets:
            option["blocked"] = True
            option["block_reason"] = "duplicate-open-goal"
        elif lowered in recent_targets:
            option["blocked"] = True
            option["block_reason"] = "cooldown-window"
        if failed:
            option["progress_gain"] = round(option["progress_gain"] + 0.05, 3)
        if waiting:
            option["risk_cost"] = round(option["risk_cost"] + 0.05, 3)
        if patterns:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.02, 3)
        if failures:
            option["progress_gain"] = round(option["progress_gain"] + 0.02, 3)
        if experiment_patterns:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.03, 3)
        if latest_experiment.get("adopt"):
            option["progress_gain"] = round(option["progress_gain"] + 0.03, 3)
        if option["goal_type"] in preferred_goal_types:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.04, 3)
        if lowered in preferred_targets:
            option["progress_gain"] = round(option["progress_gain"] + 0.04, 3)
        if lowered in avoided_targets:
            option["risk_cost"] = round(option["risk_cost"] + 0.12, 3)
        if "capability" in lowered and any(cap in lowered for cap in focus_capability_set):
            option["progress_gain"] = round(option["progress_gain"] + 0.04, 3)
        if option.get("focus_capability") in focus_capability_set:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.06, 3)
            option["progress_gain"] = round(option["progress_gain"] + 0.04, 3)
        if "scheduler" in lowered and "agent_orchestration" in focus_capability_set:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.04, 3)
        if "prompt" in lowered and "deploy_scaffold" in focus_capability_set:
            option["progress_gain"] = round(option["progress_gain"] + 0.02, 3)
        if "architecture_engine" in repo_layers and "scheduler" in lowered:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.03, 3)
        if "infrastructure_team" in repo_teams and "capability" in lowered:
            option["progress_gain"] = round(option["progress_gain"] + 0.02, 3)
        if "backend_team" in repo_teams and "verification" in lowered:
            option["goal_alignment"] = round(option["goal_alignment"] + 0.02, 3)
        option["repo_focus"] = repo_focus
        option["resource_budget"] = resource_budget
        option["patch_queue"] = patch_queue
        option["project_impact"] = project_impact
        option["goal_alignment"] = round(float(option.get("goal_alignment", 0.0) or 0.0), 3)
        option["progress_gain"] = round(float(option.get("progress_gain", 0.0) or 0.0), 3)
        option["risk_cost"] = round(
            min(1.0, max(0.0, float(option.get("risk_cost", 0.0) or 0.0))), 3
        )
        option["resource_cost"] = round(
            min(1.0, max(0.0, float(option.get("resource_cost", 0.0) or 0.0))), 3
        )
        if option.get("owner_department"):
            option["goal_alignment"] = round(option["goal_alignment"] + 0.04, 3)
            option["progress_gain"] = round(option["progress_gain"] + 0.02, 3)
        priority_class = option.get("priority_class") or "runtime"
        if priority_class == "capability-building":
            option["progress_gain"] = round(
                option["progress_gain"]
                + float(resource_budget.get("capability_building", 0.0) or 0.0) * 0.1,
                3,
            )
            option["resource_cost"] = round(
                max(
                    0.05,
                    option["resource_cost"]
                    - float(resource_budget.get("capability_building", 0.0) or 0.0) * 0.05,
                ),
                3,
            )
        elif priority_class == "verification":
            option["goal_alignment"] = round(
                option["goal_alignment"]
                + float(resource_budget.get("maintenance", 0.0) or 0.0) * 0.08,
                3,
            )
        elif priority_class == "runtime":
            option["progress_gain"] = round(
                option["progress_gain"]
                + float(resource_budget.get("runtime_tasks", 0.0) or 0.0) * 0.05,
                3,
            )
        elif priority_class == "coordination":
            option["goal_alignment"] = round(
                option["goal_alignment"]
                + 0.05
                + float(resource_budget.get("maintenance", 0.0) or 0.0) * 0.04,
                3,
            )
            option["progress_gain"] = round(option["progress_gain"] + 0.03, 3)
        option["goal_alignment"] = round(min(1.0, max(0.0, option["goal_alignment"])), 3)
        option["progress_gain"] = round(min(1.0, max(0.0, option["progress_gain"])), 3)
        option["score"] = round(
            option["goal_alignment"] * 0.4
            + option["progress_gain"] * 0.35
            + (1.0 - option["risk_cost"]) * 0.15
            + (1.0 - option["resource_cost"]) * 0.10,
            4,
        )
        if option.get("source") == "ai-testing":
            option["score"] = round(min(1.0, option["score"] + AI_TEST_PRIORITY_BONUS), 4)
            option["priority_boost"] = "ai-testing"
    options.sort(
        key=lambda item: ((1 if item.get("source") == "ai-testing" else 0), item.get("score", 0.0)),
        reverse=True,
    )
    return options


def decide_next_goal() -> dict[str, Any]:
    goals = list_goals()
    tasks = _load_json(TASKS, [])
    control = _load_json(CONTROL, {})
    knowledge = rebuild_knowledge()
    repo_focus = _repo_learning_focus(knowledge)
    project_impact = analyze_project_impact(
        "active engineering portfolio",
        focus_modules=repo_focus.get("modules", []),
    )
    cross_project = run_cross_project_coordination()
    experiment_plan = plan_experiments()
    global_policy = run_global_policy()
    organization = build_organization_model()
    build_organization_workboard()
    build_branch_workboard()
    latest_experiment = _load_json(EXPERIMENT_EVALUATION, {})
    ai_testing = load_ai_test_status(AI_TEST)
    active_goals = _active_goal_count(goals)
    active_task_count = _active_task_count(tasks)
    options = _candidate_options(
        goals, tasks, knowledge, experiment_plan, latest_experiment, global_policy, ai_testing
    )
    if active_task_count < MIN_ACTIVE_TASKS:
        for option in options:
            if option.get("source") in TASK_STARVATION_BLOCKED_SOURCES and not option.get(
                "blocked"
            ):
                option["blocked"] = True
                option["block_reason"] = "task-starvation-prefers-dispatchable-work"
            if (
                option.get("source") == "ai-testing"
                and option.get("block_reason") == "cooldown-window"
            ):
                option.pop("blocked", None)
                option.pop("block_reason", None)
                option["priority_boost"] = "task-starvation-override"

    decision = {
        "updated_at": _utc(),
        "active_goals": active_goals,
        "active_tasks": active_task_count,
        "pending_or_running_goals": active_goals,
        "candidate_count": len(options),
        "selected": None,
        "action": "hold",
        "reason": "enough-active-goals",
        "options": options[:6],
        "experiment_plan": {
            "candidate_count": experiment_plan.get("candidate_count", 0),
            "selected": experiment_plan.get("selected"),
            "knowledge_hits": experiment_plan.get("knowledge_hits", []),
        },
        "knowledge_hints": knowledge.get("decision_hints", {}),
        "repo_learning": repo_focus,
        "project_impact": project_impact,
        "global_policy": global_policy,
        "organization": {
            "department_count": len((organization.get("departments") or {})),
            "top_departments": global_policy.get("organization_priority", {}).get(
                "departments", []
            ),
        },
        "cross_project_coordination": {
            "candidate_count": cross_project.get("candidate_count", 0),
            "selected": cross_project.get("selected", [])[:3],
        },
        "ai_testing": ai_testing,
    }

    if active_goals >= MIN_ACTIVE_GOALS and active_task_count >= MIN_ACTIVE_TASKS:
        decision["reason"] = "enough-active-goals-and-tasks"
        _save_json(OUT, decision)
        return decision

    if active_goals >= MAX_PENDING_GOALS:
        decision["reason"] = "pending-goal-cap-reached"
        _save_json(OUT, decision)
        return decision

    if control.get("status") == "operator_attention":
        decision["reason"] = "control-layer-attention"
        _save_json(OUT, decision)
        return decision

    if ai_testing.get("status") == "degraded" and int(ai_testing.get("error_count", 0) or 0) > 0:
        decision["reason"] = "ai-testing-degraded"

    selected = next((item for item in options if not item.get("blocked")), None)
    if not selected:
        decision["reason"] = "no-safe-candidate"
        _save_json(OUT, decision)
        return decision

    priority_class = str(selected.get("priority_class") or "runtime")
    factory_pool = (
        "research"
        if selected.get("goal_type") == "experiment" or priority_class == "research"
        else "ops"
        if priority_class in {"release", "verification", "merge", "stability"}
        else "production"
    )
    assigned_department = selected.get("owner_department") or (
        "rnd_department"
        if factory_pool == "research"
        else "qa_department"
        if priority_class == "verification"
        else "operations_department"
        if factory_pool == "ops"
        else "engineering_department"
    )
    release_tier = (
        "experimental"
        if factory_pool == "research"
        else "mainline"
        if priority_class in {"release", "stability"}
        else "normal"
    )
    factory_priority = (
        "P3"
        if factory_pool == "research"
        else "P1"
        if factory_pool == "ops"
        else "P0"
        if priority_class == "runtime"
        else "P2"
    )

    goal = create_goal(
        selected["target"],
        goal_type=selected["goal_type"],
        notes=selected["notes"],
        assigned_department=assigned_department,
        factory_pool=factory_pool,
        factory_priority=factory_priority,
        priority_class=priority_class,
        release_tier=release_tier,
        cost=selected.get("resource_cost"),
        reward=selected.get("goal_alignment"),
        derived_from={
            "source": selected.get("source"),
            "knowledge_hits": selected.get("knowledge_hits", []),
        },
        scoring={
            "value": selected.get("goal_alignment", 0.7),
            "urgency": selected.get("progress_gain", 0.6),
            "success": 1.0 - float(selected.get("risk_cost", 0.25) or 0.25),
            "cost": max(0.05, float(selected.get("resource_cost", 0.25) or 0.25)),
            "reward": selected.get("goal_alignment", 0.7),
        },
    )
    decision["selected"] = {
        "goal_id": goal.get("goal_id"),
        "target": goal.get("target"),
        "goal_type": goal.get("type"),
        "score": selected.get("score"),
        "priority_score": goal.get("priority_score"),
        "source": selected.get("source"),
        "knowledge_hits": selected.get("knowledge_hits", []),
    }
    decision["action"] = "create-goal"
    decision["reason"] = "progress-first-policy"
    _save_json(OUT, decision)
    return decision


if __name__ == "__main__":
    print(json.dumps(decide_next_goal(), ensure_ascii=False, indent=2))
