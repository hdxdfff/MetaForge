from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LEDGER = DATA / "experiment_ledger.json"
CONTROL = DATA / "control_layer_status.json"
AUTONOMY = DATA / "autonomy_score.json"
AI_TESTING = DATA / "ai_test_status.json"


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


def _default_ledger() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "updated_at": _utc(),
        "experiments": [],
    }


def load_ledger() -> dict[str, Any]:
    ledger = _load_json(LEDGER, _default_ledger())
    if not isinstance(ledger, dict):
        ledger = _default_ledger()
    experiments = ledger.get("experiments")
    if not isinstance(experiments, list):
        ledger["experiments"] = []
    ledger.setdefault("schema_version", "1.0")
    ledger.setdefault("updated_at", _utc())
    return ledger


def save_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    ledger["updated_at"] = _utc()
    _save_json(LEDGER, ledger)
    return ledger


def _current_main_system_snapshot() -> dict[str, float | int | None]:
    control = _load_json(CONTROL, {})
    autonomy = _load_json(AUTONOMY, {})
    ai_testing = _load_json(AI_TESTING, {})
    return {
        "quality_score": float((control.get("quality_system") or {}).get("overall_score") or 0.0),
        "completed_tasks_last_24h": int((((autonomy.get("metrics") or {}).get("history") or {}).get("goal_progress") or {}).get("completed_tasks_last_24h") or 0),
        "ai_pass_rate": float(ai_testing.get("pass_rate") or 0.0),
        "captured_at": _utc(),
    }


def _new_experiment_id(kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    normalized = str(kind or "experiment").strip().replace("_", "-")
    return f"exp-{stamp}-{normalized}"


def _find_index(ledger: dict[str, Any], experiment_id: str) -> int:
    experiments = ledger.get("experiments") or []
    for index, item in enumerate(experiments):
        if str(item.get("experiment_id") or "") == experiment_id:
            return index
    return -1


def _find_open_match_index(ledger: dict[str, Any], experiment: dict[str, Any]) -> int:
    target = str(experiment.get("target") or "").strip().lower()
    kind = str(experiment.get("kind") or "").strip().lower()
    experiments = ledger.get("experiments") or []
    for index, item in enumerate(experiments):
        status = str(item.get("status") or "").strip().lower()
        if status not in {"planned", "running"}:
            continue
        existing = item.get("experiment") or {}
        existing_target = str(existing.get("target") or "").strip().lower()
        existing_kind = str(existing.get("kind") or "").strip().lower()
        if target and existing_target == target:
            return index
        if kind and existing_kind == kind:
            return index
    return -1


def _merge_dict(target: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            target[key] = _merge_dict(dict(target.get(key) or {}), value)
        else:
            target[key] = value
    return target


def get_recent_experiments(*, window_hours: int = 24, statuses: set[str] | None = None) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    recent: list[dict[str, Any]] = []
    for entry in load_ledger().get("experiments", []):
        ended_at = _parse_utc(entry.get("ended_at"))
        started_at = _parse_utc(entry.get("started_at"))
        stamp = ended_at or started_at
        if stamp is None:
            continue
        age_hours = (now - stamp).total_seconds() / 3600.0
        if age_hours < 0 or age_hours > window_hours:
            continue
        if statuses and str(entry.get("status") or "") not in statuses:
            continue
        recent.append(entry)
    return recent


def has_recent_standard_experiment(kind: str, *, window_hours: int = 24) -> bool:
    normalized = str(kind or "").strip().lower()
    if not normalized:
        return False
    for entry in get_recent_experiments(window_hours=window_hours):
        experiment = entry.get("experiment") or {}
        if str(experiment.get("kind") or "").strip().lower() == normalized:
            return True
    return False


def ensure_experiment_entry(
    experiment: dict[str, Any],
    *,
    hypothesis: str,
    owner: str = "automation_lab",
    auto_generated: bool = False,
    standard_experiment: bool = False,
    closure_mode: str = "lab_autonomous",
    seed_only: bool = False,
) -> dict[str, Any]:
    experiment_id = str(experiment.get("experiment_id") or "").strip()
    ledger = load_ledger()
    if not experiment_id:
        open_match_index = _find_open_match_index(ledger, experiment)
        if open_match_index >= 0:
            experiment_id = str((ledger.get("experiments") or [])[open_match_index].get("experiment_id") or "")
        else:
            experiment_id = _new_experiment_id(str(experiment.get("kind") or "experiment"))
    index = _find_index(ledger, experiment_id)
    if index >= 0:
        entry = ledger["experiments"][index]
        updates = {
            "experiment": {
                "target": experiment.get("target"),
                "kind": experiment.get("kind"),
                "goal_type": experiment.get("goal_type"),
                "worker": experiment.get("worker"),
                "source": experiment.get("source"),
            },
            "hypothesis": hypothesis,
            "owner": owner,
            "auto_generated": auto_generated,
            "standard_experiment": standard_experiment,
            "closure_mode": closure_mode,
        }
        if seed_only and str(entry.get("status") or "") not in {"planned", "running"}:
            updates["status"] = "planned"
        merged = _merge_dict(dict(entry), updates)
        ledger["experiments"][index] = merged
        save_ledger(ledger)
        return merged

    entry = {
        "experiment_id": experiment_id,
        "hypothesis": hypothesis,
        "owner": owner,
        "started_at": _utc(),
        "ended_at": None,
        "status": "planned",
        "experiment": {
            "target": experiment.get("target"),
            "kind": experiment.get("kind"),
            "goal_type": experiment.get("goal_type"),
            "worker": experiment.get("worker"),
            "source": experiment.get("source"),
        },
        "evidence": {
            "plan_path": str(DATA / "experiment_plan.json"),
            "run_path": None,
            "evaluation_path": None,
            "distillation_path": None,
            "history_path": str(DATA / "experiment_history.json"),
        },
        "verdict": {
            "status": "pending",
            "reason": None,
            "score": None,
        },
        "distillation_artifact_ids": [],
        "main_system_impact": {
            "baseline": _current_main_system_snapshot(),
            "current": None,
            "quality_score_delta": None,
            "task_completion_delta": None,
            "ai_pass_rate_delta": None,
        },
        "auto_generated": auto_generated,
        "standard_experiment": standard_experiment,
        "closure_mode": closure_mode,
        "notes": [],
    }
    ledger.setdefault("experiments", []).append(entry)
    save_ledger(ledger)
    return entry


def update_experiment_entry(experiment_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    ledger = load_ledger()
    index = _find_index(ledger, experiment_id)
    if index < 0:
        raise KeyError(f"experiment_id not found: {experiment_id}")
    entry = dict(ledger["experiments"][index])
    ledger["experiments"][index] = _merge_dict(entry, updates)
    save_ledger(ledger)
    return ledger["experiments"][index]


def mark_running(experiment_id: str) -> dict[str, Any]:
    return update_experiment_entry(
        experiment_id,
        {
            "status": "running",
            "started_at": _utc(),
            "evidence": {
                "run_path": str(DATA / "experiment_run.json"),
            },
        },
    )


def mark_completed(experiment_id: str, run_payload: dict[str, Any]) -> dict[str, Any]:
    return update_experiment_entry(
        experiment_id,
        {
            "status": "completed",
            "ended_at": run_payload.get("updated_at") or _utc(),
            "evidence": {
                "run_path": str(DATA / "experiment_run.json"),
                "history_path": str(DATA / "experiment_history.json"),
            },
        },
    )


def mark_evaluated(experiment_id: str, evaluation_payload: dict[str, Any]) -> dict[str, Any]:
    adopt = bool(evaluation_payload.get("adopt"))
    verdict_status = "adopt" if adopt else "reject"
    return update_experiment_entry(
        experiment_id,
        {
            "status": "evaluated",
            "evidence": {
                "evaluation_path": str(DATA / "experiment_evaluation.json"),
            },
            "verdict": {
                "status": verdict_status,
                "reason": evaluation_payload.get("reason"),
                "score": evaluation_payload.get("score"),
            },
        },
    )


def close_with_distillation(experiment_id: str, distillation_payload: dict[str, Any]) -> dict[str, Any]:
    status = str(distillation_payload.get("status") or "idle")
    artifact_ids = list(distillation_payload.get("distillation_artifact_ids") or [])
    verdict_status = "no_distillation_value" if status == "no_distillation_value" else str((distillation_payload.get("verdict") or {}).get("status") or "pending")
    ledger = load_ledger()
    index = _find_index(ledger, experiment_id)
    if index < 0:
        raise KeyError(f"experiment_id not found: {experiment_id}")
    baseline = ((ledger.get("experiments") or [])[index].get("main_system_impact") or {}).get("baseline") or {}
    current = _current_main_system_snapshot()
    quality_delta = current["quality_score"] - float(baseline.get("quality_score") or current["quality_score"])
    task_delta = int(current["completed_tasks_last_24h"] or 0) - int(baseline.get("completed_tasks_last_24h") or current["completed_tasks_last_24h"] or 0)
    pass_delta = current["ai_pass_rate"] - float(baseline.get("ai_pass_rate") or current["ai_pass_rate"])
    return update_experiment_entry(
        experiment_id,
        {
            "status": "closed",
            "evidence": {
                "distillation_path": str(DATA / "capability_distillation.json"),
            },
            "verdict": {
                "status": verdict_status,
                "reason": (distillation_payload.get("verdict") or {}).get("reason"),
                "score": (distillation_payload.get("verdict") or {}).get("score"),
            },
            "distillation_artifact_ids": artifact_ids,
            "main_system_impact": {
                "current": current,
                "quality_score_delta": round(float(quality_delta), 4),
                "task_completion_delta": int(task_delta),
                "ai_pass_rate_delta": round(float(pass_delta), 4),
            },
        },
    )
