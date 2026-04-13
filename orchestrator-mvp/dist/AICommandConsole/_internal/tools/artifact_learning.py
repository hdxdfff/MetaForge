from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TASKS = DATA / "tasks.json"
TASK_HISTORY = DATA / "task_history.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _parse_task_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        items = raw.get("tasks", [])
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _task_timestamp(task: dict[str, Any]) -> str:
    return str(task.get("updated_at") or task.get("created_at") or "")


def _latest_task_view(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (task_history, tasks):
        for item in source:
            task_id = str(item.get("id") or "").strip()
            if not task_id:
                continue
            existing = merged.get(task_id)
            if existing is None or _task_timestamp(item) >= _task_timestamp(existing):
                merged[task_id] = item
    return list(merged.values())


def load_tasks() -> list[dict[str, Any]]:
    tasks = _parse_task_items(_load_json(TASKS, []))
    history = _parse_task_items(_load_json(TASK_HISTORY, []))
    return _latest_task_view(tasks, history)


def _task_type_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("bug", "debug", "crash", "error", "deadlock", "fix")):
        return "debugging"
    if any(token in lowered for token in ("refactor", "rewrite", "restructure")):
        return "refactor"
    if any(token in lowered for token in ("design", "architecture", "strategy")):
        return "design"
    if any(token in lowered for token in ("test", "verify", "validation", "qemu")):
        return "verification"
    return "implementation"


def _related_task(artifact: dict[str, Any], tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    artifact_id = str(artifact.get("artifact_id") or "").strip()
    artifact_path = str(artifact.get("artifact_path") or "").strip().lower()
    for task in tasks:
        if str(task.get("status") or "").strip().lower() != "completed":
            continue
        artifact_spec = task.get("artifact_spec") or {}
        if str(artifact_spec.get("artifact_id") or "").strip() == artifact_id:
            return task
        repo_path = str(task.get("repo_path") or "").strip().lower()
        if repo_path and artifact_path and artifact_path.startswith(repo_path):
            return task
    return None


def _load_build_report(artifact: dict[str, Any]) -> dict[str, Any]:
    artifact_path = Path(str(artifact.get("artifact_path") or ""))
    report = _load_json(artifact_path / "build-report.json", {})
    return report if isinstance(report, dict) else {}


def _prompt_signature(task: dict[str, Any] | None, artifact: dict[str, Any]) -> str:
    prompt = str((task or {}).get("prompt") or artifact.get("artifact_id") or artifact.get("artifact_path") or "")
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _enabled_actions(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        return [str(name) for name, enabled in raw.items() if enabled]
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    return []


def _tools_used(task: dict[str, Any] | None, build_report: dict[str, Any]) -> list[str]:
    values: list[str] = []
    task_tool_policy = (task or {}).get("tool_policy") or {}
    allowed = task_tool_policy.get("allowed_actions") or {}
    values.extend(_enabled_actions(allowed))
    toolchain = build_report.get("toolchain") or {}
    values.extend(name for name, location in toolchain.items() if location)
    for item in build_report.get("checks", []) or []:
        if not isinstance(item, dict):
            continue
        command = item.get("command") or []
        if isinstance(command, list) and command:
            values.append(str(command[0]))
    return _unique_strings(values)[:10]


def _tool_actions(task: dict[str, Any] | None, artifact: dict[str, Any]) -> list[str]:
    values: list[str] = []
    task_tool_policy = (task or {}).get("tool_policy") or {}
    allowed = task_tool_policy.get("allowed_actions") or {}
    values.extend(_enabled_actions(allowed))
    checks = artifact.get("checks") or {}
    if checks.get("build_success"):
        values.append("build")
    if checks.get("generic_test_passed") or checks.get("qemu_all_passed"):
        values.append("test")
    if checks.get("generic_execution_passed") or checks.get("qemu_all_passed"):
        values.append("execute")
    return _unique_strings(values)[:10]


def _scope_tokens(repo_scope: str, artifact_path: str) -> list[str]:
    raw = repo_scope or artifact_path
    tokens = [item for item in raw.replace("/", "\\").split("\\") if item]
    return tokens[-4:]


def _structure_summary(task: dict[str, Any] | None, artifact: dict[str, Any]) -> str:
    artifact_spec = (task or {}).get("artifact_spec") or {}
    required = artifact_spec.get("required_artifacts") or []
    evidence = ((artifact.get("checks") or {}).get("existing_evidence")) or []
    entrypoint = str(artifact.get("entrypoint") or "").strip() or "none"
    return (
        f"entrypoint={entrypoint}; required_outputs={len(required)}; "
        f"evidence_files={len(evidence)}; delivery={artifact.get('delivery_status')}"
    )


def _complexity_score(task: dict[str, Any] | None, artifact: dict[str, Any], build_report: dict[str, Any]) -> float:
    checks = len(build_report.get("checks", []) or [])
    source_count = int(build_report.get("c_source_count") or 0)
    required = len((((task or {}).get("artifact_spec") or {}).get("required_artifacts")) or [])
    evidence = len((((artifact.get("checks") or {}).get("existing_evidence")) or []))
    score = 1.0 + (checks * 0.15) + (source_count * 0.25) + (required * 0.1) + (evidence * 0.05)
    return round(min(score, 10.0), 2)


def extract_success_pattern(artifact: dict[str, Any], tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    task_records = tasks or load_tasks()
    task = _related_task(artifact, task_records)
    build_report = _load_build_report(artifact)
    artifact_type = str(artifact.get("type") or "unknown").strip().lower()
    artifact_path = str(artifact.get("artifact_path") or "").strip()
    repo_scope = artifact_path or str((task or {}).get("repo_path") or "").strip()
    task_type = str((((task or {}).get("context_package") or {}).get("task_type")) or "").strip()
    if not task_type:
        task_type = _task_type_from_text(str((task or {}).get("goal") or (task or {}).get("prompt") or artifact_type))
    tools_used = _tools_used(task, build_report)
    preferred_worker = str((task or {}).get("preferred_worker") or "").strip() or None
    tool_actions = _tool_actions(task, artifact)
    scope_tokens = _scope_tokens(repo_scope, artifact_path)
    pattern_digest = hashlib.sha1(
        "|".join(
            [
                task_type,
                artifact_type,
                preferred_worker or "",
                ",".join(tools_used[:6]),
                repo_scope.lower(),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return {
        "pattern_id": f"strategy_{pattern_digest}",
        "task_type": task_type,
        "artifact_type": artifact_type,
        "preferred_worker": preferred_worker,
        "tools_used": tools_used,
        "tool_actions": tool_actions,
        "prompt_signature": _prompt_signature(task, artifact),
        "structure_summary": _structure_summary(task, artifact),
        "complexity_score": _complexity_score(task, artifact, build_report),
        "repo_scope": repo_scope,
        "scope_tokens": scope_tokens,
        "source_artifact_id": str(artifact.get("artifact_id") or "").strip() or None,
        "source_task_id": str((task or {}).get("id") or "").strip() or None,
    }

