from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import pvariance
from typing import Any

from tools.artifact_learning import extract_success_pattern, load_tasks
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STRATEGY_MEMORY = DATA / "strategy_memory.json"
STRATEGY_STATUS = DATA / "strategy_status.json"
ARTIFACT_REGISTRY = DATA / "artifact_registry.json"
RUNTIME_TASKS = ROOT / "factory" / "runtime" / "tasks"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _default_memory() -> dict[str, Any]:
    return {
        "updated_at": None,
        "revision": 0,
        "exploration_ratio": 0.2,
        "last_review": None,
        "review_summary": {},
        "patterns": [],
    }


def load_strategy_memory() -> dict[str, Any]:
    payload = _load_json(STRATEGY_MEMORY, _default_memory())
    if not isinstance(payload, dict):
        payload = _default_memory()
    payload.setdefault("revision", 0)
    payload.setdefault("exploration_ratio", 0.2)
    payload.setdefault("patterns", [])
    return payload


def _task_has_verified_completion(task: dict[str, Any]) -> bool:
    if not isinstance(task, dict) or str(task.get("status") or "").strip().lower() != "completed":
        return False
    result = task.get("result")
    if isinstance(result, dict):
        production_evidence = result.get("production_evidence")
        if isinstance(production_evidence, dict) and str(production_evidence.get("status") or "").strip().lower() == "verified":
            return True
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        return False
    payload = _load_json(RUNTIME_TASKS / task_id / "execution-evidence.json", {})
    return bool(isinstance(payload, dict) and payload.get("completed") and (payload.get("steps") or []))


def _merge_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _group_patterns(patterns: list[dict[str, Any]], previous: dict[str, Any]) -> list[dict[str, Any]]:
    previous_patterns = {
        str(item.get("pattern_id") or "").strip(): item
        for item in previous.get("patterns", [])
        if isinstance(item, dict) and str(item.get("pattern_id") or "").strip()
    }
    grouped: dict[str, dict[str, Any]] = {}
    for raw in patterns:
        pattern_id = str(raw.get("pattern_id") or "").strip()
        if not pattern_id:
            continue
        current = grouped.get(pattern_id)
        if current is None:
            current = {
                **raw,
                "source_artifact_ids": [],
                "source_task_ids": [],
                "success_count": 0,
                "failure_count": 0,
                "used_by_task_count": 0,
                "successful_reuse_count": 0,
                "failed_reuse_count": 0,
            }
            grouped[pattern_id] = current
        current["success_count"] += 1
        current["source_artifact_ids"] = _merge_unique(current["source_artifact_ids"] + [raw.get("source_artifact_id")])
        current["source_task_ids"] = _merge_unique(current["source_task_ids"] + [raw.get("source_task_id")])
        current["tools_used"] = _merge_unique(list(current.get("tools_used", [])) + list(raw.get("tools_used", [])))
        current["tool_actions"] = _merge_unique(list(current.get("tool_actions", [])) + list(raw.get("tool_actions", [])))
        current["scope_tokens"] = _merge_unique(list(current.get("scope_tokens", [])) + list(raw.get("scope_tokens", [])))
        current["complexity_score"] = round(
            (
                float(current.get("complexity_score") or 0.0) * max(current["success_count"] - 1, 0)
                + float(raw.get("complexity_score") or 0.0)
            )
            / max(current["success_count"], 1),
            2,
        )

    for pattern_id, current in grouped.items():
        previous_item = previous_patterns.get(pattern_id, {})
        if previous_item.get("status") in {"pruned", "reinforced"}:
            current["status"] = previous_item.get("status")
        if previous_item.get("last_reviewed_at"):
            current["last_reviewed_at"] = previous_item.get("last_reviewed_at")
    return list(grouped.values())


def _strategy_usage(tasks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    for task in tasks:
        scheduler_hint = task.get("scheduler_hint") or {}
        context_strategy = (task.get("context_package") or {}).get("strategy") or {}
        pattern_id = str(
            scheduler_hint.get("strategy_pattern_id")
            or context_strategy.get("pattern_id")
            or ""
        ).strip()
        strategy_applied = bool(
            scheduler_hint.get("strategy_applied")
            or context_strategy.get("applied")
        )
        if not pattern_id or not strategy_applied:
            continue
        status = str(task.get("status") or "").strip().lower()
        if status not in {"completed", "failed", "timed_out", "cancelled", "canceled"}:
            continue
        current = usage.setdefault(
            pattern_id,
            {
                "used_by_task_count": 0,
                "successful_reuse_count": 0,
                "failed_reuse_count": 0,
                "recent_task_ids": [],
            },
        )
        current["used_by_task_count"] += 1
        task_id = str(task.get("id") or "").strip()
        if task_id:
            current["recent_task_ids"] = _merge_unique(current["recent_task_ids"] + [task_id])[:10]
        if status == "completed" and _task_has_verified_completion(task):
            current["successful_reuse_count"] += 1
        else:
            current["failed_reuse_count"] += 1
    return usage


def _score_pattern(pattern: dict[str, Any]) -> float:
    source_success = int(pattern.get("success_count") or 0)
    reuse_success = int(pattern.get("successful_reuse_count") or 0)
    reuse_failures = int(pattern.get("failed_reuse_count") or 0)
    positive = source_success + reuse_success + 1
    negative = reuse_failures + 1
    base = positive / max(positive + negative, 1)
    support_bonus = min(0.15, 0.03 * len(pattern.get("source_artifact_ids", [])))
    complexity_bonus = min(0.08, float(pattern.get("complexity_score") or 0.0) / 100.0)
    return round(min(base + support_bonus + complexity_bonus, 0.99), 4)


def _normalize_pattern(pattern: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    pattern = dict(pattern)
    pattern.update(usage)
    pattern["failure_count"] = int(pattern.get("failed_reuse_count") or 0)
    pattern["score"] = _score_pattern(pattern)
    if pattern["score"] >= 0.75:
        pattern["status"] = "reinforced"
    elif pattern["score"] >= 0.55:
        pattern["status"] = "active"
    elif pattern["score"] >= 0.4:
        pattern["status"] = "learning"
    else:
        pattern["status"] = "warning"
    pattern["updated_at"] = _utc()
    pattern["source_artifact_count"] = len(pattern.get("source_artifact_ids", []))
    pattern["source_task_count"] = len(pattern.get("source_task_ids", []))
    return pattern


def _memory_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_view = {
        "exploration_ratio": previous.get("exploration_ratio"),
        "patterns": previous.get("patterns"),
        "review_summary": previous.get("review_summary"),
    }
    current_view = {
        "exploration_ratio": current.get("exploration_ratio"),
        "patterns": current.get("patterns"),
        "review_summary": current.get("review_summary"),
    }
    return json.dumps(previous_view, sort_keys=True) != json.dumps(current_view, sort_keys=True)


def _build_status(memory: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    patterns = [item for item in memory.get("patterns", []) if isinstance(item, dict)]
    scores = [float(item.get("score") or 0.0) for item in patterns]
    artifacts = registry.get("artifacts", []) if isinstance(registry, dict) else []
    artifact_count = len(artifacts)
    valuable_artifact_count = sum(1 for item in artifacts if (item.get("value") or {}).get("valuable"))
    reuse_total = sum(int(item.get("used_by_task_count") or 0) for item in patterns)
    reuse_success = sum(int(item.get("successful_reuse_count") or 0) for item in patterns)
    active_patterns = [item for item in patterns if item.get("status") in {"active", "reinforced"}]
    return {
        "updated_at": _utc(),
        "revision": memory.get("revision", 0),
        "pattern_count": len(patterns),
        "active_pattern_count": len(active_patterns),
        "strategy_guided_terminal_tasks": reuse_total,
        "reuse_success_rate": round(reuse_success / reuse_total, 4) if reuse_total else 0.0,
        "valuable_artifact_ratio": round(valuable_artifact_count / artifact_count, 4) if artifact_count else 0.0,
        "pattern_score_variance": round(pvariance(scores), 4) if len(scores) > 1 else 0.0,
        "exploration_ratio": float(memory.get("exploration_ratio") or 0.2),
        "valuable_artifact_count": valuable_artifact_count,
        "artifact_count": artifact_count,
        "top_patterns": [
            {
                "pattern_id": item.get("pattern_id"),
                "task_type": item.get("task_type"),
                "score": item.get("score"),
                "preferred_worker": item.get("preferred_worker"),
                "tools_used": item.get("tools_used", [])[:5],
                "status": item.get("status"),
            }
            for item in sorted(patterns, key=lambda entry: float(entry.get("score") or 0.0), reverse=True)[:5]
        ],
        "review_summary": memory.get("review_summary") or {},
    }


def refresh_strategy_memory(
    registry: dict[str, Any] | None = None,
    *,
    write_outputs: bool = True,
) -> dict[str, Any]:
    previous = load_strategy_memory()
    if registry is None:
        registry = _load_json(ARTIFACT_REGISTRY, {})
    if not isinstance(registry, dict):
        registry = {}
    tasks = load_tasks()
    valuable_artifacts = [
        item
        for item in (registry.get("artifacts") or [])
        if isinstance(item, dict) and (item.get("value") or {}).get("valuable")
    ]
    raw_patterns = [extract_success_pattern(item, tasks) for item in valuable_artifacts]
    grouped = _group_patterns(raw_patterns, previous)
    usage = _strategy_usage(tasks)
    previous_patterns = {
        str(item.get("pattern_id") or "").strip(): item
        for item in previous.get("patterns", [])
        if isinstance(item, dict) and str(item.get("pattern_id") or "").strip()
    }
    normalized: list[dict[str, Any]] = []
    known_pattern_ids = set()
    for item in grouped:
        pattern_id = str(item.get("pattern_id") or "").strip()
        normalized.append(_normalize_pattern(item, usage.get(pattern_id, {})))
        known_pattern_ids.add(pattern_id)
    for pattern_id, usage_data in usage.items():
        if pattern_id in known_pattern_ids:
            continue
        previous_item = previous_patterns.get(pattern_id)
        if previous_item:
            normalized.append(_normalize_pattern(previous_item, usage_data))
    normalized.sort(key=lambda item: (float(item.get("score") or 0.0), int(item.get("success_count") or 0)), reverse=True)
    memory = {
        "updated_at": _utc(),
        "revision": previous.get("revision", 0),
        "exploration_ratio": float(previous.get("exploration_ratio") or 0.2),
        "last_review": previous.get("last_review"),
        "review_summary": previous.get("review_summary") or {},
        "patterns": normalized,
    }
    if _memory_changed(previous, memory):
        memory["revision"] = int(previous.get("revision") or 0) + 1
    status = _build_status(memory, registry)
    if write_outputs:
        _save_json(STRATEGY_MEMORY, memory)
        _save_json(STRATEGY_STATUS, status)
    return {"memory": memory, "status": status}


def _normalized_scope_tokens(values: list[str]) -> set[str]:
    generic = {"d:", "codex", "generated", "workspace", "users", "lenovo"}
    return {str(item).lower() for item in values if str(item).strip() and str(item).lower() not in generic}


def _repo_scope_matches(pattern: dict[str, Any], repo_path: str | None) -> bool:
    repo_scope = str(pattern.get("repo_scope") or "").strip().lower()
    repo_value = str(repo_path or "").strip().lower()
    if not repo_value or not repo_scope:
        return False
    if repo_value.startswith(repo_scope) or repo_scope.startswith(repo_value):
        return True
    scope_tokens = _normalized_scope_tokens(list(pattern.get("scope_tokens", [])))
    repo_tokens = _normalized_scope_tokens(repo_value.replace("/", "\\").split("\\"))
    return bool(scope_tokens.intersection(repo_tokens))


def _pattern_match_bonus(pattern: dict[str, Any], *, repo_path: str | None, task_type: str, preferred_worker: str | None) -> float:
    bonus = 0.0
    repo_match = _repo_scope_matches(pattern, repo_path)
    if repo_match:
        bonus += 0.18
    pattern_task_type = str(pattern.get("task_type") or "").strip()
    if pattern_task_type == task_type and (repo_match or not repo_path):
        bonus += 0.12
    if preferred_worker and preferred_worker == pattern.get("preferred_worker"):
        bonus += 0.08
    return bonus


def _exploration_value(prompt: str, goal: str | None, repo_path: str | None, revision: int) -> float:
    digest = hashlib.sha256(
        "|".join([prompt.strip(), str(goal or "").strip(), str(repo_path or "").strip(), str(revision)]).encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def select_strategy_hint(
    prompt: str,
    goal: str | None,
    repo_path: str | None,
    task_type: str,
    *,
    preferred_worker: str | None = None,
    memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_memory = memory or load_strategy_memory()
    patterns = [
        item
        for item in current_memory.get("patterns", [])
        if isinstance(item, dict) and item.get("status") in {"active", "reinforced", "learning"}
    ]
    exploration_ratio = float(current_memory.get("exploration_ratio") or 0.2)
    exploration_value = _exploration_value(prompt, goal, repo_path, int(current_memory.get("revision") or 0))
    explored = exploration_value < exploration_ratio
    candidates = []
    for item in patterns:
        if str(item.get("task_type") or "").strip() != task_type:
            continue
        if repo_path and item.get("repo_scope") and not _repo_scope_matches(item, repo_path):
            continue
        rank = float(item.get("score") or 0.0) + _pattern_match_bonus(
            item,
            repo_path=repo_path,
            task_type=task_type,
            preferred_worker=preferred_worker,
        )
        candidates.append((rank, item))
    candidates.sort(key=lambda entry: entry[0], reverse=True)
    best = candidates[0][1] if candidates else None
    best_rank = candidates[0][0] if candidates else 0.0
    if explored:
        return {
            "applied": False,
            "explored": True,
            "reason": "exploration_budget",
            "pattern_id": None,
            "pattern_score": None,
            "preferred_worker": None,
            "tools_used": [],
            "tool_actions": [],
            "structure_summary": None,
            "hint_lines": [],
            "exploration_ratio": exploration_ratio,
            "exploration_value": round(exploration_value, 4),
            "memory_revision": current_memory.get("revision", 0),
            "candidate_count": len(candidates),
        }
    if not best or best_rank < 0.6:
        return {
            "applied": False,
            "explored": False,
            "reason": "no_strong_pattern",
            "pattern_id": None,
            "pattern_score": None,
            "preferred_worker": None,
            "tools_used": [],
            "tool_actions": [],
            "structure_summary": None,
            "hint_lines": [],
            "exploration_ratio": exploration_ratio,
            "exploration_value": round(exploration_value, 4),
            "memory_revision": current_memory.get("revision", 0),
            "candidate_count": len(candidates),
        }
    hint_lines = [
        f"Reuse strategy {best.get('pattern_id')} score={best.get('score')}: prefer tool flow {', '.join(best.get('tools_used', [])[:5]) or 'existing repo tools'}.",
        f"Preserve structure: {best.get('structure_summary')}.",
    ]
    if best.get("preferred_worker"):
        hint_lines.append(f"Preferred worker from prior success: {best.get('preferred_worker')}." )
    return {
        "applied": True,
        "explored": False,
        "reason": "matched_success_pattern",
        "pattern_id": best.get("pattern_id"),
        "pattern_score": best.get("score"),
        "preferred_worker": best.get("preferred_worker"),
        "task_type": best.get("task_type"),
        "artifact_type": best.get("artifact_type"),
        "tools_used": best.get("tools_used", []),
        "tool_actions": best.get("tool_actions", []),
        "structure_summary": best.get("structure_summary"),
        "repo_scope": best.get("repo_scope"),
        "hint_lines": hint_lines,
        "summary_block": "\n".join(hint_lines),
        "exploration_ratio": exploration_ratio,
        "exploration_value": round(exploration_value, 4),
        "memory_revision": current_memory.get("revision", 0),
        "candidate_count": len(candidates),
    }


def review_strategy_memory(*, persist: bool = True) -> dict[str, Any]:
    memory = load_strategy_memory()
    reviewed: list[dict[str, Any]] = []
    pruned_count = 0
    reinforced_count = 0
    active_count = 0
    for item in memory.get("patterns", []):
        pattern = dict(item)
        score = float(pattern.get("score") or 0.0)
        failures = int(pattern.get("failed_reuse_count") or 0)
        successes = int(pattern.get("successful_reuse_count") or 0) + int(pattern.get("success_count") or 0)
        if score < 0.35 and failures > successes:
            pattern["status"] = "pruned"
            pruned_count += 1
        elif score >= 0.75:
            pattern["status"] = "reinforced"
            reinforced_count += 1
            active_count += 1
        elif score >= 0.55:
            pattern["status"] = "active"
            active_count += 1
        else:
            pattern["status"] = "learning"
        pattern["last_reviewed_at"] = _utc()
        reviewed.append(pattern)
    memory["patterns"] = reviewed
    memory["last_review"] = _utc()
    memory["review_summary"] = {
        "reviewed_pattern_count": len(reviewed),
        "active_pattern_count": active_count,
        "reinforced_count": reinforced_count,
        "pruned_count": pruned_count,
    }
    if persist:
        previous = load_strategy_memory()
        if _memory_changed(previous, memory):
            memory["revision"] = int(previous.get("revision") or 0) + 1
        _save_json(STRATEGY_MEMORY, memory)
        status = _build_status(memory, _load_json(ARTIFACT_REGISTRY, {}))
        _save_json(STRATEGY_STATUS, status)
    return {
        "updated_at": _utc(),
        **(memory.get("review_summary") or {}),
        "reuse_success_rate": (_load_json(STRATEGY_STATUS, {}) or {}).get("reuse_success_rate", 0.0),
    }


if __name__ == "__main__":
    print(json.dumps(refresh_strategy_memory(write_outputs=True), ensure_ascii=False, indent=2))
