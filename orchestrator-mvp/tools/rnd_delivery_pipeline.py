from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "rnd_delivery_pipeline_status.json"
EXPERIMENT_PLAN = DATA / "experiment_plan.json"
EXPERIMENT_RUN = DATA / "experiment_run.json"
EXPERIMENT_EVALUATION = DATA / "experiment_evaluation.json"
VERIFICATION = DATA / "verification_status.json"
RELEASE_OPS = DATA / "release_operations_status.json"
TASKS = DATA / "tasks.json"
GOALS = ROOT / "factory" / "goals" / "goal_registry.json"


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


def _phase(name: str, status: str, evidence: dict[str, Any], automation_level: str) -> dict[str, Any]:
    return {
        "phase": name,
        "status": status,
        "automation_level": automation_level,
        "evidence": evidence,
    }


def build_rnd_delivery_pipeline_status() -> dict[str, Any]:
    plan = _load_json(EXPERIMENT_PLAN, {})
    run = _load_json(EXPERIMENT_RUN, {})
    evaluation = _load_json(EXPERIMENT_EVALUATION, {})
    verification = _load_json(VERIFICATION, {})
    release_ops = _load_json(RELEASE_OPS, {})
    tasks = _load_json(TASKS, [])
    goals = _load_json(GOALS, [])

    active_tasks = [item for item in tasks if item.get("status") in {"queued", "planning", "running", "waiting_approval"}]
    active_goals = [item for item in goals if item.get("status") in {"pending", "planned", "running"}]
    completed_goals = [item for item in goals if item.get("status") == "completed"]

    phases = [
        _phase(
            "research",
            "pass" if plan.get("candidate_count", 0) > 0 else "attention",
            {
                "candidate_count": plan.get("candidate_count", 0),
                "selected": (plan.get("selected") or {}).get("target"),
            },
            "auto-assisted",
        ),
        _phase(
            "prototype",
            "pass" if run.get("status") == "completed" else "attention",
            {
                "run_status": run.get("status"),
                "target": (run.get("experiment") or {}).get("target"),
                "kind": (run.get("experiment") or {}).get("kind"),
            },
            "auto-executed",
        ),
        _phase(
            "engineering",
            "pass" if len(active_tasks) + len(completed_goals) > 0 else "attention",
            {
                "active_task_count": len(active_tasks),
                "active_goal_count": len(active_goals),
                "completed_goal_count": len(completed_goals),
            },
            "system-dispatched",
        ),
        _phase(
            "testing",
            "pass" if (verification.get("patch_gate") or {}).get("status") == "pass" else "attention",
            {
                "verification_status": verification.get("status"),
                "patch_gate_status": (verification.get("patch_gate") or {}).get("status"),
                "tool_health_status": (verification.get("tool_health") or {}).get("status"),
            },
            "auto-validated",
        ),
        _phase(
            "release",
            "pass" if (release_ops.get("release_train") or {}).get("status") == "ready" else "attention",
            {
                "release_train_status": (release_ops.get("release_train") or {}).get("status"),
                "next_action": (release_ops.get("release_train") or {}).get("next_action"),
            },
            "controller-gated",
        ),
        _phase(
            "maintenance",
            "pass" if verification.get("status") == "pass" else "attention",
            {
                "verification_status": verification.get("status"),
                "active_task_count": len(active_tasks),
            },
            "daemon-supervised",
        ),
    ]

    passed_count = sum(1 for item in phases if item["status"] == "pass")
    stage = "stage4_productized"
    if passed_count < 6:
        stage = "stage3_platformizing"
    if passed_count < 5:
        stage = "stage2_engineering"
    if passed_count < 3:
        stage = "stage1_research_lab"

    payload = {
        "updated_at": _utc(),
        "status": "active" if passed_count >= 4 else "attention",
        "stage": stage,
        "lifecycle": phases,
        "summary": {
            "passed_phase_count": passed_count,
            "total_phase_count": len(phases),
            "evaluation_score": evaluation.get("score"),
            "evaluation_adopted": evaluation.get("adopt"),
        },
    }
    _save_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_rnd_delivery_pipeline_status(), ensure_ascii=False, indent=2))
