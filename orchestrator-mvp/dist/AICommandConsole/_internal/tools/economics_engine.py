from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
FACTORY = ROOT / "factory"
OUT = DATA / "economics_engine_status.json"

TASKS = DATA / "tasks.json"
GOALS = FACTORY / "goals" / "goal_registry.json"
USAGE = DATA / "usage_tracker.json"
QUALITY = DATA / "quality_status.json"
GLOBAL_POLICY = DATA / "global_policy_state.json"
HEALTH = DATA / "health_status.json"
RESOURCES = DATA / "resources.json"
AGENT_EXPERIENCE = DATA / "agent_experience.json"
AGENT_SCORES = FACTORY / "market" / "agent_scores.json"
EXPERIMENT_PLAN = DATA / "experiment_plan.json"

BASE_PRICES = {
    "strong_model": 10.0,
    "cheap_model": 1.0,
    "local_model": 0.2,
    "cpu_task": 0.5,
    "gpu_task": 5.0,
    "network_tool": 0.4,
}

DEFAULT_AGENT_BUDGETS = {
    "supervisor": 2000.0,
    "reviewer": 800.0,
    "coder": 500.0,
    "shell": 300.0,
    "docker": 300.0,
    "tester": 300.0,
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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _goal_reward_mfc(goal: dict[str, Any]) -> float:
    scoring = goal.get("scoring") or {}
    reward = scoring.get("reward", goal.get("reward"))
    quality = scoring.get("success", 0.7)
    try:
        reward_value = float(reward if reward is not None else scoring.get("value", 0.5))
    except Exception:
        reward_value = 0.5
    try:
        quality_value = float(quality or 0.7)
    except Exception:
        quality_value = 0.7
    return round(max(5.0, reward_value * 100.0) * _clamp(quality_value, 0.2, 1.0), 2)


def _goal_value_mfc(goal: dict[str, Any]) -> float:
    scoring = goal.get("scoring") or {}
    try:
        value = float(scoring.get("value", 0.5) or 0.5)
    except Exception:
        value = 0.5
    return round(max(10.0, value * 100.0), 2)


def _resource_registry(resources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or ""): item for item in resources}


def _build_resource_market(resources: list[dict[str, Any]], usage: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
    registry = _resource_registry(resources)
    tasks = health.get("tasks") or {}
    active_tasks = int(tasks.get("active", 0) or 0)
    max_active = max(1, int((health.get("policy") or {}).get("max_active_tasks", 8) or 8))
    load_ratio = active_tasks / max_active
    reasoning_ratio = float(usage.get("reasoning_ratio", 0.0) or 0.0)
    reasoning_allowed = bool(usage.get("reasoning_allowed", True))
    strong_ratio = float(usage.get("strong_ratio", 0.0) or 0.0)
    strong_allowed = bool(usage.get("strong_allowed", True))

    resource_specs = [
        {
            "resource_id": "reasoning_model",
            "label": "reasoning model",
            "category": "compute",
            "base_price": 4.0,
            "available": True,
            "availability": 1.0 if reasoning_allowed else 0.75,
            "multiplier": 1.0 + reasoning_ratio * 1.1 + (0.2 if not reasoning_allowed else 0.0),
            "reason": "structured reasoning lane pressure",
        },
        {
            "resource_id": "strong_model",
            "label": "GPT / strong model",
            "category": "compute",
            "base_price": BASE_PRICES["strong_model"],
            "available": True,
            "availability": 1.0 if strong_allowed else 0.5,
            "multiplier": 1.0 + strong_ratio * 2.0 + (0.4 if not strong_allowed else 0.0),
            "reason": "premium model quota pressure",
        },
        {
            "resource_id": "cheap_model",
            "label": "cheap model",
            "category": "compute",
            "base_price": BASE_PRICES["cheap_model"],
            "available": True,
            "availability": 1.0,
            "multiplier": 0.9 + load_ratio * 0.2,
            "reason": "default low-cost lane",
        },
        {
            "resource_id": "local_model",
            "label": "local model",
            "category": "compute",
            "base_price": BASE_PRICES["local_model"],
            "available": registry.get("local-llm-gateway", {}).get("status") == "available",
            "availability": 1.0 if registry.get("local-llm-gateway", {}).get("status") == "available" else 0.35,
            "multiplier": 0.85 + load_ratio * 0.1,
            "reason": "local gateway capacity",
        },
        {
            "resource_id": "cpu_task",
            "label": "CPU task",
            "category": "infrastructure",
            "base_price": BASE_PRICES["cpu_task"],
            "available": True,
            "availability": _clamp(1.0 - load_ratio * 0.25, 0.45, 1.0),
            "multiplier": 1.0 + load_ratio * 0.35,
            "reason": "runtime task load",
        },
        {
            "resource_id": "gpu_task",
            "label": "GPU task",
            "category": "infrastructure",
            "base_price": BASE_PRICES["gpu_task"],
            "available": registry.get("docker", {}).get("status") in {"available", "configured"},
            "availability": 0.8 if registry.get("docker", {}).get("status") in {"available", "configured"} else 0.3,
            "multiplier": 1.0 + load_ratio * 0.5,
            "reason": "high-cost execution lane",
        },
        {
            "resource_id": "network_tool",
            "label": "network / search / browser tool",
            "category": "tools",
            "base_price": BASE_PRICES["network_tool"],
            "available": registry.get("browser-automation-bridge", {}).get("status") == "available",
            "availability": 1.0 if registry.get("browser-automation-bridge", {}).get("status") == "available" else 0.5,
            "multiplier": 1.0 + load_ratio * 0.15,
            "reason": "browser bridge dependency",
        },
    ]

    entries = []
    for spec in resource_specs:
        unit_price = round(spec["base_price"] * _clamp(spec["multiplier"], 0.2, 3.0), 2)
        entries.append(
            {
                "resource_id": spec["resource_id"],
                "label": spec["label"],
                "category": spec["category"],
                "base_price_mfc": spec["base_price"],
                "dynamic_multiplier": round(_clamp(spec["multiplier"], 0.2, 3.0), 4),
                "unit_price_mfc": unit_price,
                "availability": round(_clamp(spec["availability"], 0.0, 1.0), 4),
                "status": "available" if spec["available"] else "constrained",
                "reason": spec["reason"],
            }
        )

    constrained = [item["resource_id"] for item in entries if item["status"] != "available"]
    price_index = round(sum(item["unit_price_mfc"] for item in entries) / len(entries), 4)
    return {
        "currency": "MFC",
        "price_index": price_index,
        "active_task_load_ratio": round(load_ratio, 4),
        "constrained_resources": constrained,
        "resources": entries,
    }


def _build_task_market(tasks: list[dict[str, Any]], goals: list[dict[str, Any]]) -> dict[str, Any]:
    goal_lookup = {str(goal.get("goal_id") or ""): goal for goal in goals}
    open_statuses = {"queued", "planning", "running", "waiting_approval"}
    open_tasks = [task for task in tasks if str(task.get("status") or "") in open_statuses]
    completed_tasks = [task for task in tasks if str(task.get("status") or "") == "completed"]
    failed_tasks = [task for task in tasks if str(task.get("status") or "") in {"failed", "timed_out"}]

    open_samples = []
    reward_pool = 0.0
    for task in open_tasks[:10]:
        goal = goal_lookup.get(str(task.get("goal_id") or ""), {})
        estimated_reward = _goal_reward_mfc(goal) if goal else 30.0
        reward_pool += estimated_reward
        success_prob = float(((goal.get("scoring") or {}).get("success", 0.65)) if goal else 0.65)
        open_samples.append(
            {
                "task_id": task.get("id"),
                "goal_id": task.get("goal_id"),
                "goal": task.get("goal"),
                "status": task.get("status"),
                "reward_mfc": round(estimated_reward, 2),
                "success_probability": round(_clamp(success_prob, 0.1, 1.0), 4),
                "selection_rule": "lowest_cost_and_highest_success_probability",
            }
        )

    failure_rate = round(len(failed_tasks) / max(1, len(tasks)), 4)
    return {
        "status": "active" if open_tasks else "idle",
        "selection_rule": "lowest_cost_and_highest_success_probability",
        "open_task_count": len(open_tasks),
        "completed_task_count": len(completed_tasks),
        "failed_task_count": len(failed_tasks),
        "reward_pool_mfc": round(reward_pool, 2),
        "failure_rate": failure_rate,
        "market_pressure": round(len(open_tasks) / max(1, 6), 4),
        "open_tasks": open_samples,
    }


def _build_agent_budgets(
    agent_experience: list[dict[str, Any]],
    agent_scores: dict[str, Any],
    task_market: dict[str, Any],
    resource_market: dict[str, Any],
) -> dict[str, Any]:
    score_by_role = {
        str(item.get("role") or ""): item for item in (agent_scores.get("agents") or [])
    }
    resource_prices = {item["resource_id"]: item["unit_price_mfc"] for item in (resource_market.get("resources") or [])}
    budgets = []
    total_budget = 0.0
    suspended = []
    at_risk = []

    for item in agent_experience:
        role = str(item.get("worker") or "")
        runs = int(item.get("completed", 0) or 0) + int(item.get("failed", 0) or 0) + int(item.get("running", 0) or 0)
        success_rate = float(item.get("success_rate", 0.0) or 0.0)
        market_score = float((score_by_role.get(role, {}) or {}).get("success_rate", success_rate) or success_rate)
        base_budget = DEFAULT_AGENT_BUDGETS.get(role, 200.0)
        operating_budget = round(base_budget * (0.85 + _clamp(market_score, 0.0, 1.0) * 0.5), 2)
        spend_estimate = round(
            int(item.get("running", 0) or 0) * resource_prices.get("cpu_task", 0.5)
            + runs * resource_prices.get("cheap_model", 1.0) * 0.2,
            2,
        )
        expected_reward = round((int(item.get("completed", 0) or 0) + int(item.get("running", 0) or 0) * 0.35) * 25.0 * (0.6 + success_rate), 2)
        balance = round(operating_budget + expected_reward - spend_estimate, 2)
        status = "active"
        if balance <= 0:
            status = "suspended"
            suspended.append(role)
        elif balance <= operating_budget * 0.1:
            status = "at_risk"
            at_risk.append(role)
        budgets.append(
            {
                "agent_id": f"{role}_agent",
                "role": role,
                "budget_mfc": operating_budget,
                "estimated_spend_mfc": spend_estimate,
                "expected_reward_mfc": expected_reward,
                "balance_mfc": balance,
                "status": status,
            }
        )
        total_budget += operating_budget

    return {
        "currency": "MFC",
        "total_budget_mfc": round(total_budget, 2),
        "active_agent_count": sum(1 for item in budgets if item["status"] == "active"),
        "at_risk_agent_count": len(at_risk),
        "suspended_agent_count": len(suspended),
        "agents": budgets,
        "at_risk_agents": at_risk,
        "suspended_agents": suspended,
        "reward_pool_mfc": task_market.get("reward_pool_mfc", 0.0),
    }


def _build_incentive_system(goals: list[dict[str, Any]], quality: dict[str, Any]) -> dict[str, Any]:
    completed_goals = [goal for goal in goals if str(goal.get("status") or "") == "completed"]
    total_rewards = round(sum(_goal_reward_mfc(goal) for goal in completed_goals), 2)
    avg_quality = round(float(quality.get("overall_score", 0.0) or 0.0), 4)
    return {
        "currency": "MFC",
        "reward_formula": "base_reward * quality",
        "quality_signals": ["tests", "code_review", "execution_success"],
        "completed_goal_reward_mfc": total_rewards,
        "average_quality_score": avg_quality,
        "rewarded_goal_count": len(completed_goals),
    }


def _build_investment_system(goals: list[dict[str, Any]], experiment_plan: dict[str, Any]) -> dict[str, Any]:
    research_goals = [
        goal for goal in goals
        if str(goal.get("type") or "") in {"experiment", "architecture_upgrade", "capability_upgrade"}
    ]
    sample = []
    for goal in research_goals[:6]:
        cost = round(max(80.0, _goal_value_mfc(goal) * 0.45), 2)
        expected_return = round(max(cost + 50.0, _goal_value_mfc(goal) * 1.8), 2)
        sample.append(
            {
                "goal_id": goal.get("goal_id"),
                "target": goal.get("target"),
                "estimated_cost_mfc": cost,
                "expected_return_mfc": expected_return,
                "risk": "high" if str(goal.get("type") or "") == "experiment" else "medium",
            }
        )
    return {
        "status": "active" if sample else "idle",
        "candidate_count": len(research_goals),
        "selected_candidate": experiment_plan.get("selected"),
        "portfolio": sample,
    }


def _build_ai_gdp(goals: list[dict[str, Any]]) -> dict[str, Any]:
    completed_goals = [goal for goal in goals if str(goal.get("status") or "") == "completed"]
    by_type: dict[str, float] = {}
    total = 0.0
    for goal in completed_goals:
        goal_type = str(goal.get("type") or "unknown")
        value = _goal_value_mfc(goal)
        by_type[goal_type] = round(by_type.get(goal_type, 0.0) + value, 2)
        total += value
    return {
        "currency": "MFC",
        "completed_value_mfc": round(total, 2),
        "completed_goal_count": len(completed_goals),
        "by_goal_type": by_type,
    }


def run_economics_engine_status() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    goals = _load_json(GOALS, [])
    usage = _load_json(USAGE, {})
    quality = _load_json(QUALITY, {})
    policy = _load_json(GLOBAL_POLICY, {})
    health = _load_json(HEALTH, {})
    resources = _load_json(RESOURCES, [])
    agent_experience = _load_json(AGENT_EXPERIENCE, [])
    agent_scores = _load_json(AGENT_SCORES, {})
    experiment_plan = _load_json(EXPERIMENT_PLAN, {})

    resource_market = _build_resource_market(resources, usage, health)
    task_market = _build_task_market(tasks, goals)
    agent_budget_system = _build_agent_budgets(agent_experience, agent_scores, task_market, resource_market)
    incentive_system = _build_incentive_system(goals, quality)
    investment_system = _build_investment_system(goals, experiment_plan)
    ai_gdp = _build_ai_gdp(goals)

    policy_budget = policy.get("resource_budget") or {}
    active_task_load = float(resource_market.get("active_task_load_ratio", 0.0) or 0.0)
    suspended_agents = int(agent_budget_system.get("suspended_agent_count", 0) or 0)
    score = round(
        (0.22 if task_market.get("open_task_count", 0) > 0 else 0.1)
        + (0.22 if bool(policy_budget) else 0.0)
        + (0.18 if agent_budget_system.get("active_agent_count", 0) > 0 else 0.0)
        + (0.18 if incentive_system.get("rewarded_goal_count", 0) >= 0 else 0.0)
        + (0.20 * (1.0 - _clamp(active_task_load, 0.0, 1.0)))
        - min(0.15, suspended_agents * 0.05),
        4,
    )
    status = "active" if score >= 0.65 else "bootstrapping"

    payload = {
        "updated_at": _utc(),
        "status": status,
        "score": score,
        "currency_system": {
            "currency": "MetaForge Credits",
            "unit": "MFC",
            "base_prices_mfc": BASE_PRICES,
            "resource_budget": policy_budget,
            "usage": {
                "cheap_calls": int(usage.get("cheap_calls", 0) or 0),
                "reasoning_calls": int(usage.get("reasoning_calls", 0) or 0),
                "strong_calls": int(usage.get("strong_calls", 0) or 0),
                "reasoning_ratio": float(usage.get("reasoning_ratio", 0.0) or 0.0),
                "strong_ratio": float(usage.get("strong_ratio", 0.0) or 0.0),
            },
        },
        "resource_market": resource_market,
        "task_market": task_market,
        "agent_budget_system": agent_budget_system,
        "incentive_system": incentive_system,
        "investment_system": investment_system,
        "bankruptcy_system": {
            "status": "attention" if suspended_agents else "pass",
            "suspended_agent_count": suspended_agents,
            "suspended_agents": agent_budget_system.get("suspended_agents", []),
            "at_risk_agent_count": agent_budget_system.get("at_risk_agent_count", 0),
            "at_risk_agents": agent_budget_system.get("at_risk_agents", []),
        },
        "ai_gdp": ai_gdp,
        "summary": {
            "open_task_count": task_market.get("open_task_count", 0),
            "reward_pool_mfc": task_market.get("reward_pool_mfc", 0.0),
            "price_index_mfc": resource_market.get("price_index", 0.0),
            "total_budget_mfc": agent_budget_system.get("total_budget_mfc", 0.0),
            "completed_value_mfc": ai_gdp.get("completed_value_mfc", 0.0),
        },
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_economics_engine_status(), ensure_ascii=False, indent=2))
