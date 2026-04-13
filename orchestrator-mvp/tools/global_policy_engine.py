from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json
from tools.autonomy_state import autonomy_is_confirmed, load_effective_autonomy
from tools.ai_testing_compat import load_ai_test_status
from tools.kernel_mode import load_kernel_mode

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "global_policy_state.json"
REPUTATION = DATA / "capability_reputation.json"
EXPERIENCE = DATA / "agent_experience.json"
QUALITY = DATA / "quality_status.json"
CONTROL = DATA / "control_layer_status.json"
EXPERIMENT_HISTORY = DATA / "experiment_history.json"
ORGANIZATION = DATA / "organization_model.json"


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


def _top_capabilities(reputation: dict[str, Any]) -> list[dict[str, Any]]:
    capabilities = reputation.get("capabilities") or {}
    items = [{"capability_id": key, **(value or {})} for key, value in capabilities.items()]
    items.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    return items[:6]


def _top_workers(reputation: dict[str, Any], experience: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exp_by_worker = {str(item.get("worker") or ""): item for item in experience}
    items = []
    for worker, payload in (reputation.get("workers") or {}).items():
        combined = dict(payload or {})
        combined["worker"] = worker
        combined["success_rate"] = float((exp_by_worker.get(worker) or {}).get("success_rate", 0.0) or 0.0)
        items.append(combined)
    items.sort(key=lambda item: (float(item.get("score", 0.0) or 0.0), float(item.get("success_rate", 0.0) or 0.0)), reverse=True)
    return items[:6]


def run_global_policy() -> dict[str, Any]:
    reputation = _load_json(REPUTATION, {"capabilities": {}, "workers": {}})
    experience = _load_json(EXPERIENCE, [])
    quality = _load_json(QUALITY, {})
    control = _load_json(CONTROL, {})
    autonomy = load_effective_autonomy()
    history = _load_json(EXPERIMENT_HISTORY, [])
    organization = _load_json(ORGANIZATION, {})
    ai_testing = load_ai_test_status()
    tasks = _load_json(DATA / "tasks.json", [])
    active_task_count = sum(1 for item in tasks if str(item.get("status") or "") in {"planning", "running", "verification_pending", "verification_running"})
    kernel_mode = load_kernel_mode({"ai_testing": ai_testing, "control": control})

    top_capabilities = _top_capabilities(reputation)
    top_workers = _top_workers(reputation, experience)

    focus_capabilities = [item.get("capability_id") for item in top_capabilities if item.get("capability_id")]
    if not focus_capabilities:
        focus_capabilities = ["agent_orchestration", "webapp_generation", "deploy_scaffold"]

    experiment_budget = {
        "coding": 0.35,
        "routing": 0.30,
        "review": 0.20,
        "infra": 0.15,
    }
    if float(quality.get("overall_score", 0.0) or 0.0) < 0.8:
        experiment_budget["routing"] += 0.05
        experiment_budget["coding"] -= 0.05
    if control.get("status") != "stable":
        experiment_budget["infra"] += 0.05
        experiment_budget["coding"] -= 0.05

    experiment_portfolio = {
        "routing-heuristics": round(experiment_budget["routing"], 4),
        "prompt-specialization": round(experiment_budget["review"], 4),
        "recovery-patterns": round(experiment_budget["infra"], 4),
        "goal-seeding": round(max(0.1, experiment_budget["coding"] * 0.5), 4),
        "pattern-rollout": round(max(0.1, experiment_budget["coding"] * 0.5), 4),
    }

    resource_budget = {
        "runtime_tasks": 0.4,
        "experiments": 0.3,
        "capability_building": 0.2,
        "maintenance": 0.1,
    }
    if control.get("status") != "stable":
        resource_budget["maintenance"] = 0.2
        resource_budget["experiments"] = 0.2
        resource_budget["runtime_tasks"] = 0.35
        resource_budget["capability_building"] = 0.15

    min_active_tasks = 3
    max_active_tasks = 12
    min_active_goals = 3
    if active_task_count < min_active_tasks:
        resource_budget["runtime_tasks"] = max(resource_budget["runtime_tasks"], 0.5)
        resource_budget["experiments"] = max(0.15, resource_budget["experiments"] - 0.05)
        resource_budget["capability_building"] = max(0.15, resource_budget["capability_building"])

    ai_status = str(ai_testing.get("status") or "missing")
    ai_error_count = int(ai_testing.get("error_count", 0) or 0)

    if kernel_mode.get("kernel_freeze"):
        resource_budget = {
            "runtime_tasks": 0.65,
            "experiments": 0.0,
            "capability_building": 0.0,
            "maintenance": 0.35,
        }
        experiment_portfolio = {
            "routing-heuristics": 0.0,
            "prompt-specialization": 0.0,
            "recovery-patterns": 1.0,
            "goal-seeding": 0.0,
            "pattern-rollout": 0.0,
        }
        min_active_tasks = 1
        max_active_tasks = 4
        min_active_goals = 1

    cadence_policy = {
        "runtime_dispatch_limit": 1 if resource_budget["runtime_tasks"] < 0.35 else 2 if resource_budget["runtime_tasks"] < 0.55 else 3,
        "goal_generation_every": 1 if active_task_count < min_active_tasks else 5 if resource_budget["runtime_tasks"] < 0.35 else 3 if resource_budget["runtime_tasks"] < 0.55 else 2,
        "maintenance_mode": "full" if resource_budget["maintenance"] >= 0.2 else "light",
        "maintenance_every": 4 if resource_budget["maintenance"] >= 0.2 else 8,
        "capability_building_every": 2 if active_task_count < min_active_tasks else 4 if resource_budget["capability_building"] >= 0.25 else 5 if resource_budget["capability_building"] >= 0.15 else 7,
        "experiment_every": 0 if active_task_count < min_active_tasks else 3 if resource_budget["experiments"] >= 0.25 else 5,
        "meta_every": 5 if resource_budget["capability_building"] >= 0.15 else 7,
        "ai_testing_every": 4 if ai_status in {"degraded", "attention", "missing"} or ai_error_count > 0 else 10,
        "min_active_tasks": min_active_tasks,
        "max_active_tasks": max_active_tasks,
        "min_active_goals": min_active_goals,
    }
    if kernel_mode.get("kernel_freeze"):
        cadence_policy.update({
            "runtime_dispatch_limit": 1,
            "goal_generation_every": 1 if active_task_count == 0 else 2,
            "maintenance_mode": "full",
            "maintenance_every": 1,
            "capability_building_every": 0,
            "experiment_every": 0,
            "meta_every": 0,
            "ai_testing_every": 2,
            "min_active_tasks": min_active_tasks,
            "max_active_tasks": max_active_tasks,
            "min_active_goals": min_active_goals,
        })

    worker_bias_policy = {
        item.get("worker"): round(min(0.25, float(item.get("score", 0.0) or 0.0) + 0.05), 4)
        for item in top_workers if item.get("worker")
    }

    organization_bias = {}
    for department, summary in (organization.get("departments") or {}).items():
        default_worker = summary.get("default_worker")
        if not default_worker:
            continue
        project_count = int(summary.get("project_count", 0) or 0)
        organization_bias[default_worker] = round(min(0.12, project_count * 0.01), 4)
    for worker, bias in organization_bias.items():
        worker_bias_policy[worker] = round(min(0.3, float(worker_bias_policy.get(worker, 0.0) or 0.0) + bias), 4)

    payload = {
        "updated_at": _utc(),
        "focus_capabilities": focus_capabilities,
        "resource_budget": resource_budget,
        "cadence_policy": cadence_policy,
        "kernel_mode": kernel_mode,
        "experiment_portfolio": experiment_portfolio,
        "worker_bias_policy": worker_bias_policy,
        "organization_priority": {
            "departments": sorted(
                [
                    {
                        "department": name,
                        "project_count": int((summary or {}).get("project_count", 0) or 0),
                        "default_worker": (summary or {}).get("default_worker"),
                    }
                    for name, summary in (organization.get("departments") or {}).items()
                ],
                key=lambda item: item["project_count"],
                reverse=True,
            )[:6]
        },
        "top_capabilities": top_capabilities,
        "top_workers": top_workers,
        "inputs": {
            "quality_score": quality.get("overall_score", 0.0),
            "control_status": control.get("status"),
            "autonomy_stage": autonomy.get("stage"),
            "autonomy_source": autonomy.get("source"),
            "autonomy_confirmed": autonomy_is_confirmed(autonomy),
            "experiment_history_count": len(history),
            "organization_departments": len((organization.get("departments") or {})),
            "ai_testing_status": ai_status,
            "ai_testing_pass_rate": ai_testing.get("pass_rate", 0.0),
            "ai_testing_error_count": ai_error_count,
            "active_task_count": active_task_count,
            "kernel_freeze": kernel_mode.get("kernel_freeze", False),
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_global_policy(), ensure_ascii=False, indent=2))
