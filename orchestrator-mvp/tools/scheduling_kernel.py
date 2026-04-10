from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime.scheduler import schedule_nodes
from tools.io_utils import atomic_write_json
from tools.production_focus import build_production_focus, goal_matches_focus

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATUS = DATA / "scheduling_kernel_status.json"
TASKS = DATA / "tasks.json"
CHECKPOINTS = DATA / "task_checkpoints.json"
VERIFICATION_STATUS = DATA / "verification_status.json"
RELEASE_OPERATIONS_STATUS = DATA / "release_operations_status.json"
FACTORY_RUNTIME = ROOT / "factory" / "runtime" / "tasks"

RUNNING_TASK_STATUSES = {"planning", "running"}
DEFAULT_TIMESLICE_SECONDS = 60
AGING_FACTOR_PER_HOUR = 0.08
PREEMPT_MARGIN = 0.12
MAINLINE_PROGRESS_THRESHOLD = 0.45
PLANNING_STUCK_MINUTES = 20
RUNNING_STUCK_MINUTES = 20
WAITING_APPROVAL_STUCK_MINUTES = 60
UNBLOCK_QUEUE_LIMIT = 25
CANONICAL_TASK_STATES = (
    "queued",
    "ready",
    "blocked",
    "running",
    "retry",
    "waiting_approval",
    "done",
    "failed",
)
PRIORITY_BONUS = {
    "P0": 0.35,
    "P1": 0.22,
    "P2": 0.1,
    "P3": 0.0,
}
POOL_BONUS = {
    "production": 0.18,
    "ops": 0.1,
    "research": 0.02,
}
RELEASE_TIER_BONUS = {
    "mainline": 0.08,
    "normal": 0.04,
    "experimental": 0.0,
}
ARTIFACT_STAGE_BONUS = {
    "artifact-build": 0.35,
    "artifact-test": 0.28,
    "artifact-audit": 0.18,
    "artifact-evidence": 0.14,
    "implementation": 0.08,
    "module-implementation": 0.08,
    "verification": 0.04,
    "architecture": -0.18,
    "planning": -0.12,
}
VALIDATION_ONLY_MARKERS = (
    "syntax",
    "strategy validation",
    "reuse probe",
    "read_only_syntax_check",
    "analysis only",
)
DELIVERY_PATH_MARKERS = (
    "build",
    "qemu",
    "kernel.bin",
    "deliver",
    "artifact",
    "release",
    "score-report",
    "build-report",
)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _is_mainline(goal: dict[str, Any]) -> bool:
    lane = str(goal.get("lane") or "").lower()
    lane_role = str(goal.get("lane_role") or "").lower()
    pool = _goal_pool(goal)
    tier = _release_tier(goal)
    return lane == "mainline" or lane_role.startswith("architecture") or pool == "production" or tier == "mainline"


def _goal_pool(goal: dict[str, Any]) -> str:
    if _is_unblock_goal(goal):
        return "ops"
    explicit = str(goal.get("factory_pool") or "").strip().lower()
    if explicit in POOL_BONUS:
        return explicit
    assigned_department = str(goal.get("assigned_department") or "").strip().lower()
    goal_type = str(goal.get("type") or "").strip().lower()
    target = str(goal.get("target") or "").strip().lower()
    priority_class = str(goal.get("priority_class") or "").strip().lower()
    if assigned_department == "rnd_department" or goal_type == "experiment" or target.startswith("experiment "):
        return "research"
    if assigned_department in {"operations_department", "qa_department"} or priority_class in {"release", "verification", "merge", "stability"}:
        return "ops"
    return "production"


def _priority_band(goal: dict[str, Any]) -> str:
    if _is_unblock_goal(goal):
        return "P1"
    explicit = str(goal.get("factory_priority") or "").strip().upper()
    if explicit in PRIORITY_BONUS:
        return explicit
    target = str(goal.get("target") or "").strip().lower()
    goal_type = str(goal.get("type") or "").strip().lower()
    pool = _goal_pool(goal)
    if pool == "research" or goal_type == "experiment":
        return "P3"
    if any(token in target for token in ("release", "repair", "stabilize ai reliability", "merge ready", "verification")):
        return "P1"
    if any(token in target for token in ("strengthen", "mainline", "ship", "build ")):
        return "P0"
    return "P2"


def _release_tier(goal: dict[str, Any]) -> str:
    explicit = str(goal.get("release_tier") or "").strip().lower()
    if explicit in RELEASE_TIER_BONUS:
        return explicit
    return "experimental" if _goal_pool(goal) == "research" else "mainline" if _priority_band(goal) == "P0" else "normal"


def _is_unblock_goal(goal: dict[str, Any]) -> bool:
    goal_type = str(goal.get("goal_type") or goal.get("type") or "").strip().lower()
    target = str(goal.get("target") or "").strip().lower()
    priority_class = str(goal.get("priority_class") or "").strip().lower()
    return (
        target.startswith("unblock ")
        or goal_type in {"repair", "recovery", "maintenance", "replan"}
        or priority_class in {"repair", "recovery", "unblock"}
    )


def _goal_progress(goal: dict[str, Any], graph: dict[str, Any]) -> float:
    evaluation = goal.get("evaluation") or {}
    ratio = evaluation.get("completion_ratio")
    if ratio is not None:
        try:
            return round(float(ratio), 4)
        except Exception:
            pass
    nodes = graph.get("nodes", []) or []
    if not nodes:
        return 0.0
    completed = sum(1 for node in nodes if node.get("status") in {"completed", "ready_for_merge"})
    return round(completed / len(nodes), 4)


def _ready_since(goal: dict[str, Any], node: dict[str, Any]) -> datetime:
    for raw in (
        node.get("ready_since"),
        node.get("updated_at"),
        goal.get("updated_at"),
        goal.get("created_at"),
    ):
        parsed = _parse_time(raw)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def _wait_hours(goal: dict[str, Any], node: dict[str, Any]) -> float:
    delta = datetime.now(timezone.utc) - _ready_since(goal, node)
    return max(0.0, delta.total_seconds() / 3600.0)


def _resource_bonus(selection: dict[str, Any]) -> float:
    success = float(selection.get("worker_success_rate", 0.0) or 0.0)
    lane = str(selection.get("execution_lane") or "")
    bonus = min(0.08, success * 0.1)
    if lane == "worker-vm":
        bonus += 0.02
    return round(bonus, 4)


def _delivery_path_bonus(node: dict[str, Any]) -> float:
    kind = str(node.get("kind") or "").strip().lower()
    corpus = " ".join(str(part or "") for part in [node.get("title"), node.get("prompt"), kind]).lower()
    bonus = 0.0
    if kind in {"artifact-build", "artifact-test", "artifact-audit", "artifact-evidence"}:
        bonus += 0.14
    elif kind in {"implementation", "module-implementation"}:
        bonus += 0.08
    elif kind == "verification":
        bonus += 0.02
    elif kind in {"architecture", "planning", "cross-project-coordination", "cross-project-work-package", "cross-project-coordination-package"}:
        bonus -= 0.12
    if any(marker in corpus for marker in DELIVERY_PATH_MARKERS):
        bonus += 0.08
    if any(marker in corpus for marker in VALIDATION_ONLY_MARKERS):
        bonus -= 0.18
    return round(bonus, 4)


def _first_artifact_bonus(graph: dict[str, Any], node: dict[str, Any]) -> float:
    meta = graph.get("meta") or {}
    policy = meta.get("first_artifact_policy") or {}
    required = bool(policy.get("required")) or str(meta.get("route_strategy") or "") == "artifact-first"
    if not required or meta.get("first_artifact_observed_at"):
        return 0.0
    kind = str(node.get("kind") or "").strip().lower()
    if kind == "artifact-build":
        return 0.32
    if kind == "artifact-test":
        return 0.24
    if kind in {"artifact-audit", "artifact-evidence"}:
        return 0.14
    if kind in {"architecture", "planning", "cross-project-coordination", "cross-project-work-package", "cross-project-coordination-package"}:
        return -0.28
    return -0.06


def _stagnation_penalty(goal: dict[str, Any], graph: dict[str, Any], node: dict[str, Any]) -> float:
    wait_hours = _wait_hours(goal, node)
    progress = _goal_progress(goal, graph)
    blockers = len((goal.get("evaluation") or {}).get("blockers", []) or [])
    penalty = min(0.35, wait_hours * AGING_FACTOR_PER_HOUR)
    if progress < 0.34:
        penalty += 0.05
    if blockers:
        penalty += min(0.05, blockers * 0.02)
    return round(min(0.35, penalty), 4)


def _priority_components(goal: dict[str, Any], graph: dict[str, Any], node: dict[str, Any], selection: dict[str, Any], focus: dict[str, Any]) -> dict[str, float | str]:
    scoring = goal.get("scoring") or {}
    goal_weight = float(goal.get("priority_score", 0.0) or 0.0)
    urgency = float(scoring.get("urgency", 0.0) or 0.0)
    stagnation_penalty = _stagnation_penalty(goal, graph, node)
    resource_bonus = _resource_bonus(selection)
    priority_band = _priority_band(goal)
    factory_pool = _goal_pool(goal)
    release_tier = _release_tier(goal)
    priority_bonus = PRIORITY_BONUS.get(priority_band, 0.0)
    pool_bonus = POOL_BONUS.get(factory_pool, 0.0)
    release_bonus = RELEASE_TIER_BONUS.get(release_tier, 0.0)
    node_kind = str(node.get("kind") or "")
    artifact_stage_bonus = ARTIFACT_STAGE_BONUS.get(node_kind, 0.0)
    delivery_bonus = _delivery_path_bonus(node)
    first_artifact_bonus = _first_artifact_bonus(graph, node)
    focus_bonus = 0.0
    if focus.get("single_product_mode") and goal_matches_focus(goal, focus) and not bool((focus.get("artifact") or {}).get("real")):
        focus_bonus = 0.35
    elif goal_matches_focus(goal, focus) and not bool((focus.get("artifact") or {}).get("real")):
        focus_bonus = 0.12
    effective_priority = round(goal_weight + urgency + stagnation_penalty + resource_bonus + priority_bonus + pool_bonus + release_bonus + artifact_stage_bonus + delivery_bonus + first_artifact_bonus + focus_bonus, 4)
    return {
        "goal_weight": round(goal_weight, 4),
        "urgency": round(urgency, 4),
        "stagnation_penalty": stagnation_penalty,
        "resource_bonus": resource_bonus,
        "priority_bonus": round(priority_bonus, 4),
        "pool_bonus": round(pool_bonus, 4),
        "release_bonus": round(release_bonus, 4),
        "artifact_stage_bonus": round(artifact_stage_bonus, 4),
        "delivery_bonus": round(delivery_bonus, 4),
        "first_artifact_bonus": round(first_artifact_bonus, 4),
        "focus_bonus": round(focus_bonus, 4),
        "priority_band": priority_band,
        "factory_pool": factory_pool,
        "release_tier": release_tier,
        "effective_priority": effective_priority,
    }


def _checkpoint_dir(task_id: str) -> str:
    return str(FACTORY_RUNTIME / task_id)


def _running_task_priority(task: dict[str, Any], goal_lookup: dict[str, dict[str, Any]], checkpoints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    goal = goal_lookup.get(str(task.get("goal_id") or ""))
    checkpoint = checkpoints.get(str(task.get("id") or ""), {})
    base = float((goal or {}).get("priority_score", 0.0) or 0.0)
    urgency = float(((goal or {}).get("scoring") or {}).get("urgency", 0.0) or 0.0)
    status_bonus = 0.04 if str(task.get("status") or "") == "running" else 0.0
    interruptible = str(checkpoint.get("phase") or "") in {"planning", "running", "step-running", "step-completed"}
    priority_band = _priority_band(goal or {})
    factory_pool = _goal_pool(goal or {})
    effective_priority = round(base + urgency + status_bonus + PRIORITY_BONUS.get(priority_band, 0.0) + POOL_BONUS.get(factory_pool, 0.0), 4)
    return {
        "task_id": task.get("id"),
        "goal_id": task.get("goal_id"),
        "node_id": task.get("node_id") or ((task.get("scheduler_hint") or {}).get("node_id")),
        "goal": task.get("goal"),
        "status": task.get("status"),
        "interruptible": interruptible,
        "factory_pool": factory_pool,
        "priority_band": priority_band,
        "effective_priority": effective_priority,
        "checkpoint_phase": checkpoint.get("phase"),
        "checkpoint_dir": _checkpoint_dir(str(task.get("id") or "")),
    }


def _task_retry_limit(task: dict[str, Any]) -> int:
    for key in ("retry_limit", "max_retries"):
        raw = task.get(key)
        if raw is None:
            continue
        try:
            return max(0, int(raw))
        except Exception:
            continue
    return 0


def _task_retry_count(task: dict[str, Any], node: dict[str, Any] | None = None) -> int:
    for source in (task, node or {}):
        for key in ("retry_count", "requeue_count", "attempt_count"):
            raw = source.get(key)
            if raw is None:
                continue
            try:
                return max(0, int(raw))
            except Exception:
                continue
    return 0


def _task_dependency_blockers(task: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for dep in task.get("dependency_task_ids") or []:
        dep_id = str(dep or "").strip()
        if not dep_id:
            continue
        blockers.append({"gate": "dependency_gate", "kind": "task_dependency", "id": dep_id})
    return blockers


def _task_artifact_spec(task: dict[str, Any]) -> dict[str, Any] | None:
    spec = task.get("artifact_spec")
    if isinstance(spec, dict) and spec:
        return dict(spec)
    scheduler_hint = task.get("scheduler_hint") or {}
    hint_spec = scheduler_hint.get("artifact_spec") or {}
    payload = dict(hint_spec) if isinstance(hint_spec, dict) else {}
    required = [str(item) for item in (scheduler_hint.get("required_artifacts") or []) if str(item).strip()]
    if required and not payload.get("required_artifacts"):
        payload["required_artifacts"] = required
    if scheduler_hint.get("min_fresh_artifacts") and not payload.get("min_fresh_artifacts"):
        payload["min_fresh_artifacts"] = int(scheduler_hint.get("min_fresh_artifacts") or 1)
    return payload or None


def _task_requires_audit_gate(task: dict[str, Any]) -> bool:
    if str(task.get("execution_mode") or "").strip().lower() != "production":
        return False
    spec = _task_artifact_spec(task)
    return bool(spec and (spec.get("required_artifacts") or []))


def _task_has_verified_audit(task: dict[str, Any]) -> bool:
    result = task.get("result") or {}
    production_evidence = result.get("production_evidence") if isinstance(result, dict) else {}
    if isinstance(production_evidence, dict) and str(production_evidence.get("status") or "").strip().lower() == "verified":
        return True
    if not _task_requires_audit_gate(task):
        return True
    artifact_spec = _task_artifact_spec(task)
    if not artifact_spec:
        return False
    # The scheduler only needs a conservative signal, not a full audit replay.
    required = artifact_spec.get("required_artifacts") or []
    return bool(required) and bool(result.get("execution_evidence_path"))


def _node_dependency_blockers(node: dict[str, Any], completed_ids: set[str]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for dep in node.get("dependencies") or []:
        dep_id = str(dep or "").strip()
        if not dep_id:
            continue
        if dep_id not in completed_ids:
            blockers.append({"gate": "dependency_gate", "kind": "node_dependency", "id": dep_id})
    return blockers


def _global_gate_states() -> dict[str, dict[str, Any]]:
    verification = _load_json(VERIFICATION_STATUS, {})
    release_ops = _load_json(RELEASE_OPERATIONS_STATUS, {})
    verification_status = str(verification.get("status") or "").strip().lower()
    release_status = str(release_ops.get("status") or "").strip().lower()
    release_tiers = release_ops.get("release_tiers") or {}
    return {
        "verification_gate": {
            "status": "pass" if verification_status == "pass" else "blocked",
            "source_status": verification_status or "missing",
            "reason": None if verification_status == "pass" else "verification_status_not_pass",
        },
        "release_gate": {
            "status": "pass" if release_status == "pass" else "blocked",
            "source_status": release_status or "missing",
            "tiers": {
                tier: str((payload or {}).get("status") or "").strip().lower()
                for tier, payload in release_tiers.items()
            },
            "reason": None if release_status == "pass" else "release_operations_not_pass",
        },
    }


def _task_recovery_reason(task: dict[str, Any], checkpoints: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    task_status = str(task.get("status") or "").strip().lower()
    if task_status not in {"planning", "running", "waiting_approval"}:
        return None
    task_id = str(task.get("id") or "").strip()
    checkpoint = checkpoints.get(task_id) or {}
    heartbeat_at = None
    for raw in (
        checkpoint.get("heartbeat_at"),
        checkpoint.get("updated_at"),
        task.get("task_heartbeat_at"),
        task.get("updated_at"),
        task.get("created_at"),
    ):
        parsed = _parse_time(str(raw) if raw else None)
        if parsed is not None:
            heartbeat_at = parsed
            break
    if heartbeat_at is None:
        return None
    age_minutes = max(0.0, (datetime.now(timezone.utc) - heartbeat_at).total_seconds() / 60.0)
    if task_status == "planning" and age_minutes < PLANNING_STUCK_MINUTES:
        return None
    if task_status == "running" and age_minutes < RUNNING_STUCK_MINUTES:
        return None
    if task_status == "waiting_approval" and age_minutes < WAITING_APPROVAL_STUCK_MINUTES:
        return None
    gate = "planning_gate" if task_status == "planning" else "running_gate" if task_status == "running" else "approval_gate"
    return {
        "gate": gate,
        "kind": "stuck_task",
        "reason": f"{task_status}_stalled_for_{round(age_minutes, 2)}m",
        "task_id": task_id,
        "task_status": task_status,
        "age_minutes": round(age_minutes, 2),
        "goal": task.get("goal"),
        "title": task.get("title") or task.get("goal") or task_id,
        "repo_path": task.get("repo_path"),
    }


def _unblock_strategy(blockers: list[dict[str, Any]], task_status: str = "") -> str:
    gates = {str((item or {}).get("gate") or "").strip().lower() for item in blockers}
    if task_status == "planning" or "planning_gate" in gates:
        return "force_replan"
    if "dependency_gate" in gates:
        return "spawn_dependency_repair"
    if "artifact_gate" in gates:
        return "spawn_evidence_repair"
    if "approval_gate" in gates:
        return "request_approval_or_degrade"
    if "production_first_gate" in gates:
        return "route_to_unblock_lane"
    if "retry_gate" in gates:
        return "reset_or_supersede"
    if "verification_gate" in gates or "release_gate" in gates:
        return "verification_or_release_repair"
    if "running_gate" in gates:
        return "heartbeat_recovery"
    return "review_blockers"


def _pool_wip_cap(dispatch_budget: int, pool: str) -> int:
    target = POOL_BONUS.get(pool, 0.0)
    return max(1, int(round(dispatch_budget * max(target, 0.33))))


def _task_gate_decision(
    *,
    goal: dict[str, Any],
    graph: dict[str, Any],
    node: dict[str, Any],
    task: dict[str, Any] | None,
    selection: dict[str, Any],
    focus: dict[str, Any],
    running_counts: dict[str, int],
    dispatch_budget: int,
    completed_ids: set[str],
    global_gates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    task = task or {}
    pool = _goal_pool(goal)
    release_tier = _release_tier(goal)
    ready_since = _ready_since(goal, node)
    wait_hours = round(max(0.0, (datetime.now(timezone.utc) - ready_since).total_seconds() / 3600.0), 4)
    retry_limit = _task_retry_limit(task)
    retry_count = _task_retry_count(task, node)
    blockers: list[dict[str, Any]] = []
    gate_status = {
        "dependency_gate": "pass",
        "artifact_gate": "pass",
        "approval_gate": "pass",
        "planning_gate": "pass",
        "quota_gate": "pass",
        "verification_gate": "pass",
        "release_gate": "pass",
        "production_first_gate": "pass",
        "retry_gate": "pass",
    }

    dependency_blockers = _node_dependency_blockers(node, completed_ids)
    if dependency_blockers:
        blockers.extend(dependency_blockers)
        gate_status["dependency_gate"] = "blocked"

    task_dependency_blockers = _task_dependency_blockers(task)
    if task_dependency_blockers:
        blockers.extend(task_dependency_blockers)
        gate_status["dependency_gate"] = "blocked"

    if _task_requires_audit_gate(task) and not _task_has_verified_audit(task):
        blockers.append(
            {
                "gate": "artifact_gate",
                "kind": "artifact_audit",
                "reason": "required artifacts are not independently verified",
            }
        )
        gate_status["artifact_gate"] = "blocked"

    auto_approve = bool(task.get("auto_approve", True))
    task_status = str(task.get("status") or "").strip().lower()
    if task_status == "waiting_approval" or (not auto_approve and task_status in {"queued", "planning"}):
        blockers.append(
            {
                "gate": "approval_gate",
                "kind": "manual_approval",
                "reason": "task awaits approval before execution can begin",
            }
        )
        gate_status["approval_gate"] = "waiting_approval" if task_status == "waiting_approval" else "blocked"

    planning_ttl_hours = float(task.get("planning_ttl_hours") or 0.0)
    if task_status == "planning":
        ttl_hours = planning_ttl_hours if planning_ttl_hours > 0 else PLANNING_STUCK_MINUTES / 60.0
        if wait_hours >= ttl_hours:
            blockers.append(
                {
                    "gate": "planning_gate",
                    "kind": "planning_timeout",
                    "reason": f"planning exceeded ttl after {wait_hours:.2f}h",
                }
            )
            gate_status["planning_gate"] = "blocked"

    if focus.get("single_product_mode") and not goal_matches_focus(goal, focus) and not _is_unblock_goal(goal):
        blockers.append(
            {
                "gate": "production_first_gate",
                "kind": "production_first",
                "reason": "deferred by production-first focus policy",
            }
        )
        gate_status["production_first_gate"] = "blocked"

    if pool == "production":
        verification_gate = global_gates["verification_gate"]
        if verification_gate["status"] != "pass":
            blockers.append(
                {
                    "gate": "verification_gate",
                    "kind": "verification",
                    "reason": verification_gate["reason"] or verification_gate["source_status"],
                }
            )
            gate_status["verification_gate"] = "blocked"

    release_gate = global_gates["release_gate"]
    tier_state = str((release_gate.get("tiers") or {}).get(release_tier) or release_gate.get("source_status") or "").strip().lower()
    if release_tier in {"mainline", "normal"} and release_gate["status"] != "pass":
        blockers.append(
            {
                "gate": "release_gate",
                "kind": "release",
                "reason": release_gate["reason"] or release_gate["source_status"],
            }
        )
        gate_status["release_gate"] = "blocked"
    elif release_tier == "mainline" and tier_state and tier_state != "ready":
        blockers.append(
            {
                "gate": "release_gate",
                "kind": "release_tier",
                "reason": f"release_tier:{release_tier}:{tier_state}",
            }
        )
        gate_status["release_gate"] = "blocked"

    pool_cap = _pool_wip_cap(dispatch_budget, pool)
    pool_running = int(running_counts.get(pool, 0) or 0)
    if task_status not in {"running", "planning"} and pool_running >= pool_cap:
        blockers.append(
            {
                "gate": "quota_gate",
                "kind": "pool_wip",
                "reason": f"pool {pool} running {pool_running}/{pool_cap}",
            }
        )
        gate_status["quota_gate"] = "blocked"

    if task_status in {"failed", "timed_out"}:
        if retry_count < retry_limit and retry_limit > 0:
            return {
                "state": "retry",
                "raw_status": task_status,
                "blocked": False,
                "blockers": [],
                "gate_status": gate_status,
                "wait_hours": wait_hours,
                "retry_count": retry_count,
                "retry_limit": retry_limit,
                "dispatch_budget_slot": None,
                "pool": pool,
                "release_tier": release_tier,
            }
        return {
            "state": "failed",
            "raw_status": task_status,
            "blocked": True,
            "blockers": blockers or [{"gate": "retry_gate", "kind": "terminal_failure", "reason": task_status}],
            "gate_status": gate_status,
            "wait_hours": wait_hours,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "dispatch_budget_slot": None,
            "pool": pool,
            "release_tier": release_tier,
        }

    if task_status in {"completed", "delivery_ready", "released"}:
        return {
            "state": "done",
            "raw_status": task_status,
            "blocked": False,
            "blockers": [],
            "gate_status": gate_status,
            "wait_hours": wait_hours,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "dispatch_budget_slot": None,
            "pool": pool,
            "release_tier": release_tier,
        }

    if task_status == "waiting_approval":
        return {
            "state": "waiting_approval",
            "raw_status": task_status,
            "blocked": True,
            "blockers": blockers,
            "gate_status": gate_status,
            "wait_hours": wait_hours,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "dispatch_budget_slot": None,
            "pool": pool,
            "release_tier": release_tier,
        }

    if task_status in {"running", "planning"}:
        return {
            "state": "running",
            "raw_status": task_status,
            "blocked": False,
            "blockers": [],
            "gate_status": gate_status,
            "wait_hours": wait_hours,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "dispatch_budget_slot": None,
            "pool": pool,
            "release_tier": release_tier,
        }

    if blockers:
        return {
            "state": "blocked",
            "raw_status": task_status or str(node.get("status") or "").strip().lower() or "pending",
            "blocked": True,
            "blockers": blockers,
            "gate_status": gate_status,
            "wait_hours": wait_hours,
            "retry_count": retry_count,
            "retry_limit": retry_limit,
            "dispatch_budget_slot": None,
            "pool": pool,
            "release_tier": release_tier,
        }

    return {
        "state": "ready",
        "raw_status": task_status or str(node.get("status") or "").strip().lower() or "pending",
        "blocked": False,
        "blockers": [],
        "gate_status": gate_status,
        "wait_hours": wait_hours,
        "retry_count": retry_count,
        "retry_limit": retry_limit,
        "dispatch_budget_slot": None,
        "pool": pool,
        "release_tier": release_tier,
    }


def build_scheduling_snapshot(
    goal_graph_pairs: list[dict[str, Any]],
    *,
    dispatch_budget: int = 3,
    persist: bool = True,
) -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    checkpoints = _load_json(CHECKPOINTS, {})
    focus = build_production_focus()
    global_gates = _global_gate_states()
    goal_lookup = {
        str(item.get("goal", {}).get("goal_id") or ""): item.get("goal", {})
        for item in goal_graph_pairs
        if item.get("goal")
    }
    task_lookup_by_node_id: dict[str, dict[str, Any]] = {}
    task_lookup_by_goal_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        task_id = str(task.get("id") or "").strip()
        node_id = str(task.get("node_id") or "").strip()
        goal_id = str(task.get("goal_id") or "").strip()
        if node_id:
            task_lookup_by_node_id[node_id] = task
        if goal_id:
            task_lookup_by_goal_id[goal_id].append(task)
    candidates: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    task_state_counts: Counter[str] = Counter()
    blocked_reason_counts: Counter[str] = Counter()
    running_tasks = [
        _running_task_priority(task, goal_lookup, checkpoints)
        for task in tasks
        if str(task.get("status") or "") in RUNNING_TASK_STATUSES
    ]
    running_counts = Counter(item.get("factory_pool") or "production" for item in running_tasks)
    stuck_tasks: list[dict[str, Any]] = []
    for task in tasks:
        recovery_reason = _task_recovery_reason(task, checkpoints)
        if not recovery_reason:
            continue
        task_state_counts["blocked"] += 1
        blocked_reason_counts[str(recovery_reason.get("gate") or "task_recovery")] += 1
        stuck_tasks.append(
            {
                "task_id": task.get("id"),
                "goal_id": task.get("goal_id"),
                "graph_id": task.get("graph_id"),
                "node_id": task.get("node_id"),
                "goal": task.get("goal") or task.get("title"),
                "title": task.get("title") or task.get("goal") or task.get("id"),
                "lane": task.get("lane") or "recovery",
                "pool": str(task.get("factory_pool") or "ops"),
                "priority_band": str(task.get("priority_band") or "P1"),
                "release_tier": str(task.get("release_tier") or "normal"),
                "task_status": str(task.get("status") or "").strip().lower(),
                "state": "blocked",
                "wait_hours": round(recovery_reason.get("age_minutes", 0.0) / 60.0, 4),
                "retry_count": _task_retry_count(task),
                "retry_limit": _task_retry_limit(task),
                "blocked": True,
                "blockers": [recovery_reason],
                "gate_status": {
                    "dependency_gate": "pass",
                    "artifact_gate": "pass",
                    "approval_gate": "pass",
                    "planning_gate": "blocked" if recovery_reason.get("gate") == "planning_gate" else "pass",
                    "quota_gate": "pass",
                    "verification_gate": "pass",
                    "release_gate": "pass",
                    "production_first_gate": "pass",
                    "retry_gate": "pass",
                },
                "selection": {},
                "effective_priority": round(
                    2.0 + min(1.0, recovery_reason.get("age_minutes", 0.0) / 180.0), 4
                ),
                "goal_progress": 0.0,
                "unblock_strategy": _unblock_strategy([recovery_reason], str(task.get("status") or "")),
            }
        )

    for item in goal_graph_pairs:
        goal = item.get("goal") or {}
        graph = item.get("graph") or {}
        ready_nodes = item.get("ready_nodes") or []
        all_nodes = graph.get("nodes", []) or []
        completed_ids = {str(node.get("id") or "") for node in all_nodes if str(node.get("status") or "").strip().lower() == "completed"}
        graph_meta = graph.get("meta") or {}
        scheduled = schedule_nodes(
            ready_nodes,
            capability_route=goal.get("capability_route"),
            vm_template=graph_meta.get("vm_template"),
            worker_vm_policy=(graph_meta.get("worker_vm_policy") or {}),
            repo_path=goal.get("repo_path"),
        ) if ready_nodes else []
        scheduled_by_node_id = {
            str(node.get("id") or ""): selection
            for node, selection in zip(ready_nodes, scheduled)
        }

        for node in all_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            task = task_lookup_by_node_id.get(node_id)
            if task is None and str(goal.get("goal_id") or "").strip():
                candidate_tasks = task_lookup_by_goal_id.get(str(goal.get("goal_id") or "").strip(), [])
                task = next((item for item in candidate_tasks if str(item.get("node_id") or "").strip() == node_id), None)
            selection = scheduled_by_node_id.get(node_id, {})
            components = _priority_components(goal, graph, node, selection, focus)
            decision = _task_gate_decision(
                goal=goal,
                graph=graph,
                node=node,
                task=task,
                selection=selection,
                focus=focus,
                running_counts=dict(running_counts),
                dispatch_budget=dispatch_budget,
                completed_ids=completed_ids,
                global_gates=global_gates,
            )
            state_rows.append(
                {
                    "goal_id": goal.get("goal_id"),
                    "graph_id": graph.get("graph_id"),
                    "node_id": node_id,
                    "goal": goal.get("target"),
                    "title": node.get("title"),
                    "lane": goal.get("lane"),
                    "pool": decision["pool"],
                    "priority_band": components["priority_band"],
                    "release_tier": decision["release_tier"],
                    "task_status": decision["raw_status"],
                    "state": decision["state"],
                    "wait_hours": decision["wait_hours"],
                    "retry_count": decision["retry_count"],
                    "retry_limit": decision["retry_limit"],
                    "blocked": decision["blocked"],
                    "blockers": decision["blockers"],
                    "gate_status": decision["gate_status"],
                    "selection": selection,
                    "effective_priority": components["effective_priority"],
                    "goal_progress": _goal_progress(goal, graph),
                }
            )
            task_state_counts[decision["state"]] += 1
            for gate_key in {str((blocker or {}).get("gate") or "unknown") for blocker in decision["blockers"]}:
                blocked_reason_counts[gate_key] += 1
            if decision["state"] == "blocked":
                blocked_rows.append(state_rows[-1])
                continue
            if decision["state"] in {"waiting_approval", "running", "retry", "done", "failed"}:
                continue
            if not ready_nodes or node_id not in scheduled_by_node_id:
                continue
            candidates.append(
                {
                    "goal_id": goal.get("goal_id"),
                    "graph_id": graph.get("graph_id"),
                    "node_id": node_id,
                    "goal": goal.get("target"),
                    "title": node.get("title"),
                    "lane": goal.get("lane"),
                    "is_mainline": _is_mainline(goal),
                    "factory_pool": components["factory_pool"],
                    "priority_band": components["priority_band"],
                    "release_tier": components["release_tier"],
                    "goal_progress": _goal_progress(goal, graph),
                    "wait_hours": round(_wait_hours(goal, node), 4),
                    "timeslice_seconds": int(node.get("timeslice_seconds") or DEFAULT_TIMESLICE_SECONDS),
                    "interruptible": bool(node.get("interruptible", True)),
                    "selection": selection,
                    "priority_components": components,
                    "effective_priority": components["effective_priority"],
                    "checkpoint_hint": {
                        "path": _checkpoint_dir(str(node.get("task_id") or node.get("id") or "pending")),
                        "mode": "task-directory",
                    },
                    "reason": (
                        f"priority={components['priority_band']} pool={components['factory_pool']} tier={components['release_tier']} "
                        f"goal_weight={components['goal_weight']:.2f} urgency={components['urgency']:.2f} "
                        f"aging={components['stagnation_penalty']:.2f} resource={components['resource_bonus']:.2f} "
                        f"artifact_stage={components['artifact_stage_bonus']:.2f} delivery={components['delivery_bonus']:.2f} "
                        f"first_artifact={components['first_artifact_bonus']:.2f} focus={components['focus_bonus']:.2f}"
                    ),
                    "scheduler_state": "ready",
                }
            )

    candidates.sort(
        key=lambda item: (
            float(item.get("effective_priority", 0.0) or 0.0),
            1 if item.get("is_mainline") else 0,
            float(item.get("wait_hours", 0.0) or 0.0),
        ),
        reverse=True,
    )

    blocked_candidates = blocked_rows + stuck_tasks
    unblock_queue: list[dict[str, Any]] = []
    for row in sorted(
        blocked_candidates,
        key=lambda item: (
            float(item.get("effective_priority", 0.0) or 0.0),
            float(item.get("wait_hours", 0.0) or 0.0),
        ),
        reverse=True,
    ):
        blockers = row.get("blockers") or []
        strategy = _unblock_strategy(blockers, str(row.get("task_status") or ""))
        unblock_queue.append(
            {
                "goal_id": row.get("goal_id"),
                "graph_id": row.get("graph_id"),
                "task_id": row.get("task_id"),
                "node_id": row.get("node_id"),
                "goal": row.get("goal"),
                "title": row.get("title"),
                "pool": row.get("pool"),
                "state": row.get("state"),
                "blockers": blockers,
                "unblock_strategy": strategy,
                "unblock_priority": float(row.get("effective_priority", 0.0) or 0.0),
                "unblock_lane": "unblock" if strategy in {"force_replan", "spawn_dependency_repair", "spawn_evidence_repair", "heartbeat_recovery"} else "ops",
                "next_action": (
                    "spawn_repair_goal" if strategy in {"spawn_dependency_repair", "spawn_evidence_repair", "force_replan"} else
                    "route_to_unblock_lane" if strategy == "route_to_unblock_lane" else
                    "review_blockers"
                ),
                "wait_hours": row.get("wait_hours"),
            }
        )
        if len(unblock_queue) >= UNBLOCK_QUEUE_LIMIT:
            break

    mainline_candidates = [item for item in candidates if item.get("is_mainline")]
    mainline_progress = round(
        sum(float(item.get("goal_progress", 0.0) or 0.0) for item in mainline_candidates) / len(mainline_candidates),
        4,
    ) if mainline_candidates else 1.0
    focus_mode = bool(mainline_candidates) and mainline_progress < MAINLINE_PROGRESS_THRESHOLD
    focus_reason = "mainline-progress-below-threshold" if focus_mode else None
    dispatch_pool = mainline_candidates if focus_mode else candidates
    dispatch_order = dispatch_pool[: max(0, dispatch_budget)]
    dispatch_ids = {(item.get("goal_id"), item.get("graph_id"), item.get("node_id")) for item in dispatch_order}
    for item in candidates:
        dispatch_key = (item.get("goal_id"), item.get("graph_id"), item.get("node_id"))
        if dispatch_key in dispatch_ids:
            item["scheduler_state"] = "ready"
        else:
            item["scheduler_state"] = "queued"
    task_state_counts["ready"] = len(dispatch_order)
    task_state_counts["queued"] = max(0, len(candidates) - len(dispatch_order))

    preemptions: list[dict[str, Any]] = []
    if dispatch_order:
        best = dispatch_order[0]
        for running in running_tasks:
            if not running.get("interruptible"):
                continue
            if best.get("goal_id") == running.get("goal_id") and best.get("node_id") == running.get("node_id"):
                continue
            if float(best.get("effective_priority", 0.0) or 0.0) <= float(running.get("effective_priority", 0.0) or 0.0) + PREEMPT_MARGIN:
                continue
            preemptions.append(
                {
                    "running_task_id": running.get("task_id"),
                    "running_goal_id": running.get("goal_id"),
                    "running_node_id": running.get("node_id"),
                    "incoming_goal_id": best.get("goal_id"),
                    "incoming_node_id": best.get("node_id"),
                    "reason": (
                        f"preempt-for-higher-priority:{running.get('effective_priority'):.2f}->"
                        f"{best.get('effective_priority'):.2f}"
                    ),
                    "checkpoint_dir": running.get("checkpoint_dir"),
                }
            )

    queue_by_pool = {
        pool: {
            "ready": sum(1 for item in candidates if item.get("factory_pool") == pool and item.get("scheduler_state") == "ready"),
            "queued": sum(1 for item in candidates if item.get("factory_pool") == pool and item.get("scheduler_state") == "queued"),
            "dispatching": sum(1 for item in dispatch_order if item.get("factory_pool") == pool),
            "blocked": sum(1 for item in blocked_candidates if item.get("pool") == pool),
        }
        for pool in POOL_BONUS
    }

    gate_counts = {
        gate: blocked_reason_counts.get(gate, 0)
        for gate in ("dependency_gate", "artifact_gate", "approval_gate", "quota_gate", "verification_gate", "release_gate", "production_first_gate", "retry_gate")
    }
    task_state_summary = {
        state: task_state_counts.get(state, 0)
        for state in CANONICAL_TASK_STATES
    }

    snapshot = {
        "updated_at": _utc(),
        "dispatch_budget": dispatch_budget,
        "default_timeslice_seconds": DEFAULT_TIMESLICE_SECONDS,
        "ordering_strategy": "constraint-first-production-first",
        "focus_mode": focus_mode,
        "focus_reason": focus_reason,
        "mainline_progress": mainline_progress,
        "queues": {
            "ready": len(candidates),
            "queued": task_state_summary["queued"],
            "blocked": len(blocked_rows),
            "running": len(running_tasks),
            "dispatchable": len(dispatch_pool),
            "by_pool": queue_by_pool,
        },
        "task_state_machine": {
            "states": task_state_summary,
            "blocked_reason_counts": gate_counts,
            "policy": {
                "states": list(CANONICAL_TASK_STATES),
                "production_first": bool(focus_mode),
                "dispatch_budget": dispatch_budget,
                "pool_wip_caps": {pool: _pool_wip_cap(dispatch_budget, pool) for pool in POOL_BONUS},
                "unblock_lane": {
                    "enabled": bool(unblock_queue),
                    "pool": "ops",
                    "wip_cap": max(1, dispatch_budget // 3 or 1),
                },
                "verification_gate": global_gates["verification_gate"],
                "release_gate": global_gates["release_gate"],
            },
            "blocked_nodes": blocked_rows[:100],
            "task_recovery": stuck_tasks[:100],
            "unblock_queue": unblock_queue[:100],
            "samples": {
                "ready": candidates[:25],
                "blocked": blocked_candidates[:25],
            },
        },
        "production_focus": {
            "enabled": focus.get("enabled"),
            "single_product_mode": focus.get("single_product_mode"),
            "primary_target": focus.get("primary_target"),
            "primary_artifact_id": focus.get("primary_artifact_id"),
            "artifact_real": bool((focus.get("artifact") or {}).get("real")),
        },
        "running_tasks": running_tasks,
        "ready_queue": candidates,
        "unblock_queue": unblock_queue,
        "dispatch_order": dispatch_order,
        "preemptions": preemptions,
        "decision_summary": {
            "ready": task_state_summary["ready"],
            "queued": task_state_summary["queued"],
            "blocked": task_state_summary["blocked"],
            "waiting_approval": task_state_summary["waiting_approval"],
            "running": task_state_summary["running"],
            "retry": task_state_summary["retry"],
            "done": task_state_summary["done"],
            "failed": task_state_summary["failed"],
        },
    }
    if persist:
        atomic_write_json(STATUS, snapshot)
    return snapshot
