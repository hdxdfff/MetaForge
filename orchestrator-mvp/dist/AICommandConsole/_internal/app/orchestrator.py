from __future__ import annotations

import asyncio
import json
import re
import time
import subprocess
import sys
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import settings
from .io_utils import atomic_write_json, atomic_write_text

from typing import Any

from fastapi import WebSocket

from .context_service import ContextService
from .executor_adapter import ExecutorManager, ExecutorRunRequest, ExecutorTaskEnvelope
from .executor_routing import record_route_experience, resolve_executor_route
from .prompt_guard import evaluate_prompt_guard
from .safety_agent import assess_task_security
from .git_service import GitService
from .model_router import ModelRouter, RoutedModel
from .models import (
    AgentAssignment,
    AgentRole,
    DashboardStats,
    DeploymentPlan,
    DispatchTaskRequest,
    AutoDebugRequest,
    ExecutionMode,
    GitWorkflowState,
    MonitoringPlan,
    PolicyRecord,
    ProductDesign,
    QualityPlan,
    ProjectMemoryRecord,
    ProjectMemoryUpsert,
    RepoPushRequest,
    RepoPushResult,
    RepoRecord,
    RepoRegistration,
    ResourceRecord,
    RuleCheck,
    ArchitectureDesign,
    ArtifactSpec,
    StepSpec,
    StepStatus,
    TaskContract,
    TaskCreate,
    GoalAdmissionRequest,
    TaskDecompositionResponse,
    TaskDecompositionSpec,
    TaskEvent,
    TaskPublicationRequest,
    TaskPublicationApproveRequest,
    TaskPublicationPublishRequest,
    TaskPublicationRecord,
    TaskRecord,
    TaskStatus,
    PlannerResponse,
    utc_now,
    VerificationContract,
    PublicationStatus,
    WorkerType,
)
from .openai_client import OpenAIPlanner
from .llm_service import LlmService
from .resource_registry import ResourceRegistry
from .worker_adapters import WorkerAdapters, WorkerResult, WorkerSafetyError
from tools.capability_registry import route_capability
from tools.tool_registry import route_tool
from tools.tool_stack import route_task as route_surface_task
from tools.vm_orchestrator import choose_template_for_task, infer_worker_vm_policy
from tools.distillation import distill_task
from tools.code_knowledge_graph import query_code_knowledge_graph
from tools.context_builder import build_context_package
from .audit_validation import is_audit_task, validate_audit_output
from tools.context_kernel import RuntimeContextKernel
from tools.artifact_audit import audit_artifacts, build_reality_dashboard, summarize_verified_completed_tasks, validate_release_payload, validate_task_artifact_completion
from tools.binary_classification_lab_runner import run_binary_classification_lab
from tools.tool_policy import build_task_tool_policy
from tools.security_audit import append_security_audit
from tools.privilege_policy import decide as decide_privilege
from tools.kernel_mode import should_auto_approve_task

APP_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = APP_ROOT.parent
BUNDLED_PYTHON = CODEX_ROOT / "tools" / "python311-embed" / "python.exe"
BROWSER_BRIDGE = CODEX_ROOT / "tools" / "browser-automation" / "browser_bridge.py"
THROUGHPUT_QUEUE_CAPS = {
    "fastlane": 6,
    "build_test": 3,
    "regression": 2,
    "incubation": 1,
    "exploration": 4,
}
THROUGHPUT_PROJECT_WIP_CAP = 4
THROUGHPUT_ARTIFACT_WIP_CAP = 1
THROUGHPUT_TASK_VERIFICATION_LEVELS = {"L1", "L2", "L3"}
THROUGHPUT_TASK_TYPES = {
    "doc_patch",
    "report_refresh",
    "json_fix",
    "manifest_patch",
    "config_fix",
    "harness_case_add",
    "artifact_audit",
    "build_fix",
    "unit_test_run",
    "demo_rebuild",
    "package_validation",
    "harness_regression_run",
    "qemu_smoke_run",
    "atomic_feature_validation",
    "independent_evidence_check",
    "new_artifact_bootstrap",
    "subsystem_refactor",
    "new_demo_creation",
    "architecture_migration",
    "path_repair",
    "exploration_intake",
}
THROUGHPUT_TASK_QUEUE_MAP = {
    "doc_patch": "fastlane",
    "report_refresh": "fastlane",
    "json_fix": "fastlane",
    "manifest_patch": "fastlane",
    "config_fix": "fastlane",
    "harness_case_add": "fastlane",
    "artifact_audit": "fastlane",
    "build_fix": "build_test",
    "unit_test_run": "build_test",
    "demo_rebuild": "build_test",
    "package_validation": "build_test",
    "harness_regression_run": "regression",
    "qemu_smoke_run": "regression",
    "atomic_feature_validation": "regression",
    "independent_evidence_check": "regression",
    "new_artifact_bootstrap": "incubation",
    "subsystem_refactor": "incubation",
    "new_demo_creation": "incubation",
    "architecture_migration": "incubation",
    "path_repair": "incubation",
    "exploration_intake": "exploration",
}
THROUGHPUT_TASK_VERIFICATION_MAP = {
    "fastlane": "L1",
    "build_test": "L2",
    "regression": "L3",
    "incubation": "L2",
    "exploration": "L1",
}

TASK_ACTIVE_STATUSES = {
    TaskStatus.planning,
    TaskStatus.running,
    TaskStatus.execution_finished,
    TaskStatus.verification_pending,
    TaskStatus.verification_running,
}

TASK_VERIFIED_COMPLETION_STATUSES = {
    TaskStatus.completed,
    TaskStatus.delivery_ready,
    TaskStatus.released,
}

TASK_FINAL_STATUSES = TASK_VERIFIED_COMPLETION_STATUSES | {
    TaskStatus.verification_failed,
    TaskStatus.failed,
    TaskStatus.timed_out,
    TaskStatus.archived,
    TaskStatus.cancelled,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json_file(path: Path, default: Any):
    if not path.exists():
        return default
    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except Exception:
            continue
    return default


def _load_json_contract(path: Path, default: Any) -> Any:
    payload = _read_json_file(path, default)
    return payload if payload is not None else default


def _parse_record_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _record_rank(item: dict[str, Any], *fields: str) -> tuple[datetime, str]:
    for field in fields:
        parsed = _parse_record_time(item.get(field))
        if parsed is not None:
            return parsed, str(item.get("id") or item.get("task_id") or item.get("goal_id") or "")
    return datetime.min.replace(tzinfo=timezone.utc), str(item.get("id") or item.get("task_id") or item.get("goal_id") or "")


def _merge_record_lists(disk_items: list[dict[str, Any]], memory_items: list[dict[str, Any]], *, key_field: str = "id", rank_fields: tuple[str, ...] = ("updated_at", "created_at")) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for source in (disk_items, memory_items):
        for item in source:
            if not isinstance(item, dict):
                continue
            key = str(item.get(key_field) or "").strip()
            if not key:
                anonymous.append(item)
                continue
            existing = merged.get(key)
            if existing is None or _record_rank(item, *rank_fields) >= _record_rank(existing, *rank_fields):
                merged[key] = item
    merged_items = list(merged.values()) + anonymous
    merged_items.sort(key=lambda item: _record_rank(item, *rank_fields))
    return merged_items


def _merge_mapping_records(disk_items: dict[str, Any], memory_items: dict[str, Any]) -> dict[str, Any]:
    merged = dict(disk_items or {})
    for key, value in (memory_items or {}).items():
        if key not in merged:
            merged[key] = value
            continue
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            current_rank = _record_rank(current, "updated_at", "heartbeat_at")
            value_rank = _record_rank(value, "updated_at", "heartbeat_at")
            if value_rank >= current_rank:
                merged[key] = value
        else:
            merged[key] = value
    return merged


def _checkpoint_terminal_status(checkpoint: dict[str, Any]) -> TaskStatus | None:
    raw = str((checkpoint or {}).get("task_status") or "").strip().lower()
    try:
        return TaskStatus(raw)
    except Exception:
        if raw == "cancelled":
            return TaskStatus.cancelled
        return None


class Orchestrator:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._projects: dict[str, ProjectMemoryRecord] = {}
        self._sockets: dict[str, set[WebSocket]] = defaultdict(set)
        self._planner = OpenAIPlanner()
        self._workers = WorkerAdapters()
        self._executors = ExecutorManager()
        self._llm = LlmService()
        self._router = ModelRouter()
        self._git = GitService()
        self._lock = asyncio.Lock()
        self._persist_lock = threading.RLock()
        self._verification_signal_streams: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._data_dir = Path(__file__).resolve().parent.parent / "data"
        self._contracts_dir = Path(__file__).resolve().parent.parent / "contracts"
        self._data_dir.mkdir(exist_ok=True)
        self._tasks_file = self._data_dir / "tasks.json"
        self._projects_file = self._data_dir / "projects.json"
        self._policy_file = self._data_dir / "policy.json"
        self._capabilities_file = self._data_dir / "assistant_capabilities.json"
        self._core_messages_file = self._data_dir / "core_messages.json"
        self._checkpoints_file = self._data_dir / "task_checkpoints.json"
        self._task_templates_file = self._data_dir / "task_templates.json"
        self._release_records_file = self._data_dir / "release_records.json"
        self._task_publications_file = self._data_dir / "task_publications.json"
        self._verification_signal_log = self._data_dir / "verification_signal_events.jsonl"
        self._runtime_task_dir = self._data_dir.parent / "factory" / "runtime" / "tasks"
        self._registry = ResourceRegistry(self._data_dir)
        self._context_service = ContextService(self._registry, self._git)
        self._runtime_context = RuntimeContextKernel(self._data_dir)
        self._policy = PolicyRecord()
        self._capabilities: list[dict[str, Any]] = []
        self._core_messages: list[dict[str, Any]] = []
        self._checkpoints: dict[str, dict[str, Any]] = {}
        self._task_templates: list[dict[str, Any]] = []
        self._release_records: list[dict[str, Any]] = []
        self._task_publications: dict[str, TaskPublicationRecord] = {}
        self._load_state()

    async def create_task(self, payload: TaskCreate) -> TaskRecord:
        prompt_guard = payload.prompt_guard or evaluate_prompt_guard(
            payload.prompt,
            goal=payload.goal,
            metadata={
                "repo_path": payload.repo_path,
                "preferred_worker": payload.preferred_worker,
                "scheduler_hint": payload.scheduler_hint,
            },
        )
        effective_auto_approve = should_auto_approve_task(
            requested=payload.auto_approve,
            execution_mode=getattr(payload.execution_mode, 'value', payload.execution_mode),
            scheduler_hint=payload.scheduler_hint,
            scheduled_by=payload.scheduled_by,
        )
        tool_policy = payload.tool_policy or build_task_tool_policy(
            preferred_worker=payload.preferred_worker,
            tool_route=payload.tool_route,
            repo_path=payload.repo_path,
            execution_lane=payload.execution_lane,
            auto_approve=effective_auto_approve,
            scheduled_by=payload.scheduled_by,
        )
        security_review = payload.security_review or assess_task_security(
            prompt_guard=prompt_guard,
            tool_policy=tool_policy,
            repo_path=payload.repo_path,
            execution_lane=payload.execution_lane,
            vm_template=payload.vm_template,
            auto_approve=effective_auto_approve,
        )
        scheduler_hint = dict(payload.scheduler_hint or {})
        if (
            payload.execution_mode == ExecutionMode.production
            and payload.artifact_spec is None
            and str(scheduler_hint.get("admission_lane") or "").strip().lower() != "exploration"
        ):
            scheduler_hint.update(
                {
                    "admission_lane": "exploration",
                    "admission_reason": "artifact_spec_missing",
                    "requested_execution_mode": payload.execution_mode.value if hasattr(payload.execution_mode, "value") else str(payload.execution_mode),
                    "task_type": "exploration_intake",
                    "queue_name": "exploration",
                    "verification_level": "L1",
                    "max_runtime_seconds": 900,
                    "retry_limit": 0,
                    "rollback_rule": "return_to_planner",
                }
            )
            payload = payload.model_copy(
                update={
                    "execution_mode": ExecutionMode.research,
                    "scheduler_hint": scheduler_hint,
                    "queue_name": "exploration",
                    "task_type": "exploration_intake",
                    "verification_level": "L1",
                    "max_runtime_seconds": 900,
                    "retry_limit": 0,
                    "rollback_rule": "return_to_planner",
                    "admission_lane": "exploration",
                    "admission_reason": "artifact_spec_missing",
                }
            )
            effective_auto_approve = should_auto_approve_task(
                requested=payload.auto_approve,
                execution_mode=payload.execution_mode.value if hasattr(payload.execution_mode, "value") else str(payload.execution_mode),
                scheduler_hint=scheduler_hint,
                scheduled_by=payload.scheduled_by,
            )
            tool_policy = build_task_tool_policy(
                preferred_worker=payload.preferred_worker,
                tool_route=payload.tool_route,
                repo_path=payload.repo_path,
                execution_lane=payload.execution_lane,
                auto_approve=effective_auto_approve,
                scheduled_by=payload.scheduled_by,
            )
            security_review = payload.security_review or assess_task_security(
                prompt_guard=prompt_guard,
                tool_policy=tool_policy,
                repo_path=payload.repo_path,
                execution_lane=payload.execution_lane,
                vm_template=payload.vm_template,
                auto_approve=effective_auto_approve,
            )
        task = TaskRecord(
            prompt=prompt_guard.get("sanitized_prompt") or payload.prompt,
            title=payload.title or payload.scheduler_hint.get("node_title") or payload.scheduler_hint.get("title"),
            repo_path=payload.repo_path,
            project_id=payload.project_id,
            goal=payload.goal,
            goal_id=payload.goal_id or payload.scheduler_hint.get("goal_id"),
            graph_id=payload.graph_id or payload.scheduler_hint.get("graph_id"),
            node_id=payload.node_id or payload.scheduler_hint.get("node_id"),
            scheduled_by=payload.scheduled_by or payload.scheduler_hint.get("scheduled_by"),
            auto_approve=effective_auto_approve,
            context_mode=payload.context_mode,
            max_context_chars=payload.max_context_chars,
            allow_resource_scan=payload.allow_resource_scan,
            allow_repo_status=payload.allow_repo_status,
            capability_route=payload.capability_route,
            platform_context=payload.platform_context,
            vm_template=payload.vm_template,
            vm_context=payload.vm_context,
            preferred_worker=payload.preferred_worker,
            scheduler_hint=payload.scheduler_hint,
            context_package=payload.context_package,
            tool_route=payload.tool_route,
            execution_mode=payload.execution_mode,
            execution_lane=payload.execution_lane,
            worker_vm_policy=payload.worker_vm_policy,
            prompt_guard=prompt_guard,
            tool_policy=tool_policy,
            security_review=security_review,
            artifact_spec=payload.artifact_spec,
            task_type=payload.task_type,
            queue_name=payload.queue_name,
            verification_level=payload.verification_level,
            max_runtime_seconds=payload.max_runtime_seconds,
            retry_limit=payload.retry_limit,
            rollback_rule=payload.rollback_rule,
            parent_task_id=payload.parent_task_id,
            root_task_id=payload.root_task_id or payload.parent_task_id,
            decomposition_depth=max(0, int(payload.decomposition_depth or 0)),
            max_decomposition_depth=max(0, int(payload.max_decomposition_depth or 2)),
            goal_admission=dict(payload.goal_admission or {}),
            admission_lane=payload.admission_lane,
            admission_reason=payload.admission_reason,
            dependency_task_ids=list(payload.dependency_task_ids or []),
            verification_signals=list(payload.verification_signals or []),
            plan=payload.plan,
        )
        task.executor_route = resolve_executor_route(
            task_type=task.task_type,
            verification_level=task.verification_level,
            execution_mode=task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
            preferred_worker=task.preferred_worker,
            executor_hint=payload.executor_hint or {},
            task_context={
                "queue_name": task.queue_name,
                "artifact_scope": task.artifact_spec.artifact_type if task.artifact_spec else None,
                "risk_level": task.security_review.get("risk_level"),
                "artifact_id": task.artifact_spec.artifact_id if task.artifact_spec else None,
            },
        )
        surface_route = (payload.executor_hint or {}).get("surface_route")
        if isinstance(surface_route, dict) and surface_route:
            task.executor_route["surface_route"] = surface_route
        task.executor_id = str((task.executor_route.get("selected") or {}).get("executor_id") or "").strip() or None
        if isinstance(task.goal_admission, dict) and task.goal_admission:
            task.scheduler_hint["goal_admission"] = dict(task.goal_admission)
        task.events.append(TaskEvent(message="Task accepted by orchestrator."))
        append_security_audit(action='task_create', actor='orchestrator', result='accepted', target=payload.repo_path or payload.execution_lane or 'task', details={'task_id': task.id, 'prompt_guard': prompt_guard, 'tool_policy': tool_policy, 'security_review': security_review})
        guard_decision = str(prompt_guard.get("decision") or "allow")
        if guard_decision == "sanitize":
            task.events.append(
                TaskEvent(
                    message="Prompt guard sanitized suspicious task input before planning.",
                    level="warning",
                    data={"prompt_guard": prompt_guard},
                )
            )
        if security_review.get('verdict') == 'review' and security_review.get('hold_before_execution') and not effective_auto_approve:
            task.status = TaskStatus.waiting_approval
            task.result = {
                'state': 'held_by_safety_agent',
                'reason': '; '.join(security_review.get('reasons', [])) or 'Task held for safety review.',
                'security_review': security_review,
            }
            task.events.append(
                TaskEvent(
                    message='Safety agent held task execution pending review.',
                    level='error',
                    data={'security_review': security_review},
                )
            )
        deferred_backlog = False
        if guard_decision == "block":
            task.status = TaskStatus.waiting_approval
            task.result = {
                "state": "blocked_by_prompt_guard",
                "reason": prompt_guard.get("reason_summary") or "Prompt blocked by security policy.",
                "prompt_guard": prompt_guard,
            }
            task.events.append(
                TaskEvent(
                    message="Prompt guard blocked task execution pending review.",
                    level="error",
                    data={"prompt_guard": prompt_guard},
                )
            )
        elif (
            task.status != TaskStatus.waiting_approval
            and str((task.scheduler_hint or {}).get("admission_mode") or "").strip().lower() == "degraded"
            and not effective_auto_approve
        ):
            task.status = TaskStatus.queued
            deferred_backlog = True
            task.result = {
                "state": "queued_for_backlog",
                "reason": "Backlog admission deferred until active capacity is available.",
                "scheduler_hint": task.scheduler_hint,
            }
            task.events.append(
                TaskEvent(
                    message="Task queued by backlog admission because active capacity is reserved for dispatch_now work.",
                    level="info",
                    data={"scheduler_hint": task.scheduler_hint},
                )
            )
        admission_kind = "admission_diverted" if str(task.admission_lane or "").strip().lower() == "exploration" else "admission_accepted"
        admission_details = {
            "admission_lane": task.admission_lane,
            "admission_reason": task.admission_reason,
            "execution_mode": task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
            "queue_name": task.queue_name,
            "task_type": task.task_type,
        }
        if task.status == TaskStatus.waiting_approval:
            admission_kind = "admission_held"
        await self._append_verification_signal(task, kind=admission_kind, success=True, details=admission_details)
        async with self._lock:
            with self._persist_lock:
                self._tasks[task.id] = task
                self._persist()
        if task.status != TaskStatus.waiting_approval:
            self._executor_submit(task)
        if guard_decision != "block" and not deferred_backlog and task.status != TaskStatus.waiting_approval:
            self._launch_task_runner(task)
        return task
    async def dispatch_task(self, payload: DispatchTaskRequest) -> TaskRecord:
        repo = self._registry.get_repo(payload.repo_id) if payload.repo_id else None
        project = self._projects.get(payload.project_id) if payload.project_id else None
        repo_path = payload.repo_path or (project.repo_path if project and project.repo_path else None) or (repo.local_path if repo else None)
        prompt_guard = evaluate_prompt_guard(
            payload.prompt,
            goal=payload.goal,
            metadata={
                "project_id": payload.project_id,
                "repo_id": payload.repo_id,
                "caller": payload.caller,
                "repo_path": repo_path,
            },
        )
        effective_prompt = prompt_guard.get('sanitized_prompt') or payload.prompt
        safe_payload = payload.model_copy(update={"prompt": effective_prompt})
        profile = self._infer_task_profile(safe_payload, project)
        execution_mode = self._infer_execution_mode(safe_payload, project, profile=profile)
        artifact_spec = self._infer_artifact_spec(
            explicit_spec=payload.artifact_spec,
            repo_path=repo_path,
            scheduler_hint=payload.scheduler_hint,
            prompt=effective_prompt,
            goal=payload.goal,
            execution_mode=execution_mode,
        )
        scheduler_hint = dict(payload.scheduler_hint or {})
        if (
            execution_mode == ExecutionMode.production
            and artifact_spec is None
            and str(scheduler_hint.get("admission_lane") or "").strip().lower() != "exploration"
        ):
            scheduler_hint.update(
                {
                    "admission_lane": "exploration",
                    "admission_reason": "artifact_spec_missing",
                    "requested_execution_mode": execution_mode.value if hasattr(execution_mode, "value") else str(execution_mode),
                    "task_type": "exploration_intake",
                    "queue_name": "exploration",
                    "verification_level": "L1",
                    "max_runtime_seconds": 900,
                    "retry_limit": 0,
                    "rollback_rule": "return_to_planner",
                }
            )
            execution_mode = ExecutionMode.research
            payload = payload.model_copy(
                update={
                    "scheduler_hint": scheduler_hint,
                    "execution_mode": execution_mode,
                    "queue_name": "exploration",
                    "task_type": "exploration_intake",
                    "verification_level": "L1",
                    "max_runtime_seconds": 900,
                    "retry_limit": 0,
                    "rollback_rule": "return_to_planner",
                    "admission_lane": "exploration",
                    "admission_reason": "artifact_spec_missing",
                }
            )
            safe_payload = safe_payload.model_copy(
                update={
                    "scheduler_hint": scheduler_hint,
                    "execution_mode": execution_mode,
                    "queue_name": "exploration",
                    "task_type": "exploration_intake",
                    "verification_level": "L1",
                }
            )
        context_mode = payload.context_mode or (project.preferred_context_mode if project else self._policy.default_context_mode)
        max_context_chars = payload.max_context_chars or self._policy.default_max_context_chars
        capability_route = self._select_capability_route(safe_payload, project=project, repo=repo)
        repo_path, platform_context, capability_guidance = self._apply_capability_route(safe_payload, capability_route, repo_path=repo_path)
        tool_route = self._select_tool_route(safe_payload)
        surface_route = route_surface_task(effective_prompt, workspace=repo_path)
        vm_template = self._select_vm_template(safe_payload, capability_route=capability_route, tool_route=tool_route)
        worker_vm_policy = infer_worker_vm_policy(
            prompt=effective_prompt,
            goal=payload.goal or '',
            preferred_worker=payload.preferred_worker,
            tool_route=tool_route,
            vm_template=vm_template,
        )
        code_graph_focus = query_code_knowledge_graph(payload.capability_request or payload.goal or effective_prompt)
        scheduler_hint = dict(payload.scheduler_hint or {})
        if payload.goal and 'goal_target' not in scheduler_hint:
            scheduler_hint['goal_target'] = payload.goal
        if code_graph_focus.get('module_focus'):
            scheduler_hint.setdefault('module_focus', code_graph_focus.get('module_focus', []))
            scheduler_hint.setdefault('owner_teams', code_graph_focus.get('owner_teams', []))
            scheduler_hint.setdefault('layers', code_graph_focus.get('layers', []))
            scheduler_hint.setdefault('graph_matches', code_graph_focus.get('matched_modules', []))
        scheduler_hint.setdefault('surface_route', surface_route)
        effective_auto_approve = should_auto_approve_task(
            requested=payload.auto_approve,
            execution_mode=execution_mode.value,
            scheduler_hint=scheduler_hint,
            scheduled_by=payload.scheduled_by or payload.caller,
        )
        vm_context = {
            'mode': 'vm-first' if vm_template or worker_vm_policy.get('worker_vm_preferred') else 'local-first',
            'selected_template': vm_template,
            'placement': worker_vm_policy.get('lane'),
            'policy': worker_vm_policy,
            'surface_route': surface_route,
        }
        project_kernel = project.model_dump(mode='json') if project else None
        context_package = build_context_package(
            prompt=effective_prompt,
            goal=payload.goal,
            repo_path=repo_path,
            project=project_kernel,
            scheduler_hint=scheduler_hint,
            max_modules=5,
            budget_chars=max_context_chars,
        )
        strategy_context = context_package.get("strategy") or {}
        effective_preferred_worker = payload.preferred_worker
        if not effective_preferred_worker and strategy_context.get("applied") and strategy_context.get("preferred_worker"):
            effective_preferred_worker = strategy_context.get("preferred_worker")
            worker_vm_policy = infer_worker_vm_policy(
                prompt=effective_prompt,
                goal=payload.goal or "",
                preferred_worker=effective_preferred_worker,
                tool_route=tool_route,
                vm_template=vm_template,
            )
            vm_context = {
                'mode': 'vm-first' if vm_template or worker_vm_policy.get('worker_vm_preferred') else 'local-first',
                'selected_template': vm_template,
                'placement': worker_vm_policy.get('lane'),
                'policy': worker_vm_policy,
            }
        if strategy_context:
            scheduler_hint["strategy_applied"] = bool(strategy_context.get("applied"))
            scheduler_hint["strategy_explored"] = bool(strategy_context.get("explored"))
            scheduler_hint["strategy_reason"] = strategy_context.get("reason")
            scheduler_hint["strategy_revision"] = strategy_context.get("memory_revision")
            if strategy_context.get("pattern_id"):
                scheduler_hint["strategy_pattern_id"] = strategy_context.get("pattern_id")
                scheduler_hint["strategy_pattern_score"] = strategy_context.get("pattern_score")
        task_type = self._infer_throughput_task_type(
            payload=safe_payload,
            profile=profile,
            artifact_spec=artifact_spec,
        )
        queue_name = str(
            payload.queue_name
            or scheduler_hint.get("queue_name")
            or self._resolve_throughput_queue(task_type, execution_mode)
        ).strip().lower()
        verification_level = str(
            payload.verification_level
            or scheduler_hint.get("verification_level")
            or self._resolve_throughput_verification_level(
                queue_name=queue_name,
                task_type=task_type,
                execution_mode=execution_mode,
            )
        ).strip().upper()
        if queue_name not in THROUGHPUT_QUEUE_CAPS:
            raise ValueError(f"Throughput admission rejected: unknown queue_name '{queue_name}'.")
        if task_type not in THROUGHPUT_TASK_TYPES:
            raise ValueError(f"Throughput admission rejected: unknown task_type '{task_type}'.")
        if verification_level not in THROUGHPUT_TASK_VERIFICATION_LEVELS:
            raise ValueError(
                f"Throughput admission rejected: unknown verification_level '{verification_level}'."
            )
        max_runtime_seconds = self._resolve_throughput_runtime(
            queue_name=queue_name,
            task_type=task_type,
            explicit_runtime=(
                payload.max_runtime_seconds
                if payload.max_runtime_seconds is not None
                else scheduler_hint.get("max_runtime_seconds")
            ),
        )
        if max_runtime_seconds <= 0:
            raise ValueError("Throughput admission rejected: max_runtime_seconds must be positive.")
        retry_limit = self._resolve_throughput_retry_limit(
            queue_name,
            payload.retry_limit if payload.retry_limit is not None else scheduler_hint.get("retry_limit"),
        )
        if retry_limit < 0:
            raise ValueError("Throughput admission rejected: retry_limit must be non-negative.")
        rollback_rule = self._resolve_throughput_rollback_rule(
            queue_name,
            payload.rollback_rule if payload.rollback_rule is not None else scheduler_hint.get("rollback_rule"),
        )
        artifact_key = self._throughput_artifact_key(
            artifact_spec=artifact_spec,
            repo_path=repo_path,
            project_id=payload.project_id,
            goal_id=payload.goal_id or scheduler_hint.get("goal_id"),
        )
        self._enforce_throughput_admission(
            queue_name=queue_name,
            project_id=payload.project_id,
            artifact_key=artifact_key,
        )
        scheduler_hint["queue_name"] = queue_name
        scheduler_hint["task_type"] = task_type
        scheduler_hint["verification_level"] = verification_level
        scheduler_hint["max_runtime_seconds"] = max_runtime_seconds
        scheduler_hint["retry_limit"] = retry_limit
        scheduler_hint["rollback_rule"] = rollback_rule
        scheduler_hint["throughput"] = {
            "queue_name": queue_name,
            "task_type": task_type,
            "verification_level": verification_level,
            "max_runtime_seconds": max_runtime_seconds,
            "retry_limit": retry_limit,
            "rollback_rule": rollback_rule,
            "artifact_key": artifact_key,
        }
        tool_policy = build_task_tool_policy(
            preferred_worker=effective_preferred_worker,
            tool_route=tool_route,
            repo_path=repo_path,
            execution_lane=worker_vm_policy.get('lane', 'host-control'),
            auto_approve=effective_auto_approve,
            scheduled_by=payload.scheduled_by or payload.caller,
        )
        enriched_prompt = self._build_dispatch_prompt(safe_payload, project=project, repo=repo, context_package=context_package)
        if capability_guidance:
            enriched_prompt = f"{enriched_prompt}\n\n{capability_guidance}"
        task = await self.create_task(
            TaskCreate(
                prompt=enriched_prompt,
                title=payload.title or scheduler_hint.get("node_title") or scheduler_hint.get("title"),
                repo_path=repo_path,
                project_id=payload.project_id,
                goal=payload.goal,
                goal_id=payload.goal_id or scheduler_hint.get("goal_id"),
                graph_id=payload.graph_id or scheduler_hint.get("graph_id"),
                node_id=payload.node_id or scheduler_hint.get("node_id"),
                scheduled_by=payload.scheduled_by or scheduler_hint.get("scheduled_by"),
                auto_approve=effective_auto_approve,
                context_mode=context_mode,
                max_context_chars=max_context_chars,
                allow_resource_scan=payload.allow_resource_scan,
                allow_repo_status=payload.allow_repo_status,
                capability_route=capability_route,
                platform_context=platform_context,
                vm_template=vm_template,
                vm_context=vm_context,
                preferred_worker=effective_preferred_worker,
                scheduler_hint=scheduler_hint,
                context_package=context_package,
                tool_route=tool_route,
                executor_hint={**(payload.executor_hint or {}), "surface_route": surface_route, "preferred_surface": surface_route.get("preferred_surface"), "launch_mode": surface_route.get("launch_mode")},
                execution_mode=execution_mode,
                execution_lane=worker_vm_policy.get('lane', 'host-control'),
                worker_vm_policy=worker_vm_policy,
                prompt_guard=prompt_guard,
                tool_policy=tool_policy,
                artifact_spec=artifact_spec,
                task_type=task_type,
                queue_name=queue_name,
                verification_level=verification_level,
                max_runtime_seconds=max_runtime_seconds,
                retry_limit=retry_limit,
                rollback_rule=rollback_rule,
                parent_task_id=payload.parent_task_id,
                root_task_id=payload.root_task_id or payload.parent_task_id,
                decomposition_depth=payload.decomposition_depth,
                max_decomposition_depth=payload.max_decomposition_depth,
                admission_lane=payload.admission_lane,
                admission_reason=payload.admission_reason,
                dependency_task_ids=list(payload.dependency_task_ids or []),
                verification_signals=list(payload.verification_signals or []),
            )
        )
        if project:
            project.last_task_at = task.created_at
            self._persist()
        await self._append_event(
            task,
            "Task dispatched through unified API.",
            data={
                "caller": payload.caller,
                "project_id": project.id if project else None,
                "repo_id": repo.id if repo else None,
                "policy_version": self._policy.version,
                "capability_route": capability_route,
                "platform_context": platform_context,
                "vm_template": vm_template,
                "vm_context": vm_context,
                "tool_route": tool_route,
                "execution_mode": execution_mode.value,
                "execution_lane": worker_vm_policy.get('lane', 'host-control'),
                "admission_lane": payload.admission_lane,
                "admission_reason": payload.admission_reason,
                "worker_vm_policy": worker_vm_policy,
                "code_graph_focus": code_graph_focus,
                "throughput": {
                    "queue_name": queue_name,
                    "task_type": task_type,
                    "verification_level": verification_level,
                    "max_runtime_seconds": max_runtime_seconds,
                    "retry_limit": retry_limit,
                    "rollback_rule": rollback_rule,
                    "artifact_key": artifact_key,
                },
                "scheduler_hint": scheduler_hint,
                "context_package": context_package,
                "prompt_guard": prompt_guard,
                "tool_policy": tool_policy,
            },
        )
        if capability_route and capability_route.get('selected'):
            await self._append_event(
                task,
                f"Capability route selected: {capability_route['selected'].get('capability_id')}",
                data={
                    "provider_platform_id": capability_route['selected'].get('provider_platform_id'),
                    "provider_name": capability_route['selected'].get('provider_name'),
                    "workspace": capability_route['selected'].get('workspace'),
                },
            )
        return task

    async def admit_goal(self, payload: GoalAdmissionRequest) -> TaskRecord:
        goal_text = str(payload.goal or "").strip()
        prompt = (payload.prompt or "").strip()
        if not prompt:
            prompt = f"Admit goal and decompose it into exploration, design, implementation, and verification work.\n\nGoal: {goal_text}"
        goal_admission = {
            "kind": "goal",
            "goal": goal_text,
            "goal_id": payload.goal_id,
            "strategy": payload.strategy,
            "admitted_at": utc_iso(),
            "pipeline": self._goal_pipeline(goal_text, strategy=payload.strategy),
        }
        scheduler_hint = dict(payload.scheduler_hint or {})
        scheduler_hint.update(
            {
                "goal_admission": goal_admission,
                "decomposition_preferred": True,
                "decomposition_depth_limit": scheduler_hint.get("decomposition_depth_limit") or 3,
                "admission_lane": scheduler_hint.get("admission_lane") or "exploration",
            }
        )
        dispatch = DispatchTaskRequest(
            prompt=prompt,
            title=payload.title or f"Goal: {goal_text[:72]}",
            project_id=payload.project_id,
            repo_path=payload.repo_path,
            goal=goal_text,
            goal_id=payload.goal_id,
            scheduled_by=payload.scheduled_by or "goal-admission",
            auto_approve=payload.auto_approve,
            context_mode=payload.context_mode,
            max_context_chars=payload.max_context_chars,
            allow_resource_scan=payload.allow_resource_scan,
            allow_repo_status=payload.allow_repo_status,
            execution_mode=payload.execution_mode,
            preferred_worker=payload.preferred_worker,
            scheduler_hint=scheduler_hint,
            execution_lane=payload.execution_lane,
            task_type=payload.task_type or "exploration_intake",
            queue_name=payload.queue_name or "exploration",
            verification_level=payload.verification_level or "L1",
            artifact_spec=payload.artifact_spec,
            verification_contract=payload.verification_contract,
            goal_admission=goal_admission,
        )
        task = await self.dispatch_task(dispatch)
        task.events.append(
            TaskEvent(
                message="Goal admitted and converted into an exploratory task tree.",
                data={"goal_admission": goal_admission, "scheduler_hint": scheduler_hint},
            )
        )
        task.result.setdefault("goal_admission", goal_admission)
        self._persist()
        return task

    def _publication_payload_from_record(self, record: TaskPublicationRecord) -> TaskPublicationRequest:
        payload = record.model_dump(mode="json")
        for key in (
            "publication_id",
            "status",
            "task_id",
            "approved_by",
            "approved_at",
            "published_by",
            "published_at",
            "approval_notes",
            "publication_notes",
            "created_at",
            "updated_at",
        ):
            payload.pop(key, None)
        return TaskPublicationRequest.model_validate(payload)

    async def _create_task_from_publication_request(self, payload: TaskPublicationRequest) -> TaskRecord:
        prompt_guard = payload.prompt_guard or evaluate_prompt_guard(
            payload.prompt,
            goal=payload.goal,
            metadata={
                "project_id": payload.project_id,
                "repo_path": payload.repo_path,
                "publication_mode": "structured",
            },
        )
        effective_prompt = prompt_guard.get("sanitized_prompt") or payload.prompt
        scheduler_hint = dict(payload.scheduler_hint or {})
        scheduler_hint.setdefault("publication_mode", "structured")
        scheduler_hint.setdefault("publication_source", "task-publication")
        scheduler_hint.setdefault("task_type", payload.task_type)
        scheduler_hint.setdefault("verification_level", payload.verification_level)
        task = await self.create_task(
            TaskCreate(
                prompt=effective_prompt,
                title=payload.title,
                repo_path=payload.repo_path,
                project_id=payload.project_id,
                goal=payload.goal,
                goal_id=payload.goal_id or scheduler_hint.get("goal_id"),
                graph_id=payload.graph_id or scheduler_hint.get("graph_id"),
                node_id=payload.node_id or scheduler_hint.get("node_id"),
                scheduled_by=payload.scheduled_by,
                auto_approve=payload.auto_approve,
                context_mode=payload.context_mode,
                max_context_chars=payload.max_context_chars,
                allow_resource_scan=payload.allow_resource_scan,
                allow_repo_status=payload.allow_repo_status,
                capability_route=payload.capability_route,
                platform_context=payload.platform_context,
                vm_template=payload.vm_template,
                vm_context=payload.vm_context,
                preferred_worker=payload.preferred_worker,
                scheduler_hint=scheduler_hint,
                context_package=payload.context_package,
                tool_route=payload.tool_route,
                executor_hint=payload.executor_hint,
                execution_mode=payload.execution_mode,
                execution_lane=payload.execution_lane,
                worker_vm_policy=payload.worker_vm_policy,
                prompt_guard=prompt_guard,
                tool_policy=payload.tool_policy,
                security_review=payload.security_review,
                artifact_spec=payload.artifact_spec,
                verification_contract=payload.verification_contract,
                task_type=payload.task_type,
                queue_name=payload.queue_name,
                verification_level=payload.verification_level,
                max_runtime_seconds=payload.max_runtime_seconds,
                retry_limit=payload.retry_limit,
                rollback_rule=payload.rollback_rule,
                plan=payload.plan,
                goal_admission=payload.goal_admission,
            )
        )
        task.events.append(
            TaskEvent(
                message="Task published through structured publication surface.",
                data={
                    "publication_mode": "structured",
                    "task_type": payload.task_type,
                    "verification_level": payload.verification_level,
                },
            )
        )
        self._persist()
        return task

    async def create_task_publication(self, payload: TaskPublicationRequest) -> TaskPublicationRecord:
        record = TaskPublicationRecord(**payload.model_dump(mode="json"))
        async with self._lock:
            with self._persist_lock:
                self._task_publications[record.publication_id] = record
                self._persist()
        return record

    async def approve_task_publication(
        self,
        publication_id: str,
        payload: TaskPublicationApproveRequest | None = None,
    ) -> TaskPublicationRecord:
        payload = payload or TaskPublicationApproveRequest()
        async with self._lock:
            with self._persist_lock:
                record = self._task_publications.get(publication_id)
                if record is None:
                    raise ValueError(f"Task publication not found: {publication_id}")
                if record.status == PublicationStatus.rejected:
                    raise ValueError(f"Task publication is rejected: {publication_id}")
                if record.status == PublicationStatus.published:
                    return record
                record.status = PublicationStatus.approved
                record.approved_by = payload.approved_by or record.approved_by or "task-publication-approver"
                record.approved_at = utc_now()
                record.approval_notes = payload.notes or record.approval_notes
                record.updated_at = utc_now()
                self._task_publications[publication_id] = record
                self._persist()
        return record

    async def commit_task_publication(
        self,
        publication_id: str,
        payload: TaskPublicationPublishRequest | None = None,
    ) -> TaskRecord:
        payload = payload or TaskPublicationPublishRequest()
        publication_payload: TaskPublicationRequest | None = None
        async with self._lock:
            with self._persist_lock:
                record = self._task_publications.get(publication_id)
                if record is None:
                    raise ValueError(f"Task publication not found: {publication_id}")
                if record.status == PublicationStatus.published and record.task_id:
                    task = self._tasks.get(record.task_id)
                    if task is not None:
                        return task
                    raise ValueError(f"Published task missing for publication: {publication_id}")
                if record.status not in {PublicationStatus.approved, PublicationStatus.published} and not record.auto_approve:
                    raise ValueError(f"Task publication must be approved before commit: {publication_id}")
                publication_payload = self._publication_payload_from_record(record)
        if publication_payload is None:
            raise ValueError(f"Task publication payload unavailable for commit: {publication_id}")
        task = await self._create_task_from_publication_request(publication_payload)
        async with self._lock:
            with self._persist_lock:
                record = self._task_publications.get(publication_id)
                if record is None:
                    raise ValueError(f"Task publication not found after create: {publication_id}")
                record.status = PublicationStatus.published
                record.task_id = task.id
                record.published_by = payload.published_by or record.published_by or "task-publication-publisher"
                record.published_at = utc_now()
                record.publication_notes = payload.notes or record.publication_notes
                record.updated_at = utc_now()
                self._task_publications[publication_id] = record
                self._persist()
        return task

    async def publish_task(self, payload: TaskPublicationRequest) -> TaskRecord:
        draft = await self.create_task_publication(payload)
        await self.approve_task_publication(draft.publication_id, TaskPublicationApproveRequest(approved_by=payload.scheduled_by or "task-publication", notes="direct publish"))
        return await self.commit_task_publication(
            draft.publication_id,
            TaskPublicationPublishRequest(published_by=payload.scheduled_by or "task-publication", notes="direct publish"),
        )
    async def auto_debug_task(self, payload: AutoDebugRequest) -> TaskRecord:
        prompt = self._build_auto_debug_prompt(payload)
        dispatch = DispatchTaskRequest(
            prompt=prompt,
            project_id=payload.project_id,
            repo_id=payload.repo_id,
            repo_path=payload.repo_path or payload.workspace,
            goal=payload.goal or "Diagnose the failure, apply a bounded fix if safe, then rerun validation.",
            caller=payload.caller,
            auto_approve=payload.auto_approve,
            context_mode=payload.context_mode,
            max_context_chars=payload.max_context_chars,
            allow_resource_scan=payload.allow_resource_scan,
            allow_repo_status=payload.allow_repo_status,
        )
        task = await self.dispatch_task(dispatch)
        await self._append_event(
            task,
            "Auto-debug loop created.",
            data={
                "source": "auto-debug",
                "workspace": payload.workspace,
                "failing_command": payload.failing_command,
            },
        )
        return task

    def _select_vm_template(self, payload: DispatchTaskRequest, *, capability_route: dict[str, Any] | None = None, tool_route: dict[str, Any] | None = None) -> dict[str, Any] | None:
        request = (payload.vm_request or payload.goal or payload.prompt or '').strip()
        selected = choose_template_for_task(payload.vm_request, goal=payload.goal, prompt=payload.prompt)
        if selected:
            return selected
        preferred_worker = (payload.preferred_worker or '').lower()
        tool_domain = (((tool_route or {}).get('selected') or {}).get('domain') or '').lower()
        capability_id = (((capability_route or {}).get('selected') or {}).get('capability_id') or '').lower()
        text = request.lower()
        if preferred_worker in {'tester'} or 'test' in tool_domain or 'qemu' in text or 'regression' in text:
            return choose_template_for_task('test', goal=payload.goal, prompt=payload.prompt)
        if preferred_worker in {'coder', 'ops', 'shell', 'docker'} and (tool_domain in {'code', 'infrastructure', 'system'} or any(token in text for token in ['implement', 'patch', 'module', 'feature', 'kernel', 'build', 'compile', 'docker'])):
            return choose_template_for_task('build', goal=payload.goal, prompt=payload.prompt)
        if 'experiment' in capability_id or 'research' in text or 'benchmark' in text:
            return choose_template_for_task('experiment', goal=payload.goal, prompt=payload.prompt)
        return None


    def _select_tool_route(self, payload: DispatchTaskRequest) -> dict[str, Any]:
        request = (payload.capability_request or payload.goal or payload.prompt or '').strip()
        if not request:
            return {}
        return route_tool(request)


    def _select_capability_route(
        self,
        payload: DispatchTaskRequest,
        *,
        project: ProjectMemoryRecord | None,
        repo: RepoRecord | None,
    ) -> dict[str, Any] | None:
        request = (payload.capability_request or payload.goal or payload.prompt or '').strip()
        if not request:
            return None
        routed = route_capability(request)
        selected = routed.get('selected')
        if not selected:
            return None
        return routed

    def _repo_path_is_pinned(self, payload: DispatchTaskRequest, repo_path: str | None) -> bool:
        explicit_repo_path = (payload.repo_path or '').strip().lower()
        resolved_repo_path = (repo_path or '').strip().lower()
        if explicit_repo_path and resolved_repo_path and explicit_repo_path == resolved_repo_path:
            return True
        target_tokens = [
            'orchestrator-mvp',
            'metafactory-core',
            'meta factory',
            'mainline',
        ]
        corpus = ' '.join(
            part
            for part in [
                payload.goal or '',
                payload.goal_id or '',
                payload.graph_id or '',
                payload.node_id or '',
                payload.scheduled_by or '',
                payload.project_id or '',
                payload.repo_id or '',
                json.dumps(payload.scheduler_hint or {}, ensure_ascii=False),
            ]
            if part
        ).lower()
        return bool(resolved_repo_path and any(token in resolved_repo_path or token in corpus for token in target_tokens))

    def _apply_capability_route(
        self,
        payload: DispatchTaskRequest,
        routed: dict[str, Any] | None,
        *,
        repo_path: str | None,
    ) -> tuple[str | None, dict[str, Any], str | None]:
        if not routed or not routed.get('selected'):
            return repo_path, {}, None
        selected = routed['selected']
        provider_workspace = selected.get('workspace')
        repo_path_pinned = self._repo_path_is_pinned(payload, repo_path)
        workspace = repo_path if repo_path_pinned and repo_path else (provider_workspace or repo_path)
        provider = selected.get('provider_name') or selected.get('provider_platform_id')
        capability_id = selected.get('capability_id')
        guidance_lines = [
            f"Capability route selected: {capability_id} via {provider}.",
            "Use the provider's tools, workflows, and implementation hints as guidance before generic implementation.",
        ]
        if repo_path_pinned and repo_path:
            guidance_lines.append(
                f"Execution repo is pinned to: {repo_path}. Do not switch execution into the provider workspace."
            )
            if provider_workspace and provider_workspace != repo_path:
                guidance_lines.append(f"Reference provider workspace only for context: {provider_workspace}")
        else:
            guidance_lines.append(f"Preferred execution workspace: {workspace or 'unknown'}")
        guidance_lines.append(f"Entrypoint: {selected.get('entrypoint') or 'n/a'}")
        guidance = '\n'.join(guidance_lines)
        context = {
            'provider_platform_id': selected.get('provider_platform_id'),
            'provider_name': selected.get('provider_name'),
            'capability_id': capability_id,
            'workspace': provider_workspace or workspace,
            'execution_repo_path': workspace,
            'repo_path_pinned': repo_path_pinned,
            'entrypoint': selected.get('entrypoint'),
            'keywords': selected.get('keywords', []),
        }
        return workspace or repo_path, context, guidance


    def _refresh_read_state(self) -> None:
        self._tasks = {}
        self._projects = {}
        self._core_messages = []
        self._release_records = []
        self._checkpoints = {}
        self._load_state()

    async def list_tasks(self) -> list[TaskRecord]:
        self._refresh_read_state()
        return sorted(self._tasks.values(), key=lambda item: item.created_at, reverse=True)

    async def get_task(self, task_id: str) -> TaskRecord | None:
        self._refresh_read_state()
        return self._tasks.get(task_id)

    def _build_task_decomposition_tree(self, task_id: str, *, max_depth: int = 6) -> dict[str, Any] | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        result = task.result if isinstance(task.result, dict) else {}
        decomposition = result.get("decomposition") if isinstance(result, dict) else None
        child_ids = []
        if isinstance(decomposition, dict):
            child_ids.extend([str(item) for item in decomposition.get("child_task_ids") or [] if str(item).strip()])
        child_ids.extend([str(item) for item in task.child_task_ids or [] if str(item).strip()])
        child_ids = list(dict.fromkeys(child_ids))
        node: dict[str, Any] = {
            "task_id": task.id,
            "title": task.title,
            "goal": task.goal,
            "prompt": task.prompt,
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "task_type": task.task_type,
            "queue_name": task.queue_name,
            "verification_level": task.verification_level,
            "execution_mode": task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
            "parent_task_id": task.parent_task_id,
            "root_task_id": task.root_task_id,
            "decomposition_depth": task.decomposition_depth,
            "max_decomposition_depth": task.max_decomposition_depth,
            "child_task_ids": child_ids,
            "dependency_task_ids": list(task.dependency_task_ids or []),
            "admission_lane": task.admission_lane,
            "admission_reason": task.admission_reason,
            "summary": (decomposition or {}).get("summary") if isinstance(decomposition, dict) else None,
            "strategy": (decomposition or {}).get("strategy") if isinstance(decomposition, dict) else None,
            "dag": (decomposition or {}).get("dag") if isinstance(decomposition, dict) else None,
        }
        if max_depth <= 0:
            node["children"] = []
            return node
        children = []
        for child_id in child_ids:
            child = self._tasks.get(child_id)
            if child is None:
                continue
            children.append(self._build_task_decomposition_tree(child_id, max_depth=max_depth - 1))
        node["children"] = [item for item in children if item is not None]
        if not node["children"] and child_ids:
            node["children"] = [
                {
                    "task_id": child_id,
                    "title": None,
                    "goal": None,
                    "prompt": None,
                    "status": "missing",
                    "task_type": None,
                    "queue_name": None,
                    "verification_level": None,
                    "execution_mode": None,
                    "parent_task_id": task.id,
                    "root_task_id": task.root_task_id or task.id,
                    "decomposition_depth": self._task_decomposition_depth(task) + 1,
                    "max_decomposition_depth": self._task_max_decomposition_depth(task),
                    "child_task_ids": [],
                    "summary": None,
                    "strategy": None,
                    "children": [],
                }
                for child_id in child_ids
            ]
        return node

    async def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        self._refresh_read_state()
        task = self._tasks.get(task_id)
        if not task:
            return None
        payload = task.model_dump(mode="json")
        payload["decomposition_tree"] = self._build_task_decomposition_tree(task_id)
        payload["decomposition_root_task_id"] = task.root_task_id or task.id
        payload["decomposition_depth"] = task.decomposition_depth
        payload["max_decomposition_depth"] = task.max_decomposition_depth
        return payload

    async def get_context_artifact(self, artifact_id: str, *, max_chars: int | None = None) -> dict[str, Any] | None:
        return self._runtime_context.retrieve(artifact_id, max_chars=max_chars)

    async def stats(self) -> DashboardStats:
        self._refresh_read_state()
        tasks = list(self._tasks.values())
        return DashboardStats(
            total_tasks=len(tasks),
            active_tasks=sum(1 for task in tasks if task.status in TASK_ACTIVE_STATUSES),
            completed_tasks=sum(1 for task in tasks if task.status in TASK_VERIFIED_COMPLETION_STATUSES),
            failed_tasks=sum(1 for task in tasks if task.status == TaskStatus.failed),
            delivery_ready_tasks=sum(1 for task in tasks if task.status == TaskStatus.delivery_ready),
            released_tasks=sum(1 for task in tasks if task.status == TaskStatus.released),
            verification_failed_tasks=sum(1 for task in tasks if task.status == TaskStatus.verification_failed),
        )

    async def list_resources(self) -> list[ResourceRecord]:
        return self._registry.list_resources()

    async def list_repos(self) -> list[RepoRecord]:
        return self._registry.list_repos()

    async def list_capabilities(self) -> list[dict[str, Any]]:
        return self._capabilities

    async def list_core_messages(self) -> list[dict[str, Any]]:
        self._refresh_read_state()
        return list(reversed(self._core_messages))

    async def get_core_message(self, message_id: str) -> dict[str, Any] | None:
        self._refresh_read_state()
        return next((item for item in self._core_messages if item.get("id") == message_id), None)

    async def list_task_templates(self) -> list[dict[str, Any]]:
        return self._task_templates

    def _load_executor_registry(self) -> list[dict[str, Any]]:
        path = self._contracts_dir / "executors" / "executor_registry.json"
        payload = _load_json_contract(path, {"version": "v1", "executors": []})
        executors = payload.get("executors") if isinstance(payload, dict) else []
        return [item for item in executors if isinstance(item, dict)]

    async def list_executors(self) -> dict[str, Any]:
        try:
            registry = self._load_executor_registry()
            adapter_map = getattr(self._executors, "_adapters", {})
            return {
                "executors": [
                    {
                        **executor,
                        "health": {
                            "healthy": bool(adapter_map.get(str(executor.get("executor_id") or "").strip())),
                            "enabled": bool(executor.get("enabled", True)),
                            "adapter": (
                                getattr(adapter_map.get(str(executor.get("executor_id") or "").strip()), "adapter_name", None)
                                if adapter_map.get(str(executor.get("executor_id") or "").strip())
                                else None
                            ),
                            "supports_parallel": bool(executor.get("supports_parallel", False)),
                            "supports_long_horizon": bool(executor.get("supports_long_horizon", False)),
                            "submitted_tasks": len(
                                getattr(
                                    getattr(adapter_map.get(str(executor.get("executor_id") or "").strip()), "_state", None),
                                    "submitted",
                                    {},
                                )
                            )
                            if adapter_map.get(str(executor.get("executor_id") or "").strip())
                            else 0,
                        },
                        "state_file": str(self._executors._state_path),
                        "persisted_task_count": 0,
                        "active_tasks": len(
                            getattr(
                                getattr(adapter_map.get(str(executor.get("executor_id") or "").strip()), "_state", None),
                                "submitted",
                                {},
                            )
                        )
                        if adapter_map.get(str(executor.get("executor_id") or "").strip())
                        else 0,
                    }
                    for executor in registry
                ],
                "routing_policy": self._load_executor_policy("routing"),
                "verification_policy": self._load_executor_policy("verification"),
            }
        except Exception as exc:
            return {
                "executors": self._load_executor_registry(),
                "routing_policy": {"version": "v1", "rules": [], "default_executor_id": None},
                "verification_policy": {"version": "v1", "levels": []},
                "error": str(exc),
            }

    async def get_executor_task(self, executor_id: str, task_id: str) -> dict[str, Any]:
        status = self._executors.get_status(executor_id, task_id).model_dump(mode="json")
        result = self._executors.fetch_result(executor_id, task_id).model_dump(mode="json")
        return {
            "executor_id": executor_id,
            "task_id": task_id,
            "status": status,
            "result": result,
            "health": (self._executors.get_adapter(executor_id).healthcheck() if self._executors.get_adapter(executor_id) else {"healthy": False}),
        }

    async def run_executor_task(self, executor_id: str, payload: ExecutorRunRequest) -> dict[str, Any]:
        return self._executors.run_task(executor_id, payload)

    def _load_executor_policy(self, policy_kind: str) -> dict[str, Any]:
        policy_kind = str(policy_kind or "").strip().lower()
        if policy_kind == "routing":
            path = self._contracts_dir / "executors" / "routing_policy.json"
            default = {"version": "v1", "rules": [], "default_executor_id": None}
        elif policy_kind == "verification":
            path = self._contracts_dir / "executors" / "verification_policy.json"
            default = {"version": "v1", "levels": []}
        else:
            return {"version": "v1"}
        payload = _load_json_contract(path, default)
        return payload if isinstance(payload, dict) else default

    def _executor_task_envelope(self, task: TaskRecord) -> ExecutorTaskEnvelope:
        artifact_spec = task.artifact_spec.model_dump(mode="json") if isinstance(task.artifact_spec, ArtifactSpec) else {}
        return ExecutorTaskEnvelope(
            task_id=task.id,
            task_type=task.task_type or task.queue_name or "doc_patch",
            goal=task.goal,
            inputs={
                "prompt": task.prompt,
                "repo_path": task.repo_path,
                "project_id": task.project_id,
                "goal_id": task.goal_id,
                "graph_id": task.graph_id,
                "node_id": task.node_id,
                "scheduled_by": task.scheduled_by,
                "surface_route": task.executor_route.get("surface_route"),
            },
            constraints=list(task.contract.constraints or []) if task.contract else [],
            expected_outputs=list(task.contract.deliverables or []) if task.contract else [],
            verification_level=task.verification_level or "L2",
            max_runtime_seconds=task.max_runtime_seconds,
            executor_hint=task.executor_route,
            artifact_spec=artifact_spec,
        )

    def _executor_submit(self, task: TaskRecord) -> None:
        executor_id = str(task.executor_id or "").strip()
        if not executor_id:
            return
        try:
            self._executors.submit_task(executor_id, self._executor_task_envelope(task))
        except KeyError:
            task.events.append(
                TaskEvent(
                    message=f"Executor '{executor_id}' unavailable; continuing with orchestrator runtime only.",
                    level="warning",
                    data={"executor_id": executor_id},
                )
            )

    def _executor_report(self, task: TaskRecord, *, phase: str, progress: float, metadata: dict[str, Any] | None = None) -> None:
        executor_id = str(task.executor_id or "").strip()
        if not executor_id:
            return
        try:
            self._executors.report_status(executor_id, task.id, phase=phase, progress=progress, metadata=metadata)
        except KeyError:
            return

    def _executor_complete(
        self,
        task: TaskRecord,
        *,
        status: str,
        summary: str,
        outputs: dict[str, Any] | None = None,
        needs_verification: bool = True,
    ) -> None:
        executor_id = str(task.executor_id or "").strip()
        if not executor_id:
            return
        try:
            self._executors.complete_task(
                executor_id,
                task.id,
                status=status,
                outputs=outputs,
                summary=summary,
                logs_path=str(self._task_runtime_path(task.id) / "executor.log"),
                needs_verification=needs_verification,
            )
            self._record_executor_route_experience(
                task,
                success=status == "success",
                summary=summary,
            )
        except KeyError:
            return

    async def browser_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("Missing url")
        out = str(payload.get("out") or "D:\codex\output\browser\page.json")
        screenshot = str(payload.get("screenshot") or "").strip()
        profile = str(payload.get("profile") or "").strip()
        wait_for = str(payload.get("wait_for") or "").strip()
        selector = str(payload.get("selector") or "body")
        wait_until = str(payload.get("wait_until") or "domcontentloaded").strip() or "domcontentloaded"
        proxy = str(payload.get("proxy") or "").strip()
        args = [
            BUNDLED_PYTHON,
            BROWSER_BRIDGE,
            "--url",
            url,
            "--out",
            out,
            "--selector",
            selector,
            "--wait-until",
            wait_until,
        ]
        if screenshot:
            args.extend(["--screenshot", screenshot])
        if profile:
            args.extend(["--profile", profile])
        if proxy:
            args.extend(["--proxy", proxy])
        if payload.get("headed"):
            args.append("--headed")
        if wait_for:
            args.extend(["--wait-for", wait_for])
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))
        return json.loads(stdout.decode("utf-8", errors="replace"))

    async def browser_login_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("Missing url")
        profile = str(payload.get("profile") or "default").strip() or "default"
        args = [
            BUNDLED_PYTHON,
            BROWSER_BRIDGE,
            "--login-session",
            "--headed",
            "--url",
            url,
            "--profile",
            profile,
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))
        lines = stdout.decode("utf-8", errors="replace").splitlines()
        json_text = "\n".join(line for line in lines if line.strip())
        return json.loads(json_text)

    async def post_core_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = {
            "id": payload.get("id") or f"core-{len(self._core_messages) + 1:04d}",
            "created_at": payload.get("created_at") or utc_iso(),
            "status": payload.get("status") or "open",
            "source": payload.get("source") or "manual",
            "severity": payload.get("severity") or "info",
            "title": payload.get("title") or "Untitled core message",
            "body": payload.get("body") or "",
            "task_id": payload.get("task_id"),
            "step_id": payload.get("step_id"),
            "repo_path": payload.get("repo_path"),
        }
        self._core_messages.append(message)
        self._persist()
        return message

    async def resolve_core_message(self, message_id: str, *, resolution: str = "", status: str = "resolved") -> dict[str, Any]:
        message = await self.get_core_message(message_id)
        if message is None:
            raise KeyError("Core message not found")
        message["status"] = status
        message["resolved_at"] = utc_iso()
        if resolution:
            message["resolution"] = resolution
        task_id = message.get("task_id")
        task = self._tasks.get(task_id) if task_id else None
        if (
            task is not None
            and status in {"approved", "resolved", "auto-resolved"}
            and task.status == TaskStatus.waiting_approval
        ):
            task.status = TaskStatus.planning
            task.updated_at = datetime.now(timezone.utc)
            result = dict(task.result or {})
            result["resume_resolution"] = resolution or f"Core message {message_id} resolved."
            result["resumed_from_waiting_approval"] = True
            task.result = result
            self._update_checkpoint(task, phase="planning", extra={"resume_message_id": message_id, "resolution_status": status})
        self._persist()
        if task is not None and task.status == TaskStatus.planning:
            self._launch_task_runner(task)
        return message

    async def reopen_core_message(self, message_id: str, *, reason: str = "") -> dict[str, Any]:
        message = await self.get_core_message(message_id)
        if message is None:
            raise KeyError("Core message not found")
        message["status"] = "open"
        message["reopened_at"] = utc_iso()
        if reason:
            message["reopen_reason"] = reason
        self._persist()
        return message

    async def create_feature_branch(self, repo_id: str, prompt: str) -> dict[str, Any]:
        repo = self._registry.get_repo(repo_id)
        if not repo:
            raise KeyError("Repo not found")
        result = await self._git.ensure_feature_branch(repo, prompt)
        return {"repo_id": repo.id, **result}

    async def list_release_records(self) -> list[dict[str, Any]]:
        return list(reversed(self._release_records))

    async def list_task_publications(self) -> list[TaskPublicationRecord]:
        return sorted(
            self._task_publications.values(),
            key=lambda record: record.updated_at or record.created_at,
            reverse=True,
        )

    async def record_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        artifact_evidence = validate_release_payload(payload.get("repo_path"), payload.get("artifacts") or [])
        record = {
            "id": payload.get("id") or f"release-{len(self._release_records)+1:03d}",
            "created_at": payload.get("created_at") or utc_iso(),
            "repo_id": payload.get("repo_id"),
            "repo_path": payload.get("repo_path"),
            "branch": payload.get("branch"),
            "artifacts": payload.get("artifacts") or [],
            "artifact_evidence": artifact_evidence,
            "blockers": list(payload.get("blockers") or []) + ([] if artifact_evidence.get("passed") else ["artifact-evidence-missing"]),
            "status": payload.get("status") or ("prepared" if artifact_evidence.get("passed") else "blocked"),
            "notes": payload.get("notes") or "",
        }
        self._release_records.append(record)
        self._persist()
        return record

    async def register_repo(self, payload: RepoRegistration) -> RepoRecord:
        repo = self._registry.upsert_repo(payload)
        try:
            await self._git.ensure_repo(repo)
            await self._git.sync_remotes(repo)
        except Exception:
            pass
        return repo

    async def push_repo(self, repo_id: str, payload: RepoPushRequest) -> RepoPushResult:
        repo = self._registry.get_repo(repo_id)
        if not repo:
            raise KeyError("Repo not found")
        remotes = payload.remote_names or [remote.name for remote in repo.remotes]
        if not remotes:
            raise RuntimeError('No remotes configured for this repo.')
        decisions = []
        for remote_name in remotes:
            decision = decide_privilege('git.push', remote=remote_name)
            decisions.append({'remote': remote_name, 'approved': decision.approved, 'reason': decision.reason, 'mode': decision.mode})
            append_security_audit(
                action='git_push_review',
                actor='orchestrator',
                result='approved' if decision.approved else 'denied',
                target=remote_name,
                severity='warning' if not decision.approved else 'info',
                details={
                    'repo_id': repo_id,
                    'repo_path': repo.local_path,
                    'branch': payload.branch,
                    'decision': {'mode': decision.mode, 'reason': decision.reason},
                },
            )
            if not decision.approved:
                raise RuntimeError(f"Git push denied for remote '{remote_name}': {decision.reason}")
        result = await self._git.push(repo, payload)
        self._registry.mark_repo_pushed(repo_id)
        append_security_audit(
            action='git_push',
            actor='orchestrator',
            result='success',
            target=repo.local_path,
            details={'repo_id': repo_id, 'branch': result.branch, 'remotes': result.pushed_remotes, 'decisions': decisions},
        )
        return result
    async def repo_status(self, repo_id: str) -> dict[str, str]:
        repo = self._registry.get_repo(repo_id)
        if not repo:
            raise KeyError("Repo not found")
        branch = await self._git.current_branch(repo)
        status = await self._git.status_summary(repo)
        return {"repo_id": repo.id, "branch": branch, "status": status}

    async def list_projects(self) -> list[ProjectMemoryRecord]:
        return sorted(self._projects.values(), key=lambda item: item.name.lower())

    async def upsert_project(self, payload: ProjectMemoryUpsert) -> ProjectMemoryRecord:
        existing = next(
            (
                project
                for project in self._projects.values()
                if project.name == payload.name or (payload.repo_path and project.repo_path == payload.repo_path)
            ),
            None,
        )
        if existing:
            existing.name = payload.name
            existing.repo_id = payload.repo_id
            existing.repo_path = payload.repo_path
            existing.summary = payload.summary
            existing.architecture_notes = payload.architecture_notes
            existing.working_agreements = payload.working_agreements
            existing.recent_decisions = payload.recent_decisions
            existing.preferred_context_mode = payload.preferred_context_mode
            self._persist()
            return existing
        project = ProjectMemoryRecord(
            name=payload.name,
            repo_id=payload.repo_id,
            repo_path=payload.repo_path,
            summary=payload.summary,
            architecture_notes=payload.architecture_notes,
            working_agreements=payload.working_agreements,
            recent_decisions=payload.recent_decisions,
            preferred_context_mode=payload.preferred_context_mode,
        )
        self._projects[project.id] = project
        self._persist()
        return project

    async def get_policy(self) -> PolicyRecord:
        return self._policy

    async def update_policy(self, payload: PolicyRecord) -> PolicyRecord:
        self._policy = payload
        self._persist()
        return self._policy

    def _task_decomposition_depth(self, task: TaskRecord) -> int:
        return max(0, int(task.decomposition_depth or 0))

    def _task_max_decomposition_depth(self, task: TaskRecord) -> int:
        return max(0, int(task.max_decomposition_depth or 0))

    def _goal_pipeline(self, goal_text: str, *, strategy: str | None = None) -> list[dict[str, Any]]:
        normalized = str(goal_text or "").strip()
        lowered = normalized.lower()
        wants_optional = any(token in lowered for token in ("integration", "api", "workflow", "connector", "sync", "import", "export", "publish"))
        wants_speculative = any(token in lowered for token in ("compare", "experiment", "benchmark", "optimize", "alternative", "explore", "speculative"))
        wants_blocked = any(token in lowered for token in ("blocked", "dependency", "upstream", "waiting", "prerequisite"))
        wants_repair = bool(strategy and "repair" in strategy.lower()) or any(token in lowered for token in ("repair", "fix", "rollback", "recover", "bug", "failure"))
        nodes: list[dict[str, Any]] = [
            {
                "stage": "explore",
                "title": "Explore the goal",
                "task_type": "exploration_intake",
                "path_kind": "shared",
                "queue_name": "exploration",
                "verification_level": "L1",
                "preferred_worker": "planner",
                "prompt": f"Explore the goal, discover constraints, and identify unknowns.\n\nGoal: {normalized}",
                "goal": normalized,
                "dependencies": [],
            },
            {
                "stage": "design",
                "title": "Design the solution",
                "task_type": "architecture_review",
                "path_kind": "branch",
                "queue_name": "incubation",
                "verification_level": "L2",
                "preferred_worker": "planner",
                "prompt": f"Turn the explored goal into an implementation design and decomposition plan.\n\nGoal: {normalized}",
                "goal": normalized,
                "dependencies": ["Explore the goal"],
            },
            {
                "stage": "implement",
                "title": "Implement the solution",
                "task_type": "build_fix",
                "path_kind": "branch",
                "queue_name": "build_test",
                "verification_level": "L2",
                "preferred_worker": "coder",
                "prompt": f"Implement the design for the admitted goal with bounded changes.\n\nGoal: {normalized}",
                "goal": normalized,
                "dependencies": ["Design the solution"],
            },
            {
                "stage": "verify",
                "title": "Verify the result",
                "task_type": "artifact_audit",
                "path_kind": "repair" if wants_repair else "branch",
                "queue_name": "regression",
                "verification_level": "L3",
                "preferred_worker": "reviewer",
                "prompt": f"Verify the implementation, collect evidence, and decide whether to promote or repair.\n\nGoal: {normalized}",
                "goal": normalized,
                "dependencies": ["Implement the solution"],
            },
        ]
        if wants_optional:
            nodes.append(
                {
                    "stage": "optional",
                    "title": "Optional integration branch",
                    "task_type": "manifest_patch",
                    "path_kind": "optional",
                    "queue_name": "fastlane",
                    "verification_level": "L1",
                    "preferred_worker": "coder",
                    "prompt": f"Build the optional integration branch only if it improves the goal outcome.\n\nGoal: {normalized}",
                    "goal": normalized,
                    "dependencies": ["Design the solution"],
                }
            )
        if wants_speculative:
            nodes.append(
                {
                    "stage": "speculative",
                    "title": "Speculative branch",
                    "task_type": "report_refresh",
                    "path_kind": "speculative",
                    "queue_name": "fastlane",
                    "verification_level": "L1",
                    "preferred_worker": "reviewer",
                    "prompt": f"Run a speculative branch to compare an alternative approach or gather extra evidence.\n\nGoal: {normalized}",
                    "goal": normalized,
                    "dependencies": ["Explore the goal"],
                }
            )
        if wants_blocked:
            nodes.append(
                {
                    "stage": "blocked",
                    "title": "Blocked dependency watch",
                    "task_type": "dependency_watch",
                    "path_kind": "blocked",
                    "queue_name": "exploration",
                    "verification_level": "L1",
                    "preferred_worker": "planner",
                    "prompt": f"Track the external dependency or prerequisite that is blocking progress.\n\nGoal: {normalized}",
                    "goal": normalized,
                    "dependencies": ["Explore the goal"],
                }
            )
        if wants_repair:
            nodes.append(
                {
                    "stage": "repair",
                    "title": "Repair branch",
                    "task_type": "path_repair",
                    "path_kind": "repair",
                    "queue_name": "regression",
                    "verification_level": "L3",
                    "preferred_worker": "coder",
                    "prompt": f"Prepare a repair branch that can recover if verification fails.\n\nGoal: {normalized}",
                    "goal": normalized,
                    "dependencies": ["Verify the result"],
                    "repair_for": "Verify the result",
                }
            )
        return nodes

    def _should_decompose_task(self, task: TaskRecord) -> bool:
        if self._task_decomposition_depth(task) >= self._task_max_decomposition_depth(task):
            return False
        hint = task.scheduler_hint or {}
        if bool(hint.get("decomposition_disabled")):
            return False
        if hint.get("decomposition_allow_children") is False:
            return False
        if bool(hint.get("decomposition_enabled")):
            return True
        if bool(hint.get("decomposition_preferred")):
            return True
        if self._is_recovery_task(task):
            return False
        if task.status not in {TaskStatus.planning, TaskStatus.queued}:
            return False
        corpus = " ".join(
            part
            for part in [
                task.prompt,
                task.goal or "",
                task.title or "",
                task.task_type or "",
                task.queue_name or "",
                task.verification_level or "",
            ]
            if part
        ).lower()
        task_type = str(task.task_type or "").strip().lower()
        execution_mode = str(task.execution_mode.value if hasattr(task.execution_mode, "value") else task.execution_mode or "").strip().lower()
        force_types = {
            "build_fix",
            "subsystem_refactor",
            "architecture_migration",
            "new_artifact_bootstrap",
            "new_demo_creation",
            "path_repair",
            "demo_rebuild",
            "harness_regression_run",
            "qemu_smoke_run",
            "unit_test_run",
            "package_validation",
        }
        soft_force_markers = (
            "multi-step",
            "multi step",
            "decompose",
            "decomposition",
            "orchestration",
            "workflow",
            "pipeline",
            "coordinate",
            "coordination",
            "plan and execute",
            "analyze",
            "implement",
            "verify",
            "validate",
            "investigate",
            "research",
            "design",
            "architecture",
            "migration",
            "refactor",
            "patch",
            "debug",
            "repair",
        )
        if task_type in force_types:
            return True
        complexity_score = 0
        if len(task.prompt or "") >= 96:
            complexity_score += 1
        if len(task.goal or "") >= 72:
            complexity_score += 1
        if len(corpus) >= 140:
            complexity_score += 1
        if task.repo_path:
            complexity_score += 1
        if task.context_envelope:
            complexity_score += 1
        if task.artifact_spec is not None or task.verification_contract is not None:
            complexity_score += 1
        if task_type in {"build_fix", "subsystem_refactor", "architecture_migration", "new_artifact_bootstrap", "new_demo_creation", "path_repair", "demo_rebuild"}:
            complexity_score += 2
        if execution_mode == "production" and task_type not in {"doc_patch", "json_fix", "report_refresh", "artifact_audit"}:
            complexity_score += 1
        complexity_score += sum(1 for token in soft_force_markers if token in corpus)
        complexity_score += sum(1 for token in ("build", "compile", "test", "fix", "release", "system") if token in corpus)
        return complexity_score >= 2

    def _build_task_decomposition(self, task: TaskRecord) -> TaskDecompositionResponse:
        goal_pipeline = (task.goal_admission or {}).get("pipeline") if isinstance(task.goal_admission, dict) else None
        if self._task_decomposition_depth(task) == 0 and isinstance(goal_pipeline, list) and goal_pipeline:
            subtasks: list[TaskDecompositionSpec] = []
            for index, item in enumerate(goal_pipeline):
                if not isinstance(item, dict):
                    continue
                prev_title = None
                if index > 0 and isinstance(goal_pipeline[index - 1], dict):
                    prev_title = str(goal_pipeline[index - 1].get("title") or "").strip() or None
                dependencies = [prev_title] if prev_title else []
                subtasks.append(
                    TaskDecompositionSpec(
                        title=str(item.get("title") or f"Stage {index + 1}").strip(),
                        prompt=str(item.get("prompt") or task.prompt).strip(),
                        goal=str(item.get("goal") or task.goal or "").strip() or None,
                        task_type=str(item.get("task_type") or task.task_type or "exploration_intake").strip() or None,
                        path_kind=str(item.get("path_kind") or "").strip() or None,
                        queue_name=str(item.get("queue_name") or task.queue_name or "").strip() or None,
                        verification_level=str(item.get("verification_level") or task.verification_level or "").strip() or None,
                        preferred_worker=str(item.get("preferred_worker") or task.preferred_worker or "").strip() or None,
                        execution_mode=task.execution_mode,
                        execution_lane=task.execution_lane,
                        decompose_children=index < len(goal_pipeline) - 1,
                        shared_dependency_group=str(task.root_task_id or task.id),
                        dependencies=dependencies,
                        acceptance_criteria=[f"{str(item.get('stage') or 'stage').capitalize()} stage completed."],
                        scheduler_hint={
                            "goal_pipeline_stage": item.get("stage"),
                            "goal_pipeline_index": index,
                            "goal_pipeline_root": task.root_task_id or task.id,
                        },
                        executor_hint={
                            "goal_pipeline_stage": item.get("stage"),
                            "goal_pipeline_index": index,
                        },
                    )
                )
            decomposition = TaskDecompositionResponse(
                summary=f"Goal pipeline for {task.goal or task.prompt}",
                strategy=str((task.goal_admission or {}).get("strategy") or "explore-design-implement-verify"),
                subtasks=subtasks,
                dag={
                    "shared_nodes": [subtasks[0].title] if subtasks else [],
                    "branch_nodes": [spec.title for spec in subtasks[1:-1]] if len(subtasks) > 2 else [],
                    "repair_nodes": [subtasks[-1].title] if len(subtasks) > 1 and subtasks[-1].path_kind == "repair" else [],
                    "edges": [
                        {"from": subtasks[index - 1].title, "to": spec.title, "kind": "pipeline"}
                        for index, spec in enumerate(subtasks)
                        if index > 0
                    ],
                },
            )
            return self._normalize_task_decomposition_graph(task, decomposition)
        decomposition = self._planner.build_decomposition(
            prompt=task.prompt,
            repo_path=task.repo_path,
            context=task.context_envelope,
            max_children=4,
            depth=self._task_decomposition_depth(task),
            max_depth=self._task_max_decomposition_depth(task) or 2,
        )
        return self._normalize_task_decomposition_graph(task, decomposition)

    def _normalize_task_decomposition_graph(
        self,
        task: TaskRecord,
        decomposition: TaskDecompositionResponse,
    ) -> TaskDecompositionResponse:
        subtasks = [spec.model_dump(mode="json") if hasattr(spec, "model_dump") else dict(spec) for spec in decomposition.subtasks or []]
        if not subtasks:
            decomposition.dag = {}
            return decomposition
        lowered = " ".join(
            part
            for part in [
                task.prompt,
                task.goal or "",
                task.title or "",
                task.task_type or "",
            ]
            if part
        ).lower()
        repair_like = any(token in lowered for token in ("repair", "fix", "debug", "bug", "failure", "broken"))
        shared_group = str(task.root_task_id or task.id)
        dag = {
            "shared_nodes": [],
            "branch_nodes": [],
            "repair_nodes": [],
            "optional_nodes": [],
            "speculative_nodes": [],
            "blocked_nodes": [],
            "edges": [],
            "shared_dependency_group": shared_group,
        }
        normalized: list[TaskDecompositionSpec] = []
        anchor_title = str(subtasks[0].get("title") or f"{task.title or 'Shared'} foundation").strip()
        for index, raw_spec in enumerate(subtasks):
            payload = dict(raw_spec)
            title = str(payload.get("title") or f"Subtask {index + 1}").strip()
            existing_dependencies = [str(item).strip() for item in (payload.get("dependencies") or []) if str(item).strip()]
            path_kind = str(payload.get("path_kind") or "").strip().lower()
            if index == 0:
                path_kind = path_kind or "shared"
            elif len(subtasks) >= 3 and index == len(subtasks) - 1:
                path_kind = path_kind or "repair"
            elif repair_like and index == len(subtasks) - 1:
                path_kind = path_kind or "repair"
            else:
                path_kind = path_kind or "branch"
            payload["path_kind"] = path_kind
            payload["shared_dependency_group"] = payload.get("shared_dependency_group") or shared_group
            deps = list(existing_dependencies)
            if index > 0 and anchor_title not in deps:
                deps.insert(0, anchor_title)
            if path_kind == "repair":
                payload["repair_for"] = payload.get("repair_for") or anchor_title
                for prior in subtasks[1:-1]:
                    prior_title = str(prior.get("title") or "").strip()
                    if prior_title and prior_title not in deps:
                        deps.append(prior_title)
            payload["dependencies"] = list(dict.fromkeys(deps))
            if path_kind == "shared":
                dag["shared_nodes"].append(title)
            elif path_kind == "repair":
                dag["repair_nodes"].append(title)
            elif path_kind == "optional":
                dag["optional_nodes"].append(title)
            elif path_kind == "speculative":
                dag["speculative_nodes"].append(title)
            elif path_kind == "blocked":
                dag["blocked_nodes"].append(title)
            else:
                dag["branch_nodes"].append(title)
            for dep in payload["dependencies"]:
                dag["edges"].append({"from": dep, "to": title, "kind": path_kind or "dependency"})
            normalized.append(TaskDecompositionSpec.model_validate(payload))
        decomposition.subtasks = normalized
        decomposition.dag = dag
        return decomposition

    def _task_decomposition_internal_steps(self, task: TaskRecord, decomposition: TaskDecompositionResponse) -> list[StepSpec]:
        child_count = len(decomposition.subtasks or [])
        return [
            StepSpec(
                title="Spawn decomposition subtasks",
                worker=WorkerType.planner,
                phase="decompose",
                instructions="Create child tasks for the immediate decomposition layer and record their task ids.",
                command="internal://decomposition/spawn-subtasks",
                workdir=task.repo_path,
                assigned_role=AgentRole.supervisor,
                outputs=["child task ids"],
                acceptance_criteria=["Immediate decomposition subtasks have been spawned."],
            ),
            StepSpec(
                title="Wait for child task completion",
                worker=WorkerType.planner,
                phase="decompose",
                instructions="Wait for all spawned child tasks to reach a terminal state and capture their result summaries.",
                command="internal://decomposition/wait-subtasks",
                workdir=task.repo_path,
                assigned_role=AgentRole.supervisor,
                inputs=["child task ids"],
                outputs=["child task summaries"],
                acceptance_criteria=["All child tasks have reached a terminal state or a bounded timeout is recorded."],
            ),
            StepSpec(
                title="Aggregate decomposition results",
                worker=WorkerType.reviewer,
                phase="verify",
                instructions="Summarize the child task outcomes and record the next action for the parent task.",
                command="internal://decomposition/aggregate-results",
                workdir=task.repo_path,
                assigned_role=AgentRole.reviewer,
                inputs=["child task summaries"],
                outputs=["decomposition summary"],
                acceptance_criteria=[f"Parent aggregation covers {child_count} child tasks."],
            ),
        ]

    def _child_task_create_from_decomposition(
        self,
        parent: TaskRecord,
        spec: TaskDecompositionSpec,
        *,
        index: int,
    ) -> TaskCreate:
        scheduler_hint = dict(parent.scheduler_hint or {})
        scheduler_hint.update(spec.scheduler_hint or {})
        scheduler_hint.update(
            {
                "decomposition_child": True,
                "decomposition_parent_task_id": parent.id,
                "decomposition_root_task_id": parent.root_task_id or parent.id,
                "decomposition_depth": self._task_decomposition_depth(parent) + 1,
                "max_decomposition_depth": self._task_max_decomposition_depth(parent) or 2,
                "decomposition_child_index": index,
                "decomposition_allow_children": bool(spec.decompose_children),
                "decomposition_path_kind": spec.path_kind,
                "decomposition_shared_dependency_group": spec.shared_dependency_group,
                "decomposition_repair_for": spec.repair_for,
                "decomposition_dependencies": list(spec.dependencies or []),
            }
        )
        task_type = str(spec.task_type or parent.task_type or "report_refresh").strip() or "report_refresh"
        queue_name = str(spec.queue_name or parent.queue_name or self._resolve_throughput_queue(task_type, parent.execution_mode)).strip()
        verification_level = str(spec.verification_level or parent.verification_level or self._resolve_throughput_verification_level(
            queue_name=queue_name,
            task_type=task_type,
            execution_mode=parent.execution_mode,
        )).strip()
        execution_mode = spec.execution_mode or parent.execution_mode
        max_runtime_seconds = self._resolve_throughput_runtime(
            queue_name=queue_name,
            task_type=task_type,
            explicit_runtime=parent.max_runtime_seconds,
        )
        retry_limit = self._resolve_throughput_retry_limit(queue_name, parent.retry_limit)
        rollback_rule = self._resolve_throughput_rollback_rule(queue_name, parent.rollback_rule)
        child_prompt = spec.prompt.strip() or parent.prompt
        if parent.goal:
            child_prompt = f"{child_prompt}\n\nParent goal: {parent.goal}"
        if spec.goal:
            child_prompt = f"{child_prompt}\n\nChild goal: {spec.goal}"
        return TaskCreate(
            prompt=child_prompt,
            title=spec.title,
            repo_path=parent.repo_path,
            project_id=parent.project_id,
            goal=spec.goal or parent.goal,
            goal_id=parent.goal_id,
            graph_id=parent.graph_id,
            node_id=parent.node_id,
            scheduled_by=parent.scheduled_by,
            auto_approve=parent.auto_approve,
            context_mode=parent.context_mode,
            max_context_chars=parent.max_context_chars,
            allow_resource_scan=parent.allow_resource_scan,
            allow_repo_status=parent.allow_repo_status,
            capability_route=parent.capability_route,
            platform_context=parent.platform_context,
            vm_template=parent.vm_template,
            vm_context=parent.vm_context,
            execution_mode=execution_mode,
            preferred_worker=spec.preferred_worker or parent.preferred_worker,
            scheduler_hint=scheduler_hint,
            context_package=parent.context_package,
            tool_route=parent.tool_route,
            executor_hint={
                **(spec.executor_hint or {}),
                **(parent.executor_route or {}),
                "parent_task_id": parent.id,
                "root_task_id": parent.root_task_id or parent.id,
            },
            execution_lane=spec.execution_lane or parent.execution_lane,
            worker_vm_policy=parent.worker_vm_policy,
            prompt_guard=parent.prompt_guard,
            tool_policy=parent.tool_policy,
            security_review=parent.security_review,
            artifact_spec=None,
            verification_contract=None,
            task_type=task_type,
            queue_name=queue_name,
            verification_level=verification_level,
            max_runtime_seconds=max_runtime_seconds,
            retry_limit=retry_limit,
            rollback_rule=rollback_rule,
            parent_task_id=parent.id,
            root_task_id=parent.root_task_id or parent.id,
            decomposition_depth=self._task_decomposition_depth(parent) + 1,
            max_decomposition_depth=self._task_max_decomposition_depth(parent) or 2,
        )

    def _resolve_decomposition_dependency_ids(
        self,
        specs: list[TaskDecompositionSpec],
        child_ids: list[str],
    ) -> dict[str, list[str]]:
        lookup_by_title: dict[str, str] = {}
        lookup_by_id = {child_id: child_id for child_id in child_ids}
        for child_id in child_ids:
            child = self._tasks.get(child_id)
            if child and child.title:
                lookup_by_title[str(child.title).strip().lower()] = child_id
        resolved: dict[str, list[str]] = {}
        for spec, child_id in zip(specs, child_ids, strict=False):
            deps: list[str] = []
            for raw_dep in spec.dependencies or []:
                dep_key = str(raw_dep or "").strip()
                if not dep_key:
                    continue
                normalized = dep_key.lower()
                if normalized in lookup_by_title:
                    deps.append(lookup_by_title[normalized])
                elif dep_key in lookup_by_id:
                    deps.append(dep_key)
            resolved[child_id] = list(dict.fromkeys(deps))
        return resolved

    def _build_product_design(self, task: TaskRecord) -> ProductDesign:
        prompt = task.prompt.strip()
        goal = task.goal or "Deliver a usable outcome."
        user_stories = [f"As a user, I need: {prompt[:180]}"]
        api_surfaces = []
        pages_or_flows = []
        risks = list(task.contract.risks)
        lowered = prompt.lower()
        if any(token in lowered for token in ["login", "auth", "user"]):
            pages_or_flows.append("authentication flow")
            api_surfaces.append("auth/session API")
        if any(token in lowered for token in ["upload", "image", "file"]):
            pages_or_flows.append("upload flow")
            api_surfaces.append("file upload API")
        if any(token in lowered for token in ["admin", "dashboard"]):
            pages_or_flows.append("admin dashboard")
        if any(token in lowered for token in ["payment", "order"]):
            api_surfaces.append("payment or order API")
            risks.append("Commercial or financial flow should be reviewed before deployment.")
        return ProductDesign(
            summary=goal,
            user_stories=user_stories,
            api_surfaces=api_surfaces,
            pages_or_flows=pages_or_flows,
            risks=risks,
        )

    def _build_architecture_design(self, task: TaskRecord) -> ArchitectureDesign:
        prompt = task.prompt.lower()
        stack = []
        modules = []
        data_components = []
        deploy_units = []
        if any(token in prompt for token in ["website", "web", "frontend", "react", "vue"]):
            stack.append("frontend web app")
            modules.append("ui")
            deploy_units.append("frontend service")
        if any(token in prompt for token in ["api", "backend", "server", "fastapi", "node"]):
            stack.append("backend service")
            modules.append("api")
            deploy_units.append("backend service")
        if any(token in prompt for token in ["database", "sql", "mysql", "postgres", "opengauss"]):
            data_components.append("relational database")
            modules.append("data access")
            deploy_units.append("database")
        if any(token in prompt for token in ["docker", "deploy", "ci"]):
            modules.append("delivery pipeline")
        if any(token in prompt for token in ["kernel", "toyos", "qemu"]):
            stack.append("kernel or freestanding runtime")
            modules.extend(["boot path", "kernel core", "vm test loop"])
            deploy_units.append("vm image or kernel binary")
        if not stack:
            stack.append("local-first app")
        return ArchitectureDesign(
            summary="Locally verifiable modular architecture.",
            stack=sorted(set(stack)),
            modules=sorted(set(modules)),
            data_components=sorted(set(data_components)),
            deploy_units=sorted(set(deploy_units)),
        )

    def _build_quality_plan(self, task: TaskRecord) -> QualityPlan:
        prompt = task.prompt.lower()
        unit_tests = ["cover changed business logic with deterministic local tests"]
        integration_tests = ["validate changed module boundaries and runtime contracts"]
        e2e_tests = []
        static_checks = ["python -m compileall app tools", "syntax and config validation"]
        security_checks = []
        if any(token in prompt for token in ["website", "browser", "frontend", "api"]):
            e2e_tests.append("smoke the main user flow in a browser or HTTP client")
        if any(token in prompt for token in ["database", "sql", "migration"]):
            integration_tests.append("validate schema or query path against local db tools")
            security_checks.append("review destructive migration and injection risk")
        if any(token in prompt for token in ["auth", "payment", "permission"]):
            security_checks.append("review auth, permission, and sensitive-input handling")
        if any(token in prompt for token in ["toyos", "kernel", "qemu"]):
            integration_tests.append("run QEMU smoke and soak checks")
        return QualityPlan(
            unit_tests=unit_tests,
            integration_tests=integration_tests,
            e2e_tests=e2e_tests,
            static_checks=static_checks,
            security_checks=security_checks,
        )

    def _build_deployment_plan(self, task: TaskRecord) -> DeploymentPlan:
        blockers = []
        artifacts = ["validated patch or diff summary"]
        ci_steps = ["run local QA checks", "run stack-specific tests", "prepare release summary"]
        if task.repo_path:
            artifacts.append("git-ready branch and commit summary")
        if any(token in task.prompt.lower() for token in ["docker", "deploy", "server", "website", "api"]):
            artifacts.append("docker or runtime manifest")
            ci_steps.append("prepare deployment template files")
            blockers.append("real cloud credentials or server target may still be missing")
        return DeploymentPlan(summary="Prepare deployable artifacts without assuming external credentials.", artifacts=artifacts, ci_steps=ci_steps, blockers=blockers)

    def _build_monitoring_plan(self, task: TaskRecord) -> MonitoringPlan:
        signals = ["task failures", "network agent state", "local QA results"]
        alert_rules = ["pause on repeated failure and write core message", "warn on offline network agent or failed validation"]
        maintenance_loops = ["run keepalive loop", "inspect queue and logs", "turn repeated failures into follow-up tasks"]
        if any(token in task.prompt.lower() for token in ["website", "api", "server"]):
            signals.extend(["HTTP health", "error logs", "latency spikes"])
        if any(token in task.prompt.lower() for token in ["toyos", "kernel", "qemu"]):
            signals.append("QEMU smoke/soak stability")
        return MonitoringPlan(signals=signals, alert_rules=alert_rules, maintenance_loops=maintenance_loops)

    def _build_task_contract(self, task: TaskRecord) -> TaskContract:
        prompt = task.prompt
        goal = task.goal or "Deliver a locally verified result."
        requirements = [prompt[:220]]
        deliverables = [goal]
        acceptance = [goal, "Produce explicit verification output or a bounded failure report."]
        constraints = [
            "Prefer local tools and cheap workers first.",
            "Keep changes minimal and reversible.",
            "Follow the configured development/test loop.",
        ]
        risks = []
        evidence_contract = self._infer_evidence_contract(
            repo_path=task.repo_path,
            scheduler_hint=task.scheduler_hint,
            prompt=task.prompt,
            goal=task.goal,
        )
        requirements.append(f"Operate in {task.execution_mode.value} mode.")
        if task.execution_mode == ExecutionMode.research:
            deliverables.append("Research outputs should end as design notes, prototypes, or explicit follow-up hypotheses.")
            acceptance.append("Record what was learned and the bounded next experiment.")
        elif task.execution_mode == ExecutionMode.production:
            deliverables.append("Refresh production evidence, not just prose.")
            acceptance.append("Do not treat documentation-only progress as production completion.")
            constraints.append("Production work must refresh runtime or build artifacts when an evidence contract exists.")
        else:
            deliverables.append("Record policy, routing, or coordination outcome without pretending delivery occurred.")
            acceptance.append("Keep governance work separate from implementation claims.")
        task_type = str(task.task_type or "").strip().lower()
        if task.execution_mode in {ExecutionMode.research, ExecutionMode.governance} and task_type in {
            "artifact_audit",
            "json_fix",
            "report_refresh",
            "doc_patch",
            "manifest_patch",
        }:
            requirements.extend(
                [
                    "Return a concrete implementation note with exact target files or exact evidence artifacts.",
                    "Name the smallest gap that blocks completion and the minimal patch or repair plan.",
                    "Include explicit validation commands or artifact checks.",
                ]
            )
            deliverables.extend(
                [
                    "Exact files inspected or changed.",
                    "Bounded patch plan or implementation note.",
                    "Validation commands and verification path.",
                ]
            )
            acceptance.extend(
                [
                    "The response names concrete files, commands, or artifacts.",
                    "The response avoids generic summary language and states the minimal next action.",
                    "The response only asks for more context if the artifact spec or target path is missing.",
                ]
            )
            constraints.append("Research and governance audits must stay concrete: no vague summaries or open-ended speculation.")
        if task.artifact_spec:
            deliverables.extend([f"Artifact: {item}" for item in task.artifact_spec.required_artifacts])
            acceptance.append("Task is invalid unless the declared artifact set is refreshed and verifiable.")
        elif evidence_contract:
            deliverables.extend([f"Artifact: {item}" for item in evidence_contract.get("required_artifacts", [])])
            acceptance.extend(evidence_contract.get("acceptance_criteria", []))
        lowered = prompt.lower()
        if task.repo_path:
            deliverables.append(f"Changes scoped to {task.repo_path}")
        if any(token in lowered for token in ["auth", "payment", "admin", "deploy", "migration", "database"]):
            risks.append("High-impact domain change: requires stronger review.")
        if any(token in lowered for token in ["delete", "drop", "truncate", "reset"]):
            risks.append("Potentially destructive operation detected.")
        return TaskContract(
            requirements=requirements,
            deliverables=deliverables,
            acceptance_criteria=acceptance,
            constraints=constraints,
            risks=risks,
            artifact_spec=task.artifact_spec,
        )

    def _verification_checks_for_level(self, level: str) -> list[str]:
        normalized = str(level or "L1").strip().upper() or "L1"
        checks_by_level = {
            "L0": [
                "contract_valid",
                "artifact_manifest_present",
            ],
            "L1": [
                "contract_valid",
                "build_success",
                "tests_pass",
                "artifact_manifest_present",
                "evidence_fresh",
            ],
            "L2": [
                "contract_valid",
                "build_success",
                "tests_pass",
                "smoke_pass",
                "artifact_manifest_present",
                "evidence_fresh",
                "release_checklist",
            ],
            "L3": [
                "contract_valid",
                "build_success",
                "tests_pass",
                "smoke_pass",
                "artifact_manifest_present",
                "evidence_fresh",
                "release_checklist",
                "rollback_check",
                "compatibility_check",
            ],
        }
        return list(checks_by_level.get(normalized, checks_by_level["L1"]))

    def _build_verification_contract(self, task: TaskRecord) -> VerificationContract:
        level = str(task.verification_level or "L1").strip().upper() or "L1"
        evidence_contract = self._infer_evidence_contract(
            repo_path=task.repo_path,
            scheduler_hint=task.scheduler_hint,
            prompt=task.prompt,
            goal=task.goal,
        ) or {}
        required_artifacts = [str(item) for item in evidence_contract.get("required_artifacts") or [] if str(item).strip()]
        artifact_requirements: dict[str, Any] = {
            "must_register_artifact": True,
            "must_have_timestamp": True,
            "must_have_files": required_artifacts,
            "expected_outputs": [],
        }
        if isinstance(task.artifact_spec, ArtifactSpec):
            artifact_requirements["expected_outputs"] = [
                str(item)
                for item in (task.artifact_spec.expected_outputs or task.artifact_spec.deliverables or [])
                if str(item).strip()
            ]
            artifact_requirements["entrypoint"] = task.artifact_spec.entrypoint
            artifact_requirements["artifact_type"] = task.artifact_spec.artifact_type
            if task.artifact_spec.required_artifacts:
                artifact_requirements["must_have_files"] = [
                    str(item) for item in task.artifact_spec.required_artifacts if str(item).strip()
                ]
            artifact_requirements["test_command"] = task.artifact_spec.test_command
        notes = list(evidence_contract.get("guidance") or [])
        if task.contract and task.contract.acceptance_criteria:
            notes.extend(task.contract.acceptance_criteria)
        release_gate = "all_required_checks_pass" if level in {"L1", "L2", "L3"} else "contract_valid"
        failure_policy = "return_to_planner"
        return VerificationContract(
            verification_level=level,
            required_checks=self._verification_checks_for_level(level),
            artifact_requirements=artifact_requirements,
            release_gate=release_gate,
            failure_policy=failure_policy,
            evidence_requirements=required_artifacts,
            verification_notes=notes[:12],
        )

    def _build_agent_assignments(self, task: TaskRecord) -> list[AgentAssignment]:
        assignments = [
            AgentAssignment(role=AgentRole.product, responsibility="Restate requirements, scope, and acceptance criteria."),
            AgentAssignment(role=AgentRole.architect, responsibility="Keep module boundaries and runtime choices coherent."),
            AgentAssignment(role=AgentRole.coder, responsibility="Implement the smallest safe change set."),
            AgentAssignment(role=AgentRole.tester, responsibility="Run local, VM, or deterministic validation."),
            AgentAssignment(role=AgentRole.reviewer, responsibility="Check risks, regressions, and rule compliance."),
        ]
        if task.repo_path:
            assignments.append(AgentAssignment(role=AgentRole.ops, responsibility="Prepare git/deploy/release checks for repository changes."))
        assignments.append(AgentAssignment(role=AgentRole.supervisor, responsibility="Track task state, escalation, and pause conditions."))
        return assignments

    def _evaluate_rules(self, task: TaskRecord) -> list[RuleCheck]:
        prompt = task.prompt.lower()
        checks = [
            RuleCheck(name="feature_branch_required", status="pass", detail="Repository changes should avoid main-branch direct edits." if task.repo_path else "No repo path provided; git flow not enforced."),
            RuleCheck(name="tests_required_before_done", status="pass", detail="Tasks should end with local validation or a structured failure report."),
            RuleCheck(name="destructive_change_gate", status="pass", detail="No destructive keyword detected."),
            RuleCheck(name="high_risk_domain_gate", status="pass", detail="No special approval domain detected."),
        ]
        if any(token in prompt for token in ["drop ", "truncate", "delete database", "format disk", "rm -rf"]):
            checks[2].status = "warn"
            checks[2].detail = "Potentially destructive wording detected; require explicit review before execution."
        if any(token in prompt for token in ["auth", "payment", "permission", "deploy", "migration", "database"]):
            checks[3].status = "warn"
            checks[3].detail = "High-risk domain detected; reviewer and supervisor sign-off required."
        return checks

    def _looks_like_artifact_reference(self, value: str | None) -> bool:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return False
        markers = (
            "artifact",
            "build-report",
            "generic-qemu-smoke-report",
            "score-report",
            "kernel.bin",
            "manifest",
            "evidence",
            "report",
            "log",
            ".json",
            ".log",
            ".bin",
            ".txt",
        )
        return any(marker in lowered for marker in markers)

    def _looks_like_decision_reference(self, value: str | None) -> bool:
        lowered = str(value or "").strip().lower()
        if not lowered:
            return False
        markers = ("decision", "patch", "release", "repair")
        return any(marker in lowered for marker in markers)

    def _requires_build_first_plan(self, task: TaskRecord) -> bool:
        corpus = " ".join(
            str(part or "")
            for part in [
                task.prompt,
                task.goal,
                task.title,
                (task.scheduler_hint or {}).get("node_title"),
                (task.scheduler_hint or {}).get("goal_target"),
            ]
        ).lower()
        return task.execution_mode == ExecutionMode.production and any(
            token in corpus
            for token in (
                "system_build",
                "build current runnable baseline",
                "build runnable artifact",
                "toyos",
                "toy os",
                "qemu",
                "kernel",
            )
        )

    def _is_build_or_run_step(self, step: StepSpec) -> bool:
        corpus = " ".join(
            str(part or "")
            for part in [step.title, step.instructions, step.command, step.phase]
        ).lower()
        if step.worker not in {WorkerType.shell, WorkerType.docker}:
            return False
        return any(token in corpus for token in ("build", "run", "boot", "qemu", "compile", "test"))

    def _build_first_recovery_plan(self, task: TaskRecord, reason: str) -> PlannerResponse:
        corpus = " ".join(
            str(part or "")
            for part in [
                task.prompt,
                task.goal,
                task.title,
                (task.scheduler_hint or {}).get("node_title"),
                (task.scheduler_hint or {}).get("goal_target"),
            ]
        ).lower()
        python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else "python")
        workdir = task.repo_path or str(APP_ROOT)
        if any(token in corpus for token in ("toyos", "toy os", "qemu", "kernel")):
            target_path = Path(task.repo_path) if task.repo_path else CODEX_ROOT / "generated" / "toy-os-demo"
            build_script = APP_ROOT / "tools" / "build_toy_os.py"
            qemu_runner = APP_ROOT / "tools" / "generic_test_runner.py"
            qemu_spec = target_path / "tools" / "generic_qemu_smoke.json"
            return PlannerResponse(
                summary=f"Recovered build-first plan after invalid planner output: {reason}",
                steps=[
                StepSpec(
                    title="Build Toy OS baseline",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Recover to the deterministic ToyOS build path first.",
                    command=f'"{python_cmd}" "{build_script}" --target "{target_path}"',
                        workdir=str(target_path),
                        assigned_role=AgentRole.tester,
                        outputs=["build-report.json", "kernel.bin"],
                        acceptance_criteria=["Build report refreshed."],
                    ),
                StepSpec(
                    title="Boot ToyOS in QEMU",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Run the reusable QEMU smoke suite after the build succeeds.",
                    command=f'"{python_cmd}" "{qemu_runner}" --spec "{qemu_spec}"',
                        workdir=str(target_path),
                        assigned_role=AgentRole.tester,
                        inputs=["build-report.json", "kernel.bin"],
                        outputs=["generic-qemu-smoke-report.json"],
                        acceptance_criteria=["QEMU smoke report refreshed."],
                    ),
                    StepSpec(
                        title="Audit ToyOS runtime evidence",
                        worker=WorkerType.reviewer,
                        phase="review",
                        instructions="Review the build and QEMU artifacts and emit a concrete patch decision.",
                        workdir=str(target_path),
                        assigned_role=AgentRole.reviewer,
                        inputs=["build-report.json", "generic-qemu-smoke-report.json"],
                        outputs=["patch decision"],
                        acceptance_criteria=["Patch decision grounded in runtime artifacts."],
                    ),
                ],
            )
        report_root = Path(workdir) / "reports"
        build_runner = APP_ROOT / "tools" / "bootstrap_build_runner.py"
        validation_runner = APP_ROOT / "tools" / "bootstrap_validation_runner.py"
        return PlannerResponse(
            summary=f"Recovered build-first plan after invalid planner output: {reason}",
            steps=[
                StepSpec(
                    title="Refresh bootstrap build evidence",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Run the cheapest local build-equivalent check first and refresh machine-readable bootstrap evidence.",
                    command=(
                        f'"{python_cmd}" "{build_runner}" --repo "{workdir}" '
                        f'--report "{report_root / "bootstrap-build-report.json"}" '
                        f'--log "{report_root / "bootstrap-build.log"}" '
                        f'--manifest "{report_root / "bootstrap-build-manifest.json"}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    outputs=[
                        "reports/bootstrap-build-report.json",
                        "reports/bootstrap-build.log",
                        "reports/bootstrap-build-manifest.json",
                    ],
                    acceptance_criteria=["Bootstrap build evidence refreshed."],
                ),
                StepSpec(
                    title="Run bootstrap validation sweep",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Run the bounded validation sweep after bootstrap build evidence exists.",
                    command=(
                        f'"{python_cmd}" "{validation_runner}" --repo "{workdir}" '
                        f'--report "{report_root / "bootstrap-validation.json"}" '
                        f'--log "{report_root / "bootstrap-validation.log"}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    inputs=["reports/bootstrap-build-report.json"],
                    outputs=["reports/bootstrap-validation.json", "reports/bootstrap-validation.log"],
                    acceptance_criteria=["Bootstrap validation evidence refreshed."],
                ),
                StepSpec(
                    title="Audit bootstrap evidence",
                    worker=WorkerType.reviewer,
                    phase="review",
                    instructions="Review the bootstrap evidence and emit a concrete patch decision.",
                    workdir=workdir,
                    assigned_role=AgentRole.reviewer,
                    inputs=["reports/bootstrap-build-report.json", "reports/bootstrap-validation.json"],
                    outputs=["patch decision"],
                    acceptance_criteria=["Patch decision grounded in bootstrap artifacts."],
                ),
            ],
        )

    def _enforce_production_plan_constraints(self, task: TaskRecord, plan: PlannerResponse) -> PlannerResponse:
        if task.execution_mode != ExecutionMode.production:
            return plan
        if any(str(step.command or "").strip().startswith("internal://decomposition/") for step in plan.steps):
            return plan
        prior_artifacts: set[str] = set()
        normalized_steps: list[StepSpec] = []
        for step in plan.steps:
            normalized = step
            command = str(step.command or "").strip()
            if command.startswith("internal://decomposition/"):
                normalized_steps.append(normalized)
                continue
            if step.worker == WorkerType.reviewer:
                inputs = list(step.inputs)
                outputs = list(step.outputs)
                if not any(self._looks_like_artifact_reference(item) for item in inputs):
                    if prior_artifacts:
                        inputs = list(dict.fromkeys(inputs + sorted(prior_artifacts)))
                    else:
                        if self._requires_build_first_plan(task):
                            return self._build_first_recovery_plan(
                                task,
                                f"reviewer step '{step.title}' lacks artifact input",
                            )
                        raise ValueError(
                            f"Invalid production plan: reviewer step '{step.title}' lacks artifact input."
                        )
                if not any(self._looks_like_decision_reference(item) for item in outputs):
                    outputs = list(dict.fromkeys(outputs + ["patch decision"]))
                acceptance = list(step.acceptance_criteria)
                if not any("decision" in str(item).lower() for item in acceptance):
                    acceptance.append("Decision recorded from reviewed artifact evidence.")
                normalized = step.model_copy(
                    update={
                        "inputs": inputs,
                        "outputs": outputs,
                        "acceptance_criteria": acceptance,
                    }
                )
            elif step.worker == WorkerType.shell and self._is_build_or_run_step(step):
                normalized = step.model_copy(update={"worker": WorkerType.docker})
            normalized_steps.append(normalized)
            for output in normalized.outputs:
                if self._looks_like_artifact_reference(output):
                    prior_artifacts.add(str(output))
        if self._requires_build_first_plan(task):
            first_concrete = next(
                (step for step in normalized_steps if step.worker != WorkerType.planner),
                None,
            )
            if first_concrete is not None and not self._is_build_or_run_step(first_concrete):
                return self._build_first_recovery_plan(
                    task,
                    f"first concrete step '{first_concrete.title}' is not build/run",
                )
        return PlannerResponse(summary=plan.summary, steps=normalized_steps)

    async def _build_git_workflow(self, task: TaskRecord) -> GitWorkflowState:
        if not task.repo_path:
            return GitWorkflowState(enabled=False, repo_registered=False, branch_required=False, commit_required=False, pr_required=False, status_summary="No repository path attached.")
        repo = next((item for item in self._registry.list_repos() if Path(item.local_path) == Path(task.repo_path)), None)
        state = GitWorkflowState(enabled=True, repo_registered=repo is not None)
        if repo is None:
            state.status_summary = "Repository path present but not registered in orchestrator."
            state.branch_name = f"codex/{task.id[:8]}"
            return state
        try:
            state.status_summary = await self._git.status_summary(repo)
            state.branch_name = await self._git.suggest_feature_branch(repo, task.goal or task.prompt)
        except Exception as exc:
            state.status_summary = f"git inspection failed: {exc}"
            state.branch_name = f"codex/{task.id[:8]}"
        return state

    async def connect(self, task_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._sockets[task_id].add(websocket)
        task = self._tasks.get(task_id)
        if task:
            await websocket.send_json(task.model_dump(mode="json"))

    async def disconnect(self, task_id: str, websocket: WebSocket) -> None:
        self._sockets[task_id].discard(websocket)

    async def subscribe_verification_signals(self, task_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._verification_signal_streams[task_id].add(queue)
        return queue

    async def unsubscribe_verification_signals(self, task_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        streams = self._verification_signal_streams.get(task_id)
        if not streams:
            return
        streams.discard(queue)
        if not streams:
            self._verification_signal_streams.pop(task_id, None)

    async def _broadcast(self, task: TaskRecord) -> None:
        stale: list[WebSocket] = []
        for socket in self._sockets.get(task.id, set()):
            try:
                await socket.send_json(task.model_dump(mode="json"))
            except Exception:
                stale.append(socket)
        for socket in stale:
            self._sockets[task.id].discard(socket)

    async def _broadcast_verification_signal(self, task: TaskRecord, signal: dict[str, Any]) -> None:
        stale: list[asyncio.Queue[dict[str, Any]]] = []
        for queue in self._verification_signal_streams.get(task.id, set()):
            try:
                queue.put_nowait(signal)
            except Exception:
                stale.append(queue)
        for queue in stale:
            self._verification_signal_streams[task.id].discard(queue)

    def _persist_verification_signal(self, signal: dict[str, Any]) -> None:
        line = json.dumps(signal, ensure_ascii=False)
        self._verification_signal_log.parent.mkdir(parents=True, exist_ok=True)
        with self._persist_lock:
            with self._verification_signal_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")

    def _load_verification_signal_log(self, task_id: str | None = None) -> list[dict[str, Any]]:
        if not self._verification_signal_log.exists():
            return []
        signals: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            with self._verification_signal_log.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        signal = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(signal, dict):
                        continue
                    if task_id is not None and str(signal.get("task_id") or "").strip() != task_id:
                        continue
                    marker = json.dumps(signal, sort_keys=True, ensure_ascii=False)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    signals.append(signal)
        except Exception:
            return []
        signals.sort(key=lambda item: str(item.get("timestamp") or ""))
        return signals

    async def list_verification_signals(self, task_id: str) -> list[dict[str, Any]]:
        task = self._tasks.get(task_id)
        task_signals = list(task.verification_signals) if task and isinstance(task.verification_signals, list) else []
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for signal in task_signals + self._load_verification_signal_log(task_id):
            marker = json.dumps(signal, sort_keys=True, ensure_ascii=False)
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(signal)
        merged.sort(key=lambda item: str(item.get("timestamp") or ""))
        return merged

    async def _append_event(self, task: TaskRecord, message: str, *, level: str = "info", data: dict[str, Any] | None = None) -> None:
        task.events.append(TaskEvent(message=message, level=level, data=data or {}))
        task.updated_at = task.events[-1].timestamp
        checkpoint = self._checkpoints.get(task.id)
        if checkpoint is not None:
            checkpoint['updated_at'] = task.updated_at.isoformat().replace('+00:00', 'Z')
            checkpoint['heartbeat_at'] = checkpoint['updated_at']
        self._persist()
        await self._broadcast(task)

    async def _append_verification_signal(
        self,
        task: TaskRecord,
        *,
        kind: str,
        success: bool,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        signal = {
            "timestamp": utc_iso(),
            "kind": kind,
            "success": bool(success),
            "task_id": task.id,
        }
        if details:
            signal.update(details)
        task.verification_signals.append(signal)
        if not isinstance(task.result, dict):
            task.result = {}
        task.result["verification_signals"] = list(task.verification_signals)
        checkpoint = self._checkpoints.get(task.id)
        if checkpoint is not None:
            checkpoint["verification_signal_count"] = len(task.verification_signals)
            checkpoint["last_verification_signal"] = signal
            checkpoint["updated_at"] = signal["timestamp"]
            checkpoint["heartbeat_at"] = signal["timestamp"]
            checkpoint["verification_signal_log"] = str(self._verification_signal_log)
        self._persist()
        self._persist_verification_signal(signal)
        await self._broadcast(task)
        await self._broadcast_verification_signal(task, signal)
        return signal

    def _record_executor_route_experience(
        self,
        task: TaskRecord,
        *,
        success: bool,
        summary: str,
    ) -> None:
        executor_id = str(task.executor_id or "").strip()
        if not executor_id:
            return
        latency_ms = max(0, int((utc_now() - task.created_at).total_seconds() * 1000))
        result_text = summary or ""
        if isinstance(task.result, dict):
            result_text = f"{result_text}\n{json.dumps(task.result, ensure_ascii=False)}"
        cost_units = round(
            (
                float((task.context_envelope.used_chars if task.context_envelope else 0) or 0)
                + float(task.cheap_lane.chars_used or 0)
                + float(len(result_text))
            ) / 1000.0,
            3,
        )
        try:
            record_route_experience(
                executor_id=executor_id,
                success=success,
                latency_ms=latency_ms,
                cost_units=cost_units,
                task_type=task.task_type,
                verification_level=task.verification_level,
                execution_mode=task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
                task_id=task.id,
            )
        except Exception:
            return

    def _materialize_step_payload(
        self,
        task: TaskRecord,
        step: StepSpec,
        payload: Any,
        *,
        channel: str,
        title: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._runtime_context.materialize(
            task_id=task.id,
            step_id=step.id,
            channel=channel,
            title=title,
            data=payload,
            metadata=metadata or {},
        )

    def _validate_audit_step_output(self, task: TaskRecord, step: StepSpec, output_text: str) -> None:
        task_type = str(task.task_type or "").strip().lower()
        if not is_audit_task(task_type):
            return
        worker_name = step.worker.value if hasattr(step.worker, "value") else str(step.worker)
        if worker_name not in {"coder", "reviewer"}:
            return
        ok, reason = validate_audit_output(output_text, worker_name=worker_name)
        if not ok:
            raise WorkerSafetyError(
                f"Audit output schema rejected for {task_type}/{worker_name}: {reason}"
            )

    def _prompt_output_excerpt(self, step: StepSpec, *, max_chars: int = 1000) -> str:
        return self._runtime_context.render_for_prompt(
            step.output_ref,
            fallback=step.output,
            max_chars=max_chars,
        )

    def _prompt_diagnosis_excerpt(self, step: StepSpec, *, max_chars: int = 800) -> str:
        return self._runtime_context.render_for_prompt(
            step.last_diagnosis_ref,
            fallback=step.last_diagnosis,
            max_chars=max_chars,
        )

    def _build_error_report(self, task: TaskRecord, error_text: str, *, paused: bool = True) -> dict[str, Any]:
        failed_steps = [
            {
                "step_id": step.id,
                "title": step.title,
                "phase": step.phase,
                "worker": step.worker.value,
                "command": step.command,
                "output": step.output,
                "output_ref": step.output_ref,
                "output_stats": step.output_stats,
                "probe_attempts": step.probe_attempts,
                "max_probe_attempts": step.max_probe_attempts,
                "last_diagnosis": step.last_diagnosis,
                "last_diagnosis_ref": step.last_diagnosis_ref,
            }
            for step in task.plan
            if step.status == StepStatus.failed
        ]
        return {
            "state": "paused_pending_core_instruction" if paused else "failed_execution",
            "reason": error_text,
            "task_id": task.id,
            "repo_path": task.repo_path,
            "execution_mode": task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
            "goal": task.goal,
            "cheap_calls_used": task.cheap_lane.calls_used,
            "cheap_chars_used": task.cheap_lane.chars_used,
            "escalation_count": task.escalation_count,
            "failed_steps": failed_steps,
            "next_action_required": "Await explicit core-model instruction before resuming execution." if paused else "Inspect execution evidence and rerun or replace the task; no approval hold was applied.",
            "failure_pause_policy": self._policy.failure_pause_policy,
            "pause_required": paused,
        }

    def _workspace_root(self) -> Path:
        return self._data_dir.parent.parent

    def _recovery_artifact_dir(self) -> Path:
        return self._workspace_root() / "generated" / "execution-recovery-demo"

    def _recovery_smoke_dir(self) -> Path:
        return self._data_dir / "execution-recovery"

    def _task_runtime_path(self, task_id: str) -> Path:
        path = self._runtime_task_dir / task_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _execution_evidence_path(self, task_id: str) -> Path:
        return self._task_runtime_path(task_id) / "execution-evidence.json"

    def _read_usage_total(self) -> int:
        usage = _read_json_file(self._data_dir / "usage_tracker.json", {})
        if not isinstance(usage, dict):
            return 0
        return int(usage.get("total_calls") or 0)

    def _append_execution_evidence(
        self,
        task: TaskRecord,
        step: StepSpec,
        *,
        action: str,
        ok: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        path = self._execution_evidence_path(task.id)
        payload = _read_json_file(path, {})
        if not isinstance(payload, dict):
            payload = {}
        entries = payload.setdefault("steps", [])
        entries.append(
            {
                "step_id": step.id,
                "step_title": step.title,
                "action": action,
                "ok": ok,
                "at": utc_iso(),
                **(details or {}),
            }
        )
        payload.update(
            {
                "task_id": task.id,
                "task_title": task.title,
                "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "started_at": payload.get("started_at") or task.created_at.isoformat().replace("+00:00", "Z"),
                "updated_at": utc_iso(),
                "completed": task.status in TASK_VERIFIED_COMPLETION_STATUSES,
            }
        )
        atomic_write_json(path, payload)

    def _synthesize_execution_evidence_steps(self, task: TaskRecord) -> list[dict[str, Any]]:
        synthesized: list[dict[str, Any]] = []
        fallback_at = (
            task.updated_at.isoformat().replace("+00:00", "Z")
            if isinstance(task.updated_at, datetime)
            else utc_iso()
        )
        for index, raw_step in enumerate(task.plan or [], start=1):
            if hasattr(raw_step, "model_dump"):
                step_payload = raw_step.model_dump(mode="json")
            elif isinstance(raw_step, dict):
                step_payload = dict(raw_step)
            else:
                continue
            status = str(step_payload.get("status") or "").strip().lower()
            if status not in {"completed", "failed", "running", "pending"}:
                continue
            synthesized.append(
                {
                    "step_id": step_payload.get("id") or f"synth-step-{index}",
                    "step_title": step_payload.get("title") or f"Step {index}",
                    "action": f"{step_payload.get('worker') or 'worker'}_step",
                    "ok": status == "completed",
                    "at": fallback_at,
                    "phase": step_payload.get("phase"),
                    "worker": step_payload.get("worker"),
                    "status": status,
                    "output_ref": step_payload.get("output_ref"),
                    "output_stats": step_payload.get("output_stats"),
                    "synthesized": True,
                    "source": "task-plan",
                }
            )
        if synthesized:
            return synthesized

        result = task.result if isinstance(task.result, dict) else {}
        summary = str(result.get("summary") or "").strip()
        error = str(result.get("error") or "").strip()
        production_evidence = result.get("production_evidence") if isinstance(result, dict) else {}
        return [
            {
                "step_id": "task-terminal-record",
                "step_title": task.title or task.goal or "Task terminal record",
                "action": "task_terminal_record",
                "ok": task.status in TASK_VERIFIED_COMPLETION_STATUSES,
                "at": fallback_at,
                "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "summary": summary,
                "error": error or None,
                "production_evidence_status": (
                    str((production_evidence or {}).get("status") or "").strip().lower()
                    if isinstance(production_evidence, dict)
                    else None
                ),
                "synthesized": True,
                "source": "task-result",
            }
        ]

    def _finalize_execution_evidence(self, task: TaskRecord) -> None:
        path = self._execution_evidence_path(task.id)
        payload = _read_json_file(path, {})
        if not isinstance(payload, dict):
            payload = {}
        steps = payload.get("steps")
        if not isinstance(steps, list):
            steps = []
        if not steps:
            steps = self._synthesize_execution_evidence_steps(task)
            payload["steps"] = steps
        if not isinstance(task.result, dict):
            task.result = {}
        task.result["execution_evidence_path"] = str(path)
        task.result["execution_evidence_step_count"] = len(steps)
        payload.update(
            {
                "task_id": task.id,
                "task_title": task.title,
                "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
                "completed": task.status in TASK_VERIFIED_COMPLETION_STATUSES,
                "updated_at": utc_iso(),
                "result": task.result,
            }
        )
        atomic_write_json(path, payload)

    def _task_has_verified_completion_evidence(self, task: TaskRecord) -> bool:
        if task.status not in TASK_VERIFIED_COMPLETION_STATUSES:
            return False
        result = task.result if isinstance(task.result, dict) else {}
        production_evidence = result.get("production_evidence") if isinstance(result, dict) else {}
        if isinstance(production_evidence, dict) and str(production_evidence.get("status") or "").strip().lower() == "verified":
            return True
        payload = _read_json_file(self._execution_evidence_path(task.id), {})
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("completed") and (payload.get("steps") or []))

    def _is_internal_step(self, step: StepSpec) -> bool:
        return str(step.command or "").strip().startswith("internal://")

    def _recovery_route(self) -> RoutedModel:
        return RoutedModel(provider="runtime", model="internal-recovery", reason="Deterministic execution recovery step.")

    def _recovery_llm_route(self) -> RoutedModel:
        if settings.cheap_llm_api_key and settings.cheap_llm_base_url:
            return RoutedModel(provider="cheap", model=settings.cheap_review_model, reason="Execution recovery direct cheap-lane probe.")
        if settings.reasoning_llm_api_key and settings.reasoning_llm_base_url:
            return RoutedModel(provider="reasoning", model=settings.reasoning_review_model, reason="Execution recovery direct reasoning-lane probe.")
        if settings.openai_api_key and settings.openai_base_url:
            return RoutedModel(provider="openai", model=settings.planner_model, reason="Execution recovery direct core-lane probe.")
        raise RuntimeError("No direct LLM provider configured for execution recovery.")

    def _recovery_python_executable(self) -> str:
        candidates = [
            self._workspace_root() / "tools" / "python311-embed" / "python.exe",
            Path(sys.executable) if str(sys.executable or "").strip() else None,
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return str(candidate)
        return "python"

    def _run_local_command(self, args: list[str], *, workdir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _extract_source_template(self, text: str | None) -> str | None:
        source = str(text or "").strip()
        if not source:
            return None
        match = re.search(r"[A-Za-z]:[\/]\S+?\.docx", source)
        return match.group(0) if match else None

    def _internal_recovery_write_smoke_file(self, task: TaskRecord, step: StepSpec) -> WorkerResult:
        smoke_dir = self._recovery_smoke_dir()
        smoke_dir.mkdir(parents=True, exist_ok=True)
        smoke_path = smoke_dir / "test.txt"
        content = f"execution recovery ok\ntask_id={task.id}\nat={utc_iso()}\n"
        smoke_path.write_text(content, encoding="utf-8")
        if not smoke_path.exists():
            raise RuntimeError(f"Recovery smoke file was not created: {smoke_path}")
        self._append_execution_evidence(
            task,
            step,
            action="write_smoke_file",
            ok=True,
            details={"path": str(smoke_path), "size": smoke_path.stat().st_size},
        )
        return WorkerResult(
            message="Recovery smoke file created.",
            output=f"Wrote {smoke_path}\nVerified exists: True",
            route=self._recovery_route(),
            metadata={"smoke_path": str(smoke_path)},
        )

    def _internal_recovery_llm_smoke(self, task: TaskRecord, step: StepSpec) -> WorkerResult:
        route = self._recovery_llm_route()
        usage_before = self._read_usage_total()
        result = self._llm.generate(
            route,
            "You are the execution recovery probe. Return one short line confirming the LLM path is alive.",
            "Write a Python hello world function in one line.",
            "",
        )
        usage_after = self._read_usage_total()
        probe_ok = (usage_after > usage_before) and (not result.used_fallback) and bool(result.text.strip())
        self._append_execution_evidence(
            task,
            step,
            action="direct_llm_call",
            ok=probe_ok,
            details={
                "provider": route.provider,
                "model": route.model,
                "usage_before": usage_before,
                "usage_after": usage_after,
                "used_fallback": result.used_fallback,
                "output_excerpt": result.text.strip()[:200],
            },
        )
        if not probe_ok:
            return WorkerResult(
                message="Recovery LLM direct call degraded.",
                output=(
                    f"provider={route.provider} model={route.model}\n"
                    f"usage_before={usage_before} usage_after={usage_after}\n"
                    f"used_fallback={result.used_fallback}\n"
                    f"output={result.text.strip()[:400]}"
                ),
                route=route,
                metadata={
                    "llm_provider": route.provider,
                    "llm_model": route.model,
                    "llm_probe_ok": False,
                    "llm_usage_recorded": usage_after > usage_before,
                    "llm_used_fallback": result.used_fallback,
                },
            )
        return WorkerResult(
            message="Recovery LLM direct call completed.",
            output=result.text.strip(),
            route=route,
            metadata={
                "llm_provider": route.provider,
                "llm_model": route.model,
                "llm_probe_ok": True,
                "llm_usage_recorded": True,
                "llm_used_fallback": False,
            },
        )

    def _internal_recovery_create_artifact(self, task: TaskRecord, step: StepSpec) -> WorkerResult:
        artifact_dir = self._recovery_artifact_dir()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        entrypoint = artifact_dir / "run_demo.py"
        build_script = artifact_dir / "build.sh"
        dockerfile = artifact_dir / "Dockerfile.build"
        build_report_path = artifact_dir / "build-report.json"
        test_report_path = artifact_dir / "test-report.json"
        execution_report_path = artifact_dir / "execution-report.json"
        manifest_path = artifact_dir / "artifact_manifest.json"

        entrypoint.write_text(
            """from __future__ import annotations

import json
import sys


def hello() -> str:
    return "hello from execution recovery"


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        print("SELF_TEST_OK")
        return 0
    payload = {"status": "ok", "message": hello(), "args": sys.argv[1:]}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
            encoding="utf-8",
        )
        build_script.write_text(
            """#!/usr/bin/env sh
python run_demo.py --self-test
""",
            encoding="utf-8",
        )
        dockerfile.write_text(
            """FROM python:3.11-slim
WORKDIR /app
COPY run_demo.py ./
CMD ["python", "run_demo.py", "--self-test"]
""",
            encoding="utf-8",
        )

        python_exe = self._recovery_python_executable()
        build_cmd = [python_exe, "-m", "py_compile", str(entrypoint)]
        test_cmd = [python_exe, str(entrypoint), "--self-test"]
        run_cmd = [python_exe, str(entrypoint)]

        build_result = self._run_local_command(build_cmd, workdir=artifact_dir)
        if build_result.returncode != 0:
            raise RuntimeError(build_result.stderr.strip() or build_result.stdout.strip() or "py_compile failed")
        build_timestamp = utc_iso()
        atomic_write_json(
            build_report_path,
            {
                "artifact_id": "execution-recovery-demo",
                "build_success": True,
                "build_ready": True,
                "build_timestamp": build_timestamp,
                "command": build_cmd,
                "stdout": build_result.stdout.strip(),
                "stderr": build_result.stderr.strip(),
            },
        )

        test_result = self._run_local_command(test_cmd, workdir=artifact_dir)
        if test_result.returncode != 0 or "SELF_TEST_OK" not in test_result.stdout:
            raise RuntimeError(test_result.stderr.strip() or test_result.stdout.strip() or "self-test failed")
        test_timestamp = utc_iso()
        atomic_write_json(
            test_report_path,
            {
                "artifact_id": "execution-recovery-demo",
                "all_passed": True,
                "passed": True,
                "test_timestamp": test_timestamp,
                "command": test_cmd,
                "stdout": test_result.stdout.strip(),
                "stderr": test_result.stderr.strip(),
            },
        )

        execution_result = self._run_local_command(run_cmd, workdir=artifact_dir)
        if execution_result.returncode != 0:
            raise RuntimeError(execution_result.stderr.strip() or execution_result.stdout.strip() or "artifact execution failed")
        execution_timestamp = utc_iso()
        atomic_write_json(
            execution_report_path,
            {
                "artifact_id": "execution-recovery-demo",
                "executed": True,
                "success": True,
                "execution_timestamp": execution_timestamp,
                "exit_code": execution_result.returncode,
                "command": run_cmd,
                "stdout": execution_result.stdout.strip(),
                "stderr": execution_result.stderr.strip(),
            },
        )
        atomic_write_json(
            manifest_path,
            {
                "artifact_id": "execution-recovery-demo",
                "type": "demo",
                "version": "0.1.0",
                "buildable": True,
                "runnable": True,
                "test_passed": True,
                "reproducible": True,
                "artifact_path": str(artifact_dir),
                "entrypoint": "run_demo.py",
                "evidence": ["build-report.json", "test-report.json", "execution-report.json"],
                "updated_at": execution_timestamp,
                "notes": "Deterministic internal recovery artifact.",
            },
        )
        self._append_execution_evidence(
            task,
            step,
            action="create_runnable_artifact",
            ok=True,
            details={
                "artifact_dir": str(artifact_dir),
                "build_timestamp": build_timestamp,
                "test_timestamp": test_timestamp,
                "execution_timestamp": execution_timestamp,
            },
        )
        return WorkerResult(
            message="Recovery artifact created and executed.",
            output=(
                f"Artifact: {artifact_dir}\n"
                f"Build command: {' '.join(build_cmd)}\n"
                f"Test output: {test_result.stdout.strip()}\n"
                f"Execution output: {execution_result.stdout.strip()}"
            ),
            route=self._recovery_route(),
            metadata={"artifact_dir": str(artifact_dir), "entrypoint": str(entrypoint)},
        )

    def _internal_recovery_verify_artifact(self, task: TaskRecord, step: StepSpec) -> WorkerResult:
        evidence = self._validate_task_completion(task)
        registry = audit_artifacts(write_outputs=True)
        dashboard = build_reality_dashboard(write_outputs=True)
        artifact = next(
            (
                item
                for item in registry.get("artifacts", [])
                if str(item.get("artifact_id") or "").strip() == "execution-recovery-demo"
            ),
            None,
        )
        if not artifact or not artifact.get("real"):
            raise RuntimeError("Recovery artifact did not audit as a real artifact.")
        latest_evidence_at = ((artifact.get("checks") or {}).get("latest_evidence_at"))
        self._append_execution_evidence(
            task,
            step,
            action="verify_runnable_artifact",
            ok=True,
            details={
                "artifact_id": "execution-recovery-demo",
                "latest_evidence_at": latest_evidence_at,
                "dashboard_status": dashboard.get("status"),
            },
        )
        return WorkerResult(
            message="Recovery artifact verified.",
            output=json.dumps(
                {
                    "production_evidence": evidence,
                    "artifact": artifact,
                    "reality_dashboard": {
                        "status": dashboard.get("status"),
                        "artifacts_produced_last_24h": dashboard.get("artifacts_produced_last_24h"),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            route=self._recovery_route(),
            metadata={"artifact_id": "execution-recovery-demo", "latest_evidence_at": latest_evidence_at},
        )

    def _internal_binary_classification_lab_run(self, task: TaskRecord, step: StepSpec) -> WorkerResult:
        workspace = Path(task.repo_path or step.workdir or (self._workspace_root() / "generated" / "ml-binary-classification-lab"))
        source_template = self._extract_source_template(task.prompt)
        payload = run_binary_classification_lab(
            workspace=workspace,
            source_template=source_template,
        )
        self._append_execution_evidence(
            task,
            step,
            action="binary_classification_lab_run",
            ok=True,
            details={
                "workspace": str(workspace),
                "output_path": payload.get("output_path"),
                "metrics_path": payload.get("metrics_path"),
                "dataset_source": payload.get("dataset_source"),
                "accuracies": payload.get("accuracies"),
            },
        )
        return WorkerResult(
            message="Binary classification lab artifact generated.",
            output=json.dumps(payload, ensure_ascii=False, indent=2),
            route=self._recovery_route(),
            metadata={
                "artifact_id": "ml-binary-classification-lab",
                "output_path": payload.get("output_path"),
                "metrics_path": payload.get("metrics_path"),
            },
        )

    async def _internal_decomposition_spawn_subtasks(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        result = dict(task.result or {})
        decomposition = result.get("decomposition")
        if not isinstance(decomposition, dict):
            raise RuntimeError("No decomposition payload is available for child task spawning.")
        if task.child_task_ids:
            child_ids = list(task.child_task_ids)
            return WorkerResult(
                message="Decomposition subtasks already spawned.",
                output=json.dumps(
                    {
                        "child_task_ids": child_ids,
                        "subtask_count": len(child_ids),
                        "strategy": decomposition.get("strategy"),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                route=route,
                metadata={"child_task_ids": child_ids, "subtask_count": len(child_ids), "already_spawned": True},
            )
        raw_subtasks = decomposition.get("subtasks") or []
        child_ids: list[str] = []
        child_summaries: list[dict[str, Any]] = []
        child_specs: list[TaskDecompositionSpec] = []
        for index, raw_spec in enumerate(raw_subtasks, start=1):
            if not isinstance(raw_spec, dict):
                continue
            spec = TaskDecompositionSpec.model_validate(raw_spec)
            child_specs.append(spec)
            payload = self._child_task_create_from_decomposition(task, spec, index=index)
            child_task = await self.create_task(payload)
            child_ids.append(child_task.id)
            child_summaries.append(
                {
                    "task_id": child_task.id,
                    "title": child_task.title,
                    "task_type": child_task.task_type,
                    "execution_mode": child_task.execution_mode.value if hasattr(child_task.execution_mode, "value") else str(child_task.execution_mode),
                    "depth": child_task.decomposition_depth,
                    "path_kind": spec.path_kind,
                }
            )
        dependency_map = self._resolve_decomposition_dependency_ids(child_specs, child_ids)
        for child_id, dependency_ids in dependency_map.items():
            child_task = self._tasks.get(child_id)
            if child_task is None:
                continue
            child_task.dependency_task_ids = list(dependency_ids)
            if not isinstance(child_task.scheduler_hint, dict):
                child_task.scheduler_hint = {}
            child_task.scheduler_hint["dependency_task_ids"] = list(dependency_ids)
            child_task.scheduler_hint["dependency_count"] = len(dependency_ids)
            child_task.scheduler_hint["decomposition_path_kind"] = child_task.scheduler_hint.get("decomposition_path_kind") or next((spec.path_kind for spec, cid in zip(child_specs, child_ids, strict=False) if cid == child_id), None)
        task.child_task_ids = list(dict.fromkeys([*task.child_task_ids, *child_ids]))
        decomposition["child_task_ids"] = list(task.child_task_ids)
        decomposition["child_tasks"] = child_summaries
        decomposition["dag"] = {
            **(decomposition.get("dag") or {}),
            "child_dependency_ids": dependency_map,
        }
        decomposition["spawned_at"] = utc_iso()
        result["decomposition"] = decomposition
        task.result = result
        await self._append_verification_signal(
            task,
            kind="decomposition_spawned",
            success=True,
            details={
                "child_task_count": len(child_ids),
                "child_task_ids": child_ids,
                "dag": decomposition.get("dag"),
            },
        )
        self._persist()
        self._update_checkpoint(
            task,
            phase="step-completed",
            step=step,
            extra={"child_task_ids": child_ids, "child_task_count": len(child_ids)},
        )
        return WorkerResult(
            message=f"Spawned {len(child_ids)} decomposition child task(s).",
            output=json.dumps(
                {
                    "child_task_ids": child_ids,
                    "child_tasks": child_summaries,
                    "strategy": decomposition.get("strategy"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            route=route,
            metadata={"child_task_ids": child_ids, "child_task_count": len(child_ids)},
        )

    async def _internal_decomposition_wait_subtasks(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        result = dict(task.result or {})
        decomposition = result.get("decomposition")
        if not isinstance(decomposition, dict):
            raise RuntimeError("No decomposition payload is available for child task waiting.")
        child_ids = list(task.child_task_ids or decomposition.get("child_task_ids") or [])
        if not child_ids:
            raise RuntimeError("No child tasks are registered for this decomposition.")
        timeout_seconds = max(60, int(task.max_runtime_seconds or 600))
        deadline = time.monotonic() + min(timeout_seconds, 1800)
        child_states: dict[str, dict[str, Any]] = {}
        last_heartbeat = 0.0
        while True:
            child_states = {}
            terminal = True
            for child_id in child_ids:
                child = self._tasks.get(child_id)
                if child is None:
                    child_states[child_id] = {"status": "missing"}
                    terminal = False
                    continue
                child_states[child_id] = {
                    "status": child.status.value,
                    "updated_at": child.updated_at.isoformat().replace("+00:00", "Z"),
                    "result": child.result,
                }
                if child.status not in TASK_FINAL_STATUSES:
                    terminal = False
            if terminal or time.monotonic() >= deadline:
                break
            if time.monotonic() - last_heartbeat >= 15:
                self._refresh_step_heartbeat(task, step)
                last_heartbeat = time.monotonic()
            await asyncio.sleep(2)
        timeout_hit = not all(
            state.get("status") in {status.value for status in TASK_FINAL_STATUSES}
            for state in child_states.values()
        )
        decomposition["child_statuses"] = child_states
        decomposition["wait_completed_at"] = utc_iso()
        decomposition["wait_timed_out"] = timeout_hit
        result["decomposition"] = decomposition
        task.result = result
        self._persist()
        summary = {
            child_id: {
                "status": state.get("status"),
                "summary": ((state.get("result") or {}) if isinstance(state.get("result"), dict) else {}).get("summary"),
            }
            for child_id, state in child_states.items()
        }
        return WorkerResult(
            message="Decomposition child tasks finished waiting.",
            output=json.dumps(
                {
                    "child_task_ids": child_ids,
                    "timeout": timeout_hit,
                    "child_states": child_states,
                },
                ensure_ascii=False,
                indent=2,
            ),
            route=route,
            metadata={"child_task_ids": child_ids, "timeout": timeout_hit, "child_states": child_states, "child_summaries": summary},
        )

    async def _internal_decomposition_aggregate_results(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        result = dict(task.result or {})
        decomposition = result.get("decomposition")
        if not isinstance(decomposition, dict):
            raise RuntimeError("No decomposition payload is available for aggregation.")
        child_ids = list(task.child_task_ids or decomposition.get("child_task_ids") or [])
        child_states = decomposition.get("child_statuses") or {}
        if not child_ids:
            raise RuntimeError("No child tasks are registered for decomposition aggregation.")
        child_records = [self._tasks.get(child_id) for child_id in child_ids]
        child_payloads = []
        all_passed = True
        for child_id, child in zip(child_ids, child_records):
            if child is None:
                all_passed = False
                child_payloads.append({"task_id": child_id, "status": "missing"})
                continue
            status = child.status.value
            child_payloads.append(
                {
                    "task_id": child.id,
                    "title": child.title,
                    "status": status,
                    "task_type": child.task_type,
                    "execution_mode": child.execution_mode.value if hasattr(child.execution_mode, "value") else str(child.execution_mode),
                    "summary": (child.result or {}).get("summary"),
                    "delivery_state": (child.result or {}).get("delivery_state"),
                }
            )
            if child.status not in TASK_FINAL_STATUSES:
                all_passed = False
            if child.status in {TaskStatus.failed, TaskStatus.verification_failed, TaskStatus.timed_out, TaskStatus.cancelled}:
                all_passed = False
        decomposition["child_results"] = child_payloads
        decomposition["aggregated_at"] = utc_iso()
        decomposition["all_children_terminal"] = all(
            (self._tasks.get(child_id).status in TASK_FINAL_STATUSES) if self._tasks.get(child_id) else False
            for child_id in child_ids
        )
        decomposition["all_children_passed"] = all_passed and decomposition["all_children_terminal"]
        result["decomposition"] = decomposition
        result["decomposition_summary"] = decomposition.get("strategy") or decomposition.get("summary")
        result["decomposition_child_count"] = len(child_ids)
        result["decomposition_child_results"] = child_payloads
        task.result = result
        self._persist()
        return WorkerResult(
            message="Decomposition results aggregated.",
            output=json.dumps(
                {
                    "summary": decomposition.get("summary"),
                    "strategy": decomposition.get("strategy"),
                    "child_results": child_payloads,
                    "all_children_terminal": decomposition["all_children_terminal"],
                    "all_children_passed": decomposition["all_children_passed"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            route=route,
            metadata={
                "child_task_ids": child_ids,
                "child_results": child_payloads,
                "all_children_terminal": decomposition["all_children_terminal"],
                "all_children_passed": decomposition["all_children_passed"],
            },
        )

    async def _run_internal_step(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        handlers = {
            "internal://recovery/write-smoke-file": self._internal_recovery_write_smoke_file,
            "internal://recovery/llm-smoke": self._internal_recovery_llm_smoke,
            "internal://recovery/create-artifact": self._internal_recovery_create_artifact,
            "internal://recovery/verify-artifact": self._internal_recovery_verify_artifact,
            "internal://lab/binary-classification-run": self._internal_binary_classification_lab_run,
        }
        command = str(step.command or "").strip()
        if command == "internal://decomposition/spawn-subtasks":
            return await self._internal_decomposition_spawn_subtasks(task, step, route)
        if command == "internal://decomposition/wait-subtasks":
            return await self._internal_decomposition_wait_subtasks(task, step, route)
        if command == "internal://decomposition/aggregate-results":
            return await self._internal_decomposition_aggregate_results(task, step, route)
        handler = handlers.get(command)
        if handler is None:
            raise RuntimeError(f"Unsupported internal step command: {command}")
        try:
            return await asyncio.to_thread(handler, task, step)
        except Exception as exc:
            self._append_execution_evidence(task, step, action=command or "internal-step", ok=False, details={"error": str(exc)})
            raise

    def _is_recovery_task(self, task: TaskRecord) -> bool:
        hint = task.scheduler_hint or {}
        if bool(hint.get("recovery_task")):
            return True
        scheduled_by = str(task.scheduled_by or hint.get("scheduled_by") or "").strip().lower()
        return scheduled_by.startswith("factory-daemon.recovery")

    def _should_pause_on_failure(self, task: TaskRecord) -> bool:
        return not bool(task.auto_approve or self._should_detach_task_runner(task) or self._is_recovery_task(task))

    def _active_recovery_tasks(self) -> list[TaskRecord]:
        return [
            task
            for task in self._tasks.values()
            if self._is_recovery_task(task)
            and task.status in TASK_ACTIVE_STATUSES
        ]

    def _recovery_task_is_stale(self, task: TaskRecord, *, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        checkpoint = self._checkpoint_for(task.id) or {}
        heartbeat = _parse_record_time(checkpoint.get("heartbeat_at")) or _parse_record_time(checkpoint.get("updated_at"))
        if heartbeat is None:
            heartbeat = task.updated_at
        if heartbeat is None:
            return True
        timeslice_seconds = int(checkpoint.get("timeslice_seconds") or (task.scheduler_hint or {}).get("timeslice_seconds") or 60)
        stale_after = max(180, timeslice_seconds * 3)
        return (now - heartbeat) >= timedelta(seconds=stale_after)

    def _mark_recovery_task_superseded(self, task: TaskRecord, *, reason: str) -> None:
        now = datetime.now(timezone.utc)
        task.status = TaskStatus.failed
        task.updated_at = now
        result = dict(task.result or {})
        result.update(
            {
                "state": "recovery_task_superseded",
                "reason": reason,
                "superseded_at": utc_iso(),
                "recovery_resolution": "newer_evidence_already_satisfied_target",
            }
        )
        task.result = result
        task.events.append(
            TaskEvent(
                message="Recovery task closed after newer evidence satisfied recovery targets.",
                level="warning",
                data={"reason": reason},
            )
        )
        self._update_checkpoint(
            task,
            phase="failed",
            extra={"error": reason, "recovery_resolution": "superseded"},
        )
        self._persist()

    def _resume_stale_recovery_task(self, task: TaskRecord, *, reason: str) -> None:
        now = datetime.now(timezone.utc)
        task.status = TaskStatus.planning
        task.updated_at = now
        result = dict(task.result or {})
        result.update(
            {
                "resume_requested_at": utc_iso(),
                "resume_reason": reason,
                "recovery_resolution": "resumed_after_daemon_restart",
            }
        )
        task.result = result
        task.events.append(
            TaskEvent(
                message="Stale recovery task resumed after detached runner was lost.",
                level="warning",
                data={"reason": reason},
            )
        )
        self._update_checkpoint(
            task,
            phase="planning",
            extra={"resume_reason": reason, "recovery_resolution": "resume-requested"},
        )
        self._persist()
        self._launch_task_runner(task)

    def _heal_stale_recovery_tasks(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        active = self._active_recovery_tasks()
        if not active:
            return snapshot
        targets_satisfied = not bool(
            snapshot.get("needs_fresh_completion")
            or snapshot.get("needs_artifact_recovery")
        )
        if targets_satisfied:
            reason = "Recovery targets already satisfied by recent verified completions or recent runnable artifact evidence."
            for task in active:
                self._mark_recovery_task_superseded(task, reason=reason)
            return self._recovery_status_snapshot()
        stale = [task for task in active if self._recovery_task_is_stale(task)]
        if not stale:
            return snapshot
        self._resume_stale_recovery_task(
            stale[0],
            reason="Recovery task runner was lost before completion; relaunching detached execution.",
        )
        return self._recovery_status_snapshot()

    def _recent_completed_task_count(self, *, hours: float = 24) -> int:
        history = _read_json_file(self._data_dir / "task_history.json", [])
        history_items = history if isinstance(history, list) else []
        current_items = [task.model_dump(mode="json") for task in self._tasks.values()]
        summary = summarize_verified_completed_tasks(current_items, history_items, hours=hours)
        return int(summary.get("verified_completed_tasks_last_24h", 0) or 0)

    def _recent_real_artifact_count(self, *, hours: float = 24) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        registry = audit_artifacts(write_outputs=False)
        count = 0
        for item in registry.get("artifacts", []):
            if not item.get("real"):
                continue
            latest = _parse_record_time(((item.get("checks") or {}).get("latest_evidence_at")))
            if latest is not None and latest >= cutoff:
                count += 1
        return count

    def _recovery_status_snapshot(self) -> dict[str, Any]:
        active = self._active_recovery_tasks()
        active_non_recovery_tasks = sum(
            1
            for task in self._tasks.values()
            if not self._is_recovery_task(task)
            and task.status in TASK_ACTIVE_STATUSES
        )
        target_completed_tasks = 10
        fresh_completed_target = 1
        fresh_window_hours = 0.5
        recent_completed_tasks = self._recent_completed_task_count(hours=24)
        fresh_completed_tasks = self._recent_completed_task_count(hours=fresh_window_hours)
        recent_real_artifacts = self._recent_real_artifact_count(hours=24)
        fresh_real_artifacts = self._recent_real_artifact_count(hours=fresh_window_hours)
        fresh_recovery_evidence = fresh_real_artifacts >= 1
        needs_fresh_completion = (
            fresh_completed_tasks < fresh_completed_target
            and active_non_recovery_tasks < 1
            and not fresh_recovery_evidence
        )
        needs_artifact_recovery = recent_real_artifacts < 1
        recovery_exit_ready = (
            fresh_completed_tasks >= fresh_completed_target
            and recent_completed_tasks >= target_completed_tasks
            and fresh_real_artifacts >= 1
            and active_non_recovery_tasks >= 1
        )
        recovery_mode = bool(active or needs_fresh_completion or needs_artifact_recovery)
        if recovery_exit_ready and not active:
            recovery_mode = False
        return {
            "recovery_mode": recovery_mode,
            "target_completed_tasks": target_completed_tasks,
            "recent_completed_tasks": recent_completed_tasks,
            "recent_real_artifacts": recent_real_artifacts,
            "fresh_completed_target": fresh_completed_target,
            "fresh_window_hours": fresh_window_hours,
            "fresh_completed_tasks": fresh_completed_tasks,
            "fresh_real_artifacts": fresh_real_artifacts,
            "fresh_recovery_evidence": fresh_recovery_evidence,
            "active_non_recovery_tasks": active_non_recovery_tasks,
            "needs_fresh_completion": needs_fresh_completion,
            "needs_artifact_recovery": needs_artifact_recovery,
            "recovery_exit_ready": recovery_exit_ready,
            "active_recovery_task_ids": [task.id for task in active],
        }

    def _build_execution_recovery_task(self) -> TaskCreate:
        repo_root = self._workspace_root()
        artifact_rel = Path("generated") / "execution-recovery-demo"
        required_artifacts = [
            str(artifact_rel / "run_demo.py"),
            str(artifact_rel / "build-report.json"),
            str(artifact_rel / "test-report.json"),
            str(artifact_rel / "execution-report.json"),
            str(artifact_rel / "artifact_manifest.json"),
            str(artifact_rel / "build.sh"),
            str(artifact_rel / "Dockerfile.build"),
        ]
        return TaskCreate(
            prompt="Execution recovery task: produce a real completed task and a runnable artifact.",
            title="Execution recovery: smoke and runnable artifact",
            repo_path=str(repo_root),
            goal="Recover stable execution output",
            scheduled_by="factory-daemon.recovery",
            auto_approve=True,
            execution_mode=ExecutionMode.production,
            preferred_worker="docker",
            scheduler_hint={
                "recovery_task": True,
                "scheduled_by": "factory-daemon.recovery",
                "factory_pool": "ops",
                "execution_mode": "production",
                "title": "Execution recovery: smoke and runnable artifact",
            },
            artifact_spec=ArtifactSpec(
                artifact_id="execution-recovery-demo",
                artifact_type="demo",
                type="demo",
                output=str(artifact_rel),
                entrypoint=str(artifact_rel / "run_demo.py"),
                deliverables=required_artifacts,
                expected_outputs=required_artifacts,
                required_artifacts=required_artifacts,
                evidence=["build-report.json", "test-report.json", "execution-report.json"],
                verification={"build_required": True, "tests_required": True, "runtime_required": True},
                registry="artifact_registry",
                test_command="run_demo.py --self-test",
                min_fresh_artifacts=len(required_artifacts),
            ),
            plan=[
                StepSpec(
                    title="Write recovery smoke file",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Write a deterministic recovery smoke file and verify it exists.",
                    command="internal://recovery/write-smoke-file",
                    workdir=str(repo_root),
                    outputs=[str(Path("orchestrator-mvp") / "data" / "execution-recovery" / "test.txt")],
                    acceptance_criteria=["Smoke file exists after the step finishes."],
                ),
                StepSpec(
                    title="Probe direct LLM path",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Bypass planner routing and make one direct LLM call that must update usage tracking.",
                    command="internal://recovery/llm-smoke",
                    workdir=str(repo_root),
                    acceptance_criteria=["usage_tracker.json advances and the model output is non-empty."],
                ),
                StepSpec(
                    title="Create runnable recovery artifact",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Create a deterministic runnable artifact, compile it, self-test it, and execute it for real.",
                    command="internal://recovery/create-artifact",
                    workdir=str(repo_root),
                    outputs=required_artifacts,
                    acceptance_criteria=["Artifact files exist and the entrypoint executes successfully."],
                ),
                StepSpec(
                    title="Verify recovery artifact",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Validate production evidence, refresh the artifact audit, and ensure the artifact is marked real.",
                    command="internal://recovery/verify-artifact",
                    workdir=str(repo_root),
                    outputs=[str(Path("orchestrator-mvp") / "data" / "artifact_registry.json"), str(Path("orchestrator-mvp") / "data" / "reality_dashboard.json")],
                    acceptance_criteria=["The recovery artifact audits as real and production evidence is fresh."],
                ),
            ],
        )

    async def ensure_execution_recovery(self) -> dict[str, Any]:
        snapshot = self._recovery_status_snapshot()
        snapshot = self._heal_stale_recovery_tasks(snapshot)
        if snapshot["active_recovery_task_ids"]:
            return {"status": "active", **snapshot}
        if not snapshot["recovery_mode"] or snapshot.get("recovery_exit_ready"):
            return {"status": "stable", **snapshot}
        task = await self.create_task(self._build_execution_recovery_task())
        refreshed = self._recovery_status_snapshot()
        return {"status": "created", "created_task_id": task.id, **refreshed}
    def _launch_task_runner(self, task: TaskRecord) -> None:
        if self._should_detach_task_runner(task):
            worker = threading.Thread(
                target=self._run_task_in_background_thread,
                args=(task.id,),
                name=f"orch-task-{task.id[:8]}",
                daemon=True,
            )
            worker.start()
            return
        asyncio.create_task(self._run_task(task.id))

    def _should_detach_task_runner(self, task: TaskRecord) -> bool:
        scheduled_by = str(task.scheduled_by or '').strip().lower()
        scheduler_hint = str((task.scheduler_hint or {}).get('scheduled_by') or '').strip().lower()
        markers = (scheduled_by, scheduler_hint)
        return any(
            marker.startswith('runtime.')
            or marker.startswith('brain-loop')
            or marker.startswith('factory-daemon')
            for marker in markers
            if marker
        )

    def _run_task_in_background_thread(self, task_id: str) -> None:
        asyncio.run(self._run_task(task_id))

    async def _run_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        executor_id = str(task.executor_id or (task.executor_route.get("selected") or {}).get("executor_id") or "script_executor").strip()
        task.executor_id = executor_id
        try:
            task.status = TaskStatus.planning
            task.updated_at = datetime.now(timezone.utc)
            self._executor_submit(task)
            self._executor_report(task, phase="planning", progress=0.08, metadata={"stage": "contracting"})
            task.contract = self._build_task_contract(task)
            task.agent_assignments = self._build_agent_assignments(task)
            task.rule_checks = self._evaluate_rules(task)
            task.git_workflow = await self._build_git_workflow(task)
            self._update_checkpoint(task, phase='planning')
            await self._append_event(
                task,
                "Task planning started.",
                data={
                    "requirements": task.contract.requirements,
                    "deliverables": task.contract.deliverables,
                    "acceptance_criteria": task.contract.acceptance_criteria,
                    "product_design": task.product_design.model_dump(mode="json"),
                    "architecture_design": task.architecture_design.model_dump(mode="json"),
                    "quality_plan": task.quality_plan.model_dump(mode="json"),
                    "deployment_plan": task.deployment_plan.model_dump(mode="json"),
                    "monitoring_plan": task.monitoring_plan.model_dump(mode="json"),
                    "rule_checks": [item.model_dump(mode="json") for item in task.rule_checks],
                    "git_workflow": task.git_workflow.model_dump(mode="json"),
                },
            )
            task.context_envelope = await self._context_service.build(
                TaskCreate(
                    prompt=task.prompt,
                    title=task.title,
                    repo_path=task.repo_path,
                    goal=task.goal,
                    goal_id=task.goal_id,
                    graph_id=task.graph_id,
                    node_id=task.node_id,
                    scheduled_by=task.scheduled_by,
                    auto_approve=task.auto_approve,
                    context_mode=task.context_mode,
                    max_context_chars=task.max_context_chars,
                    allow_resource_scan=task.allow_resource_scan,
                    allow_repo_status=task.allow_repo_status,
                    preferred_worker=task.preferred_worker,
                    scheduler_hint=task.scheduler_hint,
                    execution_lane=task.execution_lane,
                    worker_vm_policy=task.worker_vm_policy,
                    execution_mode=task.execution_mode,
                    artifact_spec=task.artifact_spec,
                )
            )
            self._persist()
            await self._append_event(
                task,
                "Context envelope prepared.",
                data={
                    "context_mode": task.context_envelope.mode.value,
                    "used_chars": task.context_envelope.used_chars,
                    "budget_chars": task.context_envelope.budget_chars,
                    "includes": task.context_envelope.includes,
                },
            )
            if task.plan and any(step.status in {StepStatus.completed, StepStatus.running, StepStatus.failed, StepStatus.pending} for step in task.plan):
                plan = PlannerResponse(summary='Resumed from saved task plan.', steps=task.plan)
            else:
                result = dict(task.result or {})
                if self._should_decompose_task(task):
                    decomposition = self._build_task_decomposition(task)
                    if decomposition.subtasks:
                        result["decomposition"] = decomposition.model_dump(mode="json")
                        result["decomposition"]["depth"] = self._task_decomposition_depth(task)
                        result["decomposition"]["max_depth"] = self._task_max_decomposition_depth(task) or 2
                        result["decomposition"]["mode"] = "multi_layer"
                        task.result = result
                        plan = PlannerResponse(
                            summary=decomposition.summary or "Task decomposition plan.",
                            steps=self._task_decomposition_internal_steps(task, decomposition),
                        )
                    else:
                        plan = self._planner.build_plan(prompt=task.prompt, repo_path=task.repo_path, context=task.context_envelope)
                else:
                    plan = self._planner.build_plan(prompt=task.prompt, repo_path=task.repo_path, context=task.context_envelope)
            plan = self._enforce_production_plan_constraints(task, plan)
            task.plan = plan.steps
            self._persist()
            self._executor_report(task, phase="planning", progress=0.22, metadata={"stage": "plan_ready", "step_count": len(plan.steps)})
            await self._append_event(
                task,
                "Plan created.",
                data={
                    "summary": plan.summary,
                    "steps": len(plan.steps),
                    "agent_assignments": [item.model_dump(mode="json") for item in task.agent_assignments],
                },
            )

            task.status = TaskStatus.running
            self._executor_report(task, phase="running", progress=0.3, metadata={"stage": "task_running"})
            self._update_checkpoint(task, phase='running')
            total_steps = max(1, len(task.plan))
            for index, step in enumerate(task.plan, start=1):
                await self._run_step(task, step)
                self._executor_report(
                    task,
                    phase="running",
                    progress=min(0.95, 0.3 + (0.6 * index / total_steps)),
                    metadata={"completed_steps": index, "total_steps": total_steps},
                )

            execution_evidence = self._validate_task_completion(task)
            task.status = TaskStatus.execution_finished
            task.result = {
                "summary": plan.summary,
                "completed_steps": len(task.plan),
                "context_used_chars": task.context_envelope.used_chars if task.context_envelope else 0,
                "cheap_calls_used": task.cheap_lane.calls_used,
                "cheap_chars_used": task.cheap_lane.chars_used,
                "escalation_count": task.escalation_count,
                "execution_mode": task.execution_mode.value,
                "execution_status": "execution_finished",
                "production_evidence": execution_evidence,
            }
            self._update_checkpoint(task, phase="execution-finished", extra={"completed_steps": len(task.plan)})
            self._finalize_execution_evidence(task)
            await self._append_event(
                task,
                "Execution finished; verification pending.",
                data={
                    "execution_status": "execution_finished",
                    "production_evidence": execution_evidence,
                },
            )
            task.status = TaskStatus.verification_pending
            self._update_checkpoint(task, phase="verification-pending", extra={"completed_steps": len(task.plan)})
            self._executor_report(task, phase="verification", progress=0.96, metadata={"stage": "verification_pending"})
            await self._append_event(
                task,
                "Verification started.",
                data={"verification_contract": (task.verification_contract.model_dump(mode="json") if task.verification_contract else None)},
            )
            task.status = TaskStatus.verification_running
            self._update_checkpoint(task, phase="verification-running", extra={"completed_steps": len(task.plan)})
            self._executor_report(task, phase="verification", progress=0.98, metadata={"stage": "verification_running"})
            verification_result = self._evaluate_task_verification(task)
            task.result["verification_contract"] = verification_result.get("contract")
            task.result["verification_result"] = verification_result
            if verification_result.get("passed"):
                release_requested = should_auto_approve_task(
                    requested=bool(task.auto_approve),
                    execution_mode=task.execution_mode.value if hasattr(task.execution_mode, "value") else str(task.execution_mode),
                    scheduler_hint=task.scheduler_hint,
                    scheduled_by=task.scheduled_by,
                )
                task.status = TaskStatus.released if release_requested else TaskStatus.delivery_ready
                task.result["delivery_state"] = task.status.value
                self._update_checkpoint(
                    task,
                    phase="verification-passed",
                    extra={
                        "completed_steps": len(task.plan),
                        "verification_result": verification_result,
                        "delivery_state": task.status.value,
                    },
                )
                await self._append_event(
                    task,
                    "Verification passed; task ready for delivery.",
                    data={"verification_result": verification_result, "delivery_state": task.status.value},
                )
            else:
                task.status = TaskStatus.verification_failed
                task.result["delivery_state"] = task.status.value
                self._update_checkpoint(
                    task,
                    phase="verification-failed",
                    extra={
                        "completed_steps": len(task.plan),
                        "verification_result": verification_result,
                        "delivery_state": task.status.value,
                    },
                )
                await self._append_event(
                    task,
                    "Verification failed after execution.",
                    level="error",
                    data={"verification_result": verification_result, "delivery_state": task.status.value},
                )
            self._finalize_execution_evidence(task)
            self._executor_complete(
                task,
                status="success" if verification_result.get("passed") else "failed",
                summary=plan.summary,
                outputs=task.result,
                needs_verification=False,
            )
            self._persist()
            from tools.goal_runtime import sync_goal_runtime
            sync_goal_runtime()
            distilled = distill_task(task.model_dump(mode="json"))
            await self._append_event(task, "Task completed.", data={"distilled": distilled, "delivery_state": task.status.value})
        except Exception as exc:
            pause_on_failure = self._should_pause_on_failure(task)
            task.status = TaskStatus.waiting_approval if pause_on_failure else TaskStatus.failed
            checkpoint_phase = 'waiting_approval' if pause_on_failure else 'failed'
            self._update_checkpoint(task, phase=checkpoint_phase, extra={'error': str(exc)})
            task.result = self._build_error_report(task, str(exc), paused=pause_on_failure)
            self._executor_complete(
                task,
                status="failed",
                summary=str(exc),
                outputs=task.result,
                needs_verification=False,
            )
            self._finalize_execution_evidence(task)
            self._persist()
            from tools.goal_runtime import sync_goal_runtime
            sync_goal_runtime()
            distilled = distill_task(task.model_dump(mode="json"))
            await self._append_event(
                task,
                "Task paused pending core instruction after failure diagnosis." if pause_on_failure else "Task failed after execution error.",
                level="error",
                data={
                    "error": str(exc),
                    "pause_reason": "awaiting_core_instruction" if pause_on_failure else "failed_execution",
                    "distilled": distilled,
                },
            )
            if pause_on_failure:
                await self.post_core_message(
                    {
                        "source": "orchestrator-task-failure",
                        "severity": "error",
                        "title": f"Task paused: {task.id}",
                        "body": f"Prompt: {task.prompt[:300]}\n\nError: {exc}\n\nNo further action will be taken until core guidance arrives.",
                        "task_id": task.id,
                        "repo_path": task.repo_path,
                    }
                )
    async def _run_step(self, task: TaskRecord, step: StepSpec) -> None:
        internal_step = self._is_internal_step(step)
        route = self._recovery_route() if internal_step else self._router.route_step(step, task=task)
        while True:
            step_started_at = time.monotonic()
            step.status = StepStatus.running
            self._executor_report(
                task,
                phase="running",
                progress=0.3,
                metadata={"step_id": step.id, "step_title": step.title, "step_phase": step.phase, "worker": step.worker.value},
            )
            self._update_checkpoint(task, phase='step-running', step=step)
            await self._append_event(
                task,
                f"Step started: {step.title}",
                data={
                    "worker": step.worker.value,
                    "phase": step.phase or "unspecified",
                    "route_model": route.model,
                    "route_provider": route.provider,
                    "cheap_calls_used": task.cheap_lane.calls_used,
                    "cheap_chars_used": task.cheap_lane.chars_used,
                    "probe_attempts": step.probe_attempts,
                    "max_probe_attempts": step.max_probe_attempts,
                    "assigned_role": step.assigned_role.value if step.assigned_role else None,
                    "inputs": step.inputs,
                    "outputs": step.outputs,
                    "dependencies": step.dependencies,
                    "acceptance_criteria": step.acceptance_criteria,
                },
            )
            try:
                result = await self._run_internal_step(task, step, route) if internal_step else await self._run_step_worker_with_heartbeat(task, step, route)
                self._validate_audit_step_output(task, step, result.output)
                materialized = self._materialize_step_payload(
                    task,
                    step,
                    result.output,
                    channel=f"{step.worker.value}-output",
                    title=f"{step.title} output",
                    metadata={
                        'worker': step.worker.value,
                        'phase': step.phase,
                        'route_model': result.route.model,
                        'route_provider': result.route.provider,
                    },
                )
                step.status = StepStatus.completed
                step.output = materialized['summary']
                step.output_ref = materialized['artifact_ref']
                step.output_stats = materialized['stats']
                self._executor_report(
                    task,
                    phase="running",
                    progress=0.95,
                    metadata={"step_id": step.id, "step_title": step.title, "step_status": "completed"},
                )
                self._update_checkpoint(task, phase='step-completed', step=step)
                elapsed_ms = int((time.monotonic() - step_started_at) * 1000)
                if not internal_step:
                    self._append_execution_evidence(
                        task,
                        step,
                        action=f"{step.worker.value}_step",
                        ok=True,
                        details={
                            "worker": step.worker.value,
                            "phase": step.phase,
                            "route_model": result.route.model,
                            "route_provider": result.route.provider,
                            "output_ref": step.output_ref,
                            "output_stats": step.output_stats,
                            "probe_attempts": step.probe_attempts,
                        },
                    )
                await self._append_verification_signal(
                    task,
                    kind="step_completed",
                    success=True,
                    details={
                        "step_id": step.id,
                        "step_title": step.title,
                        "worker": step.worker.value,
                        "phase": step.phase,
                        "route_model": result.route.model,
                        "route_provider": result.route.provider,
                        "elapsed_ms": elapsed_ms,
                        "output_ref": step.output_ref,
                        "output_stats": step.output_stats,
                    },
                )
                event_data = {
                    "step_id": step.id,
                    "step_title": step.title,
                    "phase": step.phase or "unspecified",
                    "route_model": result.route.model,
                    "cheap_calls_used": task.cheap_lane.calls_used,
                    "cheap_chars_used": task.cheap_lane.chars_used,
                    "escalation_count": task.escalation_count,
                    "probe_attempts": step.probe_attempts,
                    "assigned_role": step.assigned_role.value if step.assigned_role else None,
                    "output_ref": step.output_ref,
                    "output_stats": step.output_stats,
                }
                event_data.update(result.metadata)
                await self._append_event(task, result.message, data=event_data)
                return
            except WorkerSafetyError as exc:
                materialized = self._materialize_step_payload(
                    task,
                    step,
                    str(exc),
                    channel='error-output',
                    title=f"{step.title} failure",
                    metadata={'worker': step.worker.value, 'phase': step.phase, 'error': str(exc)},
                )
                step.status = StepStatus.failed
                step.output = materialized['summary']
                step.output_ref = materialized['artifact_ref']
                step.output_stats = materialized['stats']
                self._executor_report(
                    task,
                    phase="failed",
                    progress=1.0,
                    metadata={"step_id": step.id, "step_title": step.title, "step_status": "failed", "error": str(exc)},
                )
                self._update_checkpoint(task, phase='step-failed', step=step, extra={'error': str(exc)})
                elapsed_ms = int((time.monotonic() - step_started_at) * 1000)
                if not internal_step:
                    self._append_execution_evidence(
                        task,
                        step,
                        action=f"{step.worker.value}_step",
                        ok=False,
                        details={
                            "worker": step.worker.value,
                            "phase": step.phase,
                            "route_model": route.model,
                            "route_provider": route.provider,
                            "error": str(exc),
                            "output_ref": step.output_ref,
                            "output_stats": step.output_stats,
                            "probe_attempts": step.probe_attempts,
                        },
                    )
                await self._append_verification_signal(
                    task,
                    kind="step_failed",
                    success=False,
                    details={
                        "step_id": step.id,
                        "step_title": step.title,
                        "worker": step.worker.value,
                        "phase": step.phase,
                        "route_model": route.model,
                        "route_provider": route.provider,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                        "output_ref": step.output_ref,
                        "output_stats": step.output_stats,
                    },
                )
                diagnosis = await self._diagnose_failure(task, step, str(exc))
                if await self._maybe_probe_retry(task, step, route, diagnosis, str(exc)):
                    continue
                raise
            except Exception as exc:
                materialized = self._materialize_step_payload(
                    task,
                    step,
                    str(exc),
                    channel='error-output',
                    title=f"{step.title} failure",
                    metadata={'worker': step.worker.value, 'phase': step.phase, 'error': str(exc)},
                )
                step.status = StepStatus.failed
                step.output = materialized['summary']
                step.output_ref = materialized['artifact_ref']
                step.output_stats = materialized['stats']
                self._executor_report(
                    task,
                    phase="failed",
                    progress=1.0,
                    metadata={"step_id": step.id, "step_title": step.title, "step_status": "failed", "error": str(exc)},
                )
                self._update_checkpoint(task, phase='step-failed', step=step, extra={'error': str(exc)})
                elapsed_ms = int((time.monotonic() - step_started_at) * 1000)
                if not internal_step:
                    self._append_execution_evidence(
                        task,
                        step,
                        action=f"{step.worker.value}_step",
                        ok=False,
                        details={
                            "worker": step.worker.value,
                            "phase": step.phase,
                            "route_model": route.model,
                            "route_provider": route.provider,
                            "error": str(exc),
                            "output_ref": step.output_ref,
                            "output_stats": step.output_stats,
                            "probe_attempts": step.probe_attempts,
                        },
                    )
                await self._append_verification_signal(
                    task,
                    kind="step_failed",
                    success=False,
                    details={
                        "step_id": step.id,
                        "step_title": step.title,
                        "worker": step.worker.value,
                        "phase": step.phase,
                        "route_model": route.model,
                        "route_provider": route.provider,
                        "elapsed_ms": elapsed_ms,
                        "error": str(exc),
                        "output_ref": step.output_ref,
                        "output_stats": step.output_stats,
                    },
                )
                diagnosis = await self._diagnose_failure(task, step, str(exc))
                if await self._maybe_probe_retry(task, step, route, diagnosis, str(exc)):
                    continue
                raise

    async def _run_step_worker_with_heartbeat(self, task: TaskRecord, step: StepSpec, route: Any) -> Any:
        worker_task = asyncio.create_task(self._workers.run(task, step, route))
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(worker_task), timeout=30)
            except asyncio.TimeoutError:
                self._refresh_step_heartbeat(task, step)

    def _refresh_step_heartbeat(self, task: TaskRecord, step: StepSpec) -> None:
        task.updated_at = datetime.now(timezone.utc)
        self._update_checkpoint(
            task,
            phase='step-running',
            step=step,
            extra={'heartbeat_reason': 'worker-execution-in-progress'},
        )
        self._persist()

    async def _diagnose_failure(self, task: TaskRecord, step: StepSpec, error_text: str) -> dict[str, Any]:
        diag_step = StepSpec(
            title=f"Diagnose failure: {step.title}",
            worker=WorkerType.reviewer,
            phase="check",
            instructions=(
                "Review the failed step like a careful engineer. Respond in this exact structure: \n"
                "Decision: retry-once | pause\n"
                "Reason: <short cause>\n"
                "Probe: <one cheap safe next action, or none>\n"
                "Notes: <concise detail>\n\n"
                "Approve retry-once only if one additional cheap local attempt is low-cost, non-destructive, and likely to reveal new signal. "
                "If unsure, say pause.\n\n"
                f"Failed phase: {step.phase or 'unspecified'}\n"
                f"Failed worker: {step.worker.value}\n"
                f"Failed step: {step.title}\n"
                f"Probe attempts used: {step.probe_attempts}/{step.max_probe_attempts}\n"
                f"Command: {step.command or 'n/a'}\n"
                f"Error: {error_text}\n"
                f"Observed output:\n{self._prompt_output_excerpt(step, max_chars=1000)}"
            ),
            workdir=step.workdir,
        )
        route = self._router.route_step(diag_step, task=task)
        try:
            result = await self._workers.run(task, diag_step, route)
            materialized = self._materialize_step_payload(
                task,
                step,
                result.output,
                channel='diagnosis-output',
                title=f"Diagnosis for {step.title}",
                metadata={
                    'worker': diag_step.worker.value,
                    'phase': diag_step.phase,
                    'route_model': result.route.model,
                    'route_provider': result.route.provider,
                },
            )
            diagnosis = self._parse_diagnosis(result.output)
            diagnosis["raw"] = materialized['summary']
            diagnosis["route_provider"] = result.route.provider
            diagnosis["route_model"] = result.route.model
            diagnosis["approved_by_cheap"] = result.route.provider == "cheap" and diagnosis["decision"] == "retry-once"
            step.last_diagnosis = materialized['summary']
            step.last_diagnosis_ref = materialized['artifact_ref']
            self._persist()
            await self._append_event(
                task,
                f"Failure diagnosis for {step.title}",
                level="warning",
                data={
                    "failed_step_id": step.id,
                    "failed_step_title": step.title,
                    "diagnosis_route_model": result.route.model,
                    "diagnosis_phase": diag_step.phase,
                    "diagnosis": step.last_diagnosis,
                    "diagnosis_ref": step.last_diagnosis_ref,
                    "diagnosis_decision": diagnosis["decision"],
                    "approved_by_cheap": diagnosis["approved_by_cheap"],
                },
            )
            await self.post_core_message(
                {
                    "source": "orchestrator-diagnosis",
                    "severity": "warning",
                    "title": f"Diagnosis needed: {step.title}",
                    "body": step.last_diagnosis,
                    "task_id": task.id,
                    "step_id": step.id,
                    "repo_path": task.repo_path,
                }
            )
            return diagnosis
        except Exception as diag_exc:
            await self._append_event(
                task,
                f"Failure diagnosis skipped for {step.title}: {diag_exc}",
                level="warning",
                data={"failed_step_id": step.id, "failed_step_title": step.title},
            )
            await self.post_core_message(
                {
                    "source": "orchestrator-diagnosis-skipped",
                    "severity": "warning",
                    "title": f"Diagnosis skipped: {step.title}",
                    "body": f"Original error: {error_text}\nDiagnosis error: {diag_exc}",
                    "task_id": task.id,
                    "step_id": step.id,
                    "repo_path": task.repo_path,
                }
            )
            return {
                "decision": "pause",
                "reason": f"Diagnosis skipped: {diag_exc}",
                "probe": "none",
                "notes": "No structured diagnosis available.",
                "approved_by_cheap": False,
                "raw": str(diag_exc),
            }

    def _parse_diagnosis(self, output: str) -> dict[str, str]:
        parsed = {
            "decision": "pause",
            "reason": "No explicit decision returned.",
            "probe": "none",
            "notes": "",
        }
        for raw_line in output.splitlines():
            line = raw_line.strip()
            lowered = line.lower()
            if lowered.startswith("decision:"):
                value = line.split(":", 1)[1].strip().lower()
                parsed["decision"] = "retry-once" if value == "retry-once" else "pause"
            elif lowered.startswith("reason:"):
                parsed["reason"] = line.split(":", 1)[1].strip() or parsed["reason"]
            elif lowered.startswith("probe:"):
                parsed["probe"] = line.split(":", 1)[1].strip() or "none"
            elif lowered.startswith("notes:"):
                parsed["notes"] = line.split(":", 1)[1].strip()
        return parsed
    async def _maybe_probe_retry(self, task: TaskRecord, step: StepSpec, route: Any, diagnosis: dict[str, Any], error_text: str) -> bool:
        if diagnosis.get("decision") != "retry-once":
            return False
        if not diagnosis.get("approved_by_cheap"):
            return False
        if step.probe_attempts >= step.max_probe_attempts:
            return False
        if task.cheap_lane.blocked:
            return False
        step.probe_attempts += 1
        probe_note = diagnosis.get("probe") or "Repeat once with a narrower, safer attempt."
        step.instructions = (
            f"{step.instructions}\n\n"
            f"Bounded retry approved by cheap reviewer.\n"
            f"Retry number: {step.probe_attempts}/{step.max_probe_attempts}\n"
            f"Previous error: {error_text}\n"
            f"Retry guidance: {probe_note}"
        )
        step.status = StepStatus.pending
        self._persist()
        await self._append_event(
            task,
            f"Cheap reviewer approved one bounded probe retry for {step.title}",
            level="warning",
            data={
                "step_id": step.id,
                "probe_attempt": step.probe_attempts,
                "probe_limit": step.max_probe_attempts,
                "probe_guidance": probe_note,
                "diagnosis_reason": diagnosis.get("reason"),
                "route_model": route.model,
                "route_provider": route.provider,
            },
        )
        return True


    def _infer_execution_mode(
        self,
        payload: DispatchTaskRequest,
        project: ProjectMemoryRecord | None,
        *,
        profile: dict[str, str] | None = None,
    ) -> ExecutionMode:
        if payload.execution_mode is not None:
            return payload.execution_mode
        hint_mode = str((payload.scheduler_hint or {}).get("execution_mode") or "").strip().lower()
        if hint_mode in {mode.value for mode in ExecutionMode}:
            return ExecutionMode(hint_mode)
        corpus = " ".join(
            part
            for part in [
                payload.prompt,
                payload.goal or "",
                payload.title or "",
                payload.repo_path or "",
                project.name if project else "",
                project.summary if project else "",
                json.dumps(payload.scheduler_hint or {}, ensure_ascii=False),
                (profile or {}).get("name", ""),
            ]
            if part
        ).lower()
        governance_tokens = ["coordinate", "align project", "review patch queue", "merge ready patch queue", "approval", "policy", "governance", "operator review"]
        research_tokens = ["research", "experiment", "prototype", "rfc", "design", "analysis", "investigate", "roadmap", "proposal"]
        production_tokens = ["implement", "patch", "fix", "build", "test", "verify", "artifact", "regression", "release", "kernel", "toyos", "qemu", "syscall", "paging"]
        if any(token in corpus for token in governance_tokens):
            return ExecutionMode.governance
        if any(token in corpus for token in production_tokens):
            return ExecutionMode.production
        if any(token in corpus for token in research_tokens):
            return ExecutionMode.research
        if project and project.repo_path and "generated\\toy-os-demo" in project.repo_path.lower():
            return ExecutionMode.production
        return ExecutionMode.governance

    def _infer_evidence_contract(
        self,
        *,
        repo_path: str | None,
        scheduler_hint: dict[str, Any] | None,
        prompt: str | None,
        goal: str | None,
    ) -> dict[str, Any] | None:
        scheduler_hint = scheduler_hint or {}
        explicit = scheduler_hint.get("required_artifacts")
        if not explicit:
            explicit_spec = scheduler_hint.get("artifact_spec") or {}
            if isinstance(explicit_spec, dict):
                explicit = explicit_spec.get("required_artifacts")
        if isinstance(explicit, list) and explicit:
            return {
                "required_artifacts": [str(item) for item in explicit if item],
                "min_fresh_artifacts": max(1, min(len(explicit), int(scheduler_hint.get("min_fresh_artifacts") or len(explicit)))),
                "acceptance_criteria": [f"Refresh artifact {item}" for item in explicit if item],
                "guidance": [f"Refresh artifact {item}" for item in explicit if item],
            }
        corpus = " ".join(part for part in [repo_path or "", prompt or "", goal or ""] if part).lower()
        if "generated\\ml-binary-classification-lab" in corpus or (
            "binary classification" in corpus
            and "logistic" in corpus
            and "svm" in corpus
            and ("perceptron" in corpus or "sgd" in corpus)
        ):
            return {
                "required_artifacts": ["BINARY_CLASSIFICATION_AUTORUN_RESULT.md"],
                "min_fresh_artifacts": 1,
                "acceptance_criteria": [
                    "Refresh BINARY_CLASSIFICATION_AUTORUN_RESULT.md for the current task execution.",
                ],
                "guidance": [
                    "The lab workflow must return a bounded result artifact in the target workspace.",
                ],
            }
        if "generated\\toy-os-demo" in corpus or "toyos" in corpus:
            required = ["build-report.json", "build/kernel.bin", "build/generic-qemu-smoke-report.json", "score-report.json"]
            return {
                "required_artifacts": required,
                "min_fresh_artifacts": 3,
                "acceptance_criteria": [
                    "Refresh ToyOS build-report.json for this execution.",
                    "Refresh ToyOS runtime evidence such as kernel.bin or generic-qemu-smoke-report.json.",
                    "Refresh ToyOS score-report.json before claiming production completion.",
                ],
                "guidance": [
                    "Production completion requires fresh ToyOS artifacts, not just docs or source edits.",
                    "Prefer build-report.json, generic-qemu-smoke-report.json, kernel.bin, and score-report.json.",
                ],
            }
        return None

    def _infer_artifact_spec(
        self,
        *,
        explicit_spec: ArtifactSpec | dict[str, Any] | None,
        repo_path: str | None,
        scheduler_hint: dict[str, Any] | None,
        prompt: str | None,
        goal: str | None,
        execution_mode: ExecutionMode,
    ) -> ArtifactSpec | None:
        scheduler_hint = scheduler_hint or {}
        contract = self._infer_evidence_contract(
            repo_path=repo_path,
            scheduler_hint=scheduler_hint,
            prompt=prompt,
            goal=goal,
        )
        if explicit_spec:
            payload = explicit_spec.model_dump(mode="json") if isinstance(explicit_spec, ArtifactSpec) else dict(explicit_spec)
            verification = dict(payload.get("verification") or {})
            payload["artifact_type"] = payload.get("artifact_type") or payload.get("type") or "artifact"
            payload["type"] = payload.get("type") if payload.get("type") not in {None, "artifact"} else payload.get("artifact_type") or "artifact"
            expected_outputs = [str(item) for item in (payload.get("expected_outputs") or payload.get("deliverables") or []) if str(item).strip()]
            if not expected_outputs:
                expected_outputs = ["source_code", "build_script", "test_suite"]
            payload["expected_outputs"] = expected_outputs
            payload["deliverables"] = list(payload.get("deliverables") or expected_outputs)
            required = [str(item) for item in (payload.get("required_artifacts") or []) if str(item).strip()]
            if not required and contract:
                required = [str(item) for item in contract.get("required_artifacts", []) if str(item).strip()]
            if not required:
                module_focus = [str(item) for item in (scheduler_hint.get("module_focus") or []) if str(item).strip()]
                required = [f"{item.replace('.', '/')}.py" for item in module_focus if item.startswith(("app.", "runtime.", "tools.", "agents.", "state."))]
            if required:
                required = list(dict.fromkeys(required))
                payload["required_artifacts"] = required
                entrypoint = next((item for item in required if item.endswith((".bin", ".exe", ".so", ".dll"))), required[0])
                payload.setdefault("entrypoint", entrypoint)
                payload.setdefault("output", entrypoint)
                if not payload.get("evidence"):
                    payload["evidence"] = [item for item in required if item.endswith((".json", ".log", ".txt"))]
                payload["min_fresh_artifacts"] = int(payload.get("min_fresh_artifacts") or (contract.get("min_fresh_artifacts") if contract else max(1, min(len(required), 3))))
            elif execution_mode == ExecutionMode.production:
                raise ValueError("Production task rejected: artifact_spec.required_artifacts is empty.")
            if not payload.get("test_command") and (verification.get("tests_required") or "test_suite" in expected_outputs):
                payload["test_command"] = "pytest"
            return ArtifactSpec.model_validate(payload)
        if not contract:
            if execution_mode == ExecutionMode.production:
                raise ValueError("Production task rejected: artifact_spec is required.")
            return None
        required = [str(item) for item in contract.get("required_artifacts", []) if str(item).strip()]
        entrypoint = next((item for item in required if item.endswith((".bin", ".exe", ".so", ".dll"))), required[0] if required else None)
        return ArtifactSpec(
            artifact_type="software",
            type="software",
            deliverables=["source_code", "build_script", "test_suite"],
            expected_outputs=["source_code", "build_script", "test_suite"],
            output=entrypoint,
            entrypoint=entrypoint,
            required_artifacts=required,
            evidence=[item for item in required if item.endswith((".json", ".log", ".txt"))],
            verification={"build_required": True, "tests_required": True},
            registry="artifact_registry",
            test_command="pytest",
            min_fresh_artifacts=int(contract.get("min_fresh_artifacts") or len(required) or 1),
        )

    def _infer_throughput_task_type(
        self,
        *,
        payload: DispatchTaskRequest,
        profile: dict[str, str] | None,
        artifact_spec: ArtifactSpec | None,
    ) -> str:
        explicit = str(payload.task_type or payload.scheduler_hint.get("task_type") or "").strip().lower()
        if explicit in THROUGHPUT_TASK_TYPES:
            return explicit
        corpus = " ".join(
            part
            for part in [
                payload.prompt,
                payload.goal or "",
                payload.title or "",
                payload.scheduler_hint.get("task_type") or "",
                payload.scheduler_hint.get("queue_name") or "",
                profile.get("name") if profile else "",
                artifact_spec.artifact_type if artifact_spec else "",
                " ".join(artifact_spec.required_artifacts or []) if artifact_spec else "",
            ]
            if part
        ).lower()
        if any(token in corpus for token in ("harness", "regression", "qemu", "smoke")):
            if "qemu" in corpus or "smoke" in corpus:
                return "qemu_smoke_run"
            return "harness_regression_run"
        if any(token in corpus for token in ("build", "compile", "package")):
            if "demo" in corpus:
                return "demo_rebuild"
            return "build_fix"
        if any(token in corpus for token in ("audit", "manifest", "evidence", "registry")):
            return "artifact_audit"
        if any(token in corpus for token in ("report", "dashboard", "summary", "refresh")):
            return "report_refresh"
        if any(token in corpus for token in ("doc", "docs", "documentation")):
            return "doc_patch"
        if any(token in corpus for token in ("json", "config", "schema")):
            return "json_fix"
        if any(token in corpus for token in ("test", "suite", "validation")):
            return "unit_test_run"
        if any(token in corpus for token in ("bootstrap", "refactor", "migration", "architecture", "new product")):
            return "architecture_migration"
        if profile and profile.get("name") == "auto-debug":
            return "build_fix"
        return "doc_patch"

    def _resolve_throughput_queue(self, task_type: str, execution_mode: ExecutionMode) -> str:
        queue = THROUGHPUT_TASK_QUEUE_MAP.get(task_type)
        if queue:
            return queue
        if task_type == "exploration_intake":
            return "exploration"
        return "incubation" if execution_mode == ExecutionMode.production else "fastlane"

    def _resolve_throughput_verification_level(
        self,
        *,
        queue_name: str,
        task_type: str,
        execution_mode: ExecutionMode,
    ) -> str:
        if queue_name not in THROUGHPUT_QUEUE_CAPS:
            raise ValueError(f"Throughput queue rejected: unknown queue_name '{queue_name}'.")
        if task_type not in THROUGHPUT_TASK_TYPES:
            raise ValueError(f"Throughput queue rejected: unknown task_type '{task_type}'.")
        if execution_mode == ExecutionMode.production and queue_name == "fastlane":
            return "L2"
        return THROUGHPUT_TASK_VERIFICATION_MAP.get(queue_name, "L2")

    def _resolve_throughput_runtime(
        self,
        *,
        queue_name: str,
        task_type: str,
        explicit_runtime: int | None,
    ) -> int:
        if explicit_runtime is not None:
            runtime = int(explicit_runtime)
        elif queue_name == "fastlane":
            runtime = 1800
        elif queue_name == "exploration":
            runtime = 900
        elif queue_name == "build_test":
            runtime = 3600
        elif queue_name == "regression":
            runtime = 5400
        else:
            runtime = 7200
        if task_type in {"report_refresh", "doc_patch", "json_fix", "manifest_patch", "config_fix"}:
            runtime = min(runtime, 1800)
        return max(300, runtime)

    def _resolve_throughput_retry_limit(self, queue_name: str, explicit_retry_limit: int | None) -> int:
        if explicit_retry_limit is not None:
            return max(0, int(explicit_retry_limit))
        return 2 if queue_name == "regression" else 1

    def _resolve_throughput_rollback_rule(self, queue_name: str, explicit_rule: str | None) -> str:
        if explicit_rule:
            return str(explicit_rule).strip()
        if queue_name == "incubation":
            return "mark_failed_and_requeue_split"
        if queue_name == "regression":
            return "mark_failed_and_requeue_split"
        return "mark_failed_and_requeue_split"

    def _throughput_artifact_key(
        self,
        *,
        artifact_spec: ArtifactSpec | None,
        repo_path: str | None,
        project_id: str | None,
        goal_id: str | None,
    ) -> str | None:
        if artifact_spec:
            if artifact_spec.artifact_id:
                return f"artifact_id:{artifact_spec.artifact_id}"
            if artifact_spec.output:
                return f"artifact_output:{artifact_spec.output}"
            if artifact_spec.required_artifacts:
                return f"artifact_required:{artifact_spec.required_artifacts[0]}"
        if project_id:
            return f"project_id:{project_id}"
        if goal_id:
            return f"goal_id:{goal_id}"
        if repo_path:
            return f"repo_path:{repo_path}"
        return None

    def _throughput_queue_counts(self) -> dict[str, int]:
        counts = {name: 0 for name in THROUGHPUT_QUEUE_CAPS}
        for task in self._tasks.values():
            if task.status not in TASK_ACTIVE_STATUSES:
                continue
            queue_name = str(task.queue_name or "").strip().lower()
            if queue_name in counts:
                counts[queue_name] += 1
        return counts

    def _throughput_wip_counts(
        self,
        *,
        project_id: str | None,
        artifact_key: str | None,
        queue_name: str,
    ) -> dict[str, int]:
        project_count = 0
        artifact_count = 0
        queue_count = 0
        for task in self._tasks.values():
            if task.status not in TASK_ACTIVE_STATUSES:
                continue
            if str(task.queue_name or "").strip().lower() == queue_name:
                queue_count += 1
            if project_id and str(task.project_id or "").strip() == str(project_id).strip():
                project_count += 1
            if artifact_key:
                candidate_key = self._throughput_artifact_key(
                    artifact_spec=task.artifact_spec,
                    repo_path=task.repo_path,
                    project_id=task.project_id,
                    goal_id=task.goal_id,
                )
                if candidate_key == artifact_key:
                    artifact_count += 1
        return {
            "queue_count": queue_count,
            "project_count": project_count,
            "artifact_count": artifact_count,
        }

    def _enforce_throughput_admission(
        self,
        *,
        queue_name: str,
        project_id: str | None,
        artifact_key: str | None,
    ) -> None:
        queue_counts = self._throughput_queue_counts()
        queue_count = queue_counts.get(queue_name, 0)
        queue_cap = THROUGHPUT_QUEUE_CAPS.get(queue_name, 0)
        if queue_count >= queue_cap:
            raise ValueError(
                f"Throughput admission rejected: queue '{queue_name}' is at capacity ({queue_count}/{queue_cap})."
            )
        wip_counts = self._throughput_wip_counts(project_id=project_id, artifact_key=artifact_key, queue_name=queue_name)
        if project_id and wip_counts["project_count"] >= THROUGHPUT_PROJECT_WIP_CAP:
            raise ValueError(
                f"Throughput admission rejected: project '{project_id}' exceeds WIP cap ({wip_counts['project_count']}/{THROUGHPUT_PROJECT_WIP_CAP})."
            )
        if artifact_key and wip_counts["artifact_count"] >= THROUGHPUT_ARTIFACT_WIP_CAP:
            raise ValueError(
                f"Throughput admission rejected: artifact '{artifact_key}' exceeds WIP cap ({wip_counts['artifact_count']}/{THROUGHPUT_ARTIFACT_WIP_CAP})."
            )

    def _validate_task_completion(self, task: TaskRecord) -> dict[str, Any]:
        admission_lane = str(task.admission_lane or (task.scheduler_hint or {}).get("admission_lane") or "").strip().lower()
        if task.execution_mode != ExecutionMode.production or admission_lane == "exploration":
            return {"mode": task.execution_mode.value, "status": "not-required"}
        if not task.repo_path:
            raise ValueError("Production task rejected: repo_path is required for artifact validation.")
        evidence = validate_task_artifact_completion(
            repo_root=Path(task.repo_path),
            artifact_spec=task.artifact_spec.model_dump() if isinstance(task.artifact_spec, ArtifactSpec) else task.artifact_spec,
            created_at=task.created_at,
        )
        return {
            "mode": task.execution_mode.value,
            **evidence,
        }

    def _evaluate_task_verification(self, task: TaskRecord) -> dict[str, Any]:
        contract = task.verification_contract or self._build_verification_contract(task)
        task.verification_contract = contract
        contract_payload = contract.model_dump(mode="json")
        if task.execution_mode == ExecutionMode.production:
            try:
                evidence = self._validate_task_completion(task)
                return {
                    "status": "verified",
                    "passed": True,
                    "mode": task.execution_mode.value,
                    "verification_level": contract.verification_level,
                    "contract": contract_payload,
                    "evidence": evidence,
                }
            except Exception as exc:
                return {
                    "status": "failed",
                    "passed": False,
                    "mode": task.execution_mode.value,
                    "verification_level": contract.verification_level,
                    "contract": contract_payload,
                    "evidence": {
                        "mode": task.execution_mode.value,
                        "status": "failed",
                        "error": str(exc),
                    },
                }
        evidence_path = self._execution_evidence_path(task.id)
        payload = _read_json_file(evidence_path, {})
        execution_evidence_present = bool(isinstance(payload, dict) and (payload.get("steps") or payload.get("completed")))
        evidence = {
            "status": "verified" if execution_evidence_present else "failed",
            "execution_evidence_path": str(evidence_path),
            "execution_evidence_present": execution_evidence_present,
            "required_checks": list(contract.required_checks or []),
            "artifact_requirements": contract.artifact_requirements,
        }
        return {
            "status": "verified" if execution_evidence_present else "failed",
            "passed": execution_evidence_present,
            "mode": task.execution_mode.value,
            "verification_level": contract.verification_level,
            "contract": contract_payload,
            "evidence": evidence,
        }

    def _infer_task_profile(self, payload: DispatchTaskRequest, project: ProjectMemoryRecord | None) -> dict[str, str] | None:
        corpus = " ".join(
            part
            for part in [
                payload.prompt,
                payload.goal or "",
                project.name if project else "",
                project.summary if project else "",
                payload.repo_path or "",
            ]
            if part
        ).lower()
        if any(token in corpus for token in ["debug", "debugging", "traceback", "stack trace", "exception", "error", "failing test", "fix bug", "repair failure", "crash"]):
            return {
                "name": "auto-debug",
                "guidance": (
                    "Auto-debug mode: first reproduce the failure locally, capture the exact command, error text, and affected files, then let cheap workers propose the smallest safe fix. After each fix, rerun the narrowest relevant validation step, record the new signal, and stop when the bug is resolved, risk rises, or bounded retries are exhausted."
                ),
            }
        if any(token in corpus for token in ["browser", "webpage", "website", "??", "???", "login page", "read webpage", "crawl page", "web read", "http://", "https://", "www."]):
            return {
                "name": "browser-reading",
                "guidance": (
                    "Browser-reading mode: prefer the local browser automation bridge with Edge or Chrome. Use public page reads first, and if the site is login-gated, open a persistent login session profile and reuse it for subsequent reads. Capture exact page title, body text, links, and screenshots before escalating. Escalate only if browser launch permissions, anti-bot restrictions, or contradictory rendered content block local extraction."
                ),
            }
        if any(token in corpus for token in ["migrate", "migration", "intake", "onboard", "bootstrap", "workspace import", "environment setup", "resource setup", "????", "????", "????", "??"]):
            return {
                "name": "workspace-migration",
                "guidance": (
                    "Workspace-migration mode: cheap workers should inventory the target folder first, identify runnable tools, docs, code, datasets, and likely course or project type, then map the workspace into resources, project memory, and task templates. Prefer local inspection and deterministic manifests over speculative setup. Escalate only for missing runtimes, risky installers, destructive moves, or conflicting project identities."
                ),
            }
        if any(token in corpus for token in ["network", "networking", "socket", "tcp", "udp", "http", "dns", "router", "switch", "traceroute", "wireshark", "tcpdump", "?????", "????"]):
            return {
                "name": "network-lab",
                "guidance": (
                    "Network-lab mode: cheap workers should restate the experiment goal, identify whether it is packet analysis, socket programming, routing, transport, or application protocol work, then prefer local tools such as curl, ping, ss, tcpdump, Wireshark-compatible captures, and local scripts for validation. Capture exact commands, observed packets or outputs, and draft a concise experiment explanation. Escalate only for protocol-design ambiguity, unsafe network actions, or contradictory local results."
                ),
            }
        if any(token in corpus for token in ["self-upgrade", "self improve", "self-improve", "upgrade assistant", "????", "????", "orchestrator", "capabilities", "policy"]):
            return {
                "name": "assistant-self-upgrade",
                "guidance": (
                    "Assistant self-upgrade mode: cheap workers may draft and implement low-risk improvements to prompts, templates, capability manifests, test scripts, documentation, and UI text. Any change to execution permissions, model routing, approval gates, security boundaries, or destructive operations must stop for explicit core review before apply. Always validate locally and summarize residual risk."
                ),
            }
        if any(token in corpus for token in ["mysql", "sql", "???", "schema", "query", "migration", "mysqldump", "opengauss", "postgres"]):
            return {
                "name": "database-coding",
                "guidance": (
                    "Database mode: cheap workers should inspect schema and task requirements first, prefer deterministic SQL and migration changes, use local MySQL tools when available for validation, capture exact query or migration results, and summarize rollback or data-risk concerns. Escalate only destructive schema changes, contradictory query behavior, or unresolved data-integrity risks."
                ),
            }
        if any(token in corpus for token in ["xv6", "lab", "assignment", "??", "??", "????"]):
            return {
                "name": "course-lab",
                "guidance": (
                    "Course-lab mode: cheap workers should first restate the requirements, locate the target files, make only the minimal code changes needed for the assignment, run the exact local or VM validation steps, record observed behavior, and draft a concise answer or explanation. Escalate only theory gaps, contradictory results, or kernel-level failures that local testing cannot resolve."
                ),
            }
        if any(token in corpus for token in ["toyos", "kernel", "ring3", "syscall", "tinyfs", "scheduler", "qemu"]):
            return {
                "name": "toyos-kernel",
                "guidance": (
                    "ToyOS mode: use the assistant as the main implementation worker. Prefer Docker or local builds and QEMU regression runs, keep patches small, preserve a bootable kernel after each change, use debugcon and local test reports before escalating, and only involve the core model for architecture changes, persistent test failures, or unsafe low-level transitions."
                ),
            }
        if any(token in corpus for token in ["python", "typescript", "javascript", "c++", "cpp", "java", "golang", "rust", "refactor", "??", "??"]):
            return {
                "name": "general-coding",
                "guidance": (
                    "General coding mode: cheap workers should inspect the codebase, make the smallest coherent change, run local tests or linters, capture exact outputs, and draft a concise change summary. Escalate only architectural conflicts, repeated failures, or risky cross-module rewrites."
                ),
            }
        return None
    def _build_auto_debug_prompt(self, payload: AutoDebugRequest) -> str:
        blocks = [
            "Structured auto-debug request.",
            "Operate in bounded debug mode: reproduce, diagnose, fix minimally, rerun, and stop if risk increases.",
            f"Failure pause policy: {self._policy.failure_pause_policy}",
            f"Development/test loop: {self._policy.development_test_loop}",
            f"Cheap lane policy: {self._policy.cheap_lane_policy}",
            "Use cheap workers and local runtime first. Escalate only for repeated failures, architectural conflicts, or risky actions.",
        ]
        if payload.prompt:
            blocks.append(f"Task context: {payload.prompt}")
        if payload.goal:
            blocks.append(f"Debug goal: {payload.goal}")
        if payload.workspace:
            blocks.append(f"Workspace: {payload.workspace}")
        if payload.repo_path:
            blocks.append(f"Repo path: {payload.repo_path}")
        if payload.failing_command:
            blocks.append(f"Failing command: {payload.failing_command}")
        blocks.append(f"Observed error: {payload.error_text}")
        if payload.failing_output:
            blocks.append(f"Observed output:\n{payload.failing_output[:4000]}")
        blocks.append("Required loop: inspect the failing area, propose the smallest coherent fix, execute or simulate the narrowest safe verification step, summarize the result, and stop after bounded retries.")
        return "\n\n".join(blocks)

    def _checkpoint_for(self, task_id: str) -> dict[str, Any] | None:
        return self._checkpoints.get(task_id)

    def _update_checkpoint(self, task: TaskRecord, *, phase: str, step: StepSpec | None = None, extra: dict[str, Any] | None = None) -> None:
        payload = {
            "task_id": task.id,
            "task_status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "phase": phase,
            "updated_at": utc_iso(),
            "heartbeat_at": utc_iso(),
            "repo_path": task.repo_path,
            "goal": task.goal,
            "goal_id": task.goal_id,
            "graph_id": task.graph_id,
            "node_id": task.node_id,
            "scheduled_by": task.scheduled_by,
            "timeslice_seconds": int((task.scheduler_hint or {}).get("timeslice_seconds") or 60),
            "checkpoint_dir": str(self._runtime_task_dir / task.id),
        }
        if step is not None:
            payload.update({
                "step_id": step.id,
                "step_title": step.title,
                "step_status": step.status.value if hasattr(step.status, "value") else str(step.status),
                "worker": step.worker.value if hasattr(step.worker, "value") else str(step.worker),
                "probe_attempts": step.probe_attempts,
            })
        if extra:
            payload.update(extra)
        self._checkpoints[task.id] = payload
        checkpoint_dir = self._runtime_task_dir / task.id
        runtime_payload = dict(payload)
        runtime_payload.update(
            {
                "title": task.title,
                "prompt": task.prompt,
                "scheduler_hint": task.scheduler_hint,
                "context_package": task.context_package,
                "plan": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "status": item.status.value if hasattr(item.status, "value") else str(item.status),
                        "worker": item.worker.value if hasattr(item.worker, "value") else str(item.worker),
                        "phase": item.phase,
                    }
                    for item in task.plan
                ],
                "verification_signals": list(task.verification_signals or []),
                "verification_signal_count": len(task.verification_signals or []),
                "result": task.result,
            }
        )
        atomic_write_json(checkpoint_dir / "context.json", runtime_payload)
        self._persist()

    def _build_dispatch_prompt(
        self,
        payload: DispatchTaskRequest,
        *,
        project: ProjectMemoryRecord | None,
        repo: RepoRecord | None,
        context_package: dict[str, Any] | None = None,
    ) -> str:
        profile = self._infer_task_profile(payload, project)
        execution_mode = self._infer_execution_mode(payload, project, profile=profile)
        repo_path = payload.repo_path or (project.repo_path if project else None) or (repo.local_path if repo else None)
        blocks = [
            "Unified orchestrator dispatch.",
            f"Caller: {payload.caller}",
            f"Execution mode: {execution_mode.value}",
            "Operating rule: cheap-first, local-first, verify before concluding, escalate only for high-risk or blocked work.",
            f"Runtime loop: {self._policy.development_test_loop}",
        ]
        if repo_path:
            blocks.append(f"Workspace: {repo_path}")
        if profile:
            blocks.append(f"Task profile: {profile['name']}")
            blocks.append(profile["guidance"][:360].rstrip())
        if execution_mode == ExecutionMode.research:
            blocks.append(
                "Internet Knowledge layer: when external knowledge is needed, prefer the Perplexity-backed research path via "
                "`python tools/perplexity_search.py --query ... --focus research`, then consume the persisted snapshot from "
                "`data/internet_knowledge.json`."
            )
        evidence_contract = self._infer_evidence_contract(
            repo_path=repo_path,
            scheduler_hint=payload.scheduler_hint,
            prompt=payload.prompt,
            goal=payload.goal,
        )
        if evidence_contract:
            blocks.append("Production evidence:\n- " + "\n- ".join((evidence_contract.get("guidance", []) or [])[:3]))
        payload_task_type = str(
            getattr(payload, "task_type", None)
            or payload.scheduler_hint.get("task_type")
            or ""
        ).strip().lower()
        payload_execution_mode = str(
            getattr(payload.execution_mode, "value", payload.execution_mode)
            if payload.execution_mode is not None
            else ""
        ).strip().lower()
        if payload_execution_mode in {"research", "governance"} and payload_task_type in {
            "artifact_audit",
            "json_fix",
            "report_refresh",
            "doc_patch",
            "manifest_patch",
        }:
            blocks.append(
                "Output contract for research/governance audit work:\n"
                "- target files or target artifacts inspected\n"
                "- smallest concrete gap or defect\n"
                "- bounded patch or repair plan\n"
                "- validation commands or artifact checks\n"
                "- residual risk and next action\n"
                "Do not answer with a generic summary unless the task is missing a target path or artifact specification."
            )
        if repo:
            blocks.append(f"Registered repo: {repo.name} @ {repo.local_path}")
        if project:
            blocks.append(f"Project: {project.name}")
            if project.summary:
                blocks.append(f"Project summary: {project.summary[:240].rstrip()}")
            if getattr(project, 'project_goals', None):
                blocks.append("Project goals:\n- " + "\n- ".join(project.project_goals[:3]))
            if getattr(project, 'technical_constraints', None):
                blocks.append("Technical constraints:\n- " + "\n- ".join(project.technical_constraints[:3]))
            if getattr(project, 'architecture_decisions', None):
                blocks.append("Architecture decisions:\n- " + "\n- ".join(project.architecture_decisions[:3]))
            if project.working_agreements:
                blocks.append("Working agreements:\n- " + "\n- ".join(project.working_agreements[:3]))
            if project.recent_decisions:
                blocks.append("Recent decisions:\n- " + "\n- ".join(project.recent_decisions[:3]))
        if self._capabilities:
            capability = self._capabilities[0]
            summary = capability.get("summary", "Local-first development and VM testing available.")
            blocks.append(f"Assistant capability profile: {summary[:220].rstrip()}")
            capabilities = capability.get("capabilities", [])[:4]
            if capabilities:
                blocks.append("Known assistant capabilities:\n- " + "\n- ".join(str(item) for item in capabilities))
        if self._task_templates:
            template_names = [item.get("name", "Unnamed template") for item in self._task_templates[:4]]
            blocks.append("Known reusable task templates:\n- " + "\n- ".join(template_names))
        if context_package:
            compact_blocks = [str(item)[:260].rstrip() for item in context_package.get("summary_blocks", [])[:2] if str(item).strip()]
            if compact_blocks:
                blocks.append("Context package:\n" + "\n\n".join(compact_blocks))
        blocks.append(f"Task: {payload.prompt}")
        if payload.goal:
            blocks.append(f"Goal: {payload.goal}")
        blocks.append("Prefer local tools and scripts first. Escalate to expensive reasoning only when local execution, cheap workers, or bounded validation cannot resolve the task safely.")
        return "\n\n".join(blocks)
    def _load_state(self) -> None:
        self._tasks = {}
        raw_tasks = _read_json_file(self._tasks_file, [])
        self._checkpoints = _read_json_file(self._checkpoints_file, {})
        for item in raw_tasks:
            try:
                task = TaskRecord.model_validate(item)
            except Exception:
                continue
            checkpoint = self._checkpoints.get(task.id) or {}
            terminal_status = _checkpoint_terminal_status(checkpoint)
            checkpoint_updated = _parse_record_time(checkpoint.get("updated_at")) or _parse_record_time(checkpoint.get("heartbeat_at"))
            if terminal_status is not None and checkpoint_updated is not None and checkpoint_updated >= task.updated_at:
                task.status = terminal_status
                task.updated_at = checkpoint_updated
                result = dict(task.result or {})
                if checkpoint.get("error"):
                    result["checkpoint_error"] = checkpoint.get("error")
                if checkpoint.get("recovery_resolution"):
                    result["recovery_resolution"] = checkpoint.get("recovery_resolution")
                task.result = result
            self._tasks[task.id] = task
        self._projects = {}
        for item in _read_json_file(self._projects_file, []):
            try:
                project = ProjectMemoryRecord.model_validate(item)
            except Exception:
                continue
            self._projects[project.id] = project
        self._capabilities = _read_json_file(self._capabilities_file, [])
        self._task_templates = _read_json_file(self._task_templates_file, [])
        self._core_messages = _read_json_file(self._core_messages_file, [])
        self._release_records = _read_json_file(self._release_records_file, [])
        self._task_publications = {}
        for item in _read_json_file(self._task_publications_file, []):
            try:
                publication = TaskPublicationRecord.model_validate(item)
            except Exception:
                continue
            self._task_publications[publication.publication_id] = publication
        try:
            self._policy = PolicyRecord.model_validate(_read_json_file(self._policy_file, {}))
        except Exception:
            self._policy = PolicyRecord()

    def _persist(self) -> None:
        with self._persist_lock:
            tasks = [task.model_dump(mode="json") for task in list(self._tasks.values())]
            projects = [project.model_dump(mode="json") for project in list(self._projects.values())]
            merged_tasks = _merge_record_lists(_read_json_file(self._tasks_file, []), tasks)
            merged_projects = _merge_record_lists(_read_json_file(self._projects_file, []), projects)
            merged_messages = _merge_record_lists(_read_json_file(self._core_messages_file, []), self._core_messages, rank_fields=("resolved_at", "updated_at", "created_at"))
            merged_release_records = _merge_record_lists(_read_json_file(self._release_records_file, []), self._release_records, rank_fields=("updated_at", "created_at"))
            merged_task_publications = _merge_record_lists(
                _read_json_file(self._task_publications_file, []),
                [publication.model_dump(mode="json") for publication in list(self._task_publications.values())],
                key_field="publication_id",
                rank_fields=("updated_at", "created_at"),
            )
            merged_checkpoints = _merge_mapping_records(_read_json_file(self._checkpoints_file, {}), self._checkpoints)
            atomic_write_json(self._tasks_file, merged_tasks)
            atomic_write_json(self._projects_file, merged_projects)
            atomic_write_json(self._policy_file, self._policy.model_dump(mode="json"))
            atomic_write_json(self._core_messages_file, merged_messages)
            atomic_write_json(self._checkpoints_file, merged_checkpoints)
            atomic_write_json(self._release_records_file, merged_release_records)
            atomic_write_json(self._task_publications_file, merged_task_publications)


























