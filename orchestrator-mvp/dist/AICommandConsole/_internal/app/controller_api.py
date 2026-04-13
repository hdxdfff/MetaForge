from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .executor_adapter import ExecutorManager
from .external_integrations import collect_external_integration_status, load_external_integration_bindings
from .io_utils import atomic_write_json, atomic_write_text

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONTROL_CENTER_STATE_PATH = DATA / "control_center_state.json"
CONTROLLER_STATE_PATH = DATA / "controller_state.json"
CONTROLLER_JOURNAL_PATH = DATA / "controller_journal.jsonl"
TASKS_PATH = DATA / "tasks.json"
VERIFICATION_STATUS_PATH = DATA / "verification_status.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"
RUNTIME_EPOCH_PATH = DATA / "runtime_epoch.json"
REPAIR_QUEUE_PATH = DATA / "controller_repair_queue.json"
RELEASE_QUEUE_PATH = DATA / "controller_release_queue.json"
FACTORY_DAEMON_LOG_PATH = DATA / "factory_daemon.log"

app = FastAPI(title="MetaForge Controller API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
EXECUTOR_MANAGER = ExecutorManager()


class ActionEnvelope(BaseModel):
    actor: str = "webui"
    source: str = "open-webui"
    reason: str | None = None


class GoalActivateRequest(ActionEnvelope):
    goal_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    queue_name: str | None = None


class TaskDecisionRequest(ActionEnvelope):
    task_id: str = Field(min_length=1)


class RepairScheduleRequest(ActionEnvelope):
    repair_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    details: str | None = None
    target_workspace: str | None = None


class DangerActionRequest(ActionEnvelope):
    confirm: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _append_journal(entry: dict[str, Any]) -> None:
    existing = []
    if CONTROLLER_JOURNAL_PATH.exists():
        try:
            existing = CONTROLLER_JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
        except Exception:
            existing = []
    existing.append(json.dumps(entry, ensure_ascii=False))
    atomic_write_text(CONTROLLER_JOURNAL_PATH, "\n".join(existing) + "\n")


def _default_controller_state() -> dict[str, Any]:
    return {
        "updated_at": None,
        "active_goal": None,
        "queue": {"paused": False, "reason": ""},
        "last_action": None,
        "pending_repairs": [],
        "pending_release_requests": [],
    }


def _read_controller_state() -> dict[str, Any]:
    state = _default_controller_state()
    state.update(_load_json(CONTROLLER_STATE_PATH, {}))
    return state


def _write_controller_state(update: dict[str, Any]) -> dict[str, Any]:
    state = _read_controller_state()
    state.update(update)
    state["updated_at"] = _utc_now()
    _write_json(CONTROLLER_STATE_PATH, state)
    return state


def _read_tasks() -> list[dict[str, Any]]:
    tasks = _load_json(TASKS_PATH, [])
    return tasks if isinstance(tasks, list) else []


def _write_tasks(tasks: list[dict[str, Any]]) -> None:
    _write_json(TASKS_PATH, tasks)


def _read_verification() -> dict[str, Any]:
    verification = _load_json(VERIFICATION_STATUS_PATH, {})
    return verification if isinstance(verification, dict) else {}


def _read_artifacts() -> dict[str, Any]:
    artifacts = _load_json(ARTIFACT_REGISTRY_PATH, {})
    return artifacts if isinstance(artifacts, dict) else {}


def _read_control_center_state() -> dict[str, Any]:
    control = _load_json(CONTROL_CENTER_STATE_PATH, {})
    if not isinstance(control, dict):
        control = {}
    control.setdefault("paused", False)
    control.setdefault("status", "active")
    control.setdefault("reason", "")
    control.setdefault("resident", True)
    return control


def _write_control_center_state(*, paused: bool, reason: str, actor: str, source: str) -> dict[str, Any]:
    state = _read_control_center_state()
    state["paused"] = paused
    state["status"] = "paused" if paused else "active"
    state["reason"] = reason
    state["updated_at"] = _utc_now()
    state["actor"] = actor
    state["source"] = source
    _write_json(CONTROL_CENTER_STATE_PATH, state)
    return state


def _runtime_epoch() -> dict[str, Any]:
    epoch = _load_json(RUNTIME_EPOCH_PATH, {})
    return epoch if isinstance(epoch, dict) else {}


def _task_counts(tasks: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(task.get("status") or "unknown") for task in tasks)
    return {
        "total": len(tasks),
        "pending": counts.get("pending", 0),
        "queued": counts.get("queued", 0),
        "waiting_approval": counts.get("waiting_approval", 0),
        "active": sum(counts.get(status, 0) for status in ("planning", "running")),
        "terminal": sum(counts.get(status, 0) for status in ("completed", "failed", "timed_out", "cancelled")),
    }


def _pending_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pending_statuses = {"pending", "queued", "waiting_approval"}
    return [
        task
        for task in tasks
        if str(task.get("status") or "") in pending_statuses
    ][:20]


def _artifact_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    items = artifacts.get("artifacts") if isinstance(artifacts.get("artifacts"), list) else []
    recent = sorted(
        [item for item in items if isinstance(item, dict)],
        key=lambda item: str(
            (item.get("checks") or {}).get("latest_evidence_at")
            or item.get("updated_at")
            or item.get("artifact_id")
            or ""
        ),
        reverse=True,
    )[:8]
    return {
        "status": str(artifacts.get("status") or "unknown"),
        "artifact_count": int(artifacts.get("artifact_count") or len(items)),
        "real_artifact_count": int(artifacts.get("real_artifact_count") or 0),
        "valuable_artifact_count": int(artifacts.get("valuable_artifact_count") or 0),
        "recent": recent,
    }


def _recent_log_summary(hours: int = 24, limit: int = 20) -> dict[str, Any]:
    if not FACTORY_DAEMON_LOG_PATH.exists():
        return {
            "status": "missing",
            "log_path": str(FACTORY_DAEMON_LOG_PATH),
            "window_hours": hours,
            "line_count": 0,
            "matched_count": 0,
            "latest_tick": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "tail": [],
        }
    try:
        lines = FACTORY_DAEMON_LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return {
            "status": "unreadable",
            "log_path": str(FACTORY_DAEMON_LOG_PATH),
            "window_hours": hours,
            "line_count": 0,
            "matched_count": 0,
            "latest_tick": None,
            "first_seen_at": None,
            "last_seen_at": None,
            "tail": [],
        }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    pattern = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+tick=(?P<tick>\d+)\s+(?P<body>.*)$")
    matched: list[dict[str, Any]] = []
    latest_tick = None
    first_seen_at = None
    last_seen_at = None
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        ts_text = match.group("ts")
        try:
            ts = datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        tick = int(match.group("tick"))
        latest_tick = tick
        if first_seen_at is None:
            first_seen_at = ts.isoformat().replace("+00:00", "Z")
        last_seen_at = ts.isoformat().replace("+00:00", "Z")
        matched.append(
            {
                "timestamp": ts.isoformat().replace("+00:00", "Z"),
                "tick": tick,
                "body": match.group("body"),
            }
        )
    return {
        "status": "ok",
        "log_path": str(FACTORY_DAEMON_LOG_PATH),
        "window_hours": hours,
        "line_count": len(lines),
        "matched_count": len(matched),
        "latest_tick": latest_tick,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "tail": matched[-limit:],
    }


def _recent_output_summary() -> dict[str, Any]:
    artifacts = _read_artifacts()
    verification = _read_verification()
    return {
        "status": "ok",
        "window_hours": 24,
        "runtime": _runtime_summary(),
        "log": _recent_log_summary(),
        "artifacts": _artifact_summary(artifacts),
        "verification": {
            "status": verification.get("status"),
            "updated_at": verification.get("updated_at"),
            "release_gate": verification.get("release_gate", {}),
            "tool_health": verification.get("tool_health", {}),
            "ai_testing": verification.get("ai_testing", {}),
        },
    }


def _verification_summary() -> dict[str, Any]:
    verification = _read_verification()
    return {
        "status": str(verification.get("status") or "unknown"),
        "updated_at": verification.get("updated_at"),
        "release_gate": verification.get("release_gate", {}),
        "delayed_verification": verification.get("delayed_verification", {}),
        "runtime_health": verification.get("runtime_health", {}),
        "tool_health": verification.get("tool_health", {}),
        "ai_testing": verification.get("ai_testing", {}),
    }


def _runtime_summary() -> dict[str, Any]:
    tasks = _read_tasks()
    control = _read_control_center_state()
    artifacts = _read_artifacts()
    verification = _read_verification()
    epoch = _runtime_epoch()
    counts = _task_counts(tasks)
    return {
        "status": "healthy" if not control.get("paused") else "paused",
        "state_version": epoch.get("state_version"),
        "epoch_id": epoch.get("epoch_id"),
        "control_center": control,
        "tasks": counts,
        "verification": {
            "status": verification.get("status"),
            "updated_at": verification.get("updated_at"),
        },
        "artifacts": {
            "status": artifacts.get("status"),
            "artifact_count": artifacts.get("artifact_count", 0),
            "real_artifact_count": artifacts.get("real_artifact_count", 0),
        },
    }


def _controller_topology() -> dict[str, Any]:
    return {
        "version": "v1",
        "ssot": {
            "name": "Core Controller",
            "responsibilities": [
                "state model",
                "policy",
                "queue",
                "memory",
                "verification gates",
                "artifact ledger",
                "audit trail",
            ],
            "state_sources": [
                "data/controller_state.json",
                "data/controller_journal.jsonl",
                "data/tasks.json",
                "data/verification_status.json",
                "data/artifact_registry.json",
                "data/runtime_epoch.json",
                "data/controller_repair_queue.json",
                "data/controller_release_queue.json",
            ],
        },
        "layers": [
            {
                "name": "human_entry",
                "description": "Human-facing ingress for intent capture and result review.",
                "surfaces": ["Open WebUI"],
            },
            {
                "name": "control_surface",
                "description": "Operational console for status, approvals, and manual intervention.",
                "surfaces": ["Appsmith"],
            },
            {
                "name": "orchestration_layer",
                "description": "Event-driven and AI workflow orchestration with no SSOT authority.",
                "surfaces": ["n8n", "Dify"],
            },
            {
                "name": "execution_layer",
                "description": "Bounded execution workers and tool runners.",
                "surfaces": ["OpenHands", "Browser", "Shell", "Docker", "MCP tools"],
            },
            {
                "name": "evidence_layer",
                "description": "Artifacts, logs, metrics, and audit outputs that prove what happened.",
                "surfaces": ["Artifact registry", "Logs", "Metrics", "Verification reports"],
            },
        ],
        "integrations": {
            "live_status_endpoint": "/integrations/status",
            "bindings": load_external_integration_bindings(),
        },
        "interfaces": {
            "read_only": [
                "/health",
                "/runtime/summary",
                "/control/status",
                "/queue/status",
                "/tasks/pending",
                "/verification/status",
                "/artifacts/recent",
                "/integrations/status",
                "/topology",
            ],
            "controlled_write": [
                "/goal/activate",
                "/queue/pause",
                "/queue/resume",
                "/task/approve",
                "/task/reject",
                "/repair/schedule",
            ],
            "confirmation_gated": [
                "/daemon/restart",
                "/release/promote",
                "/queue/clear-stale",
                "/runtime/rotate-epoch",
            ],
        },
        "boundary_rules": [
            "Core Controller is the only state source.",
            "Appsmith may observe and approve, but it does not own state.",
            "n8n handles system automation and external events, not governance.",
            "Dify handles AI workflows, not release or priority decisions.",
            "OpenHands executes work and returns artifacts, patches, and test evidence.",
            "Open WebUI is only the human entry surface and is owned by a separate integration session.",
        ],
        "role_map": {
            "Open WebUI": {
                "role": "human_entry",
                "authority": "intent capture and result review only",
            },
            "Appsmith": {
                "role": "control_surface",
                "authority": "dashboards, approvals, manual intervention",
            },
            "n8n": {
                "role": "automation_orchestrator",
                "authority": "events, schedules, notifications, integrations",
            },
            "Dify": {
                "role": "ai_workflow_orchestrator",
                "authority": "workflow composition, tool calling, business AI flows",
            },
            "OpenHands": {
                "role": "execution_worker",
                "authority": "code, tests, patch output, evidence generation",
            },
            "Core Controller": {
                "role": "ssot",
                "authority": "policy, queue, memory, verification, audit",
            },
        },
        "delivery_sequence": [
            "Open WebUI captures intent or review request.",
            "Core Controller normalizes the request and records state.",
            "Appsmith visualizes the queue and provides manual intervention.",
            "n8n or Dify fans out automation and workflow steps.",
            "OpenHands or other execution adapters perform bounded work.",
            "Core Controller validates evidence and updates the ledger.",
        ],
    }


def _event(
    action: str,
    *,
    actor: str,
    source: str,
    ok: bool,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    entry = {
        "id": uuid4().hex,
        "timestamp": _utc_now(),
        "action": action,
        "actor": actor,
        "source": source,
        "ok": ok,
        "reason": reason,
        "payload": payload or {},
        "result": result or {},
    }
    _append_journal(entry)
    return entry


def _response(action: str, *, actor: str, source: str, summary: str, evidence: list[str]) -> dict[str, Any]:
    epoch = _runtime_epoch()
    return {
        "ok": True,
        "action": action,
        "state_version": epoch.get("state_version") or _utc_now(),
        "epoch_id": epoch.get("epoch_id"),
        "summary": summary,
        "evidence": evidence,
        "actor": actor,
        "source": source,
    }


@app.get("/health")
async def health() -> dict[str, Any]:
    runtime = _runtime_summary()
    return {
        "ok": True,
        "runtime": runtime,
        "control": runtime["control_center"],
        "tasks": runtime["tasks"],
        "verification": runtime["verification"],
        "artifacts": runtime["artifacts"],
    }


@app.get("/status", operation_id="get_status", tags=["metaforge-controller"])
async def status() -> dict[str, Any]:
    return _recent_output_summary()


@app.get("/output/recent", operation_id="get_recent_output", tags=["metaforge-controller"])
async def recent_output() -> dict[str, Any]:
    return _recent_output_summary()


@app.get("/runtime/summary")
async def runtime_summary() -> dict[str, Any]:
    return _runtime_summary()


@app.get("/control/status")
async def control_status() -> dict[str, Any]:
    control = _read_control_center_state()
    runtime = _runtime_summary()
    return {
        "control_center": control,
        "queue": {
            "paused": bool(control.get("paused")),
            "reason": control.get("reason"),
        },
        "runtime": runtime,
    }


@app.get("/queue/status")
async def queue_status() -> dict[str, Any]:
    tasks = _read_tasks()
    counts = _task_counts(tasks)
    return {
        "counts": counts,
        "pending_tasks": _pending_tasks(tasks),
    }


@app.get("/tasks/pending")
async def tasks_pending() -> list[dict[str, Any]]:
    return _pending_tasks(_read_tasks())


@app.get("/verification/status")
async def verification_status() -> dict[str, Any]:
    return _verification_summary()


@app.get("/artifacts/recent")
async def artifacts_recent() -> dict[str, Any]:
    artifacts = _read_artifacts()
    return _artifact_summary(artifacts)


@app.get("/topology")
async def topology() -> dict[str, Any]:
    return _controller_topology()


@app.get("/integrations/status")
async def integrations_status() -> dict[str, Any]:
    return collect_external_integration_status(executor_manager=EXECUTOR_MANAGER)


@app.post("/goal/activate")
async def activate_goal(payload: GoalActivateRequest) -> dict[str, Any]:
    state = _write_controller_state(
        {
            "active_goal": {
                "goal_id": payload.goal_id,
                "goal": payload.goal,
                "queue_name": payload.queue_name,
                "activated_at": _utc_now(),
                "actor": payload.actor,
                "source": payload.source,
            },
            "last_action": "goal.activate",
        }
    )
    _event(
        "goal.activate",
        actor=payload.actor,
        source=payload.source,
        ok=True,
        payload=payload.model_dump(mode="json"),
        result=state,
    )
    return _response(
        "goal.activate",
        actor=payload.actor,
        source=payload.source,
        summary=f"Activated goal {payload.goal_id}: {payload.goal}",
        evidence=["controller_state.json", "controller_journal.jsonl"],
    )


@app.post("/queue/pause")
async def queue_pause(payload: ActionEnvelope | None = None) -> dict[str, Any]:
    request = payload or ActionEnvelope()
    control = _write_control_center_state(
        paused=True,
        reason=request.reason or "Paused from controller API.",
        actor=request.actor,
        source=request.source,
    )
    _write_controller_state(
        {
            "queue": {"paused": True, "reason": control.get("reason") or ""},
            "last_action": "queue.pause",
        }
    )
    _event(
        "queue.pause",
        actor=request.actor,
        source=request.source,
        ok=True,
        payload=request.model_dump(mode="json"),
        result=control,
    )
    return _response(
        "queue.pause",
        actor=request.actor,
        source=request.source,
        summary=control.get("reason") or "Queue paused.",
        evidence=["control_center_state.json", "controller_journal.jsonl"],
    )


@app.post("/queue/resume")
async def queue_resume(payload: ActionEnvelope | None = None) -> dict[str, Any]:
    request = payload or ActionEnvelope()
    control = _write_control_center_state(
        paused=False,
        reason=request.reason or "Resumed from controller API.",
        actor=request.actor,
        source=request.source,
    )
    _write_controller_state(
        {
            "queue": {"paused": False, "reason": control.get("reason") or ""},
            "last_action": "queue.resume",
        }
    )
    _event(
        "queue.resume",
        actor=request.actor,
        source=request.source,
        ok=True,
        payload=request.model_dump(mode="json"),
        result=control,
    )
    return _response(
        "queue.resume",
        actor=request.actor,
        source=request.source,
        summary=control.get("reason") or "Queue resumed.",
        evidence=["control_center_state.json", "controller_journal.jsonl"],
    )


def _update_task_decision(task_id: str, *, status: str, actor: str, source: str, reason: str | None) -> dict[str, Any]:
    tasks = _read_tasks()
    updated = False
    task_snapshot: dict[str, Any] | None = None
    for task in tasks:
        if str(task.get("id") or "") != task_id:
            continue
        task["status"] = status
        task["updated_at"] = _utc_now()
        result = task.setdefault("result", {})
        if reason:
            result["controller_reason"] = reason
        result["controller_actor"] = actor
        result["controller_source"] = source
        updated = True
        task_snapshot = task
        break
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    _write_tasks(tasks)
    return task_snapshot or {}


@app.post("/task/approve")
async def task_approve(payload: TaskDecisionRequest) -> dict[str, Any]:
    task = _update_task_decision(
        payload.task_id,
        status="queued",
        actor=payload.actor,
        source=payload.source,
        reason=payload.reason,
    )
    _event(
        "task.approve",
        actor=payload.actor,
        source=payload.source,
        ok=True,
        payload=payload.model_dump(mode="json"),
        result=task,
    )
    return _response(
        "task.approve",
        actor=payload.actor,
        source=payload.source,
        summary=f"Approved task {payload.task_id}",
        evidence=["tasks.json", "controller_journal.jsonl"],
    )


@app.post("/task/reject")
async def task_reject(payload: TaskDecisionRequest) -> dict[str, Any]:
    task = _update_task_decision(
        payload.task_id,
        status="cancelled",
        actor=payload.actor,
        source=payload.source,
        reason=payload.reason,
    )
    _event(
        "task.reject",
        actor=payload.actor,
        source=payload.source,
        ok=True,
        payload=payload.model_dump(mode="json"),
        result=task,
    )
    return _response(
        "task.reject",
        actor=payload.actor,
        source=payload.source,
        summary=f"Rejected task {payload.task_id}",
        evidence=["tasks.json", "controller_journal.jsonl"],
    )


@app.post("/repair/schedule")
async def schedule_repair(payload: RepairScheduleRequest) -> dict[str, Any]:
    requests = _load_json(REPAIR_QUEUE_PATH, [])
    if not isinstance(requests, list):
        requests = []
    item = {
        "id": uuid4().hex,
        "repair_type": payload.repair_type,
        "title": payload.title,
        "details": payload.details,
        "target_workspace": payload.target_workspace,
        "actor": payload.actor,
        "source": payload.source,
        "created_at": _utc_now(),
        "status": "requested",
    }
    requests.append(item)
    _write_json(REPAIR_QUEUE_PATH, requests)
    _write_controller_state(
        {
            "pending_repairs": requests[-20:],
            "last_action": "repair.schedule",
        }
    )
    _event(
        "repair.schedule",
        actor=payload.actor,
        source=payload.source,
        ok=True,
        payload=payload.model_dump(mode="json"),
        result=item,
    )
    return _response(
        "repair.schedule",
        actor=payload.actor,
        source=payload.source,
        summary=f"Scheduled repair {payload.repair_type}: {payload.title}",
        evidence=["controller_repair_queue.json", "controller_journal.jsonl"],
    )


def _danger_action(action: str, payload: DangerActionRequest, *, label: str) -> dict[str, Any]:
    _event(
        action,
        actor=payload.actor,
        source=payload.source,
        ok=False,
        payload=payload.model_dump(mode="json"),
        result={"requires_confirmation": True, "confirm": payload.confirm},
        reason="confirmation-required",
    )
    if not payload.confirm:
        return {
            "ok": False,
            "action": action,
            "requires_confirmation": True,
            "summary": f"{label} requires explicit confirmation.",
            "evidence": ["controller_journal.jsonl"],
        }
    return _response(
        action,
        actor=payload.actor,
        source=payload.source,
        summary=f"{label} confirmation recorded.",
        evidence=["controller_journal.jsonl"],
    )


@app.post("/daemon/restart")
async def restart_daemon(payload: DangerActionRequest) -> dict[str, Any]:
    return _danger_action("daemon.restart", payload, label="Daemon restart")


@app.post("/release/promote")
async def promote_release_candidate(payload: DangerActionRequest) -> dict[str, Any]:
    if not payload.confirm:
        requests = _load_json(RELEASE_QUEUE_PATH, [])
        if not isinstance(requests, list):
            requests = []
        requests.append(
            {
                "id": uuid4().hex,
                "action": "release.promote",
                "actor": payload.actor,
                "source": payload.source,
                "created_at": _utc_now(),
                "status": "pending_confirmation",
            }
        )
        _write_json(RELEASE_QUEUE_PATH, requests)
        _event(
            "release.promote",
            actor=payload.actor,
            source=payload.source,
            ok=False,
            payload=payload.model_dump(mode="json"),
            result={"requires_confirmation": True},
            reason="confirmation-required",
        )
        return {
            "ok": False,
            "action": "release.promote",
            "requires_confirmation": True,
            "summary": "Release promotion requires explicit confirmation.",
            "evidence": ["controller_release_queue.json", "controller_journal.jsonl"],
        }
    return _danger_action("release.promote", payload, label="Release promotion")


@app.post("/queue/clear-stale")
async def clear_stale_queue(payload: DangerActionRequest) -> dict[str, Any]:
    return _danger_action("queue.clear_stale", payload, label="Clear stale queue")


@app.post("/runtime/rotate-epoch")
async def rotate_runtime_epoch(payload: DangerActionRequest) -> dict[str, Any]:
    return _danger_action("runtime.rotate_epoch", payload, label="Runtime epoch rotation")
