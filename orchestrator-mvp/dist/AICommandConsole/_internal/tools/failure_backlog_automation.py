from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.goal_backlog_replenisher import build_goal_backlog_plan, record_goal_backlog_result
from tools.io_utils import atomic_write_json

DATA = ROOT / "data"
TASKS_PATH = DATA / "tasks.json"
TASK_HISTORY_PATH = DATA / "task_history.json"
TASK_ARCHIVE_PATH = DATA / "task_archive.json"
TASK_TEMPLATES_PATH = DATA / "task_templates.json"
REPORT_PATH = DATA / "task_backlog_automation.json"

ACTIVE_STATUSES = {"planning", "running", "verification_pending", "verification_running"}
PENDING_STATUSES = {"queued", "waiting_approval"}
TERMINAL_STATUSES = {"completed", "failed", "timed_out", "cancelled"}
MAX_CREATED_PER_RUN = 4
TOP_CLUSTER_LIMIT = 5
DESIRED_ACTIVE = 2
DESIRED_PENDING = 5

TOYOS_MARKERS = ("toyos", "toy-os", "generated/toy-os-demo")
ORCHESTRATION_MARKERS = ("agent orchestration", "throughput", "dispatch", "executor")
WEB_MARKERS = ("webapp", "browser", "ui", "frontend")
DELIVERY_MARKERS = ("artifact", "delivery", "release", "bundle")
TOOLING_MARKERS = ("tool extension", "tooling", "capability", "integration")

HANDLING_MODE_TEMPLATE_PRIORITY: dict[str, list[str]] = {
    "toyos_replenishment": ["toyos-mainline", "toyos-throughput-smoke-pack", "deployment-wrapup", "lab-report"],
    "control_plane_stabilization": ["throughput-policy-audit", "throughput-dispatch-schema", "throughput-rollout-checklist", "software-factory"],
    "web_or_document_followup": ["browser-reading", "lab-report", "workspace-intake", "general-coding"],
    "delivery_followup": ["deployment-wrapup", "throughput-rollout-checklist", "lab-report", "general-coding"],
    "tooling_followup": ["auto-debug", "general-coding", "software-factory", "throughput-dispatch-schema"],
    "generic_saturation": ["auto-debug", "general-coding", "software-factory", "deployment-wrapup", "lab-report"],
}

DEFAULT_TEMPLATE_IDS = ["auto-debug", "general-coding", "software-factory", "deployment-wrapup", "lab-report"]

TEMPLATE_CONTRACTS: dict[str, dict[str, Any]] = {
    "auto-debug": {
        "task_type": "build_fix",
        "queue_name": "build_test",
        "verification_level": "L2",
        "max_runtime_seconds": 2400,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "coder",
    },
    "browser-reading": {
        "task_type": "exploration_intake",
        "queue_name": "exploration",
        "verification_level": "L1",
        "max_runtime_seconds": 1200,
        "retry_limit": 0,
        "rollback_rule": "return_to_planner",
        "preferred_worker": "browser",
    },
    "deployment-wrapup": {
        "task_type": "report_refresh",
        "queue_name": "fastlane",
        "verification_level": "L1",
        "max_runtime_seconds": 1200,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "reviewer",
    },
    "general-coding": {
        "task_type": "build_fix",
        "queue_name": "build_test",
        "verification_level": "L2",
        "max_runtime_seconds": 2400,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "coder",
    },
    "lab-report": {
        "task_type": "report_refresh",
        "queue_name": "fastlane",
        "verification_level": "L1",
        "max_runtime_seconds": 1200,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "reviewer",
    },
    "software-factory": {
        "task_type": "report_refresh",
        "queue_name": "fastlane",
        "verification_level": "L1",
        "max_runtime_seconds": 1800,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "reviewer",
    },
    "throughput-dispatch-schema": {
        "task_type": "json_fix",
        "queue_name": "build_test",
        "verification_level": "L2",
        "max_runtime_seconds": 2400,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "coder",
    },
    "throughput-policy-audit": {
        "task_type": "artifact_audit",
        "queue_name": "fastlane",
        "verification_level": "L1",
        "max_runtime_seconds": 1800,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "reviewer",
    },
    "throughput-rollout-checklist": {
        "task_type": "doc_patch",
        "queue_name": "fastlane",
        "verification_level": "L1",
        "max_runtime_seconds": 1200,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "reviewer",
    },
    "toyos-mainline": {
        "task_type": "subsystem_refactor",
        "queue_name": "incubation",
        "verification_level": "L2",
        "max_runtime_seconds": 3600,
        "retry_limit": 1,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "coder",
    },
    "toyos-throughput-smoke-pack": {
        "task_type": "qemu_smoke_run",
        "queue_name": "regression",
        "verification_level": "L3",
        "max_runtime_seconds": 5400,
        "retry_limit": 2,
        "rollback_rule": "mark_failed_and_requeue_split",
        "preferred_worker": "docker",
    },
    "workspace-intake": {
        "task_type": "exploration_intake",
        "queue_name": "exploration",
        "verification_level": "L1",
        "max_runtime_seconds": 900,
        "retry_limit": 0,
        "rollback_rule": "return_to_planner",
        "preferred_worker": "shell",
    },
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    for attempt in range(5):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.1 * (attempt + 1))
        except Exception:
            return default
    return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize(text: Any) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _task_status(task: dict[str, Any]) -> str:
    return _normalize(task.get("status"))


def _task_corpus(task: dict[str, Any]) -> str:
    result = task.get("result") or {}
    scheduler_hint = task.get("scheduler_hint") or {}
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("prompt"),
        task.get("repo_path"),
        task.get("task_type"),
        task.get("queue_name"),
        result.get("error") if isinstance(result, dict) else None,
        result.get("summary") if isinstance(result, dict) else None,
        scheduler_hint.get("template_id"),
        scheduler_hint.get("goal_primary"),
        scheduler_hint.get("goal_target"),
    ]
    return " ".join(_normalize(part) for part in parts if _normalize(part))


def _classify_terminal_task(task: dict[str, Any]) -> str:
    status = _task_status(task)
    result = task.get("result") or {}
    error = _normalize(result.get("error") if isinstance(result, dict) else "")
    summary = _normalize(result.get("summary") if isinstance(result, dict) else "")
    corpus = " ".join(part for part in [error, summary, _task_corpus(task)] if part)
    if status == "timed_out" or "timed out" in error or "timeout" in error or "timed out" in summary:
        return "timeout"
    if "permission denied" in corpus or "access is denied" in corpus or "[winerror 5]" in corpus:
        return "permission_denied"
    if "verification" in corpus or "validation" in corpus or "audit" in corpus:
        return "validation_or_audit_failure"
    if not error and status == "failed":
        return "missing_error"
    if status == "failed":
        return "execution_error"
    return "terminal"


def _is_toyos_record(task: dict[str, Any]) -> bool:
    corpus = _task_corpus(task)
    return any(marker in corpus for marker in TOYOS_MARKERS)


def _terminal_records(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in sources:
        for task in source:
            if not isinstance(task, dict):
                continue
            if _task_status(task) in TERMINAL_STATUSES:
                records.append(task)
    return records


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("id") or record.get("task_id") or "").strip()
        if not key:
            anonymous.append(record)
            continue
        existing = merged.get(key)
        existing_rank = _parse_time((existing or {}).get("updated_at") or (existing or {}).get("created_at") or (existing or {}).get("heartbeat_at")) if existing else None
        record_rank = _parse_time(record.get("updated_at") or record.get("created_at") or record.get("heartbeat_at"))
        if existing is None:
            merged[key] = record
            continue
        if record_rank is None and existing_rank is not None:
            continue
        if record_rank is not None and existing_rank is None:
            merged[key] = record
            continue
        if (record_rank or datetime.min.replace(tzinfo=timezone.utc)) >= (existing_rank or datetime.min.replace(tzinfo=timezone.utc)):
            merged[key] = record
    return list(merged.values()) + anonymous


def _count_runtime(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    active = 0
    pending = 0
    by_status: Counter[str] = Counter()
    for task in tasks:
        status = _task_status(task)
        by_status[status] += 1
        if status in ACTIVE_STATUSES:
            active += 1
        if status in PENDING_STATUSES:
            pending += 1
    return {
        "active": active,
        "pending": pending,
        "by_status": dict(by_status),
    }


def _cluster_key(task: dict[str, Any]) -> str:
    for field in ("goal", "title"):
        value = _normalize(task.get(field))
        if value:
            return value
    return "unlabelled-terminal-task"


def _handling_mode_for_text(text: str) -> str:
    if any(marker in text for marker in TOYOS_MARKERS):
        return "toyos_replenishment"
    if any(marker in text for marker in ORCHESTRATION_MARKERS):
        return "control_plane_stabilization"
    if any(marker in text for marker in WEB_MARKERS):
        return "web_or_document_followup"
    if any(marker in text for marker in DELIVERY_MARKERS):
        return "delivery_followup"
    if any(marker in text for marker in TOOLING_MARKERS):
        return "tooling_followup"
    return "generic_saturation"


def _template_ids_for_handling_mode(handling_mode: str) -> list[str]:
    return list(HANDLING_MODE_TEMPLATE_PRIORITY.get(handling_mode, DEFAULT_TEMPLATE_IDS))


def _load_templates() -> list[dict[str, Any]]:
    payload = _load_json(TASK_TEMPLATES_PATH, [])
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _template_lookup() -> dict[str, dict[str, Any]]:
    return {str(item.get("id") or "").strip(): item for item in _load_templates() if str(item.get("id") or "").strip()}


def _template_payload(template: dict[str, Any], *, repo_path: str, cluster: dict[str, Any], dispatch_now: bool) -> dict[str, Any]:
    template_id = str(template.get("id") or "").strip()
    contract = dict(TEMPLATE_CONTRACTS.get(template_id) or {})
    title = str(template.get("name") or template.get("title") or template_id or "Maintenance follow-up").strip()
    prompt = str(template.get("prompt") or "Review the current failure backlog, keep the work queue saturated, and summarize the exact next step.").strip()
    goal = str(template.get("goal") or "Maintain system throughput while isolating repeated failure patterns.").strip()
    context_mode = str(template.get("recommended_context_mode") or "lean").strip().lower() or "lean"
    task_type = str(template.get("task_type") or contract.get("task_type") or "report_refresh").strip()
    queue_name = str(template.get("queue_name") or contract.get("queue_name") or "fastlane").strip()
    verification_level = str(template.get("verification_level") or contract.get("verification_level") or "L1").strip().upper()
    max_runtime_seconds = int(template.get("max_runtime_seconds") or contract.get("max_runtime_seconds") or 1200)
    retry_limit = int(template.get("retry_limit") or contract.get("retry_limit") or 1)
    rollback_rule = str(template.get("rollback_rule") or contract.get("rollback_rule") or "mark_failed_and_requeue_split").strip()
    preferred_worker = str(template.get("preferred_worker") or contract.get("preferred_worker") or "coder").strip()
    scheduler_hint = {
        "automation_source": "failure_backlog_automation",
        "template_id": template_id,
        "template_category": template.get("category"),
        "cluster_key": cluster.get("cluster_key"),
        "cluster_count": cluster.get("count"),
        "cluster_status": cluster.get("status"),
        "handling_mode": cluster.get("handling_mode"),
        "dispatch_now": dispatch_now,
        "admission_mode": "normal" if dispatch_now else "degraded",
        "scheduled_by": "runtime.failure_backlog_automation",
    }
    payload: dict[str, Any] = {
        "prompt": prompt,
        "title": title,
        "repo_path": repo_path,
        "goal": goal,
        "scheduled_by": "runtime.failure_backlog_automation",
        "auto_approve": True,
        "context_mode": context_mode,
        "allow_resource_scan": bool(template.get("default_allow_resource_scan", True)),
        "allow_repo_status": bool(template.get("default_allow_repo_status", True)),
        "preferred_worker": preferred_worker,
        "scheduler_hint": scheduler_hint,
        "execution_mode": "governance",
        "execution_lane": "host-control",
        "task_type": task_type,
        "queue_name": queue_name,
        "verification_level": verification_level,
        "max_runtime_seconds": max_runtime_seconds,
        "retry_limit": retry_limit,
        "rollback_rule": rollback_rule,
    }
    return payload


def _cluster_recommendation(task: dict[str, Any], *, count: int) -> dict[str, Any]:
    text = _cluster_key(task)
    handling_mode = _handling_mode_for_text(text)
    template_ids = _template_ids_for_handling_mode(handling_mode)
    return {
        "cluster_key": text,
        "count": count,
        "handling_mode": handling_mode,
        "template_ids": template_ids,
        "status": "attention" if count >= 10 else "watch",
    }


async def _create_tasks(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.models import TaskCreate
    from app.orchestrator import Orchestrator

    orch = Orchestrator()
    created: list[dict[str, Any]] = []
    for payload in payloads:
        task = await orch.create_task(TaskCreate(**payload))
        created.append(
            {
                "task_id": task.id,
                "title": task.title,
                "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "task_type": task.task_type,
                "queue_name": task.queue_name,
                "verification_level": task.verification_level,
                "executor_id": task.executor_id,
                "template_id": (task.scheduler_hint or {}).get("template_id"),
                "cluster_key": (task.scheduler_hint or {}).get("cluster_key"),
                "handling_mode": (task.scheduler_hint or {}).get("handling_mode"),
                "automation_source": (task.scheduler_hint or {}).get("automation_source"),
            }
        )
    return created


def _open_template_ids(tasks: list[dict[str, Any]]) -> set[str]:
    open_ids: set[str] = set()
    for task in tasks:
        if _task_status(task) not in ACTIVE_STATUSES | PENDING_STATUSES:
            continue
        scheduler_hint = task.get("scheduler_hint") or {}
        template_id = str(scheduler_hint.get("template_id") or "").strip()
        if template_id:
            open_ids.add(template_id)
    return open_ids


def _select_payloads(
    *,
    templates: dict[str, dict[str, Any]],
    tasks: list[dict[str, Any]],
    cluster_recommendations: list[dict[str, Any]],
    desired_active: int,
    desired_pending: int,
    mode: str,
) -> list[dict[str, Any]]:
    open_template_ids = _open_template_ids(tasks)
    runtime = _count_runtime(tasks)
    deficit = max(0, desired_active - int(runtime["active"])) + max(0, desired_pending - int(runtime["pending"]))
    if mode == "light":
        return []
    budget = min(MAX_CREATED_PER_RUN, max(0, deficit))
    if budget <= 0 and not cluster_recommendations:
        return []

    repo_path = str(ROOT)
    selected: list[dict[str, Any]] = []
    seen_templates: set[str] = set()

    for cluster in cluster_recommendations:
        if len(selected) >= budget:
            break
        for template_id in cluster.get("template_ids") or []:
            if len(selected) >= budget:
                break
            template = templates.get(template_id)
            if not template or template_id in open_template_ids or template_id in seen_templates:
                continue
            selected.append(_template_payload(template, repo_path=repo_path, cluster=cluster, dispatch_now=len(selected) < max(1, budget // 2)))
            seen_templates.add(template_id)

    if len(selected) < budget:
        fallback_template_ids = [
            "auto-debug",
            "general-coding",
            "software-factory",
            "deployment-wrapup",
            "lab-report",
            "browser-reading",
            "throughput-policy-audit",
            "throughput-dispatch-schema",
            "throughput-rollout-checklist",
            "toyos-mainline",
            "toyos-throughput-smoke-pack",
        ]
        for template_id in fallback_template_ids:
            if len(selected) >= budget:
                break
            template = templates.get(template_id)
            if not template or template_id in open_template_ids or template_id in seen_templates:
                continue
            selected.append(
                _template_payload(
                    template,
                    repo_path=repo_path,
                    cluster={
                        "cluster_key": "throughput_backfill",
                        "count": 0,
                        "status": "watch",
                        "handling_mode": "generic_saturation",
                    },
                    dispatch_now=len(selected) < max(1, budget // 2),
                )
            )
            seen_templates.add(template_id)
    return selected


def run_failure_backlog_automation(mode: str = "full") -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    history = _load_json(TASK_HISTORY_PATH, [])
    archive = _load_json(TASK_ARCHIVE_PATH, [])
    templates = _template_lookup()

    terminal_live = _terminal_records(tasks)
    terminal_history = _terminal_records(history)
    terminal_archive = _terminal_records(archive)
    terminal_records = _dedupe_records(terminal_live + terminal_history + terminal_archive)

    cluster_counts: dict[str, int] = defaultdict(int)
    cluster_sources: dict[str, str] = {}
    cluster_status: dict[str, str] = {}
    cluster_examples: dict[str, dict[str, Any]] = {}
    for record in terminal_records:
        cluster_key = _cluster_key(record)
        cluster_counts[cluster_key] += 1
        cluster_sources.setdefault(cluster_key, _task_status(record))
        cluster_status.setdefault(cluster_key, _classify_terminal_task(record))
        cluster_examples.setdefault(cluster_key, record)

    recommendations = [
        _cluster_recommendation(cluster_examples[key], count=count)
        for key, count in sorted(cluster_counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_CLUSTER_LIMIT]
    ]
    recommendations.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("cluster_key") or "")))

    runtime = _count_runtime(tasks)
    desired_active = DESIRED_ACTIVE
    desired_pending = DESIRED_PENDING
    current_report = {
        "updated_at": _utc(),
        "mode": mode,
        "runtime": runtime,
        "terminal_counts": {
            "live": len(terminal_live),
            "history": len(terminal_history),
            "archive": len(terminal_archive),
            "unique_clusters": len(cluster_counts),
        },
        "cluster_recommendations": recommendations,
        "cluster_breakdown": [
            {
                "cluster_key": key,
                "count": count,
                "status": cluster_status.get(key),
                "source_status": cluster_sources.get(key),
                "handling_mode": _cluster_recommendation(cluster_examples[key], count=count)["handling_mode"],
            }
            for key, count in sorted(cluster_counts.items(), key=lambda item: (-item[1], item[0]))[:TOP_CLUSTER_LIMIT]
        ],
        "desired_active": desired_active,
        "desired_pending": desired_pending,
        "deficit": max(0, desired_active - int(runtime["active"])) + max(0, desired_pending - int(runtime["pending"])),
        "created_tasks": [],
        "created_count": 0,
        "toyos_replenishment": {"status": "skipped"},
        "residual_risk": "Historical terminal failures are summarized, but existing completed/final tasks remain in archival history for auditability.",
    }

    payloads: list[dict[str, Any]] = []
    toyos_payloads: list[dict[str, Any]] = []
    toyos_present = any(_is_toyos_record(record) for record in terminal_records) or any(_is_toyos_record(task) for task in tasks)
    toyos_report: dict[str, Any] | None = None

    toyos_plan: dict[str, Any] | None = None
    if mode != "light" and toyos_present:
        toyos_plan = build_goal_backlog_plan()
        toyos_candidates = list(toyos_plan.get("dispatch_candidates") or [])
        open_template_ids = _open_template_ids(tasks)
        for candidate in toyos_candidates:
            template_id = str((candidate.get("scheduler_hint") or {}).get("template_id") or "").strip()
            if template_id and template_id in open_template_ids:
                continue
            clean_candidate = {key: value for key, value in candidate.items() if key != "caller"}
            scheduler_hint = dict(clean_candidate.get("scheduler_hint") or {})
            scheduler_hint.update(
                {
                    "handling_mode": "toyos_replenishment",
                    "automation_source": "failure_backlog_automation",
                }
            )
            clean_candidate["scheduler_hint"] = scheduler_hint
            toyos_payloads.append(clean_candidate)
        payloads.extend(toyos_payloads[: max(0, MAX_CREATED_PER_RUN - len(payloads))])
        toyos_report = {
            "status": "planned",
            "goal_id": toyos_plan.get("goal_id"),
            "goal_health": toyos_plan.get("goal_health"),
            "dispatch_now_count": int(toyos_plan.get("dispatch_now_count") or 0),
            "pending_candidate_count": int(toyos_plan.get("pending_candidate_count") or 0),
            "active_candidate_count": int(toyos_plan.get("active_candidate_count") or 0),
            "template_ids": [str(item.get("scheduler_hint", {}).get("template_id") or "") for item in toyos_candidates],
        }
        current_report["toyos_replenishment"] = toyos_report

    if mode != "light":
        remaining_budget = max(0, MAX_CREATED_PER_RUN - len(payloads))
        if remaining_budget > 0:
            payloads.extend(
                _select_payloads(
                    templates=templates,
                    tasks=tasks,
                    cluster_recommendations=recommendations,
                    desired_active=desired_active,
                    desired_pending=desired_pending,
                    mode=mode,
                )[:remaining_budget]
            )

    created: list[dict[str, Any]] = []
    if payloads and mode != "light":
        try:
            created = asyncio.run(_create_tasks(payloads))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                created = loop.run_until_complete(_create_tasks(payloads))
            finally:
                loop.close()
        except Exception as exc:
            current_report["creation_error"] = str(exc)
            created = []

    if toyos_report is not None:
        try:
            toyos_created = [
                item
                for item in created
                if item.get("handling_mode") == "toyos_replenishment"
            ]
            if toyos_plan is not None:
                record_goal_backlog_result(toyos_plan, dispatched=toyos_created)
        except Exception as exc:
            current_report["toyos_replenishment"] = {
                **current_report["toyos_replenishment"],
                "record_error": str(exc),
            }

    current_report["created_tasks"] = created
    current_report["created_count"] = len(created)
    current_report["template_ids_created"] = [str(item.get("template_id") or "") for item in created if item.get("template_id")]
    current_report["runtime_after"] = _count_runtime(_load_json(TASKS_PATH, tasks))
    _save_json(REPORT_PATH, current_report)
    return current_report


if __name__ == "__main__":
    print(json.dumps(run_failure_backlog_automation(), ensure_ascii=False, indent=2))
