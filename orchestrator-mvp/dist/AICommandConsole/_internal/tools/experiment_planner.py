from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.experiment_ledger import ensure_experiment_entry, get_recent_experiments, has_recent_standard_experiment
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
FACTORY = ROOT / "factory"
OUT = DATA / "experiment_plan.json"
GOALS = FACTORY / "goals" / "goal_registry.json"
KNOWLEDGE = DATA / "knowledge_base.json"
AUTONOMY = DATA / "autonomy_score.json"
EXPERIENCE = DATA / "agent_experience.json"
EVALUATION = DATA / "experiment_evaluation.json"
EXPERIMENT_HISTORY = DATA / "experiment_history.json"
CAPABILITY_REPUTATION = DATA / "capability_reputation.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"
STANDARD_REFILL_WINDOW_HOURS = 24


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


def _active_experiment_targets(goals: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("target") or "").strip().lower()
        for item in goals
        if item.get("status") in {"pending", "planned", "running"}
    }


def _standard_experiment_batch() -> list[dict[str, Any]]:
    return [
        {
            "target": "Experiment prompt and routing comparison",
            "goal_type": "experiment",
            "notes": "Compare prompt compactness and capability routing for low-risk runtime choices.",
            "kind": "prompt-routing-comparison",
            "hypothesis": "A standardized prompt and routing comparison can improve routing quality without increasing risk.",
            "goal_alignment": 0.86,
            "progress_gain": 0.82,
            "risk_cost": 0.1,
            "resource_cost": 0.1,
            "knowledge_hits": ["routing-policy", "prompt-template"],
            "source": "lab-auto-refill",
            "owner": "automation_lab",
            "standard_experiment": True,
        },
        {
            "target": "Experiment evaluator stability",
            "goal_type": "experiment",
            "notes": "Check evaluator scoring consistency and adoption threshold stability against recent patterns.",
            "kind": "evaluator-stability",
            "hypothesis": "Evaluator outputs can stay stable across repeated low-risk checks with bounded variance.",
            "goal_alignment": 0.84,
            "progress_gain": 0.8,
            "risk_cost": 0.08,
            "resource_cost": 0.1,
            "knowledge_hits": ["experiment-evaluation", "score-threshold"],
            "source": "lab-auto-refill",
            "owner": "automation_lab",
            "standard_experiment": True,
        },
        {
            "target": "Experiment harness reliability",
            "goal_type": "experiment",
            "notes": "Check harness evidence completeness and pass/fail stability for a low-risk validation path.",
            "kind": "harness-reliability",
            "hypothesis": "Harness evidence completeness can remain stable under repeated low-risk execution.",
            "goal_alignment": 0.83,
            "progress_gain": 0.79,
            "risk_cost": 0.09,
            "resource_cost": 0.11,
            "knowledge_hits": ["harness", "evidence-completeness"],
            "source": "lab-auto-refill",
            "owner": "automation_lab",
            "standard_experiment": True,
        },
        {
            "target": "Experiment capability distillation regression",
            "goal_type": "experiment",
            "notes": "Verify that experiment outputs still produce valid distillation artifacts or an explicit no-value verdict.",
            "kind": "distillation-regression",
            "hypothesis": "Capability distillation can close every experiment with either reusable output or an explicit no-value verdict.",
            "goal_alignment": 0.85,
            "progress_gain": 0.81,
            "risk_cost": 0.08,
            "resource_cost": 0.09,
            "knowledge_hits": ["capability-distillation", "experiment-ledger"],
            "source": "lab-auto-refill",
            "owner": "automation_lab",
            "standard_experiment": True,
        },
    ]


def _seed_standard_experiments() -> list[dict[str, Any]]:
    seeded: list[dict[str, Any]] = []
    for item in _standard_experiment_batch():
        kind = str(item.get("kind") or "")
        if has_recent_standard_experiment(kind, window_hours=STANDARD_REFILL_WINDOW_HOURS):
            continue
        seeded.append(
            ensure_experiment_entry(
                item,
                hypothesis=str(item.get("hypothesis") or ""),
                owner=str(item.get("owner") or "automation_lab"),
                auto_generated=True,
                standard_experiment=True,
                seed_only=True,
            )
        )
    return seeded


def _recent_experiment_kinds() -> list[str]:
    history = _load_json(EXPERIMENT_HISTORY, [])
    kinds = []
    for item in history[-8:]:
        experiment = item.get("experiment") or {}
        kind = str(experiment.get("kind") or "").strip()
        if kind:
            kinds.append(kind)
    return kinds


def _reputation_gaps() -> dict[str, float]:
    reputation = _load_json(CAPABILITY_REPUTATION, {"capabilities": {}, "workers": {}})
    capability_count = len(reputation.get("capabilities") or {})
    worker_count = len(reputation.get("workers") or {})
    return {
        "routing-heuristics": 0.08 if capability_count == 0 else 0.0,
        "prompt-specialization": 0.05 if worker_count == 0 else 0.0,
        "recovery-patterns": 0.04 if capability_count + worker_count < 2 else 0.0,
    }


def _rotation_strategy_bonus(recent_kinds: list[str], kind: str) -> float:
    core_rotation = ["routing-heuristics", "prompt-specialization", "recovery-patterns"]
    if kind not in core_rotation:
        return 0.0
    recent_window = recent_kinds[-3:]
    return 0.06 if kind not in recent_window else 0.0


def _candidate_experiments(
    knowledge: dict[str, Any],
    autonomy: dict[str, Any],
    experience: list[dict[str, Any]],
    latest_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    recent_closed = get_recent_experiments(window_hours=STANDARD_REFILL_WINDOW_HOURS, statuses={"closed"})
    open_backlog = get_recent_experiments(window_hours=STANDARD_REFILL_WINDOW_HOURS, statuses={"planned", "running"})
    refill_priority_bonus = 0.18 if not recent_closed else 0.0

    for entry in open_backlog:
        if not entry.get("standard_experiment"):
            continue
        experiment = entry.get("experiment") or {}
        candidates.append(
            {
                "target": experiment.get("target"),
                "goal_type": experiment.get("goal_type"),
                "notes": f"Continue queued standardized experiment {experiment.get('kind')}.",
                "kind": experiment.get("kind"),
                "hypothesis": entry.get("hypothesis"),
                "worker": experiment.get("worker"),
                "knowledge_hits": [],
                "source": experiment.get("source") or "lab-auto-refill",
                "owner": entry.get("owner") or "automation_lab",
                "standard_experiment": True,
                "experiment_id": entry.get("experiment_id"),
                "goal_alignment": 0.9,
                "progress_gain": 0.84,
                "risk_cost": 0.08,
                "resource_cost": 0.08,
                "backlog_priority_bonus": 0.14,
            }
        )

    for item in _standard_experiment_batch():
        candidate = dict(item)
        candidate["refill_priority_bonus"] = refill_priority_bonus
        candidates.append(candidate)

    failure_solutions = knowledge.get("failure_solutions", [])
    experiment_patterns = knowledge.get("experiment_patterns", [])
    decision_hints = knowledge.get("decision_hints", {})
    autonomy_metrics = autonomy.get("metrics", {})

    if failure_solutions:
        candidates.append(
            {
                "target": "Experiment cheap-agent recovery patterns",
                "goal_type": "experiment",
                "notes": "Evaluate whether recent failure solutions can be converted into cheaper runtime-native recoveries.",
                "kind": "recovery-patterns",
                "hypothesis": "Failure-derived recovery hints can be converted into cheaper runtime-native recoveries.",
                "goal_alignment": 0.82,
                "progress_gain": 0.8,
                "risk_cost": 0.14,
                "resource_cost": 0.18,
                "knowledge_hits": [item.get("failure") for item in failure_solutions[:3]],
                "source": "knowledge-engine",
            }
        )

    active_tasks = autonomy_metrics.get("active_tasks", {}).get("active_tasks", 0)
    if active_tasks <= 2:
        candidates.append(
            {
                "target": "Experiment progress-first goal seeding",
                "goal_type": "experiment",
                "notes": "Evaluate additional low-risk goal seeds to keep runtime from idling.",
                "kind": "goal-seeding",
                "hypothesis": "Low-risk goal seeding can keep runtime utilization from idling without destabilizing delivery.",
                "goal_alignment": 0.8,
                "progress_gain": 0.78,
                "risk_cost": 0.1,
                "resource_cost": 0.12,
                "knowledge_hits": decision_hints.get("priority_targets", []),
                "source": "autonomy-engine",
            }
        )

    weak_workers = [
        item
        for item in experience
        if float(item.get("success_rate", 0.0) or 0.0) < 0.9 and (item.get("completed", 0) or 0) > 0
    ]
    if weak_workers:
        worker = weak_workers[0].get("worker") or "cheap-worker"
        candidates.append(
            {
                "target": f"Experiment {worker} prompt specialization",
                "goal_type": "experiment",
                "notes": f"Try a narrower prompt/skill template for {worker} using recent task outcomes.",
                "kind": "prompt-specialization",
                "hypothesis": f"Narrow prompt specialization can raise {worker} quality without increasing runtime cost.",
                "worker": worker,
                "goal_alignment": 0.84,
                "progress_gain": 0.76,
                "risk_cost": 0.12,
                "resource_cost": 0.15,
                "knowledge_hits": [worker],
                "source": "agent-experience",
            }
        )

    if experiment_patterns:
        candidates.append(
            {
                "target": "Experiment capability routing heuristics",
                "goal_type": "experiment",
                "notes": "Use prior successful experiments to improve capability routing heuristics.",
                "kind": "routing-heuristics",
                "hypothesis": "Experiment history can improve low-risk capability routing heuristics.",
                "goal_alignment": 0.83,
                "progress_gain": 0.74,
                "risk_cost": 0.16,
                "resource_cost": 0.16,
                "knowledge_hits": [item.get("target") for item in experiment_patterns[:3]],
                "source": "experiment-history",
            }
        )

    github_learning = knowledge.get("github_learning", {}) or {}
    if int(github_learning.get("ready_repo_count", 0) or 0) > 0:
        candidates.append(
            {
                "target": "Experiment GitHub repo capability extraction",
                "goal_type": "experiment",
                "notes": "Validate whether newly learned GitHub repositories produce reusable capability modules.",
                "kind": "github-capability-extraction",
                "hypothesis": "Recently learned GitHub repositories can yield reusable capability modules.",
                "goal_alignment": 0.87,
                "progress_gain": 0.81,
                "risk_cost": 0.11,
                "resource_cost": 0.18,
                "knowledge_hits": [item.get("full_name") for item in (github_learning.get("top_candidates") or [])[:3]],
                "source": "github-learning",
            }
        )

    if latest_evaluation.get("adopt"):
        candidates.append(
            {
                "target": "Experiment adopted-pattern rollout",
                "goal_type": "experiment",
                "notes": "Validate whether the latest adopted experiment pattern improves current runtime decisions.",
                "kind": "pattern-rollout",
                "hypothesis": "Recently adopted patterns can improve runtime decisions when rolled out cautiously.",
                "goal_alignment": 0.8,
                "progress_gain": 0.75,
                "risk_cost": 0.14,
                "resource_cost": 0.14,
                "knowledge_hits": [latest_evaluation.get("experiment", {}).get("target")],
                "source": "experiment-evaluation",
            }
        )

    if not candidates:
        candidates.append(
            {
                "target": "Experiment capability routing heuristics",
                "goal_type": "experiment",
                "notes": "Run a low-risk routing heuristic experiment using existing platform capabilities.",
                "kind": "routing-heuristics",
                "hypothesis": "A fallback routing heuristic experiment can still produce reusable routing guidance.",
                "goal_alignment": 0.76,
                "progress_gain": 0.7,
                "risk_cost": 0.15,
                "resource_cost": 0.16,
                "knowledge_hits": [],
                "source": "default-fallback",
            }
        )

    recent_kinds = _recent_experiment_kinds()
    last_kind = recent_kinds[-1] if recent_kinds else None
    gap_bonus = _reputation_gaps()
    global_policy = _load_json(GLOBAL_POLICY, {})
    experiment_portfolio = global_policy.get("experiment_portfolio", {})
    for item in candidates:
        kind = str(item.get("kind") or "")
        penalty = 0.0
        if kind == last_kind:
            penalty += 0.08
        if recent_kinds.count(kind) >= 2:
            penalty += 0.04
        rotation_bonus = _rotation_strategy_bonus(recent_kinds, kind)
        reputation_gap_bonus = float(gap_bonus.get(kind, 0.0) or 0.0)
        portfolio_bonus = float(experiment_portfolio.get(kind, 0.0) or 0.0) * 0.1
        refill_bonus = float(item.get("refill_priority_bonus", 0.0) or 0.0)
        backlog_bonus = float(item.get("backlog_priority_bonus", 0.0) or 0.0)
        base_score = (
            item["goal_alignment"] * 0.35
            + item["progress_gain"] * 0.35
            + (1.0 - item["risk_cost"]) * 0.15
            + (1.0 - item["resource_cost"]) * 0.15
        )
        item["rotation_penalty"] = round(penalty, 4)
        item["rotation_bonus"] = round(rotation_bonus, 4)
        item["reputation_gap_bonus"] = round(reputation_gap_bonus, 4)
        item["portfolio_bonus"] = round(portfolio_bonus, 4)
        item["refill_priority_bonus"] = round(refill_bonus, 4)
        item["backlog_priority_bonus"] = round(backlog_bonus, 4)
        item["score"] = round(base_score - penalty + rotation_bonus + reputation_gap_bonus + portfolio_bonus + refill_bonus + backlog_bonus, 4)
    return sorted(candidates, key=lambda item: item.get("score", 0.0), reverse=True)


def plan_experiments() -> dict[str, Any]:
    goals = _load_json(GOALS, [])
    knowledge = _load_json(KNOWLEDGE, {})
    autonomy = _load_json(AUTONOMY, {})
    experience = _load_json(EXPERIENCE, [])
    latest_evaluation = _load_json(EVALUATION, {})
    active_targets = _active_experiment_targets(goals)
    seeded = _seed_standard_experiments()
    candidates = _candidate_experiments(knowledge, autonomy, experience, latest_evaluation)
    selected = next((item for item in candidates if item["target"].strip().lower() not in active_targets), None)
    if selected:
        selected_entry = ensure_experiment_entry(
            selected,
            hypothesis=str(selected.get("hypothesis") or f"Validate {selected.get('target')} under a bounded experiment."),
            owner=str(selected.get("owner") or "automation_lab"),
            auto_generated=bool(selected.get("source") == "lab-auto-refill"),
            standard_experiment=bool(selected.get("standard_experiment")),
        )
        selected["experiment_id"] = selected_entry["experiment_id"]
    payload = {
        "updated_at": _utc(),
        "candidate_count": len(candidates),
        "selected": selected,
        "selection_reason": (selected or {}).get("source"),
        "knowledge_hits": (selected or {}).get("knowledge_hits", []),
        "auto_refill": {
            "window_hours": STANDARD_REFILL_WINDOW_HOURS,
            "seeded_count": len(seeded),
            "seeded_experiment_ids": [item.get("experiment_id") for item in seeded],
        },
        "candidates": candidates[:6],
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(plan_experiments(), ensure_ascii=False, indent=2))
