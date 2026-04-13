from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from tools.kernel_mode import load_kernel_mode

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
EXECUTOR_DIR = CONTRACTS / "executors"
SCHEMA_DIR = CONTRACTS / "schemas"
REGISTRY_PATH = EXECUTOR_DIR / "executor_registry.json"
ROUTING_POLICY_PATH = EXECUTOR_DIR / "routing_policy.json"
VERIFICATION_POLICY_PATH = EXECUTOR_DIR / "verification_policy.json"
ROUTE_EXPERIENCE_PATH = EXECUTOR_DIR / "route_experience.json"

SURFACE_EXECUTOR_MAP = {
    "aider": "aider_executor",
    "openhands": "openhands_executor",
    "plandex": "plandex_executor",
    "goose": "goose_executor",
    "continue": "continue_executor",
    "codex": "opencode_executor",
    "opencode": "opencode_executor",
}

INTERACTION_ONLY_LOCAL_EXECUTORS = {"opencode_executor", "codex_executor", "script_executor"}
INTERACTION_ONLY_EXTERNAL_EXECUTORS = {
    "aider_executor",
    "openhands_executor",
    "plandex_executor",
    "goose_executor",
    "continue_executor",
    "ci_executor",
    "human_review_executor",
}
MUTATING_TASK_TYPES = {
    "build_fix",
    "subsystem_refactor",
    "architecture_migration",
    "path_repair",
    "unit_test_run",
    "demo_rebuild",
    "package_validation",
    "harness_regression_run",
    "qemu_smoke_run",
    "doc_patch",
    "json_fix",
    "config_fix",
    "manifest_patch",
    "small_json_patch",
    "new_artifact_bootstrap",
    "new_demo_creation",
}
READ_ONLY_TASK_TYPES = {
    "report_refresh",
    "registry_reconcile",
    "evidence_collect",
    "artifact_audit",
    "independent_evidence_check",
    "release_decision_review",
}


@dataclass(frozen=True)
class ExecutorRoute:
    executor_id: str
    adapter: str | None
    reason: str
    score: int
    rule_id: str | None = None
    supported_task_types: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "executor_id": self.executor_id,
            "adapter": self.adapter,
            "reason": self.reason,
            "score": self.score,
            "supported_task_types": list(self.supported_task_types),
        }
        if self.rule_id is not None:
            payload["rule_id"] = self.rule_id
        return payload


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


@lru_cache(maxsize=1)
def load_executor_registry() -> dict[str, Any]:
    return _load_json(REGISTRY_PATH, {"version": "v1", "executors": []})


@lru_cache(maxsize=1)
def load_routing_policy() -> dict[str, Any]:
    return _load_json(
        ROUTING_POLICY_PATH,
        {"version": "v1", "default_executor_id": "script_executor", "rules": []},
    )


@lru_cache(maxsize=1)
def load_verification_policy() -> dict[str, Any]:
    return _load_json(VERIFICATION_POLICY_PATH, {"version": "v1", "levels": []})


@lru_cache(maxsize=1)
def load_route_experience() -> dict[str, Any]:
    return _load_json(ROUTE_EXPERIENCE_PATH, {"version": "v1", "executors": {}})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _normalize_experience_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    samples = int(bucket.get("samples") or 0)
    success_count = int(bucket.get("success_count") or 0)
    failure_count = int(bucket.get("failure_count") or 0)
    total_latency_ms = int(bucket.get("total_latency_ms") or 0)
    total_cost_units = float(bucket.get("total_cost_units") or 0.0)
    total_samples = max(0, samples)
    success_rate = round((success_count / total_samples), 3) if total_samples else 0.0
    avg_latency_ms = round(total_latency_ms / total_samples, 2) if total_samples else 0.0
    avg_cost_units = round(total_cost_units / total_samples, 3) if total_samples else 0.0
    bucket.update(
        {
            "samples": total_samples,
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_rate,
            "avg_latency_ms": avg_latency_ms,
            "avg_cost_units": avg_cost_units,
        }
    )
    return bucket


def record_route_experience(
    *,
    executor_id: str,
    success: bool,
    latency_ms: int,
    cost_units: float,
    task_type: str | None = None,
    verification_level: str | None = None,
    execution_mode: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    executor_key = str(executor_id or "").strip()
    if not executor_key:
        return load_route_experience()
    snapshot = load_route_experience()
    executors = snapshot.setdefault("executors", {})
    bucket = executors.setdefault(
        executor_key,
        {
            "samples": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_latency_ms": 0,
            "total_cost_units": 0.0,
            "last_seen_at": None,
            "last_task_id": None,
            "last_task_type": None,
            "last_verification_level": None,
            "last_execution_mode": None,
        },
    )
    bucket["samples"] = int(bucket.get("samples") or 0) + 1
    if success:
        bucket["success_count"] = int(bucket.get("success_count") or 0) + 1
    else:
        bucket["failure_count"] = int(bucket.get("failure_count") or 0) + 1
    bucket["total_latency_ms"] = int(bucket.get("total_latency_ms") or 0) + max(0, int(latency_ms))
    bucket["total_cost_units"] = float(bucket.get("total_cost_units") or 0.0) + max(0.0, float(cost_units))
    bucket["last_seen_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    bucket["last_task_id"] = task_id
    bucket["last_task_type"] = task_type
    bucket["last_verification_level"] = verification_level
    bucket["last_execution_mode"] = execution_mode
    executors[executor_key] = _normalize_experience_bucket(bucket)
    snapshot["executors"] = executors
    _write_json(ROUTE_EXPERIENCE_PATH, snapshot)
    load_route_experience.cache_clear()
    return snapshot


def _experience_adjustment(executor_id: str, *, task_type: str, verification_level: str) -> tuple[int, dict[str, Any]]:
    snapshot = load_route_experience()
    bucket = dict((snapshot.get("executors") or {}).get(executor_id) or {})
    if not bucket:
        return 0, {"samples": 0, "success_rate": 0.0, "avg_latency_ms": 0.0, "avg_cost_units": 0.0}
    samples = int(bucket.get("samples") or 0)
    success_rate = float(bucket.get("success_rate") or 0.0)
    avg_latency_ms = float(bucket.get("avg_latency_ms") or 0.0)
    avg_cost_units = float(bucket.get("avg_cost_units") or 0.0)
    confidence_bonus = min(3.0, samples / 4.0)
    success_bonus = (success_rate - 0.5) * 6.0
    latency_penalty = min(3.5, avg_latency_ms / 20000.0)
    cost_penalty = min(2.5, avg_cost_units / 4.0)
    adjustment = int(round(success_bonus + confidence_bonus - latency_penalty - cost_penalty))
    snapshot_info = {
        "samples": samples,
        "success_rate": round(success_rate, 3),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "avg_cost_units": round(avg_cost_units, 3),
        "task_type": task_type,
        "verification_level": verification_level,
    }
    return adjustment, snapshot_info


def list_executors() -> list[dict[str, Any]]:
    registry = load_executor_registry()
    return list(registry.get("executors") or [])


def _executor_lookup() -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for executor in list_executors():
        executor_id = str(executor.get("executor_id") or "").strip()
        if executor_id and bool(executor.get("enabled", True)):
            lookup[executor_id] = executor
    return lookup


def _normalize_set(value: Any) -> set[str]:
    return {str(item).strip().lower() for item in (value or []) if str(item).strip()}


def _verification_profile(level: str) -> dict[str, Any]:
    verification_policy = load_verification_policy()
    for item in verification_policy.get("levels") or []:
        if str(item.get("level") or "").strip().upper() == level:
            return item
    return {"level": level or "L2", "required_checks": [], "human_review_required": False}


def _interaction_only_active() -> bool:
    return str((load_kernel_mode() or {}).get("profile") or "").strip().lower() == "interaction_only"


def _interaction_only_forces_external(task_type: str) -> bool:
    if not _interaction_only_active():
        return False
    normalized = str(task_type or "").strip().lower()
    if not normalized:
        return False
    return normalized in MUTATING_TASK_TYPES or normalized not in READ_ONLY_TASK_TYPES


def resolve_executor_route(
    *,
    task_type: str | None,
    verification_level: str | None,
    execution_mode: str | None,
    preferred_worker: str | None = None,
    executor_hint: dict[str, Any] | None = None,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = load_executor_registry()
    policy = load_routing_policy()
    executors = _executor_lookup()
    hint = executor_hint or {}
    explicit_executor_id = str(hint.get("executor_id") or "").strip()
    explicit_surface = str(
        hint.get("preferred_surface")
        or hint.get("surface")
        or ((hint.get("surface_route") or {}).get("preferred_surface"))
        or ""
    ).strip().lower()
    normalized_task_type = str(task_type or "").strip().lower()
    normalized_verification = str(verification_level or "").strip().upper()
    normalized_mode = str(execution_mode or "").strip().lower()
    normalized_worker = str(preferred_worker or "").strip().lower()
    interaction_only = _interaction_only_active()
    force_external = _interaction_only_forces_external(normalized_task_type)

    if explicit_executor_id and explicit_executor_id in executors:
        selected = executors[explicit_executor_id]
        if interaction_only and force_external and explicit_executor_id in INTERACTION_ONLY_LOCAL_EXECUTORS:
            selected = None
        else:
            return {
                "selected": {
                    "executor_id": explicit_executor_id,
                    "adapter": selected.get("adapter"),
                    "reason": "explicit executor hint",
                    "score": 999,
                    "supported_task_types": list(selected.get("task_types") or []),
                },
                "candidates": [],
                "policy_version": policy.get("version", "v1"),
                "registry_version": registry.get("version", "v1"),
                "verification_profile": _verification_profile(normalized_verification),
                "resolved_task_type": normalized_task_type,
                "interaction_only": interaction_only,
                "force_external_executor": force_external,
                "task_context": task_context or {},
            }
    if explicit_surface:
        executor_id = SURFACE_EXECUTOR_MAP.get(explicit_surface)
        if interaction_only and force_external and executor_id in INTERACTION_ONLY_LOCAL_EXECUTORS:
            executor_id = None
        if executor_id and executor_id in executors:
            selected = executors[executor_id]
            return {
                "selected": {
                    "executor_id": executor_id,
                    "adapter": selected.get("adapter"),
                    "reason": f"surface route hint: {explicit_surface}",
                    "score": 998,
                    "supported_task_types": list(selected.get("task_types") or []),
                },
                "candidates": [],
                "policy_version": policy.get("version", "v1"),
                "registry_version": registry.get("version", "v1"),
                "verification_profile": _verification_profile(normalized_verification),
                "resolved_task_type": normalized_task_type,
                "interaction_only": interaction_only,
                "force_external_executor": force_external,
                "task_context": task_context or {},
            }
    if explicit_executor_id:
        return {
            "selected": None,
            "candidates": [],
            "policy_version": policy.get("version", "v1"),
            "registry_version": registry.get("version", "v1"),
            "verification_profile": _verification_profile(normalized_verification),
            "resolved_task_type": normalized_task_type,
            "interaction_only": interaction_only,
            "force_external_executor": force_external,
            "task_context": task_context or {},
            "reason": f"executor '{explicit_executor_id}' is unavailable or disabled",
        }

    candidates: list[dict[str, Any]] = []
    for rule in policy.get("rules") or []:
        rule_task_types = _normalize_set(rule.get("task_types"))
        rule_modes = _normalize_set(rule.get("execution_modes"))
        rule_verification_levels = _normalize_set(rule.get("verification_levels"))
        rule_workers = _normalize_set(rule.get("preferred_workers"))
        score = 0
        reasons: list[str] = []
        if normalized_task_type and normalized_task_type in rule_task_types:
            score += 4
            reasons.append(f"task_type={normalized_task_type}")
        if normalized_mode and normalized_mode in rule_modes:
            score += 2
            reasons.append(f"execution_mode={normalized_mode}")
        if normalized_verification and normalized_verification.lower() in rule_verification_levels:
            score += 2
            reasons.append(f"verification_level={normalized_verification}")
        if normalized_worker and normalized_worker in rule_workers:
            score += 1
            reasons.append(f"preferred_worker={normalized_worker}")
        if score <= 0:
            continue
        executor_id = str(rule.get("executor_id") or "").strip()
        if executor_id not in executors:
            continue
        if interaction_only and force_external and executor_id in INTERACTION_ONLY_LOCAL_EXECUTORS:
            continue
        executor = executors.get(executor_id, {})
        experience_adjustment, experience = _experience_adjustment(
            executor_id,
            task_type=normalized_task_type,
            verification_level=normalized_verification,
        )
        candidates.append(
            {
                "executor_id": executor_id,
                "adapter": executor.get("adapter"),
                "reason": "; ".join(reasons) if reasons else "matched routing rule",
                "score": score + experience_adjustment,
                "rule_id": rule.get("rule_id"),
                "supported_task_types": sorted(rule_task_types),
                "supports_parallel": bool(executor.get("supports_parallel", False)),
                "supports_long_horizon": bool(executor.get("supports_long_horizon", False)),
                "experience": experience,
            }
        )

    candidates.sort(key=lambda item: (-item["score"], str(item["executor_id"])))
    selected = candidates[0] if candidates else None
    if selected is None:
        if interaction_only and force_external:
            external_defaults = [
                "aider_executor",
                "goose_executor",
                "continue_executor",
                "openhands_executor",
                "plandex_executor",
                "ci_executor",
                "human_review_executor",
            ]
            default_executor_id = next((executor_id for executor_id in external_defaults if executor_id in executors), None)
            if default_executor_id is None:
                return {
                    "selected": None,
                    "candidates": candidates[:5],
                    "policy_version": policy.get("version", "v1"),
                    "registry_version": registry.get("version", "v1"),
                    "verification_profile": _verification_profile(normalized_verification),
                    "resolved_task_type": normalized_task_type,
                    "interaction_only": interaction_only,
                    "force_external_executor": force_external,
                    "task_context": task_context or {},
                    "reason": "interaction_only requires an external executor, but no external executor is available",
                }
        else:
            default_executor_id = str(policy.get("default_executor_id") or "script_executor").strip()
        default_executor = executors.get(default_executor_id, {})
        default_experience_adjustment, default_experience = _experience_adjustment(
            default_executor_id,
            task_type=normalized_task_type,
            verification_level=normalized_verification,
        )
        selected = {
            "executor_id": default_executor_id,
            "adapter": default_executor.get("adapter"),
            "reason": "default routing fallback",
            "score": default_experience_adjustment,
            "rule_id": None,
            "supported_task_types": list(default_executor.get("task_types") or []),
            "supports_parallel": bool(default_executor.get("supports_parallel", False)),
            "supports_long_horizon": bool(default_executor.get("supports_long_horizon", False)),
            "experience": default_experience,
        }

    context = task_context or {}
    return {
        "selected": selected,
        "candidates": candidates[:5],
        "policy_version": policy.get("version", "v1"),
        "registry_version": registry.get("version", "v1"),
        "verification_profile": _verification_profile(normalized_verification),
        "resolved_task_type": normalized_task_type,
        "interaction_only": interaction_only,
        "force_external_executor": force_external,
        "task_context": {
            key: value
            for key, value in context.items()
            if key in {"queue_name", "artifact_scope", "risk_level", "artifact_id"}
        },
    }
