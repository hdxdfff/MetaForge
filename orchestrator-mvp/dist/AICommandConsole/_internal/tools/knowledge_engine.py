from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.embedding_engine import embedding_status
from tools.repo_learning_engine import rebuild_repo_learning
from tools.github_capability_library import refresh_github_capability_library
from tools.autonomy_state import autonomy_is_confirmed, load_effective_autonomy
from tools.perplexity_search import load_internet_knowledge, load_perplexity_status
DATA = ROOT / "data"
OUT = DATA / "knowledge_base.json"
DECISIONS = DATA / "decision_log.json"
FAILURES = DATA / "failure_patterns.json"
TASK_HISTORY = DATA / "task_history.json"
EXPERIENCE = DATA / "agent_experience.json"
EXPERIMENT_HISTORY = DATA / "experiment_history.json"
EXPERIMENT_EVALUATION = DATA / "experiment_evaluation.json"
EXPERIMENT_PLAN = DATA / "experiment_plan.json"
EXPERIMENT_RUN = DATA / "experiment_run.json"
CAPABILITY_DISTILLATION = DATA / "capability_distillation.json"
CAPABILITY_REPUTATION = DATA / "capability_reputation.json"
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


def _decision_patterns(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns: dict[str, dict[str, Any]] = {}
    for item in decisions:
        category = item.get("category") or item.get("type") or "general"
        entry = patterns.setdefault(category, {"pattern": category, "count": 0, "examples": []})
        entry["count"] += 1
        detail = item.get("detail") or item.get("message") or item.get("decision") or ""
        if detail and len(entry["examples"]) < 3:
            entry["examples"].append(detail)
    return sorted(patterns.values(), key=lambda item: item["count"], reverse=True)


def _failure_solutions(failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for item in failures[:20]:
        items.append({
            "failure": item.get("pattern") or item.get("error") or "unknown",
            "solution": item.get("solution") or item.get("mitigation") or item.get("next_action") or "investigate",
            "scope": item.get("scope") or item.get("task_type") or "runtime",
        })
    return items


def _agent_knowledge(experience: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for item in sorted(experience, key=lambda entry: (entry.get("success_rate", 0.0), entry.get("completed", 0)), reverse=True)[:12]:
        items.append({
            "worker": item.get("worker"),
            "success_rate": item.get("success_rate", 0.0),
            "completed": item.get("completed", 0),
            "preferred_domains": item.get("preferred_domains", []),
        })
    return items


def _experiment_patterns(history: list[dict[str, Any]], evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    latest = evaluation.get("experiment") or {}
    if latest:
        patterns.append({
            "pattern": latest.get("kind") or "experiment",
            "target": latest.get("target"),
            "score": evaluation.get("score", 0.0),
            "adopt": bool(evaluation.get("adopt", False)),
            "decision_bias": (evaluation.get("decision_bias") or {}),
        })
    for item in history[-8:]:
        exp = item.get("experiment") or {}
        result = item.get("result") or {}
        patterns.append({
            "pattern": exp.get("kind") or "experiment-history",
            "target": exp.get("target"),
            "score": result.get("quality_score", 0.0),
            "adopt": bool(item.get("adopt", True)),
            "decision_bias": result.get("decision_bias") or {},
        })
    deduped: dict[str, dict[str, Any]] = {}
    for item in patterns:
        key = str(item.get("target") or item.get("pattern") or "experiment")
        deduped[key] = item
    return list(deduped.values())[:12]


def _reputation_summary(reputation: dict[str, Any]) -> dict[str, Any]:
    capabilities = reputation.get("capabilities") or {}
    workers = reputation.get("workers") or {}
    top_capabilities = sorted(
        [{"capability_id": key, **(value or {})} for key, value in capabilities.items()],
        key=lambda item: float(item.get("score", 0.0) or 0.0),
        reverse=True,
    )[:8]
    top_workers = sorted(
        [{"worker": key, **(value or {})} for key, value in workers.items()],
        key=lambda item: float(item.get("score", 0.0) or 0.0),
        reverse=True,
    )[:8]
    return {
        "capability_count": len(capabilities),
        "worker_count": len(workers),
        "top_capabilities": top_capabilities,
        "top_workers": top_workers,
    }


def _decision_hints(plan: dict[str, Any], run: dict[str, Any], evaluation: dict[str, Any], reputation: dict[str, Any]) -> dict[str, Any]:
    selected = plan.get("selected") or {}
    run_result = run.get("result") or {}
    hints = {
        "preferred_goal_types": [],
        "priority_targets": [],
        "avoid_targets": [],
        "routing_bias": {},
        "worker_bias": {},
        "preferred_capabilities": [],
        "preferred_workers": [],
    }
    if selected.get("goal_type"):
        hints["preferred_goal_types"].append(selected["goal_type"])
    if evaluation.get("adopt") and selected.get("target"):
        hints["priority_targets"].append(selected["target"])
    elif selected.get("target"):
        hints["avoid_targets"].append(selected["target"])
    decision_bias = evaluation.get("decision_bias") or run_result.get("decision_bias") or {}
    hints["routing_bias"] = decision_bias.get("routing_bias") or {}
    hints["worker_bias"] = decision_bias.get("worker_bias") or {}
    reputation_summary = _reputation_summary(reputation)
    hints["preferred_capabilities"] = [item.get("capability_id") for item in reputation_summary.get("top_capabilities", []) if item.get("capability_id")]
    hints["preferred_workers"] = [item.get("worker") for item in reputation_summary.get("top_workers", []) if item.get("worker")]
    return hints


def rebuild_knowledge() -> dict[str, Any]:
    decisions = _load_json(DECISIONS, [])
    failures = _load_json(FAILURES, [])
    task_history = _load_json(TASK_HISTORY, [])
    experience = _load_json(EXPERIENCE, [])
    experiment_history = _load_json(EXPERIMENT_HISTORY, [])
    experiment_evaluation = _load_json(EXPERIMENT_EVALUATION, {})
    experiment_plan = _load_json(EXPERIMENT_PLAN, {})
    experiment_run = _load_json(EXPERIMENT_RUN, {})
    capability_distillation = _load_json(CAPABILITY_DISTILLATION, {})
    capability_reputation = _load_json(CAPABILITY_REPUTATION, {"capabilities": {}, "workers": {}})
    global_policy = _load_json(GLOBAL_POLICY, {})
    autonomy = load_effective_autonomy()
    repo_learning = rebuild_repo_learning()
    github_capability_library = refresh_github_capability_library()
    embedding = embedding_status()
    internet_knowledge = load_internet_knowledge()
    internet_status = load_perplexity_status()
    payload = {
        "updated_at": _utc(),
        "decision_patterns": _decision_patterns(decisions),
        "failure_solutions": _failure_solutions(failures),
        "recent_task_summaries": task_history[-20:],
        "agent_knowledge": _agent_knowledge(experience),
        "experiment_patterns": _experiment_patterns(experiment_history, experiment_evaluation),
        "decision_hints": _decision_hints(experiment_plan, experiment_run, experiment_evaluation, capability_reputation),
        "capability_distillation": capability_distillation,
        "capability_reputation": _reputation_summary(capability_reputation),
        "global_policy": global_policy,
        "autonomy": {
            "stage": autonomy.get("stage"),
            "score": autonomy.get("score"),
            "source": autonomy.get("source"),
            "confirmed": autonomy_is_confirmed(autonomy),
        },
        "repo_learning": repo_learning,
        "github_learning": repo_learning.get("github_learning", {}),
        "github_capability_library": github_capability_library,
        "internet_knowledge": internet_knowledge,
        "internet_knowledge_status": internet_status,
        "embedding": embedding,
        "counts": {
            "decisions": len(decisions),
            "failures": len(failures),
            "task_history": len(task_history),
            "agents": len(experience),
            "experiments": len(experiment_history),
            "internet_history": len(internet_knowledge.get("history", [])),
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    rendered = json.dumps(rebuild_knowledge(), ensure_ascii=False, indent=2)
    try:
        print(rendered)
    except UnicodeEncodeError:
        print(rendered.encode("gbk", errors="replace").decode("gbk", errors="replace"))

