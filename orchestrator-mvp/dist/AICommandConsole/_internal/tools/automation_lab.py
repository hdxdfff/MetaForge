from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.identity_kernel import identity_kernel_status
from tools.autonomy_state import autonomy_is_confirmed

DATA = ROOT / "data"
OUT = DATA / "automation_lab_status.json"


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


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _round_metric(value: float | int | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _ledger_recent_experiments(ledger: dict[str, Any], *, now: datetime, window_hours: int) -> list[dict[str, Any]]:
    recent: list[dict[str, Any]] = []
    for entry in ledger.get("experiments", []):
        ended_at = _parse_utc(entry.get("ended_at"))
        started_at = _parse_utc(entry.get("started_at"))
        stamp = ended_at or started_at
        if stamp is None:
            continue
        age_hours = (now - stamp).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > window_hours:
            continue
        recent.append(entry)
    return recent


def _ledger_is_completed(entry: dict[str, Any]) -> bool:
    return str(entry.get("status") or "").lower() == "closed"


def _ledger_has_distillation(entry: dict[str, Any]) -> bool:
    return bool(entry.get("distillation_artifact_ids") or [])


def _ledger_is_independent(entry: dict[str, Any]) -> bool:
    if str(entry.get("closure_mode") or "").strip().lower() == "lab_autonomous":
        return True
    owner = str(entry.get("owner") or "").strip().lower()
    return owner in {"automation_lab", "rnd_department", "ai_algorithm_research_group"}


def run_automation_lab_status() -> dict[str, Any]:
    previous = _load_json(OUT, {})
    now = datetime.now(timezone.utc)
    window_hours = 24
    plan = _load_json(DATA / "experiment_plan.json", {})
    run = _load_json(DATA / "experiment_run.json", {})
    evaluation = _load_json(DATA / "experiment_evaluation.json", {})
    experiment_history = _load_json(DATA / "experiment_history.json", [])
    experiment_ledger = _load_json(DATA / "experiment_ledger.json", {"experiments": []})
    distillation = _load_json(DATA / "capability_distillation.json", {})
    reputation = _load_json(DATA / "capability_reputation.json", {"capabilities": {}, "workers": {}})
    knowledge = _load_json(DATA / "knowledge_base.json", {})
    global_policy = _load_json(DATA / "global_policy_state.json", {})
    organization_workboard = _load_json(DATA / "organization_workboard.json", {})
    release_ops = _load_json(DATA / "release_operations_status.json", previous.get("release_operations") or {})
    rnd_department = _load_json(DATA / "rnd_department_status.json", {})
    delivery_pipeline = _load_json(DATA / "rnd_delivery_pipeline_status.json", {})
    asset_governance = _load_json(DATA / "rnd_asset_governance_status.json", {})
    control = _load_json(DATA / "control_layer_status.json", {})
    autonomy = _load_json(DATA / "autonomy_score.json", {})
    verification = _load_json(DATA / "verification_status.json", {})
    ai_testing = _load_json(DATA / "ai_test_status.json", {})
    patch_system = control.get("patch_system") or previous.get("engineering_os") or {}
    patch_queue = patch_system.get("queue") or {}

    capabilities = reputation.get("capabilities") or {}
    workers = reputation.get("workers") or {}
    top_capability = None
    if capabilities:
        top_capability = max(capabilities.items(), key=lambda item: float((item[1] or {}).get("score", 0.0) or 0.0))[0]
    top_worker = None
    if workers:
        top_worker = max(workers.items(), key=lambda item: float((item[1] or {}).get("score", 0.0) or 0.0))[0]

    formalized = (
        control.get("status") in {"stable", "constrained"}
        and bool(evaluation.get("adopt"))
        and (verification.get("patch_gate") or {}).get("status") == "pass"
    )

    recent_ledger_experiments = _ledger_recent_experiments(experiment_ledger, now=now, window_hours=window_hours)
    completed_ledger_experiments = [entry for entry in recent_ledger_experiments if _ledger_is_completed(entry)]
    valid_experiment_count = len(completed_ledger_experiments)
    distilled_experiment_count = sum(1 for entry in completed_ledger_experiments if _ledger_has_distillation(entry))
    independent_experiment_count = sum(1 for entry in completed_ledger_experiments if _ledger_is_independent(entry))
    total_quality_delta = round(sum(float((entry.get("main_system_impact") or {}).get("quality_score_delta") or 0.0) for entry in completed_ledger_experiments), 4)
    total_task_delta = int(sum(int((entry.get("main_system_impact") or {}).get("task_completion_delta") or 0) for entry in completed_ledger_experiments))
    total_ai_delta = round(sum(float((entry.get("main_system_impact") or {}).get("ai_pass_rate_delta") or 0.0) for entry in completed_ledger_experiments), 4)
    current_quality_score = float((control.get("quality_system") or {}).get("overall_score") or 0.0)
    current_task_completion = int((((autonomy.get("metrics") or {}).get("history") or {}).get("goal_progress") or {}).get("completed_tasks_last_24h") or 0)
    current_pass_rate = float((ai_testing.get("pass_rate") or 0.0) or 0.0)

    payload = {
        "updated_at": _utc(),
        "status": "department" if str(control.get("status") or "").strip().lower() in {"stable", "constrained", "lean_execution"} else "attention",
        "organization_unit": {
            "name": "AI研发部",
            "department_id": "rnd_department",
            "type": "department",
            "upgrade_source": "automation_lab",
            "formalized": formalized,
        },
        "operating_model": rnd_department.get("operating_model", {}),
        "functional_groups": rnd_department.get("functional_groups", {}),
        "experiment_planner": {
            "candidate_count": plan.get("candidate_count", 0),
            "selected": (plan.get("selected") or {}).get("target"),
            "selection_reason": plan.get("selection_reason"),
            "auto_refill": plan.get("auto_refill", {}),
        },
        "experiment_executor": {
            "status": run.get("status"),
            "target": (run.get("experiment") or {}).get("target"),
            "kind": (run.get("experiment") or {}).get("kind"),
        },
        "experiment_evaluator": {
            "status": evaluation.get("status"),
            "score": evaluation.get("score"),
            "adopt": evaluation.get("adopt"),
        },
        "capability_distillation": {
            "status": distillation.get("status"),
            "adopted": distillation.get("adopted"),
            "capability_hint_count": len(distillation.get("capability_hints", [])),
            "worker_bias_count": len((distillation.get("worker_bias") or {})),
        },
        "knowledge_engine": {
            "experiment_patterns": len(knowledge.get("experiment_patterns", [])),
            "decision_patterns": len(knowledge.get("decision_patterns", [])),
            "repo_learning_chunks": (knowledge.get("repo_learning") or {}).get("chunk_count", 0),
            "learned_repositories": (knowledge.get("repo_learning") or {}).get("learned_repository_count", 0),
            "github_ready_repos": (knowledge.get("github_learning") or {}).get("ready_repo_count", 0),
        },
        "strategy": {
            "focus_capabilities": global_policy.get("focus_capabilities", []),
            "portfolio": global_policy.get("experiment_portfolio", {}),
            "organization_focus": organization_workboard.get("top_departments", []),
            "owning_department": "rnd_department",
        },
        "reputation": {
            "capability_count": len(capabilities),
            "worker_count": len(workers),
            "top_capability": top_capability,
            "top_worker": top_worker,
        },
        "autonomy": {
            "stage": autonomy.get("stage"),
            "score": autonomy.get("score"),
            "source": autonomy.get("source") or "autonomy_score",
            "confirmed": autonomy_is_confirmed(autonomy),
        },
        "engineering_os": {
            "status": "pass" if (verification.get("patch_gate") or {}).get("status") == "pass" else "attention",
            "patch_gate_status": (verification.get("patch_gate") or {}).get("status"),
            "patch_ready_count": patch_queue.get("ready_count"),
            "patch_blocked_count": patch_queue.get("blocked_count"),
            "patch_merge_ready": patch_queue.get("ready_count"),
        },
        "ai_testing": {
            "status": ai_testing.get("status"),
            "release_signal": ai_testing.get("release_signal"),
            "overall_score": ai_testing.get("overall_score"),
            "accuracy_score": ai_testing.get("accuracy_score"),
            "reasoning_score": ai_testing.get("reasoning_score"),
            "code_score": ai_testing.get("code_score"),
            "stability_score": ai_testing.get("stability_score"),
            "pass_rate": ai_testing.get("pass_rate"),
            "passed_cases": ai_testing.get("passed_cases"),
            "total_cases": ai_testing.get("total_cases"),
            "error_count": ai_testing.get("error_count"),
            "failing_case_ids": ai_testing.get("failing_case_ids", []),
            "layers": ai_testing.get("layers", {}),
            "updated_at": ai_testing.get("updated_at"),
        },
        "release_operations": {
            "status": release_ops.get("status"),
            "release_train_status": (release_ops.get("release_train") or {}).get("status"),
            "next_action": (release_ops.get("release_train") or {}).get("next_action"),
        },
        "delivery_pipeline": {
            "status": delivery_pipeline.get("status"),
            "stage": delivery_pipeline.get("stage"),
            "passed_phase_count": (delivery_pipeline.get("summary") or {}).get("passed_phase_count"),
            "total_phase_count": (delivery_pipeline.get("summary") or {}).get("total_phase_count"),
        },
        "asset_governance": {
            "status": asset_governance.get("status"),
            "automation_ratio": (asset_governance.get("kpi") or {}).get("automation_ratio"),
            "platform_output": (asset_governance.get("kpi") or {}).get("platform_output"),
            "product_output": (asset_governance.get("kpi") or {}).get("product_output"),
        },
        "maturity": {
            "score": round(
                min(
                    1.0,
                    (0.2 if control.get("status") in {"stable", "constrained"} else 0.0)
                    + (0.15 if evaluation.get("adopt") else 0.0)
                    + min(0.15, len(capabilities) * 0.03)
                    + min(0.1, len(workers) * 0.05)
                    + (0.1 if (verification.get("patch_gate") or {}).get("status") == "pass" else 0.0)
                    + (0.1 if organization_workboard.get("department_count", 0) >= 3 else 0.0)
                    + (0.1 if (rnd_department.get("readiness") or {}).get("organization_ready") else 0.0)
                    + (0.1 if delivery_pipeline.get("status") == "active" else 0.0),
                ),
                4,
            ),
            "status": "mature" if formalized and control.get("status") == "stable" else "developing",
            "upgraded_to": "rnd_department",
        },
        "r_and_d_readiness": {
            "status": "engineering-system"
            if delivery_pipeline.get("stage") in {"stage2_engineering", "stage3_platformizing", "stage4_productized"}
            else "research-system",
            "delivery_stage": delivery_pipeline.get("stage"),
            "organization_ready": (rnd_department.get("readiness") or {}).get("organization_ready"),
            "platform_group_ready": (rnd_department.get("readiness") or {}).get("platform_group_ready"),
            "product_group_ready": (rnd_department.get("readiness") or {}).get("product_group_ready"),
        },
        "hard_metrics": {
            "window_hours": window_hours,
            "experiment_throughput": {
                "valid_experiments_last_24h": valid_experiment_count,
                "daily_rate": valid_experiment_count,
                "measurement": "closed experiments recorded in experiment_ledger.json within the last 24 hours",
            },
            "distillation_conversion_rate": {
                "distilled_outputs_last_24h": distilled_experiment_count,
                "valid_experiments_last_24h": valid_experiment_count,
                "rate": _safe_ratio(distilled_experiment_count, valid_experiment_count),
                "measurement": "closed ledger experiments that produced at least one distillation artifact id",
            },
            "main_system_gain": {
                "measured_since": min(
                    [entry.get("started_at") for entry in completed_ledger_experiments if entry.get("started_at")] or [None]
                ),
                "attribution_mode": "ledger-recorded-main_system_impact",
                "contributing_experiment_count": valid_experiment_count,
                "current_quality_score": _round_metric(current_quality_score),
                "quality_score_delta": _round_metric(total_quality_delta),
                "current_completed_tasks_last_24h": current_task_completion,
                "task_completion_delta": total_task_delta,
                "current_ai_pass_rate": _round_metric(current_pass_rate),
                "ai_pass_rate_delta": _round_metric(total_ai_delta),
            },
            "independent_r_and_d_rate": {
                "independent_closed_loop_experiments_last_24h": independent_experiment_count,
                "valid_experiments_last_24h": valid_experiment_count,
                "rate": _safe_ratio(independent_experiment_count, valid_experiment_count),
                "measurement": "closed ledger experiments whose owner or closure_mode indicates lab-side autonomous closure",
            },
        },
    }
    kernel = identity_kernel_status()
    payload["identity_kernel"] = kernel
    payload["identity_integrity"] = {
        "status": kernel.get("status"),
        "consistency": kernel.get("consistency") or {},
        "memory": kernel.get("memory") or {},
        "authority": kernel.get("authority") or {},
        "runtime": kernel.get("runtime") or {},
        "updated_at": kernel.get("updated_at"),
    }
    payload["identity_gate"] = payload["identity_integrity"]
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_automation_lab_status(), ensure_ascii=False, indent=2))
