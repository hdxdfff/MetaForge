from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.signal_policy import is_runtime_blocker_state, summarize_signal_policy
from tools.strategy_engine import review_strategy_memory
from tools.execution_engine import python_command, run_hidden

LOCAL_TZ = datetime.now().astimezone().tzinfo or timezone.utc
WORKSPACE_ROOT = ROOT.parent
DATA = ROOT / "data"
IDENTITY_PATH = WORKSPACE_ROOT / "METAFORGE_OS_SYSTEM_IDENTITY.json"
WORLD_PATH = WORKSPACE_ROOT / "METAFORGE_OS_WORLD_MODEL.json"
CONTROL_CENTER_PATH = DATA / "control_center_state.json"
PID_PATH = DATA / "factory_daemon.pid"
OUT_PATH = DATA / "self_model_runtime.json"
HISTORY_PATH = DATA / "self_model_history.json"
EXECUTION_PATH = DATA / "self_model_execution.json"
TASKS_PATH = DATA / "tasks.json"
PRODUCTION_FOCUS_PATH = DATA / "production_focus_status.json"
PRIORITY_DIRECTIVES_PATH = DATA / "priority_directives.json"
SOAK_STATE_PATH = DATA / "soak_monitor_state.json"
CODEX_ROOT = ROOT.parent
PYTHON_EXE = CODEX_ROOT / "tools" / "python311-embed" / "python.exe"
DAEMON_STARTER = ROOT / "tools" / "start_factory_daemon.py"
FACTORYCTL_PY = CODEX_ROOT / "factoryctl.py"

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    _KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _KERNEL32.OpenProcess.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def _windows_process_handle(pid: int):
    handle = _KERNEL32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    return handle


def _windows_process_snapshot(pid: int) -> dict[str, Any] | None:
    handle = _windows_process_handle(pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        image_path = None
        if _KERNEL32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            image_path = buffer.value
        return {
            "Id": int(pid),
            "ProcessName": Path(image_path).name if image_path else f"pid_{pid}",
            "ImagePath": image_path,
        }
    finally:
        _KERNEL32.CloseHandle(handle)
TOYOS_BUILD_REPORT = WORKSPACE_ROOT / "generated" / "toy-os-demo" / "build-report.json"
TOYOS_QEMU_REPORT = WORKSPACE_ROOT / "generated" / "toy-os-demo" / "build" / "generic-qemu-smoke-report.json"
TOYOS_MANIFEST = WORKSPACE_ROOT / "generated" / "toy-os-demo" / "artifact_manifest.json"
DAEMON_STALE_SECONDS = 180
TASK_STALL_MINUTES = 20


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _parse_log_stamp(line: str) -> datetime | None:
    if not line.startswith("[") or "]" not in line:
        return None
    stamp = line[1 : line.index("]")]
    try:
        local_value = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
        return local_value.astimezone(timezone.utc)
    except Exception:
        return None


def _tail_lines(path: Path, limit: int = 20) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]


def _pid_running(pid: int | None) -> bool:
    if not pid:
        return False
    if sys.platform == "win32":
        handle = _windows_process_handle(int(pid))
        if not handle:
            return False
        try:
            return True
        finally:
            _KERNEL32.CloseHandle(handle)
    completed = subprocess.run(["ps", "-p", str(int(pid))], capture_output=True, text=True)
    return completed.returncode == 0


def _daemon_snapshot() -> dict[str, Any]:
    daemon = _load_json(DATA / "factory_daemon_state.json", {})
    if not daemon:
        return {
            "status": "unknown",
            "running": False,
            "started_at": None,
            "last_error": None,
            "last_tick_at": None,
            "cycle": None,
            "pid": None,
        }

    pid = daemon.get("pid")
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        except Exception:
            pass

    tick_at = _parse_utc(daemon.get("last_tick_at"))
    heartbeat_fresh = bool(
        tick_at
        and (datetime.now(timezone.utc) - tick_at) <= timedelta(seconds=DAEMON_STALE_SECONDS)
    )
    state_running = bool(daemon.get("running"))
    pid_running = _pid_running(pid)
    running = bool(
        heartbeat_fresh
        and (daemon.get("status") == "running" or state_running or pid_running)
    )
    if not running and pid_running and daemon.get("status") == "running":
        running = True

    normalized = dict(daemon)
    normalized["pid"] = pid
    normalized["running"] = running
    if running and normalized.get("status") in {None, "stopped", "stale", "unknown"}:
        normalized["status"] = "running"
    elif not running and normalized.get("status") == "running":
        normalized["status"] = "stopped"
    return normalized


def _control_center_snapshot() -> dict[str, Any]:
    return _load_json(
        CONTROL_CENTER_PATH,
        {
            "paused": False,
            "status": "active",
            "updated_at": None,
            "reason": "",
            "resident": True,
        },
    )


def _write_control_center(paused: bool, reason: str) -> dict[str, Any]:
    payload = _control_center_snapshot()
    payload.update(
        {
            "paused": paused,
            "status": "paused" if paused else "active",
            "updated_at": _utc_now(),
            "reason": reason,
            "resident": True,
        }
    )
    _save_json(CONTROL_CENTER_PATH, payload)
    return payload


def _priority_directive() -> dict[str, Any]:
    return _load_json(PRIORITY_DIRECTIVES_PATH, {}) or {}


def _production_focus_snapshot() -> dict[str, Any]:
    return _load_json(PRODUCTION_FOCUS_PATH, {}) or {}


def _toyos_artifact_snapshot() -> dict[str, Any]:
    build_report = _load_json(TOYOS_BUILD_REPORT, {}) or {}
    qemu_report = _load_json(TOYOS_QEMU_REPORT, {}) or {}
    manifest = _load_json(TOYOS_MANIFEST, {}) or {}
    return {
        "artifact_id": "toy-os-demo",
        "build_report_exists": TOYOS_BUILD_REPORT.exists(),
        "build_success": bool(build_report.get("build_success")),
        "build_ready": bool(build_report.get("build_ready")),
        "qemu_report_exists": TOYOS_QEMU_REPORT.exists(),
        "qemu_status": qemu_report.get("status"),
        "manifest_exists": TOYOS_MANIFEST.exists(),
        "manifest_reproducible": bool(manifest.get("reproducible")),
    }


def _build_state() -> dict[str, Any]:
    control = _control_center_snapshot()
    autonomy = _load_json(DATA / "autonomy_score.json", {})
    quality = _load_json(DATA / "quality_status.json", {})
    verification = _load_json(DATA / "verification_status.json", {})
    release_ops = _load_json(DATA / "release_operations_status.json", {})
    strategy_status = _load_json(DATA / "strategy_status.json", {})
    status_cache = _load_json(DATA / "status_cache.json", {})
    core_messages = _load_json(DATA / "core_messages.json", [])
    production_focus = _production_focus_snapshot()
    priority_directive = _priority_directive()
    soak_state = _load_json(SOAK_STATE_PATH, {}) or {}
    daemon = _daemon_snapshot()
    tasks_registry = _load_json(TASKS_PATH, [])

    active_statuses = {"queued", "planning", "running", "waiting_approval"}
    active_tasks = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "goal": item.get("goal"),
            "repo_path": item.get("repo_path"),
            "updated_at": item.get("updated_at"),
        }
        for item in tasks_registry
        if item.get("status") in active_statuses
    ]
    active_tasks.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    open_messages = [item for item in core_messages if item.get("status", "open") == "open"]
    open_errors = [item for item in open_messages if item.get("severity") == "error"]
    waiting_approval = [item for item in active_tasks if item.get("status") == "waiting_approval"]
    now_utc = datetime.now(timezone.utc)
    stalled_active = []
    for item in active_tasks:
        if item.get("status") in {"queued", "planning"}:
            continue
        updated = _parse_utc(item.get("updated_at"))
        if updated and (now_utc - updated) > timedelta(minutes=TASK_STALL_MINUTES):
            stalled_active.append(
                {
                    "id": item.get("id"),
                    "goal": item.get("goal"),
                    "status": item.get("status"),
                    "updated_at": item.get("updated_at"),
                    "stalled_minutes": round((now_utc - updated).total_seconds() / 60, 1),
                }
            )
    runtime_candidates: list[str] = []
    maturity_signals: list[str] = []
    release_signals: list[str] = []

    daemon_status = str(daemon.get("status") or "unknown")
    daemon_running = bool(daemon.get("running"))
    control_status = str(control.get("status") or "unknown")
    quality_status = str(quality.get("status") or "unknown")
    quality_score = _safe_float(quality.get("overall_score"))
    patch_gate_status = str((verification.get("patch_gate") or {}).get("status") or "unknown")
    delayed_verification_status = str(
        (verification.get("delayed_verification") or {}).get("status") or patch_gate_status
    )
    release_gate_status = str((verification.get("release_gate") or {}).get("status") or "unknown")
    release_train_status = str(
        (release_ops.get("release_train") or {}).get("status")
        or release_ops.get("release_train_status")
        or release_ops.get("status")
        or "unknown"
    )
    strategy_pattern_count = _safe_int(strategy_status.get("pattern_count"))
    strategy_active_pattern_count = _safe_int(strategy_status.get("active_pattern_count"))
    strategy_reuse_success_rate = _safe_float(strategy_status.get("reuse_success_rate"))

    if not daemon_running or is_runtime_blocker_state(daemon_status):
        runtime_candidates.append("daemon_unhealthy")
    if is_runtime_blocker_state(control_status):
        runtime_candidates.append("control_layer_unstable")
    if open_errors:
        maturity_signals.append("quality_attention")
    if delayed_verification_status != "pass":
        release_signals.append("verification_delay")
    if quality_status != "pass" and quality_score < 0.75:
        maturity_signals.append("quality_attention")
    queued_backlog = [item for item in active_tasks if item.get("status") in {"queued", "planning"}]
    if queued_backlog:
        maturity_signals.append("queued_task_backlog")
    if waiting_approval:
        release_signals.append("tasks_waiting_approval")
    if stalled_active:
        maturity_signals.append("active_task_stall")
    if release_gate_status == "blocked" or release_train_status == "blocked":
        release_signals.append("sampled_release_blocked")
    if strategy_pattern_count == 0:
        maturity_signals.append("strategy_memory_empty")
    elif strategy_active_pattern_count == 0:
        maturity_signals.append("strategy_needs_reinforcement")
    elif _safe_int(strategy_status.get("strategy_guided_terminal_tasks")) > 0 and strategy_reuse_success_rate < 0.5:
        maturity_signals.append("strategy_reuse_underperforming")
    if bool(control.get("paused")):
        release_signals.append("dispatch_paused")

    signal_policy = summarize_signal_policy(
        runtime_blockers=runtime_candidates,
        maturity_signals=maturity_signals,
        release_gate_signals=release_signals,
        source="self_model",
    )
    blockers = [str(item.get("code") or "") for item in signal_policy.get("runtime_blockers") or []]
    weak_signals = [str(item.get("code") or "") for item in signal_policy.get("maturity_signals") or []]
    release_signals = [str(item.get("code") or "") for item in signal_policy.get("release_gate_signals") or []]

    health = "healthy"
    if blockers:
        health = "degraded"

    autonomy_level = "full"
    if health == "degraded":
        autonomy_level = "restricted"
    elif weak_signals or release_signals:
        autonomy_level = "bounded"

    return {
        "updated_at": _utc_now(),
        "health": health,
        "control_status": control_status,
        "control_center": {
            "paused": bool(control.get("paused")),
            "reason": control.get("reason"),
            "updated_at": control.get("updated_at"),
        },
        "autonomy": {
            "stage": autonomy.get("stage"),
            "score": autonomy.get("score"),
            "level": autonomy_level,
        },
        "daemon": {
            "status": daemon_status,
            "running": daemon_running,
            "started_at": daemon.get("started_at"),
            "cycle": daemon.get("cycle"),
            "last_tick_at": daemon.get("last_tick_at"),
            "last_error": daemon.get("last_error"),
        },
        "tasks": {
            "active_count": len(active_tasks),
            "failed_count": sum(
                1 for item in tasks_registry if item.get("status") in {"failed", "timed_out"}
            ),
            "waiting_approval_count": len(waiting_approval),
            "queued_backlog_count": len(queued_backlog),
            "stalled_active_count": len(stalled_active),
            "stalled_active": stalled_active[:6],
            "active": active_tasks[:6],
        },
        "escalations": {
            "open_count": len(open_messages),
            "open_error_count": len(open_errors),
            "top_open": [
                {
                    "id": item.get("id"),
                    "severity": item.get("severity"),
                    "title": item.get("title"),
                }
                for item in open_messages[:5]
            ],
        },
        "verification": {
            "status": verification.get("status"),
            "patch_gate_status": patch_gate_status,
            "delayed_status": delayed_verification_status,
            "pending_checks": (verification.get("delayed_verification") or {}).get("pending_checks")
            or [],
            "release_gate_status": release_gate_status,
            "release_sample_failures": (verification.get("release_gate") or {}).get(
                "sample_failures"
            )
            or [],
            "runtime_health_status": (verification.get("runtime_health") or {}).get("status"),
            "compileall_passed": bool((verification.get("compileall") or {}).get("passed")),
        },
        "quality": {
            "status": quality_status,
            "score": quality_score,
        },
        "release_signals": release_signals,
        "release": {
            "status": release_ops.get("status"),
            "release_train_status": release_train_status,
        },
        "strategy": {
            "pattern_count": strategy_pattern_count,
            "active_pattern_count": strategy_active_pattern_count,
            "reuse_success_rate": strategy_reuse_success_rate,
            "valuable_artifact_ratio": _safe_float(strategy_status.get("valuable_artifact_ratio")),
            "pattern_score_variance": _safe_float(strategy_status.get("pattern_score_variance")),
            "top_patterns": (strategy_status.get("top_patterns") or [])[:3],
        },
        "resources": {
            "tool_health": (status_cache.get("tool_health") or {}).get("status"),
            "engineering_os": (status_cache.get("engineering_os") or {}).get("status"),
        },
        "production_focus": {
            "enabled": bool(production_focus.get("enabled")),
            "reason": production_focus.get("reason"),
            "primary_artifact_id": production_focus.get("primary_artifact_id"),
        },
        "priority_directive": {
            "highest_priority_project": priority_directive.get("highest_priority_project"),
            "force_single_product_mode": bool(priority_directive.get("force_single_product_mode")),
            "soak_focus_artifact_id": ((priority_directive.get("soak_focus") or {}).get("artifact_id")),
            "soak_required_hours": ((priority_directive.get("soak_focus") or {}).get("required_hours")),
        },
        "soak": {
            "status": soak_state.get("status"),
            "label": soak_state.get("label"),
            "report_path": soak_state.get("report_path"),
        },
        "toyos": _toyos_artifact_snapshot(),
        "signals": weak_signals,
        "blockers": blockers,
        "signal_policy": signal_policy,
    }


def _select_goal(state: dict[str, Any]) -> dict[str, Any]:
    blockers = set(state.get("blockers") or [])
    daemon = state.get("daemon") or {}
    tasks = state.get("tasks") or {}
    escalations = state.get("escalations") or {}
    verification = state.get("verification") or {}
    quality = state.get("quality") or {}
    control_center = state.get("control_center") or {}
    priority_directive = state.get("priority_directive") or {}
    toyos = state.get("toyos") or {}

    if "factory_daemon_unhealthy" in blockers:
        return {
            "primary": "stabilize_factory_daemon",
            "mode": "incident_response",
            "priority": "critical",
            "rationale": [
                f"daemon running={daemon.get('running')} status={daemon.get('status')}",
                "planner and worker continuity depend on daemon health",
            ],
        }
    if control_center.get("paused") and escalations.get("open_error_count", 0) == 0:
        return {
            "primary": "resume_normal_operation",
            "mode": "recovery",
            "priority": "high",
            "rationale": [
                "critical daemon blocker is cleared",
                "control center is still paused and should be resumed to restore throughput",
            ],
        }
    if escalations.get("open_error_count", 0) > 0:
        return {
            "primary": "clear_open_error_escalations",
            "mode": "operator_attention",
            "priority": "high",
            "rationale": [
                f"{escalations.get('open_error_count', 0)} open error escalations are blocking normal flow",
                "unresolved core errors increase risk of bad autonomous decisions",
            ],
        }
    if str(priority_directive.get("highest_priority_project") or "").strip().lower() == "toy-os-demo":
        return {
            "primary": "restore_toyos_delivery",
            "mode": "toyos_priority_mode",
            "priority": "critical",
            "rationale": [
                "priority directive pins ToyOS as the highest-priority project",
                f"ToyOS build_success={toyos.get('build_success')} qemu_report_exists={toyos.get('qemu_report_exists')}",
            ],
        }
    if tasks.get("stalled_active_count", 0) > 0:
        return {
            "primary": "recover_stalled_active_tasks",
            "mode": "throughput_recovery",
            "priority": "high",
            "rationale": [
                f"{tasks.get('stalled_active_count', 0)} active tasks are stale beyond the recovery window",
                "delivery should repair stalled execution before opening more throughput",
            ],
        }
    if tasks.get("waiting_approval_count", 0) > 0:
        return {
            "primary": "unblock_waiting_approvals",
            "mode": "throughput_recovery",
            "priority": "medium",
            "rationale": [
                f"{tasks.get('waiting_approval_count', 0)} tasks are waiting approval",
                "clearing approvals is the fastest way to restore task throughput",
            ],
        }
    if tasks.get("active_count", 0) > 0:
        return {
            "primary": "advance_active_delivery",
            "mode": "normal_execution",
            "priority": "medium",
            "rationale": [
                f"{tasks.get('active_count', 0)} active tasks are in progress",
                "delivery should stay execution-first while weak-control signals are handled off the critical path",
            ],
        }
    if verification.get("delayed_status") != "pass":
        return {
            "primary": "drain_verification_backlog",
            "mode": "verification_followup",
            "priority": "medium",
            "rationale": [
                f"delayed verification is {verification.get('delayed_status')}",
                "verification should catch up without blocking execution throughput",
            ],
        }
    if verification.get("release_gate_status") == "blocked":
        return {
            "primary": "clear_sampled_release_blockers",
            "mode": "release_review",
            "priority": "medium",
            "rationale": [
                f"release gate is blocked by sampled failures={verification.get('release_sample_failures')}",
                "release should hold only the sampled blockers while execution continues",
            ],
        }
    if (quality.get("score") or 0.0) < 0.75:
        return {
            "primary": "raise_quality_score",
            "mode": "quality_recovery",
            "priority": "medium",
            "rationale": [
                f"quality score is {quality.get('score')}",
                "low quality score should be repaired after active execution pressure is handled",
            ],
        }
    return {
        "primary": "expand_verified_throughput",
        "mode": "steady_state",
        "priority": "low",
        "rationale": [
            "no active critical blockers detected",
            "system can focus on verified throughput and capability growth",
        ],
    }


def _action(action_id: str, title: str, owner: str, expected_outcome: str) -> dict[str, Any]:
    return {
        "action": action_id,
        "title": title,
        "owner": owner,
        "preconditions": [],
        "expected_outcome": expected_outcome,
    }


def _plan_actions(goal: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    primary = goal.get("primary")
    daemon_running = bool(((state.get("daemon") or {}).get("running")))
    if primary == "restore_toyos_delivery":
        return [
            _action(
                "inspect_toyos_priority_status",
                "Inspect ToyOS priority directive and production focus state",
                "planner",
                "ToyOS priority mode is explicitly visible in the control plane",
            ),
            _action(
                "inspect_toyos_artifact_evidence",
                "Inspect ToyOS build, smoke, and manifest evidence",
                "auditor",
                "ToyOS artifact freshness and gaps are explicit",
            ),
            _action(
                "inspect_toyos_soak_state",
                "Inspect ToyOS-focused soak monitor state",
                "ops",
                "ToyOS soak progress is visible for stability confirmation",
            ),
        ]
    if primary == "stabilize_factory_daemon":
        actions = [
            _action(
                "inspect_daemon_state",
                "Inspect daemon status, last tick, and last error",
                "controller",
                "Current daemon failure mode is explicit and actionable",
            ),
            _action(
                "review_recent_daemon_log",
                "Review recent daemon log tail for the latest fault signature",
                "diagnostics",
                "A concrete fault signature is captured for repair or escalation",
            ),
        ]
        if not daemon_running:
            actions.append(
                _action(
                    "attempt_daemon_recovery",
                    "Attempt a bounded daemon restart",
                    "orchestrator",
                    "Daemon control loop is restarted for a clean recovery attempt",
                )
            )
        actions.append(
            _action(
                "freeze_noncritical_dispatch",
                "Pause noncritical dispatch until daemon health recovers",
                "orchestrator",
                "System load stays bounded during recovery",
            )
        )
        return actions
    if primary == "resume_normal_operation":
        return [
            _action(
                "resume_noncritical_dispatch",
                "Resume control center dispatch after recovery",
                "orchestrator",
                "Normal automated execution resumes",
            ),
            _action(
                "inspect_active_task_frontier",
                "Inspect the current active task frontier",
                "planner",
                "The next delivery bottleneck is visible",
            ),
        ]
    if primary == "clear_open_error_escalations":
        return [
            _action(
                "summarize_open_errors",
                "Summarize open error escalations by severity and title",
                "controller",
                "The blocking error set is visible to the planner",
            ),
            _action(
                "route_highest_severity_error",
                "Route the highest-severity escalation to the next repair lane",
                "planner",
                "The main blocking error has a bounded repair owner",
            ),
            _action(
                "hold_risky_promotion",
                "Hold risky promotion until the error backlog is reduced",
                "governor",
                "Autonomous actions stay inside bounded risk",
            ),
        ]
    if primary == "drain_verification_backlog":
        return [
            _action(
                "inspect_verification_snapshot",
                "Inspect delayed verification status and backlog reasons",
                "verification",
                "The delayed verification backlog is explicit",
            ),
            _action(
                "select_verification_repair_target",
                "Select one bounded verification repair target",
                "planner",
                "Verification work is reduced without freezing execution",
            ),
            _action(
                "keep_execution_open",
                "Keep execution lane open while verification catches up",
                "governor",
                "Execution throughput stays non-blocking",
            ),
        ]
    if primary == "clear_sampled_release_blockers":
        return [
            _action(
                "inspect_release_sample_gate",
                "Inspect sampled release blockers and failing evidence",
                "release_governor",
                "The sampled release blockers are explicit",
            ),
            _action(
                "select_release_blocker_repair_target",
                "Select one sampled release blocker for repair",
                "planner",
                "Release risk is reduced with bounded repair work",
            ),
            _action(
                "hold_sampled_release_only",
                "Hold sampled release promotion while execution continues",
                "release_governor",
                "Release stays bounded without stopping task execution",
            ),
        ]
    if primary == "raise_quality_score":
        return [
            _action(
                "inspect_quality_drivers",
                "Inspect quality score and candidate bottlenecks",
                "quality_system",
                "The main quality drag is identified",
            ),
            _action(
                "prioritize_quality_candidate",
                "Promote the highest-leverage quality candidate into the active plan",
                "planner",
                "Quality recovery work is explicit and bounded",
            ),
            _action(
                "monitor_score_recovery",
                "Monitor quality score changes after the next execution cycle",
                "observer",
                "Quality recovery can be measured instead of guessed",
            ),
        ]
    if primary == "unblock_waiting_approvals":
        return [
            _action(
                "list_waiting_approval_tasks",
                "List tasks currently waiting approval",
                "controller",
                "Approval-bound tasks are visible",
            ),
            _action(
                "prepare_operator_digest",
                "Prepare a short digest for the most important waiting approval",
                "planner",
                "Approval friction drops for the highest-value task",
            ),
            _action(
                "avoid_new_low_priority_dispatch",
                "Avoid adding low-priority work while approvals are blocked",
                "governor",
                "Queue pressure stays bounded",
            ),
        ]
    if primary == "recover_stalled_active_tasks":
        return [
            _action(
                "inspect_active_task_frontier",
                "Inspect stalled active tasks and the current task frontier",
                "planner",
                "The stalled execution set is explicit",
            ),
            _action(
                "run_runtime_maintenance",
                "Run runtime maintenance to reconcile stale execution state",
                "orchestrator",
                "Stale tasks and graph/task mismatches are reconciled",
            ),
            _action(
                "reset_orphaned_active_tasks",
                "Reset orphaned graph-backed tasks so the scheduler can redispatch them",
                "orchestrator",
                "Lost in-process work is returned to a dispatchable state",
            ),
            _action(
                "close_resolved_stalled_tasks",
                "Close stalled tasks whose incident goals are already satisfied",
                "orchestrator",
                "Recovered incidents stop occupying the active frontier",
            ),
            _action(
                "verify_active_task_recovery",
                "Verify that stalled active task count decreased after maintenance",
                "observer",
                "Recovery is measured from task state, not assumed",
            ),
        ]
    if primary == "advance_active_delivery":
        active = (state.get("tasks") or {}).get("active") or []
        first_task = active[0] if active else {}
        task_id = first_task.get("id") or "unknown"
        return [
            _action(
                "inspect_active_task_frontier",
                "Inspect the current active task frontier",
                "planner",
                "The next delivery bottleneck is visible",
            ),
            _action(
                "advance_top_active_task",
                f"Advance the top active task ({task_id}) with bounded execution",
                "worker",
                "At least one active task moves forward",
            ),
            _action(
                "verify_progress_after_execution",
                "Verify that active task progress changed after execution",
                "observer",
                "Delivery progress is measured from task state, not assumed",
            ),
        ]
    return [
        _action(
            "refresh_status_snapshot",
            "Refresh operating status before expanding throughput",
            "observer",
            "The system starts from a fresh state snapshot",
        ),
        _action(
            "select_next_verified_candidate",
            "Select the next verified candidate for execution",
            "planner",
            "Throughput growth stays aligned with verification",
        ),
        _action(
            "preserve_idle_readiness",
            "Preserve readiness for new bounded goals",
            "controller",
            "System can accept new work without losing control",
        ),
    ]


def _build_model() -> dict[str, Any]:
    identity = _load_json(IDENTITY_PATH, {})
    world = _load_json(WORLD_PATH, {})
    state = _build_state()
    goal = _select_goal(state)
    next_actions = _plan_actions(goal, state)
    return {
        "updated_at": _utc_now(),
        "identity": {
            "name": identity.get("name"),
            "system_id": identity.get("system_id"),
            "type": identity.get("type"),
            "mission": identity.get("mission"),
        },
        "world": {
            "workspace_root": world.get("workspace_root"),
            "primary_workspaces": world.get("primary_workspaces"),
            "runtime_surfaces": world.get("runtime_surfaces"),
        },
        "state": state,
        "goal": goal,
        "next_actions": next_actions,
    }


def _append_history(model: dict[str, Any]) -> None:
    history = _load_json(HISTORY_PATH, [])
    entry = {
        "updated_at": model.get("updated_at"),
        "health": ((model.get("state") or {}).get("health")),
        "goal": ((model.get("goal") or {}).get("primary")),
        "mode": ((model.get("goal") or {}).get("mode")),
        "blockers": ((model.get("state") or {}).get("blockers")),
    }
    history.append(entry)
    history = history[-100:]
    _save_json(HISTORY_PATH, history)


def build_self_model(*, persist: bool = True) -> dict[str, Any]:
    model = _build_model()
    if persist:
        _save_json(OUT_PATH, model)
        _append_history(model)
    return model


def _attempt_daemon_recovery() -> dict[str, Any]:
    if not DAEMON_STARTER.exists():
        return {"status": "failed", "reason": f"missing start helper: {DAEMON_STARTER}"}
    command = python_command(
        DAEMON_STARTER,
        "--interval",
        "60",
        "--meta-every",
        "5",
        "--evolution-every",
        "5",
        interpreter=PYTHON_EXE,
    )
    completed = run_hidden(command, cwd=str(ROOT))
    daemon = _daemon_snapshot()
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "daemon": daemon,
    }


def _run_factoryctl(command_name: str) -> dict[str, Any]:
    if not FACTORYCTL_PY.exists():
        return {"status": "failed", "reason": f"missing factoryctl script: {FACTORYCTL_PY}"}
    command = python_command(
        FACTORYCTL_PY,
        command_name,
        interpreter=PYTHON_EXE,
    )
    completed = run_hidden(command, cwd=str(WORKSPACE_ROOT))
    stdout = completed.stdout.strip()
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except Exception:
            parsed = None
    return {
        "status": "completed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": completed.stderr.strip(),
        "payload": parsed,
    }


def _extract_compileall_target(compileall: dict[str, Any]) -> dict[str, Any] | None:
    lines = (compileall.get("stdout_tail") or []) + (compileall.get("stderr_tail") or [])
    for idx, line in enumerate(lines):
        if line.startswith('***   File "') and '", line ' in line:
            prefix, suffix = line.split('", line ', 1)
            return {
                "path": prefix.replace('***   File "', ""),
                "line": suffix.strip(),
                "context": lines[idx : idx + 3],
            }
    return None


def _task_record(task_id: str | None) -> dict[str, Any] | None:
    if not task_id:
        return None
    tasks = _load_json(TASKS_PATH, [])
    return next((item for item in tasks if item.get("id") == task_id), None)


def _task_snapshot(task_id: str | None) -> dict[str, Any] | None:
    task = _task_record(task_id)
    if not task:
        return None
    plan = task.get("plan") or []
    running_steps = [step.get("title") for step in plan if step.get("status") == "running"]
    completed_steps = sum(1 for step in plan if step.get("status") == "completed")
    return {
        "id": task.get("id"),
        "status": task.get("status"),
        "updated_at": task.get("updated_at"),
        "goal": task.get("goal"),
        "repo_path": task.get("repo_path"),
        "result": task.get("result"),
        "running_steps": running_steps,
        "completed_step_count": completed_steps,
    }


def _run_bounded_brain_loop() -> dict[str, Any]:
    from tools.brain_loop import run_once

    payload = run_once(
        policy_schedule={
            "run_experiments": False,
            "run_capability_building": False,
            "allow_goal_generation": False,
            "runtime_dispatch_limit": 1,
        }
    )
    actions = payload.get("actions") or []
    return {
        "status": "completed",
        "updated_at": payload.get("updated_at"),
        "action_count": len(actions),
        "dispatch_count": sum(1 for item in actions if item.get("phase") == "dispatch-node"),
        "completed_goal_count": sum(
            1 for item in actions if str(item.get("phase") or "").startswith("complete-")
        ),
        "recent_phases": [item.get("phase") for item in actions[-8:]],
    }


def _run_runtime_maintenance() -> dict[str, Any]:
    from tools.runtime_maintenance import run_maintenance

    payload = run_maintenance(mode="full")
    tasks = payload.get("tasks") or {}
    return {
        "status": "completed",
        "updated_at": payload.get("updated_at"),
        "mode": payload.get("mode"),
        "reconciled_running": (tasks.get("reconciled_running") or {}).get(
            "completed_stale_running"
        ),
        "reconciled_planning": (tasks.get("reconciled_planning") or {}).get(
            "completed_stale_planning"
        ),
        "reconciled_duplicates": (tasks.get("reconciled_duplicates") or {}).get(
            "completed_duplicate_tasks"
        ),
        "timed_out": len(tasks.get("timed_out") or []),
        "archived": len(tasks.get("archived") or []),
    }


def _resolved_stalled_task_ids(state: dict[str, Any]) -> list[str]:
    blockers = set(state.get("blockers") or [])
    daemon = state.get("daemon") or {}
    verification = state.get("verification") or {}
    stalled = (state.get("tasks") or {}).get("stalled_active") or []
    resolved = []
    for item in stalled:
        goal = str(item.get("goal") or "").lower()
        if (
            "daemon" in goal
            and daemon.get("running")
            and "factory_daemon_unhealthy" not in blockers
        ):
            resolved.append(str(item.get("id") or ""))
            continue
        if "patch gate" in goal and verification.get("patch_gate_status") == "pass":
            resolved.append(str(item.get("id") or ""))
            continue
    return [item for item in resolved if item]


def _close_resolved_stalled_tasks(state: dict[str, Any]) -> dict[str, Any]:
    from tools.task_state_tools import complete_tasks

    task_ids = _resolved_stalled_task_ids(state)
    summary = "Task auto-completed by Self Model because its incident goal has already been satisfied by the current system state."
    closed = complete_tasks(task_ids, summary) if task_ids else 0
    return {
        "status": "completed",
        "closed_count": closed,
        "task_ids": task_ids,
        "summary": summary if task_ids else "No resolved stalled tasks matched auto-closure rules.",
    }


def _reset_orphaned_active_tasks(state: dict[str, Any]) -> dict[str, Any]:
    tasks = _load_json(TASKS_PATH, [])
    daemon_started = _parse_utc((state.get("daemon") or {}).get("started_at"))
    checkpoints = _load_json(DATA / "task_checkpoints.json", {})
    reset_task_ids: list[str] = []
    reset_nodes: list[dict[str, Any]] = []
    changed = False

    for item in tasks:
        task_id = str(item.get("id") or "")
        if item.get("status") != "running":
            continue
        graph_id = item.get("graph_id") or ((item.get("scheduler_hint") or {}).get("graph_id"))
        node_id = item.get("node_id") or ((item.get("scheduler_hint") or {}).get("node_id"))
        if not graph_id or not node_id:
            continue
        updated_at = _parse_utc(item.get("updated_at"))
        if not updated_at or not daemon_started or updated_at >= daemon_started:
            continue
        checkpoint = checkpoints.get(task_id) or {}
        if checkpoint.get("phase") != "step-running":
            continue

        graph_path = ROOT / "factory" / "graphs" / f"{graph_id}.json"
        graph = _load_json(graph_path, {})
        nodes = graph.get("nodes") or []
        node = next((entry for entry in nodes if entry.get("id") == node_id), None)
        if node is None:
            continue

        item["status"] = "completed"
        item["updated_at"] = _utc_now()
        result = item.setdefault("result", {})
        result["summary"] = (
            "Task auto-closed by Self Model after daemon restart orphaned the in-process execution context."
        )
        result["orphaned_reset"] = True
        checkpoint["task_status"] = "completed"
        checkpoint["phase"] = "self_model_reset"
        checkpoint["updated_at"] = _utc_now()
        checkpoints[task_id] = checkpoint

        node["task_id"] = None
        node["status"] = "pending"
        node.pop("worker", None)
        node.pop("selection_reason", None)
        node.pop("worker_success_rate", None)
        node.pop("skill_matches", None)
        changed = True
        _save_json(graph_path, graph)
        reset_task_ids.append(task_id)
        reset_nodes.append({"graph_id": graph_id, "node_id": node_id})

    if changed:
        _save_json(TASKS_PATH, tasks)
        _save_json(DATA / "task_checkpoints.json", checkpoints)

    return {
        "status": "completed",
        "reset_task_count": len(reset_task_ids),
        "task_ids": reset_task_ids,
        "nodes": reset_nodes,
    }


def _execute_action(
    action: dict[str, Any], model: dict[str, Any], prior_results: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    action_id = action.get("action")
    started_at = _utc_now()
    result: dict[str, Any] = {
        "action": action_id,
        "title": action.get("title"),
        "owner": action.get("owner"),
        "started_at": started_at,
        "status": "completed",
        "observations": {},
    }

    if action_id == "inspect_daemon_state":
        result["observations"] = {
            "daemon": (model.get("state") or {}).get("daemon"),
            "blockers": (model.get("state") or {}).get("blockers"),
        }
    elif action_id == "review_recent_daemon_log":
        daemon_started_at = _parse_utc(
            ((model.get("state") or {}).get("daemon") or {}).get("started_at")
        )
        lines = _tail_lines(DATA / "factory_daemon.log", limit=30)
        current_lines = [
            line
            for line in lines
            if daemon_started_at is None
            or (
                (_parse_log_stamp(line) or datetime.min.replace(tzinfo=timezone.utc))
                >= daemon_started_at
            )
        ]
        matched_errors = [line for line in current_lines if "error tick=" in line][-5:]
        result["observations"] = {
            "recent_log_tail": lines,
            "current_log_tail": current_lines,
            "matched_error_lines": matched_errors,
        }
    elif action_id == "attempt_daemon_recovery":
        recovery = _attempt_daemon_recovery()
        result["status"] = recovery.get("status", "failed")
        result["observations"] = recovery
    elif action_id == "freeze_noncritical_dispatch":
        current = _control_center_snapshot()
        if current.get("paused"):
            result["observations"] = {
                "control_center": current,
                "reason": "Dispatch was already paused.",
            }
        else:
            updated = _write_control_center(
                True, "Self Model: paused noncritical dispatch during daemon incident response."
            )
            result["observations"] = {
                "control_center": updated,
                "reason": "Noncritical dispatch paused to protect recovery bandwidth.",
            }
    elif action_id == "resume_noncritical_dispatch":
        current = _control_center_snapshot()
        if not current.get("paused"):
            result["observations"] = {
                "control_center": current,
                "reason": "Dispatch was already active.",
            }
        else:
            updated = _write_control_center(
                False, "Self Model: resumed noncritical dispatch after recovery."
            )
            result["observations"] = {
                "control_center": updated,
                "reason": "Recovery conditions are satisfied, so normal dispatch is restored.",
            }
    elif action_id == "summarize_open_errors":
        result["observations"] = {
            "open_errors": ((model.get("state") or {}).get("escalations") or {}).get(
                "top_open", []
            ),
        }
    elif action_id == "inspect_verification_snapshot":
        result["observations"] = {
            "verification": (model.get("state") or {}).get("verification"),
            "quality": (model.get("state") or {}).get("quality"),
        }
    elif action_id in {"select_patch_gate_repair_target", "select_verification_repair_target"}:
        refresh = _run_factoryctl("verify-engine")
        verification_payload = refresh.get("payload") or {}
        compileall = verification_payload.get("compileall") or {}
        repair_target = _extract_compileall_target(compileall)
        result["status"] = refresh.get("status", "failed")
        result["observations"] = {
            "verification_refresh": refresh,
            "repair_target": repair_target,
            "patch_gate_status": (verification_payload.get("patch_gate") or {}).get("status"),
            "delayed_verification_status": (
                verification_payload.get("delayed_verification") or {}
            ).get("status"),
        }
    elif action_id == "inspect_release_sample_gate":
        release_status = _load_json(DATA / "release_operations_status.json", {})
        result["observations"] = {
            "release_train": release_status.get("release_train"),
            "verification_release_gate": release_status.get("verification_release_gate"),
            "operations_readiness": release_status.get("operations_readiness"),
        }
    elif action_id == "select_release_blocker_repair_target":
        release_status = _load_json(DATA / "release_operations_status.json", {})
        release_gate = release_status.get("verification_release_gate") or {}
        result["observations"] = {
            "release_gate": release_gate,
            "repair_target": (release_gate.get("sample_failures") or [None])[0],
            "next_action": release_gate.get("next_action"),
        }
    elif action_id in {"keep_release_blocked", "keep_execution_open", "hold_sampled_release_only"}:
        release_status = _load_json(DATA / "release_operations_status.json", {})
        reason = {
            "keep_release_blocked": "Release remains bounded until patch gate returns to pass.",
            "keep_execution_open": "Execution remains open while delayed verification catches up.",
            "hold_sampled_release_only": "Only sampled release promotion is held while execution continues.",
        }.get(action_id, "Release remains bounded.")
        result["observations"] = {
            "release_status": release_status.get("status"),
            "release_train_status": ((release_status.get("release_train") or {}).get("status")),
            "verification_release_gate": release_status.get("verification_release_gate"),
            "reason": reason,
        }
    elif action_id == "list_waiting_approval_tasks":
        result["observations"] = {
            "waiting_approval_tasks": [
                task
                for task in ((model.get("state") or {}).get("tasks") or {}).get("active", [])
                if task.get("status") == "waiting_approval"
            ],
        }
    elif action_id == "inspect_active_task_frontier":
        task_state = (model.get("state") or {}).get("tasks") or {}
        result["observations"] = {
            "active_tasks": task_state.get("active", []),
            "stalled_active": task_state.get("stalled_active", []),
        }
    elif action_id == "inspect_toyos_priority_status":
        result["observations"] = {
            "priority_directive": _priority_directive(),
            "production_focus": _production_focus_snapshot(),
        }
    elif action_id == "inspect_toyos_artifact_evidence":
        result["observations"] = _toyos_artifact_snapshot()
    elif action_id == "inspect_toyos_soak_state":
        soak_state = _load_json(SOAK_STATE_PATH, {}) or {}
        result["observations"] = {
            "soak_state": soak_state,
            "focus_matches_toyos": str(((soak_state.get("focus_artifact") or {}).get("artifact_id")) or "").strip().lower() == "toy-os-demo",
        }
    elif action_id == "run_runtime_maintenance":
        before_stalled = ((model.get("state") or {}).get("tasks") or {}).get(
            "stalled_active_count", 0
        )
        maintenance = _run_runtime_maintenance()
        after_hot = _load_json(DATA / "hot_context.json", {})
        after_active = after_hot.get("active_tasks") or []
        after_stalled = 0
        now_utc = datetime.now(timezone.utc)
        for item in after_active:
            updated = _parse_utc(item.get("updated_at"))
            if updated and (now_utc - updated) > timedelta(minutes=TASK_STALL_MINUTES):
                after_stalled += 1
        result["status"] = maintenance.get("status", "failed")
        result["observations"] = {
            "before_stalled_active_count": before_stalled,
            "after_stalled_active_count": after_stalled,
            "maintenance": maintenance,
        }
    elif action_id == "reset_orphaned_active_tasks":
        reset_result = _reset_orphaned_active_tasks(model.get("state") or {})
        refreshed_tasks = [
            item
            for item in _load_json(TASKS_PATH, [])
            if item.get("status") in {"queued", "planning", "running", "waiting_approval"}
        ]
        now_utc = datetime.now(timezone.utc)
        after_stalled = 0
        for item in refreshed_tasks:
            updated = _parse_utc(item.get("updated_at"))
            if updated and (now_utc - updated) > timedelta(minutes=TASK_STALL_MINUTES):
                after_stalled += 1
        result["status"] = reset_result.get("status", "failed")
        result["observations"] = {
            **reset_result,
            "after_stalled_active_count": after_stalled,
        }
    elif action_id == "close_resolved_stalled_tasks":
        close_result = _close_resolved_stalled_tasks(model.get("state") or {})
        refreshed_tasks = [
            item
            for item in _load_json(TASKS_PATH, [])
            if item.get("status") in {"queued", "planning", "running", "waiting_approval"}
        ]
        now_utc = datetime.now(timezone.utc)
        after_stalled = 0
        for item in refreshed_tasks:
            updated = _parse_utc(item.get("updated_at"))
            if updated and (now_utc - updated) > timedelta(minutes=TASK_STALL_MINUTES):
                after_stalled += 1
        result["status"] = close_result.get("status", "failed")
        result["observations"] = {
            **close_result,
            "after_stalled_active_count": after_stalled,
        }
    elif action_id == "verify_active_task_recovery":
        recovery = next(
            (
                item
                for item in (prior_results or [])
                if item.get("action") == "run_runtime_maintenance"
            ),
            None,
        )
        closure = next(
            (
                item
                for item in (prior_results or [])
                if item.get("action") == "close_resolved_stalled_tasks"
            ),
            None,
        )
        if not recovery and not closure:
            result["status"] = "skipped"
            result["observations"] = {"reason": "No recovery action ran earlier in this cycle."}
        else:
            reset = next(
                (
                    item
                    for item in (prior_results or [])
                    if item.get("action") == "reset_orphaned_active_tasks"
                ),
                None,
            )
            before_stalled = int(
                ((recovery or {}).get("observations") or {}).get("before_stalled_active_count")
                or ((model.get("state") or {}).get("tasks") or {}).get("stalled_active_count", 0)
            )
            after_from_maintenance = int(
                ((recovery or {}).get("observations") or {}).get("after_stalled_active_count")
                or before_stalled
            )
            after_from_reset = int(
                ((reset or {}).get("observations") or {}).get("after_stalled_active_count")
                or after_from_maintenance
            )
            after_from_closure = int(
                ((closure or {}).get("observations") or {}).get("after_stalled_active_count")
                or after_from_reset
            )
            after_stalled = min(after_from_maintenance, after_from_reset, after_from_closure)
            result["observations"] = {
                "verified": after_stalled < before_stalled,
                "before_stalled_active_count": before_stalled,
                "after_stalled_active_count": after_stalled,
                "recovered_count": max(0, before_stalled - after_stalled),
                "reset_count": int(
                    ((reset or {}).get("observations") or {}).get("reset_task_count") or 0
                ),
                "closed_count": int(
                    ((closure or {}).get("observations") or {}).get("closed_count") or 0
                ),
            }
    elif action_id == "advance_top_active_task":
        active_tasks = ((model.get("state") or {}).get("tasks") or {}).get("active", [])
        top_task_id = (active_tasks[0] or {}).get("id") if active_tasks else None
        before = _task_snapshot(top_task_id)
        brain_loop = _run_bounded_brain_loop()
        after = _task_snapshot(top_task_id)
        progress_changed = before != after
        result["status"] = brain_loop.get("status", "failed")
        result["observations"] = {
            "task_id": top_task_id,
            "before": before,
            "after": after,
            "progress_changed": progress_changed,
            "brain_loop": brain_loop,
        }
    elif action_id == "verify_progress_after_execution":
        advance = next(
            (
                item
                for item in (prior_results or [])
                if item.get("action") == "advance_top_active_task"
            ),
            None,
        )
        if not advance:
            result["status"] = "skipped"
            result["observations"] = {
                "reason": "advance_top_active_task did not run earlier in this cycle."
            }
        else:
            advance_obs = advance.get("observations") or {}
            before = advance_obs.get("before") or {}
            after = advance_obs.get("after") or {}
            updated = before.get("updated_at") != after.get("updated_at")
            status_changed = before.get("status") != after.get("status")
            result_changed = before.get("result") != after.get("result")
            verified = bool(
                advance_obs.get("progress_changed") or updated or status_changed or result_changed
            )
            result["observations"] = {
                "task_id": advance_obs.get("task_id"),
                "verified": verified,
                "updated_at_changed": updated,
                "status_changed": status_changed,
                "result_changed": result_changed,
                "before": before,
                "after": after,
            }
    else:
        result["status"] = "skipped"
        result["observations"] = {
            "reason": "No executor implemented for this action yet.",
        }

    result["completed_at"] = _utc_now()
    return result


def _build_reflection(model: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    goal = model.get("goal") or {}
    state = model.get("state") or {}
    daemon = state.get("daemon") or {}
    top_issue = None
    hypothesis = []

    for item in results:
        if item.get("action") == "review_recent_daemon_log":
            matched = item.get("observations", {}).get("matched_error_lines") or []
            if matched:
                top_issue = matched[-1]
                break

    recovery = next(
        (item for item in results if item.get("action") == "attempt_daemon_recovery"), None
    )
    frozen = next(
        (item for item in results if item.get("action") == "freeze_noncritical_dispatch"), None
    )
    resumed = next(
        (item for item in results if item.get("action") == "resume_noncritical_dispatch"), None
    )

    if goal.get("primary") == "stabilize_factory_daemon":
        if daemon.get("last_error"):
            hypothesis.append(f"Latest daemon exception: {daemon.get('last_error')}")
        if top_issue:
            hypothesis.append(f"Current-run log evidence: {top_issue}")
        else:
            hypothesis.append(
                "No new daemon error line was observed after the current daemon start timestamp."
            )
        if recovery:
            hypothesis.append(f"Daemon recovery attempt status={recovery.get('status')}")
        if frozen:
            hypothesis.append(
                "Control center is paused for noncritical dispatch, so recovery can proceed without new pressure."
            )
        if not daemon.get("running"):
            hypothesis.append(
                "Daemon is not running, so recovery should stay ahead of throughput work."
            )
    if goal.get("primary") == "resume_normal_operation" and resumed:
        hypothesis.append(
            "Control center can return to active mode because critical daemon blockers are clear."
        )

    if goal.get("primary") == "advance_active_delivery":
        advance = next(
            (item for item in results if item.get("action") == "advance_top_active_task"), None
        )
        verify = next(
            (item for item in results if item.get("action") == "verify_progress_after_execution"),
            None,
        )
        if advance:
            changed = bool((advance.get("observations") or {}).get("progress_changed"))
            hypothesis.append(f"Bounded runtime execution changed the active task state={changed}.")
        if verify:
            hypothesis.append(
                f"Progress verification status={bool((verify.get('observations') or {}).get('verified'))}."
            )
    if goal.get("primary") == "recover_stalled_active_tasks":
        verify = next(
            (item for item in results if item.get("action") == "verify_active_task_recovery"), None
        )
        if verify:
            recovered = (verify.get("observations") or {}).get("recovered_count")
            hypothesis.append(f"Stalled active task recovery reduced stalled count by {recovered}.")
            reset_count = (verify.get("observations") or {}).get("reset_count")
            if reset_count:
                hypothesis.append(
                    f"Orphaned graph-backed tasks reset for redispatch={reset_count}."
                )

    return {
        "updated_at": _utc_now(),
        "goal": goal.get("primary"),
        "mode": goal.get("mode"),
        "summary": "Executed bounded self-model actions and converted evidence into a control decision.",
        "top_issue": top_issue,
        "hypothesis": hypothesis,
        "next_step_bias": "repair_primary_blocker_first"
        if goal.get("primary") == "stabilize_factory_daemon"
        else "resume_then_measure",
    }


def run_self_model_cycle(*, persist: bool = True) -> dict[str, Any]:
    model = build_self_model(persist=False)
    results: list[dict[str, Any]] = []
    for action in model.get("next_actions", []):
        results.append(_execute_action(action, model, results))
    refreshed_model = _build_model()
    reflection = _build_reflection(refreshed_model, results)
    strategy_review = review_strategy_memory(persist=persist)
    payload = {
        **refreshed_model,
        "execution": {
            "updated_at": _utc_now(),
            "executed_action_count": len(results),
            "results": results,
        },
        "reflection": reflection,
        "strategy_review": strategy_review,
    }
    if persist:
        _save_json(OUT_PATH, payload)
        _save_json(EXECUTION_PATH, payload.get("execution"))
        _append_history(payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_self_model(), ensure_ascii=False, indent=2))

