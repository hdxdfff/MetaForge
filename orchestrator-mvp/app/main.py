from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from .io_utils import atomic_write_json

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import read_network_runtime_config, settings, strategic_llm_api_style
from .executor_adapter import ExecutorManager
from .external_integrations import collect_external_integration_status, load_external_integration_bindings
from .model_usage import load_usage_snapshot
from .network_agent import NetworkAgent
from .provider_gateway import provider_gateway
from .models import (
    AutoDebugRequest,
    DispatchTaskRequest,
    GoalAdmissionRequest,
    PolicyRecord,
    ProjectMemoryUpsert,
    RepoPushRequest,
    RepoRegistration,
    TaskPublicationApproveRequest,
    TaskPublicationPublishRequest,
    TaskCreate,
    TaskPublicationRequest,
)
from .executor_adapter import ExecutorRunRequest
from .orchestrator import Orchestrator
from tools.risk_scan import read_incident_ledger, read_risk_status, run_risk_branch

app = FastAPI(title="Orchestrator MVP", version="0.6.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class _LazySingleton:
    def __init__(self, factory):
        self._factory = factory
        self._instance = None

    def _get(self):
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def __getattr__(self, item):
        return getattr(self._get(), item)


orchestrator = _LazySingleton(Orchestrator)
integration_executor_manager = _LazySingleton(ExecutorManager)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
app.state.network_agent = None

CONTROL_CENTER_STATE_PATH = Path(__file__).parent.parent / "data" / "control_center_state.json"
GOAL_BACKLOG_STATUS_PATH = Path(__file__).parent.parent / "data" / "goal_backlog_status.json"
TOOL_STACK_PATH = Path(__file__).parent.parent / "contracts" / "tool_stack.json"
FACTORY_STATE_PATH = Path(__file__).parent.parent / "data" / "factory_state.json"


def _default_control_center_state() -> dict:
    return {
        "paused": False,
        "status": "active",
        "updated_at": None,
        "reason": "",
        "resident": True,
    }


def _read_control_center_state() -> dict:
    import json as _json

    if not CONTROL_CENTER_STATE_PATH.exists():
        return _default_control_center_state()
    try:
        payload = _json.loads(CONTROL_CENTER_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_control_center_state()
    state = _default_control_center_state()
    state.update(payload)
    return state


def _write_control_center_state(paused: bool, reason: str = "") -> dict:
    state = _default_control_center_state()
    state.update(
        {
            "paused": paused,
            "status": "paused" if paused else "active",
            "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "reason": reason,
            "resident": True,
        }
    )
    atomic_write_json(CONTROL_CENTER_STATE_PATH, state)
    return state


def _read_tool_stack() -> dict:
    import json as _json

    default = {
        "version": "v1",
        "primary_interactive_surface": "Aider",
        "control_shells": ["OpenCode", "Goose"],
        "control_plane": "MetaForge",
        "long_task_executors": ["OpenHands", "Plandex"],
        "development_executors": ["Codex"],
        "inspection_surface": "Continue",
        "final_verification_boundary": ["Verification", "Artifact"],
        "routing": [],
    }
    if not TOOL_STACK_PATH.exists():
        return default
    try:
        payload = _json.loads(TOOL_STACK_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return default
    merged = dict(default)
    merged.update(payload)
    return merged


def _read_goal_backlog_status() -> dict:
    import json as _json

    if not GOAL_BACKLOG_STATUS_PATH.exists():
        return {}
    try:
        return _json.loads(GOAL_BACKLOG_STATUS_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _read_factory_state() -> dict:
    import json as _json

    if not FACTORY_STATE_PATH.exists():
        return {}
    try:
        return _json.loads(FACTORY_STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _read_goal_backlog_preview(limit: int = 3) -> list[dict]:
    backlog = _read_goal_backlog_status()
    candidates = backlog.get("dispatch_candidates")
    if not isinstance(candidates, list):
        return []
    return [candidate for candidate in candidates[: max(0, limit)] if isinstance(candidate, dict)]


def _bootstrap_payload() -> dict:
    control_center = _read_control_center_state()
    factory_state = _read_factory_state()
    goal_backlog = _read_goal_backlog_status()
    lightweight_control = {
        "paused": bool(control_center.get("paused")),
        "status": control_center.get("status") or "active",
        "updated_at": control_center.get("updated_at"),
        "reason": control_center.get("reason") or "",
        "resident": bool(control_center.get("resident", True)),
    }
    lightweight_factory = {
        "updated_at": factory_state.get("updated_at"),
        "daemon": factory_state.get("daemon") or {},
        "delivery_summary": factory_state.get("delivery_summary") or {},
        "control_layer": factory_state.get("control_layer") or {},
        "autonomy": factory_state.get("autonomy") or {},
        "release_ops": factory_state.get("release_ops") or {},
        "messages": factory_state.get("messages") or {},
        "task_runtime": factory_state.get("task_runtime") or {},
        "goal_primary": factory_state.get("goal_primary") or goal_backlog.get("goal_primary"),
        "goal_mode": factory_state.get("goal_mode") or goal_backlog.get("goal_mode"),
    }
    lightweight_goal_backlog = {
        "updated_at": goal_backlog.get("updated_at"),
        "goal_primary": goal_backlog.get("goal_primary"),
        "goal_mode": goal_backlog.get("goal_mode"),
        "goal_health": goal_backlog.get("goal_health"),
    }
    return {
        "control_center": lightweight_control,
        "factory_state": lightweight_factory,
        "goal_backlog": lightweight_goal_backlog,
        "goal_backlog_preview": _read_goal_backlog_preview(),
    }


def _delivery_summary_from_factory_state(factory_state: dict) -> dict:
    delivery = factory_state.get("delivery_summary") or {}
    if not delivery:
        task_runtime = factory_state.get("task_runtime") or {}
        by_status = task_runtime.get("by_status") or {}
        delivery = {
            "completed_tasks": int(by_status.get("completed") or 0) + int(by_status.get("released") or 0),
            "delivery_ready_tasks": int(by_status.get("delivery_ready") or 0),
            "released_tasks": int(by_status.get("released") or 0),
            "verification_failed_tasks": int(by_status.get("verification_failed") or 0),
        }
    return {
        "completed_tasks": int(delivery.get("completed_tasks") or 0),
        "delivery_ready_tasks": int(delivery.get("delivery_ready_tasks") or 0),
        "released_tasks": int(delivery.get("released_tasks") or 0),
        "verification_failed_tasks": int(delivery.get("verification_failed_tasks") or 0),
    }


def _integration_status_bundle() -> dict:
    bindings = load_external_integration_bindings()
    status = collect_external_integration_status(executor_manager=integration_executor_manager)
    summary = dict(status.get("summary") or {})
    services = status.get("services") if isinstance(status.get("services"), list) else []
    configured = int(summary.get("configured") or 0)
    total = int(summary.get("total") or 0)
    healthy = int(summary.get("healthy") or 0)
    complete = total > 0 and configured == total and healthy == total
    return {
        "configured": bool(bindings),
        "complete": complete,
        "summary": summary,
        "services": services,
        "updated_at": status.get("updated_at"),
        "bindings": bindings,
    }


@app.on_event("startup")
async def startup_event() -> None:
    # Keep browser startup fast and stable; network-agent bootstrap is disabled
    # here so the dashboard can open even when external probing is unhealthy.
    return


@app.on_event("shutdown")
async def shutdown_event() -> None:
    agent = getattr(app.state, "network_agent", None)
    if agent is not None:
        await agent.stop()


@app.get("/")
async def index() -> HTMLResponse:
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    asset_version = str(int((static_dir / "app.js").stat().st_mtime))
    html = html.replace("/static/app.js", f"/static/app.js?v={asset_version}")
    html = html.replace("/static/styles.css", f"/static/styles.css?v={asset_version}")
    bootstrap = _bootstrap_payload()
    injection = f"<script>window.__FACTORY_BOOTSTRAP__ = {json.dumps(bootstrap, ensure_ascii=False)};</script>"
    if "</head>" in html:
        html = html.replace("</head>", f"{injection}\n</head>", 1)
    else:
        html = f"{injection}\n{html}"
    return HTMLResponse(html)


@app.get("/api/bootstrap")
async def bootstrap() -> dict:
    return _bootstrap_payload()


@app.get("/api/control-center/status")
async def control_center_status() -> dict:
    control = _read_control_center_state()
    stats_payload = (await orchestrator.stats()).model_dump(mode="json")
    core_messages = await orchestrator.list_core_messages()
    goal_backlog = _read_goal_backlog_status()
    from tools.goal_storage_audit import run_goal_storage_audit

    goal_storage = run_goal_storage_audit()
    network_agent = getattr(app.state, "network_agent", None)
    network_state = (
        network_agent.get_state()
        if network_agent is not None
        else {"status": "disabled", "queue_size": 0}
    )
    risk_status = read_risk_status()
    integrations = _integration_status_bundle()
    return {
        **control,
        "stats": stats_payload,
        "delivery_summary": {
            "completed_tasks": stats_payload.get("completed_tasks", 0),
            "delivery_ready_tasks": stats_payload.get("delivery_ready_tasks", 0),
            "released_tasks": stats_payload.get("released_tasks", 0),
            "verification_failed_tasks": stats_payload.get("verification_failed_tasks", 0),
        },
        "goal_backlog": goal_backlog,
        "network": network_state,
        "risk_branch": {
            "status": risk_status.get("scan_status") or "unknown",
            "risk_count": risk_status.get("risk_count", 0),
            "open_incident_count": risk_status.get("open_incident_count", 0),
            "closed_incident_count": risk_status.get("closed_incident_count", 0),
            "updated_at": risk_status.get("updated_at"),
        },
        "open_core_messages": core_messages[:8],
        "core_message_count": len(core_messages),
        "goal_storage": goal_storage,
        "integrations": integrations,
    }


@app.post("/api/control-center/pause")
async def control_center_pause(payload: dict | None = None) -> dict:
    reason = (payload or {}).get("reason") or "Paused from control center."
    return _write_control_center_state(True, str(reason))


@app.post("/api/control-center/resume")
async def control_center_resume(payload: dict | None = None) -> dict:
    reason = (payload or {}).get("reason") or "Resumed from control center."
    return _write_control_center_state(False, str(reason))


@app.get("/api/goals")
async def list_goal_records(status: str | None = None) -> list[dict]:
    from tools.goal_registry import list_goals

    goals = list_goals()
    if status is None:
        return goals
    return [goal for goal in goals if goal.get("status") == status]


@app.get("/api/goals/audit")
async def goal_storage_audit() -> dict:
    from tools.goal_storage_audit import run_goal_storage_audit

    return run_goal_storage_audit()


@app.get("/api/goals/report")
async def goal_engine_report(limit: int = 8, sync: bool = False) -> dict:
    from tools.goal_registry import goal_report
    from tools.goal_runtime import sync_goal_runtime

    sync_payload = sync_goal_runtime() if sync else None
    payload = goal_report(top_n=max(1, min(limit, 20)))
    if sync_payload is not None:
        payload["runtime_sync"] = sync_payload
    return payload


@app.get("/api/goals/backlog")
async def goal_backlog_status() -> dict:
    return _read_goal_backlog_status()


@app.post("/api/goals/admit")
async def admit_goal(payload: GoalAdmissionRequest) -> dict:
    try:
        task = await orchestrator.admit_goal(payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/goals/sync")
async def sync_goals() -> dict:
    from tools.goal_runtime import sync_goal_runtime

    return sync_goal_runtime()


@app.get("/api/risk/status")
async def risk_status() -> dict:
    return read_risk_status()


@app.post("/api/risk/scan")
async def risk_scan(payload: dict | None = None) -> dict:
    payload = payload or {}
    return run_risk_branch(
        apply_repairs=bool(payload.get("apply_repairs")),
        source=str(payload.get("source") or "api"),
    )


@app.get("/api/incidents")
async def incidents(limit: int = 20) -> list[dict]:
    return read_incident_ledger(limit=limit)


@app.get("/api/security/status")
async def get_security_status(limit: int = 25) -> dict:
    from tools.security_status import security_status

    return security_status(limit=max(1, min(limit, 100)))


@app.get("/api/security/audit")
async def get_security_audit(limit: int = 50) -> dict:
    from tools.security_status import read_security_audit_tail

    return {"entries": read_security_audit_tail(limit=max(1, min(limit, 200)))}


@app.get("/api/health")
async def health() -> dict[str, str | bool | int | float | None | dict | list]:
    from tools.goal_storage_audit import run_goal_storage_audit

    policy = await orchestrator.get_policy()
    projects = await orchestrator.list_projects()
    capabilities = await orchestrator.list_capabilities()
    core_messages = await orchestrator.list_core_messages()
    goal_storage = run_goal_storage_audit()
    network_agent = getattr(app.state, "network_agent", None)
    network_state = (
        network_agent.get_state()
        if network_agent is not None
        else {"status": "disabled", "queue_size": 0}
    )
    usage = load_usage_snapshot()
    integrations = _integration_status_bundle()
    return {
        "status": "ok",
        "real_execution_enabled": settings.real_execution_enabled,
        "approval_mode": settings.approval_mode,
        "shell_backend": settings.shell_backend,
        "cheap_llm_configured": bool(settings.cheap_llm_api_key and settings.cheap_llm_base_url),
        "planner_configured": bool(settings.openai_api_key and settings.openai_base_url),
        "llm_gateway": {
            "cheap_base_url": settings.cheap_llm_base_url,
            "planner_base_url": settings.openai_base_url,
            "planner_api_style": strategic_llm_api_style(),
            "shared_gateway": settings.cheap_llm_base_url == settings.openai_base_url,
            "cheap_local_gateway": settings.cheap_llm_base_url.startswith("http://localhost:11434"),
            "planner_local_gateway": settings.openai_base_url.startswith("http://localhost:11434"),
        },
        "model_usage": {
            "demand_pressure": usage.get("demand_pressure"),
            "reasoning_allowed": usage.get("reasoning_allowed"),
            "strong_allowed": usage.get("strong_allowed"),
            "effective_ratio_source": usage.get("effective_ratio_source"),
            "reasoning_ratio": usage.get("reasoning_ratio"),
            "strong_ratio": usage.get("strong_ratio"),
        },
        "resource_count": len(await orchestrator.list_resources()),
        "repo_count": len(await orchestrator.list_repos()),
        "project_count": len(projects),
        "capability_count": len(capabilities),
        "core_message_count": len(core_messages),
        "goal_storage": goal_storage,
        "integrations": {
            "configured": integrations["configured"],
            "complete": integrations["complete"],
            "summary": integrations["summary"],
            "updated_at": integrations["updated_at"],
        },
        "policy_version": policy.version,
        "cheap_max_calls_per_task": settings.cheap_max_calls_per_task,
        "cheap_max_chars_per_task": settings.cheap_max_chars_per_task,
        "cheap_max_output_chars": settings.cheap_max_output_chars,
        "cheap_request_timeout_seconds": settings.cheap_request_timeout_seconds,
        "planner_request_timeout_seconds": settings.planner_request_timeout_seconds,
        "max_escalations_per_task": settings.max_escalations_per_task,
        "denied_command_pattern_count": len(settings.denied_command_patterns),
        "network_agent_enabled": settings.network_agent_enabled,
        "network_agent_status": network_state.get("status"),
        "external_queue_size": network_state.get("queue_size", 0),
        "current_proxy": network_state.get("current_proxy"),
        "provider_gateway": provider_gateway.get_state(),
    }


@app.get("/api/stats")
async def stats() -> dict:
    return (await orchestrator.stats()).model_dump(mode="json")


@app.post("/api/recovery/ensure")
async def ensure_execution_recovery() -> dict:
    return await orchestrator.ensure_execution_recovery()


@app.get("/api/policy")
async def get_policy() -> dict:
    return (await orchestrator.get_policy()).model_dump(mode="json")


@app.put("/api/policy")
async def update_policy(payload: PolicyRecord) -> dict:
    return (await orchestrator.update_policy(payload)).model_dump(mode="json")


@app.get("/api/projects")
async def list_projects() -> list[dict]:
    return [item.model_dump(mode="json") for item in await orchestrator.list_projects()]


@app.post("/api/projects")
async def upsert_project(payload: ProjectMemoryUpsert) -> dict:
    return (await orchestrator.upsert_project(payload)).model_dump(mode="json")


@app.get("/api/resources")
async def list_resources() -> list[dict]:
    return [item.model_dump(mode="json") for item in await orchestrator.list_resources()]


@app.get("/api/capabilities")
async def list_capabilities() -> list[dict]:
    return await orchestrator.list_capabilities()


@app.get("/api/task-templates")
async def list_task_templates() -> list[dict]:
    return await orchestrator.list_task_templates()


@app.get("/api/executors")
async def list_executors() -> dict:
    return await orchestrator.list_executors()


@app.get("/api/executors/{executor_id}/tasks/{task_id}")
async def get_executor_task(executor_id: str, task_id: str) -> dict:
    return await orchestrator.get_executor_task(executor_id, task_id)


@app.post("/api/executors/{executor_id}/run")
async def run_executor_task(executor_id: str, payload: ExecutorRunRequest) -> dict:
    try:
        return await orchestrator.run_executor_task(executor_id, payload)
    except (KeyError, NotImplementedError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/core-messages")
async def list_core_messages() -> list[dict]:
    return await orchestrator.list_core_messages()


@app.post("/api/core-messages")
async def post_core_message(payload: dict) -> dict:
    return await orchestrator.post_core_message(payload)


@app.post("/api/core-messages/{message_id}/resolve")
async def resolve_core_message(message_id: str, payload: dict | None = None) -> dict:
    try:
        return await orchestrator.resolve_core_message(
            message_id,
            resolution=str((payload or {}).get("resolution") or ""),
            status=str((payload or {}).get("status") or "resolved"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/core-messages/{message_id}/reopen")
async def reopen_core_message(message_id: str, payload: dict | None = None) -> dict:
    try:
        return await orchestrator.reopen_core_message(
            message_id,
            reason=str((payload or {}).get("reason") or ""),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/browser/read")
async def browser_read(payload: dict) -> dict:
    return await orchestrator.browser_read(payload)


@app.post("/api/browser/login-session")
async def browser_login_session(payload: dict) -> dict:
    return await orchestrator.browser_login_session(payload)


@app.get("/api/factory/market")
async def factory_market() -> dict:
    import json as _json

    path = Path(__file__).parent.parent / "factory" / "market" / "agent_scores.json"
    return _json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"agents": []}


@app.post("/api/factory/market/run")
async def factory_market_run() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "agent_market_loop.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "agent market failed"
        )
    return _json.loads(completed.stdout)


@app.get("/api/factory/architecture-proposals")
async def factory_architecture_proposals() -> list[dict]:
    import json as _json

    path = Path(__file__).parent.parent / "factory" / "evaluations" / "architecture_proposals.json"
    return _json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@app.post("/api/factory/architecture-search")
async def factory_architecture_search() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "architecture_search.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "architecture search failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/factory/product-ideas")
async def factory_product_ideas() -> list[dict]:
    import json as _json

    path = Path(__file__).parent.parent / "factory" / "goals" / "product_ideas.json"
    return _json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


@app.post("/api/factory/product-discovery")
async def factory_product_discovery() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "product_discovery.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "product discovery failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/system/templates")
async def system_templates() -> list[dict]:
    import json as _json

    root = Path(__file__).parent.parent / "templates" / "systems"
    items = []
    for template in sorted(root.glob("*/template.json")):
        items.append(_json.loads(template.read_text(encoding="utf-8")))
    return items


@app.post("/api/system/generate")
async def system_generate(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    template_id = str(payload.get("template_id") or "").strip()
    project_name = str(payload.get("project_name") or "").strip()
    if not template_id or not project_name:
        raise HTTPException(status_code=400, detail="Missing template_id or project_name")
    script = root / "tools" / "generate_system_workspace.py"
    completed = subprocess.run(
        [sys.executable, str(script), template_id, project_name],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "system generate failed"
        )
    return _json.loads(completed.stdout)


@app.post("/api/system/evaluate")
async def system_evaluate(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    workspace = str(payload.get("workspace") or "").strip()
    template_id = str(payload.get("template_id") or "").strip()
    if not workspace or not template_id:
        raise HTTPException(status_code=400, detail="Missing workspace or template_id")
    script = root / "tools" / "evaluate_system_workspace.py"
    completed = subprocess.run(
        [sys.executable, str(script), workspace, template_id],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "system evaluate failed"
        )
    return _json.loads(completed.stdout)


@app.post("/api/system/fix")
async def system_fix(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    workspace = str(payload.get("workspace") or "").strip()
    template_id = str(payload.get("template_id") or "").strip()
    if not workspace or not template_id:
        raise HTTPException(status_code=400, detail="Missing workspace or template_id")
    script = root / "tools" / "fix_system_workspace.py"
    completed = subprocess.run(
        [sys.executable, str(script), workspace, template_id],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "system fix failed"
        )
    return _json.loads(completed.stdout)


@app.get("/api/execution-trace")
async def execution_trace(limit: int = 120) -> list[dict]:
    import sys

    root = Path(__file__).parent.parent
    sys.path.insert(0, str(root / "tools"))
    from execution_trace import read_tail

    return read_tail(limit)


@app.get("/api/evolution/status")
async def evolution_status() -> dict:
    import json as _json

    root = Path(__file__).parent.parent / "data"
    files = {
        "telemetry": root / "telemetry_events.json",
        "evaluation": root / "evolution_evaluation.json",
        "patches": root / "self_patch_candidates.json",
        "sandbox": root / "sandbox_upgrade_state.json",
        "patch_record": root / "evolution_patch_record.json",
        "adoption": root / "evolution_adoption_state.json",
    }
    payload = {}
    for key, file in files.items():
        payload[key] = (
            _json.loads(file.read_text(encoding="utf-8"))
            if file.exists()
            else {"status": "not-run"}
        )
    return payload


@app.get("/api/evolution/history")
async def evolution_history() -> list[dict]:
    import json as _json

    path = Path(__file__).parent.parent / "data" / "evolution_history.json"
    if not path.exists():
        return []
    return _json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/evolution/prepare-patch")
async def evolution_prepare_patch(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "prepare_self_patch_branch.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "prepare self patch failed",
        )
    result = _json.loads(completed.stdout)
    repo_id = payload.get("repo_id")
    prompt = str(payload.get("prompt") or "evolution patch")
    if repo_id:
        try:
            branch_info = await orchestrator.create_feature_branch(str(repo_id), prompt)
            result["git_branch"] = branch_info
        except Exception as exc:
            result["git_branch_error"] = str(exc)
    return result


@app.post("/api/evolution/promote")
async def evolution_promote(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "promote_sandbox_candidate.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "promote sandbox candidate failed",
        )
    result = _json.loads(completed.stdout)
    if result.get("status") == "candidate":
        await orchestrator.record_release(
            {
                "repo_id": payload.get("repo_id"),
                "repo_path": payload.get("repo_path"),
                "branch": result.get("branch"),
                "artifacts": result.get("artifacts", []),
                "status": "candidate",
                "notes": result.get("notes", ""),
            }
        )
    return result


@app.post("/api/evolution/run")
async def evolution_run() -> dict:
    if _read_control_center_state().get("paused"):
        raise HTTPException(status_code=409, detail="Control center is paused")
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    scripts = [
        "telemetry_store.py",
        "evaluator_loop.py",
        "self_patch_loop.py",
        "sandbox_upgrade_runner.py",
        "prepare_self_patch_branch.py",
        "promote_sandbox_candidate.py",
        "evolution_history_recorder.py",
    ]
    results = []
    for name in scripts:
        script = root / "tools" / name
        completed = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True, cwd=root
        )
        if completed.returncode != 0:
            raise HTTPException(
                status_code=500, detail=completed.stderr or completed.stdout or f"{name} failed"
            )
        results.append(_json.loads(completed.stdout))
    return {"ok": True, "steps": results}


@app.get("/api/meta-factory/status")
async def meta_factory_status() -> dict:
    import json as _json

    root = Path(__file__).parent.parent
    state_path = root / "data" / "meta_factory_state.json"
    candidates_path = root / "data" / "self_upgrade_candidates.json"
    state = (
        _json.loads(state_path.read_text(encoding="utf-8"))
        if state_path.exists()
        else {"status": "not-run"}
    )
    candidates = (
        _json.loads(candidates_path.read_text(encoding="utf-8")) if candidates_path.exists() else []
    )
    return {**state, "candidates": candidates}


@app.post("/api/meta-factory/run")
async def meta_factory_run() -> dict:
    if _read_control_center_state().get("paused"):
        raise HTTPException(status_code=409, detail="Control center is paused")
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "meta_factory_loop.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "meta factory loop failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/network/state")
async def network_state() -> dict:
    agent = getattr(app.state, "network_agent", None)
    network = {"status": "disabled", "queue_size": 0} if agent is None else agent.get_state()
    return {
        **network,
        "provider_gateway": provider_gateway.get_state(),
    }


@app.get("/api/network/provider-routes")
async def network_provider_routes() -> dict:
    return provider_gateway.get_state()


@app.get("/api/tool-stack")
async def tool_stack() -> dict:
    return _read_tool_stack()


@app.get("/api/network/log-tail")
async def network_log_tail(lines: int = 60) -> dict:
    log_path = Path(__file__).parent.parent / "data" / "network_keepalive.log"
    if not log_path.exists():
        return {"path": str(log_path), "lines": []}
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        tail = list(deque(handle, maxlen=max(1, min(lines, 300))))
    return {"path": str(log_path), "lines": [line.rstrip("\n") for line in tail]}


@app.get("/api/runtime/db-check")
async def db_runtime_check() -> dict:
    script = Path(__file__).parent.parent / "tools" / "db_runtime_check.py"
    import json as _json
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "db runtime check failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/network/tasks")
async def list_network_tasks() -> list[dict]:
    agent = getattr(app.state, "network_agent", None)
    if agent is None:
        return []
    return agent.list_tasks()


@app.get("/api/network/provider-gateway")
async def get_provider_gateway_state() -> dict:
    return provider_gateway.get_state()


@app.post("/api/network/tasks")
async def enqueue_network_task(payload: dict) -> dict:
    agent = getattr(app.state, "network_agent", None)
    if agent is None:
        raise HTTPException(status_code=400, detail="Network agent is disabled")
    try:
        return await agent.enqueue(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/network/reload")
async def reload_network_config() -> dict:
    network_cfg = read_network_runtime_config()
    agent = getattr(app.state, "network_agent", None)
    if agent is None:
        return (
            {"status": "disabled", "queue_size": 0} if not network_cfg["enabled"] else network_cfg
        )
    return agent.refresh_config(
        probe_urls=list(network_cfg["probe_urls"]),
        poll_seconds=int(network_cfg["poll_seconds"]),
        proxy_url=str(network_cfg["proxy_url"]),
        proxy_candidates=list(network_cfg["proxy_candidates"]),
        no_proxy=list(network_cfg["no_proxy"]),
    )


@app.post("/api/network/rotate-proxy")
async def rotate_network_proxy() -> dict:
    agent = getattr(app.state, "network_agent", None)
    if agent is None:
        return {"status": "disabled", "queue_size": 0}
    agent.rotate_proxy()
    return agent.get_state()


@app.get("/api/testing/scaffold")
async def testing_scaffold(workspace: str) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "generate_test_scaffold.py"
    completed = subprocess.run(
        [sys.executable, str(script), workspace], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "testing scaffold failed",
        )
    return _json.loads(completed.stdout)


@app.post("/api/deploy/prepare")
async def deploy_prepare(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    workspace = str(payload.get("workspace") or "").strip()
    if not workspace:
        raise HTTPException(status_code=400, detail="Missing workspace")
    root = Path(__file__).parent.parent
    script = root / "tools" / "prepare_deployment.py"
    completed = subprocess.run(
        [sys.executable, str(script), workspace], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "deployment prepare failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/maintenance/summary")
async def maintenance_summary() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "maintenance_summary.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "maintenance summary failed",
        )
    return _json.loads(completed.stdout)


@app.post("/api/reports/lab")
async def generate_lab_report(payload: dict) -> dict:
    import subprocess
    import sys
    from uuid import uuid4

    root = Path(__file__).parent.parent
    payload_dir = root / "data" / "report_payloads"
    out_dir = root / "data" / "reports"
    payload_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_id = payload.get("id") or f"lab-{uuid4().hex[:8]}"
    payload_path = payload_dir / f"{report_id}.json"
    out_path = out_dir / f"{report_id}.md"
    atomic_write_json(payload_path, payload)
    script = root / "tools" / "generate_lab_report.py"
    completed = subprocess.run(
        [sys.executable, str(script), str(payload_path), "--out", str(out_path)],
        capture_output=True,
        text=True,
        cwd=root,
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "report generation failed",
        )
    return {"ok": True, "report_id": report_id, "report_path": str(out_path)}


@app.get("/api/releases")
async def list_releases() -> list[dict]:
    return await orchestrator.list_release_records()


@app.post("/api/releases")
async def record_release(payload: dict) -> dict:
    return await orchestrator.record_release(payload)


@app.get("/api/reality-dashboard")
async def reality_dashboard_status() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    factory_state = _read_factory_state()
    script = root / "tools" / "audit_production.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "reality dashboard failed",
        )
    payload = _json.loads(completed.stdout)
    payload["delivery_summary"] = _delivery_summary_from_factory_state(factory_state)
    return payload


@app.get("/api/report-chain")
async def report_chain_status() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "report_chain.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=completed.stderr or completed.stdout or "report chain failed",
        )
    return _json.loads(completed.stdout)


@app.get("/api/release-manager")
async def release_manager_status() -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "release_manager.py"
    completed = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, cwd=root
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "release manager failed"
        )
    return _json.loads(completed.stdout)


@app.post("/api/release-manager/run")
async def release_manager_run(payload: dict) -> dict:
    import json as _json
    import subprocess
    import sys

    root = Path(__file__).parent.parent
    script = root / "tools" / "release_manager.py"
    args = [sys.executable, str(script)]
    if bool(payload.get("advance")):
        args.append("--advance")
    completed = subprocess.run(args, capture_output=True, text=True, cwd=root)
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500, detail=completed.stderr or completed.stdout or "release manager failed"
        )
    return _json.loads(completed.stdout)


@app.post("/api/repos/{repo_id}/feature-branch")
async def create_feature_branch(repo_id: str, payload: dict) -> dict:
    try:
        return await orchestrator.create_feature_branch(
            repo_id, str(payload.get("prompt") or "task")
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/repos")
async def list_repos() -> list[dict]:
    return [item.model_dump(mode="json") for item in await orchestrator.list_repos()]


@app.post("/api/repos")
async def register_repo(payload: RepoRegistration) -> dict:
    repo = await orchestrator.register_repo(payload)
    return repo.model_dump(mode="json")


@app.get("/api/repos/{repo_id}/status")
async def repo_status(repo_id: str) -> dict:
    try:
        return await orchestrator.repo_status(repo_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")


@app.post("/api/repos/{repo_id}/push")
async def push_repo(repo_id: str, payload: RepoPushRequest) -> dict:
    try:
        result = await orchestrator.push_repo(repo_id, payload)
        return result.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="Repo not found")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/tasks")
async def list_tasks() -> list[dict]:
    return [item.model_dump(mode="json") for item in await orchestrator.list_tasks()]


@app.post("/api/tasks")
async def create_task(payload: TaskCreate) -> dict:
    try:
        task = await orchestrator.create_task(payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/dispatch")
async def dispatch_task(payload: DispatchTaskRequest) -> dict:
    try:
        task = await orchestrator.dispatch_task(payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/task-publish")
async def publish_task(payload: TaskPublicationRequest) -> dict:
    try:
        task = await orchestrator.publish_task(payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/task-publish/draft")
async def draft_task_publication(payload: TaskPublicationRequest) -> dict:
    try:
        record = await orchestrator.create_task_publication(payload)
        return record.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/task-publish/{publication_id}/approve")
async def approve_task_publication(publication_id: str, payload: TaskPublicationApproveRequest) -> dict:
    try:
        record = await orchestrator.approve_task_publication(publication_id, payload)
        return record.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.post("/api/task-publish/{publication_id}/publish")
async def commit_task_publication(publication_id: str, payload: TaskPublicationPublishRequest) -> dict:
    try:
        task = await orchestrator.commit_task_publication(publication_id, payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.get("/api/task-publications")
async def list_task_publications() -> list[dict]:
    records = await orchestrator.list_task_publications()
    return [record.model_dump(mode="json") for record in records]


@app.post("/api/debug/auto")
async def auto_debug(payload: AutoDebugRequest) -> dict:
    try:
        task = await orchestrator.auto_debug_task(payload)
        return task.model_dump(mode="json")
    except ValueError as exc:
        status_code = 409 if "Throughput admission rejected" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str) -> dict:
    task = await orchestrator.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/tasks/{task_id}/verification-signals")
async def get_task_verification_signals(task_id: str) -> dict:
    task = await orchestrator.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    signals = await orchestrator.list_verification_signals(task_id)
    return {
        "task_id": task_id,
        "signal_count": len(signals),
        "signals": signals,
        "latest_signal": signals[-1] if signals else None,
    }


@app.get("/api/tasks/{task_id}/verification-signals/stream")
async def stream_task_verification_signals(task_id: str) -> StreamingResponse:
    task = await orchestrator.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    async def event_stream():
        queue = await orchestrator.subscribe_verification_signals(task_id)
        try:
            snapshot = await orchestrator.list_verification_signals(task_id)
            yield f"event: snapshot\ndata: {json.dumps({'task_id': task_id, 'signal_count': len(snapshot), 'signals': snapshot}, ensure_ascii=False)}\n\n"
            while True:
                signal = await queue.get()
                yield f"event: signal\ndata: {json.dumps(signal, ensure_ascii=False)}\n\n"
        finally:
            await orchestrator.unsubscribe_verification_signals(task_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/tasks/{task_id}/tree")
async def get_task_tree(task_id: str) -> dict:
    task = await orchestrator.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task_id,
        "decomposition_tree": task.get("decomposition_tree"),
        "decomposition_depth": task.get("decomposition_depth", 0),
        "max_decomposition_depth": task.get("max_decomposition_depth", 0),
    }


@app.get("/api/tasks/{task_id}/graph")
async def get_task_graph(task_id: str) -> dict:
    task = await orchestrator.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tree = task.get("decomposition_tree")
    dag = tree.get("dag") if isinstance(tree, dict) else None
    return {
        "task_id": task_id,
        "goal_admission": task.get("goal_admission", {}),
        "admission_lane": task.get("admission_lane"),
        "admission_reason": task.get("admission_reason"),
        "decomposition_tree": tree,
        "dag": dag or {},
    }


@app.get("/api/context/artifacts/{artifact_id}")
async def get_context_artifact(artifact_id: str, max_chars: int | None = None) -> dict:
    artifact = await orchestrator.get_context_artifact(artifact_id, max_chars=max_chars)
    if not artifact:
        raise HTTPException(status_code=404, detail="Context artifact not found")
    return artifact


@app.websocket("/ws/tasks/{task_id}")
async def watch_task(websocket: WebSocket, task_id: str) -> None:
    await orchestrator.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await orchestrator.disconnect(task_id, websocket)


