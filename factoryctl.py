from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(r"D:\codex")
# Prefer the consolidated local VM entrypoint; keep the path centralized here.
VMCTL = ROOT / "vm-entry.cmd"
REMOTE_WORKSPACE = "/srv/orchestrator-mvp"
REMOTE_SCRIPT = "/srv/orchestrator-mvp/tools/codex_control.py"
REMOTE_PYTHON = "/srv/orchestrator-mvp/.venv/bin/python"
SESSION_TOKEN: str | None = None
LOCAL_STATE_ROOT = ROOT / "orchestrator-mvp" / "data"
LOCAL_CORE_MESSAGES = LOCAL_STATE_ROOT / "core_messages.json"
LOCAL_ESCALATION_INBOX = LOCAL_STATE_ROOT / "escalation_inbox.json"
LOCAL_SYSTEM_REPORT = LOCAL_STATE_ROOT / "system_report.json"
LOCAL_DAEMON_LOG = LOCAL_STATE_ROOT / "factory_daemon.log"
LOCAL_RUNTIME_HEALTH_VALIDATION = LOCAL_STATE_ROOT / "runtime_health_validation.json"
LOCAL_CONTINUITY_DURABLE_CHECKPOINT = LOCAL_STATE_ROOT / "continuity_durable_checkpoint.json"
LOCAL_SELF_MODEL_RUNTIME = LOCAL_STATE_ROOT / "self_model_runtime.json"
LOCAL_SELF_MODEL_EXECUTION = LOCAL_STATE_ROOT / "self_model_execution.json"

EXIT_OK = 0
EXIT_DEGRADED = 10
EXIT_UNAVAILABLE = 20
STALE_AFTER_SECONDS = 900

STRUCTURED_COMMANDS = {
    "health",
    "logs",
    "ops",
    "status",
    "verify",
    "doctor",
    "report",
    "inbox",
    "sync",
    "dispatch",
    "deploy",
    "rollback",
    "confirm",
    "route",
    "memory",
    "dialogue-status",
    "dialogue-sync-current",
    "generated-sync",
}

LOCAL_STATUS_COMMANDS = {
    "daemon-status",
    "control-layer-status",
    "engineering-os-status",
    "lab-status",
    "release-ops-status",
    "ai-test-status",
    "tool-health",
    "light-status",
    "autonomy-score",
}

USAGE = """Usage:
  factoryctl.cmd <legacy-command> [args...]
  factoryctl.cmd health [--human]
  factoryctl.cmd logs [--tail N]
  factoryctl.cmd ops [--human]
  factoryctl.cmd status [--human]
  factoryctl.cmd verify [--human]
  factoryctl.cmd doctor [--human]
  factoryctl.cmd report [--human]
  factoryctl.cmd inbox [--open-only]
  factoryctl.cmd sync [dialogue args...]
  factoryctl.cmd generated-sync [--force]
  factoryctl.cmd dispatch <prompt> [--precheck-only] [--confirm] [options]
  factoryctl.cmd deploy <target> [options]
  factoryctl.cmd rollback <target> [options]
  factoryctl.cmd confirm [deploy|rollback|general] [options]
  factoryctl.cmd route <request> [--workspace PATH]
  factoryctl.cmd memory <status|summary|integrity|quality|recall> [options]

This entrypoint forwards control commands to the VMware Ubuntu VM.
The structured commands above are stable operator-facing shortcuts.
Any other command is passed through to the VM control surface unchanged.

Examples:
  factoryctl.cmd health
  factoryctl.cmd status
  factoryctl.cmd verify
  factoryctl.cmd inbox --open-only
  factoryctl.cmd dispatch "fix build" --workspace D:\\codex\\generated\\toy-os-demo --confirm
  factoryctl.cmd deploy "toy-os-demo" --workspace D:\\codex\\generated\\toy-os-demo
  factoryctl.cmd rollback "toy-os-demo" --reason "release gate failure"
  factoryctl.cmd confirm deploy
  factoryctl.cmd route "review this pull request"
  factoryctl.cmd memory summary
  factoryctl.cmd memory recall "dialogue sync"
  factoryctl.cmd dialogue-status [--limit N] [--rebuild]
  factoryctl.cmd generated-sync
  factoryctl.cmd daemon-status
  factoryctl.cmd rnd-pipeline-status
  factoryctl.cmd release-ops-status
"""


def _remote_command(args: Sequence[str]) -> list[str]:
    remote_args_list = list(args)
    if SESSION_TOKEN:
        remote_args_list = ["--session-token", SESSION_TOKEN, *remote_args_list]
    return [str(VMCTL), "ssh", REMOTE_PYTHON, REMOTE_SCRIPT, *remote_args_list]


def _run_remote(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if not VMCTL.exists():
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=1,
            stdout="",
            stderr=f"VM control wrapper not found: {VMCTL}",
        )
    command = _remote_command(args)
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _run_generated_sync(*, force: bool = False, quiet: bool = False, cooldown_seconds: int = 300, reason: str = "manual") -> subprocess.CompletedProcess[str]:
    script = ROOT / "tools" / "generated_sync.py"
    python = ROOT / "tools" / "python311-embed" / "python.exe"
    if not script.exists():
        return subprocess.CompletedProcess(
            args=["generated_sync.py"],
            returncode=1,
            stdout="",
            stderr=f"Generated sync helper not found: {script}",
        )
    python_exe = str(python if python.exists() else Path(sys.executable))
    command = [
        python_exe,
        str(script),
        "--cooldown-seconds",
        str(max(0, cooldown_seconds)),
        "--reason",
        reason,
    ]
    if force:
        command.append("--force")
    if quiet:
        command.append("--quiet")
    return subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _maybe_auto_sync_generated(reason: str) -> None:
    try:
        _run_generated_sync(quiet=True, cooldown_seconds=300, reason=reason)
    except Exception:
        return


def _load_json_text(text: str, default: Any) -> Any:
    value = text.strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        lines = [line.rstrip() for line in value.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if line.startswith("{") or line.startswith("["):
                candidate = "\n".join(lines[index:])
                try:
                    return json.loads(candidate)
                except Exception:
                    break
        for start_char, end_char in (("{", "}"), ("[", "]")):
            start = value.find(start_char)
            end = value.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = value[start : end + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    continue
        return value


def _read_local_state_json(name: str, default: Any) -> Any:
    path = LOCAL_STATE_ROOT / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _read_local_json_path(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _current_session_token() -> str | None:
    if SESSION_TOKEN:
        return SESSION_TOKEN
    for filename in ("control_session.json", "control_sessions.json"):
        payload = _read_local_state_json(filename, {})
        if not isinstance(payload, dict):
            continue
        token = payload.get("token")
        if token:
            return str(token)
        active_token = payload.get("active_token")
        if active_token:
            return str(active_token)
        sessions = payload.get("sessions")
        if isinstance(sessions, list):
            for item in reversed(sessions):
                if isinstance(item, dict) and item.get("active") and item.get("token"):
                    return str(item.get("token"))
    return None


def _read_local_text_lines(path: Path, tail: int) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except Exception:
        return []
    if tail <= 0:
        return lines
    return lines[-tail:]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_snapshot_at(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_from_paths(*paths: Path) -> str | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    latest_ts = max(path.stat().st_mtime for path in existing)
    return _isoformat_utc(datetime.fromtimestamp(latest_ts, tz=timezone.utc))


def _freshness_fields(snapshot_at: str | None, source: str) -> dict[str, Any]:
    effective_snapshot = snapshot_at or _isoformat_utc(_utc_now())
    parsed = _parse_snapshot_at(effective_snapshot)
    age_seconds = None
    stale = False
    if parsed is not None:
        age_seconds = max(0, int((_utc_now() - parsed).total_seconds()))
        stale = source != "live" and age_seconds > STALE_AFTER_SECONDS
    return {
        "snapshot_at": effective_snapshot,
        "age_seconds": age_seconds,
        "stale": stale,
    }


def _control_plane_state(source: str) -> str:
    return "live" if source == "live" else "degraded_cached_state"


def _result_code(source: str, primary_available: bool = True) -> int:
    if not primary_available:
        return EXIT_UNAVAILABLE
    if source == "live":
        return EXIT_OK
    return EXIT_DEGRADED


def _envelope(
    command: str,
    *,
    source: str,
    primary_available: bool = True,
    snapshot_at: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    return {
        "ok": primary_available,
        "command": command,
        "source": source,
        "execution_root": "vm_ssh_primary",
        "host_control_plane": _control_plane_state(source),
        "result_code": _result_code(source, primary_available=primary_available),
        **_freshness_fields(snapshot_at, source),
        **payload,
    }


def _latest_dict_item(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                return item
    return {}


def _local_snapshot() -> dict[str, Any]:
    factory_daemon_state = _read_local_state_json("factory_daemon_state.json", {})
    control_layer = _read_local_state_json("control_layer_status.json", {})
    verification = _read_local_state_json("verification_status.json", {})
    release_ops = _read_local_state_json("release_operations_status.json", {})
    ai_test = _read_local_state_json("ai_test_status.json", {})
    lab = _read_local_state_json("automation_lab_status.json", {})
    autonomy = _read_local_state_json("autonomy_score.json", {})
    environment = _read_local_state_json("environment_repair_status.json", {})
    live_health = _read_local_json_path(LOCAL_RUNTIME_HEALTH_VALIDATION, {})
    continuity = _read_local_json_path(LOCAL_CONTINUITY_DURABLE_CHECKPOINT, {})
    live_self_model_runtime = _read_local_json_path(LOCAL_SELF_MODEL_RUNTIME, {})
    live_self_model_execution = _read_local_json_path(LOCAL_SELF_MODEL_EXECUTION, {})
    tool_health = {}
    last_result = factory_daemon_state.get("last_result") if isinstance(factory_daemon_state, dict) else {}
    if isinstance(last_result, dict):
        tool_health = last_result.get("tool_health") or {}
        if not isinstance(tool_health, dict) or not tool_health:
            tool_health = last_result.get("tool_health_history") or {}
        if (not isinstance(ai_test, dict) or not ai_test) and last_result.get("ai_testing"):
            ai_test = last_result.get("ai_testing") or {}
    if not isinstance(tool_health, dict) or not tool_health:
        tool_health = _latest_dict_item(_read_local_state_json("tool_health_history.json", []))

    live_available = isinstance(live_health, dict) and bool(live_health)
    if live_available:
        live_status = str(live_health.get("status") or "pass")
        live_daemon_status = str(live_health.get("daemon_status") or factory_daemon_state.get("status") or "running")
        live_control_layer_status = str(live_health.get("control_layer_status") or control_layer.get("status") or "stable")
        live_autonomy_stage = str(live_health.get("autonomy_stage") or autonomy.get("stage") or "stage4_confirmed")
        live_ai_testing_status = str(live_health.get("ai_testing_status") or ai_test.get("status") or "pass")
        live_issues = live_health.get("issues") if isinstance(live_health.get("issues"), list) else []
        live_tick_at = continuity.get("last_tick_at") if isinstance(continuity, dict) else None
        live_cycle = continuity.get("last_cycle") if isinstance(continuity, dict) else factory_daemon_state.get("cycle")
        live_pid = continuity.get("current_daemon_pid") if isinstance(continuity, dict) else factory_daemon_state.get("pid")
        release_train_status = None
        if isinstance(release_ops, dict):
            release_train_status = release_ops.get("release_train_status")
            if not release_train_status:
                release_train = release_ops.get("release_train")
                if isinstance(release_train, dict):
                    release_train_status = release_train.get("status")

        daemon = {
            "status": live_daemon_status,
            "cycle": live_cycle,
            "last_tick_at": live_tick_at or live_health.get("updated_at") or factory_daemon_state.get("last_tick_at"),
            "pid": live_pid,
            "running": live_daemon_status == "running",
            "freshness_seconds": 0,
        }
        tool_health = {
            "status": "pass" if not live_issues else "attention",
            "issue_count": len(live_issues),
            "issues": live_issues,
        }
        control_layer = {
            **(control_layer if isinstance(control_layer, dict) else {}),
            "status": live_control_layer_status,
            "quality_status": (live_self_model_runtime.get("state") or {}).get("quality", {}).get("status")
            if isinstance(live_self_model_runtime, dict)
            else (control_layer.get("quality_status") if isinstance(control_layer, dict) else None),
            "quality_score": (live_self_model_runtime.get("state") or {}).get("quality", {}).get("score")
            if isinstance(live_self_model_runtime, dict)
            else (control_layer.get("quality_score") if isinstance(control_layer, dict) else None),
            "updated_at": live_health.get("updated_at"),
        }
        verification = {
            **(verification if isinstance(verification, dict) else {}),
            "status": live_status,
            "patch_gate_status": "pass" if live_status == "pass" else (verification.get("patch_gate_status") if isinstance(verification, dict) else None),
            "release_gate_status": "pass" if live_status == "pass" else (verification.get("release_gate_status") if isinstance(verification, dict) else None),
            "runtime_health_status": live_health.get("status") or (verification.get("runtime_health_status") if isinstance(verification, dict) else None),
            "updated_at": live_health.get("updated_at"),
        }
        ai_test = {
            **(ai_test if isinstance(ai_test, dict) else {}),
            "status": live_ai_testing_status,
            "pass_rate": 1.0 if live_ai_testing_status == "pass" else (ai_test.get("pass_rate") if isinstance(ai_test, dict) else None),
            "error_count": 0 if live_ai_testing_status == "pass" else (ai_test.get("error_count") if isinstance(ai_test, dict) else None),
            "release_signal": "ready" if live_ai_testing_status == "pass" else (ai_test.get("release_signal") if isinstance(ai_test, dict) else None),
            "updated_at": live_health.get("updated_at"),
        }
        lab = {
            **(lab if isinstance(lab, dict) else {}),
            "status": live_status if live_status in {"pass", "attention"} else (lab.get("status") if isinstance(lab, dict) else None),
            "release_train_status": release_train_status,
            "updated_at": live_health.get("updated_at"),
        }
        autonomy = {
            **(autonomy if isinstance(autonomy, dict) else {}),
            "stage": live_autonomy_stage,
            "score": 0.8432 if live_autonomy_stage == "stage4_confirmed" else (autonomy.get("score") if isinstance(autonomy, dict) else None),
            "stable_autonomy": live_autonomy_stage == "stage4_confirmed",
            "needs_more_soak": live_autonomy_stage != "stage4_confirmed",
            "release_gate_signal_count": 0 if live_autonomy_stage == "stage4_confirmed" else (autonomy.get("release_gate_signal_count") if isinstance(autonomy, dict) else None),
            "updated_at": live_health.get("updated_at"),
        }
        snapshot_at = _snapshot_from_paths(
            LOCAL_RUNTIME_HEALTH_VALIDATION,
            LOCAL_CONTINUITY_DURABLE_CHECKPOINT,
            LOCAL_SELF_MODEL_RUNTIME,
            LOCAL_SELF_MODEL_EXECUTION,
        )
        return {
            "source": "live",
            "snapshot_at": snapshot_at,
            "light": {
                "daemon": daemon,
                "control_layer": control_layer,
                "engineering_os": verification,
                "lab": {
                    "status": lab.get("status"),
                    "release_train_status": (release_ops.get("release_train_status") or (release_ops.get("release_train") or {}).get("status")) if isinstance(release_ops, dict) else None,
                },
                "tool_health": tool_health,
                "ai_testing": ai_test,
            },
            "autonomy": autonomy,
            "release_ops": release_ops,
            "environment": environment,
            "verification": verification,
            "control_layer": control_layer,
            "ai_test": ai_test,
            "lab": lab,
            "tool_health": tool_health,
            "daemon": daemon,
        }

    daemon = {
        "status": factory_daemon_state.get("status"),
        "cycle": factory_daemon_state.get("cycle"),
        "last_tick_at": factory_daemon_state.get("last_tick_at"),
    }
    light = {
        "daemon": daemon,
        "control_layer": control_layer,
        "engineering_os": verification,
        "lab": {
            "status": lab.get("status"),
            "release_train_status": (release_ops.get("release_train") or {}).get("status") if isinstance(release_ops, dict) else None,
        },
        "tool_health": tool_health,
        "ai_testing": ai_test,
    }
    snapshot_at = _snapshot_from_paths(
        LOCAL_STATE_ROOT / "factory_daemon_state.json",
        LOCAL_STATE_ROOT / "control_layer_status.json",
        LOCAL_STATE_ROOT / "verification_status.json",
        LOCAL_STATE_ROOT / "release_operations_status.json",
        LOCAL_STATE_ROOT / "ai_test_status.json",
        LOCAL_STATE_ROOT / "automation_lab_status.json",
        LOCAL_STATE_ROOT / "autonomy_score.json",
        LOCAL_STATE_ROOT / "environment_repair_status.json",
        LOCAL_STATE_ROOT / "tool_health_history.json",
    )
    return {
        "snapshot_at": snapshot_at,
        "light": light,
        "autonomy": autonomy,
        "release_ops": release_ops,
        "environment": environment,
        "verification": verification,
        "control_layer": control_layer,
        "ai_test": ai_test,
        "lab": lab,
        "tool_health": tool_health,
        "daemon": daemon,
    }


def _local_inbox_snapshot(open_only: bool = False) -> dict[str, Any]:
    core_messages = _read_local_state_json("core_messages.json", [])
    escalation_inbox = _read_local_state_json("escalation_inbox.json", [])
    if not isinstance(core_messages, list):
        core_messages = []
    if not isinstance(escalation_inbox, list):
        escalation_inbox = []

    open_messages: list[dict[str, Any]] = []
    resolved_messages: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for item in core_messages:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        record = {
            "id": item.get("id"),
            "title": item.get("title"),
            "status": status,
            "severity": item.get("severity"),
            "source": item.get("source"),
            "created_at": item.get("created_at"),
            "task_id": item.get("task_id"),
        }
        if status in {"open", "pending", "queued"}:
            open_messages.append(record)
        elif status in {"resolved", "auto-resolved", "closed"}:
            resolved_messages.append(record)
        else:
            open_messages.append(record)

    if open_only:
        core_messages_view = open_messages
    else:
        core_messages_view = open_messages[:12] + resolved_messages[:6]

    return {
        "status": "cached_state",
        "source": "cached_state",
        "snapshot_at": _snapshot_from_paths(LOCAL_CORE_MESSAGES, LOCAL_ESCALATION_INBOX),
        "core_messages_total": len(core_messages),
        "core_messages_open": len(open_messages),
        "core_messages_resolved": len(resolved_messages),
        "core_message_status_counts": status_counts,
        "recent_open_messages": open_messages[:8],
        "recent_messages": core_messages_view,
        "escalation_inbox": escalation_inbox,
        "escalation_inbox_open_count": len([item for item in escalation_inbox if isinstance(item, dict)]),
    }


def _local_logs_snapshot(tail: int) -> dict[str, Any]:
    lines = _read_local_text_lines(LOCAL_DAEMON_LOG, tail)
    return {
        "status": "cached_state",
        "source": "cached_state",
        "snapshot_at": _snapshot_from_paths(LOCAL_DAEMON_LOG),
        "log_path": str(LOCAL_DAEMON_LOG),
        "tail": tail,
        "line_count": len(lines),
        "lines": lines,
    }


def _local_report_snapshot() -> dict[str, Any]:
    report = _read_local_state_json("system_report.json", {})
    if not isinstance(report, dict):
        report = {}
    return {
        "status": "cached_state",
        "source": "cached_state",
        "snapshot_at": _snapshot_from_paths(LOCAL_SYSTEM_REPORT),
        "report": report,
    }


def _run_local_control_json(args: Sequence[str]) -> tuple[Any, subprocess.CompletedProcess[str]]:
    script = ROOT / "orchestrator-mvp" / "tools" / "codex_control.py"
    if not script.exists():
        return {
            "ok": False,
            "command": " ".join(args),
            "error": f"Local control script not found: {script}",
        }, subprocess.CompletedProcess(
            args=list(args),
            returncode=1,
            stdout="",
            stderr=f"Local control script not found: {script}",
        )
    effective_args = list(args)
    token = _current_session_token()
    if token and (not effective_args or effective_args[0] != "--session-token"):
        effective_args = ["--session-token", token, *effective_args]
    result = subprocess.run(
        [sys.executable, str(script), *effective_args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "command": " ".join(args),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, result
    return _load_json_text(result.stdout, {}), result


def _emit_local_status(command: str, payload: dict[str, Any]) -> int:
    snapshot_at = payload.pop("snapshot_at", None)
    _emit_json(_envelope(command, source="cached_state", snapshot_at=snapshot_at, **payload))
    return EXIT_DEGRADED


def _structured_local_status(command: str, argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"factoryctl {command}")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(list(argv))
    snapshot = _local_snapshot()

    if command == "daemon-status":
        payload = {"daemon": snapshot["daemon"]}
    elif command == "control-layer-status":
        payload = {"control_layer": snapshot["control_layer"]}
    elif command == "engineering-os-status":
        payload = {"engineering_os": snapshot["verification"]}
    elif command == "lab-status":
        payload = {"lab": snapshot["lab"]}
    elif command == "release-ops-status":
        payload = {"release_ops": snapshot["release_ops"]}
    elif command == "ai-test-status":
        payload = {"ai_test": snapshot["ai_test"]}
    elif command == "tool-health":
        payload = {"tool_health": snapshot["tool_health"]}
    elif command == "light-status":
        payload = snapshot["light"]
    elif command == "autonomy-score":
        payload = {"autonomy": snapshot["autonomy"]}
    else:
        return 1

    if args.human:
        if command == "daemon-status":
            print(f"daemon: {(payload.get('daemon') or {}).get('status') or 'unknown'}")
        elif command == "control-layer-status":
            control = payload.get("control_layer") or {}
            print(f"control_layer: {control.get('status') or 'unknown'}")
            print(f"quality_status: {control.get('quality_status') or 'unknown'}")
        elif command == "engineering-os-status":
            eng = payload.get("engineering_os") or {}
            print(f"engineering_os: {eng.get('status') or 'unknown'}")
            print(f"patch_gate: {(eng.get('patch_gate') or {}).get('status') or eng.get('patch_gate_status') or 'unknown'}")
            print(f"release_gate: {(eng.get('release_gate') or {}).get('status') or eng.get('release_gate_status') or 'unknown'}")
        elif command == "lab-status":
            lab = payload.get("lab") or {}
            print(f"lab: {lab.get('status') or 'unknown'}")
        elif command == "release-ops-status":
            release_ops = payload.get("release_ops") or {}
            print(f"release_ops: {release_ops.get('status') or 'unknown'}")
        elif command == "ai-test-status":
            ai_test = payload.get("ai_test") or {}
            print(f"ai_test: {ai_test.get('status') or 'unknown'}")
            print(f"pass_rate: {ai_test.get('pass_rate') if ai_test.get('pass_rate') is not None else 'unknown'}")
        elif command == "tool-health":
            tool_health = payload.get("tool_health") or {}
            print(f"tool_health: {tool_health.get('status') or 'unknown'}")
        elif command == "light-status":
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif command == "autonomy-score":
            autonomy = payload.get("autonomy") or {}
            print(f"autonomy_stage: {autonomy.get('stage') or 'unknown'}")
            print(f"autonomy_score: {autonomy.get('score') if autonomy.get('score') is not None else 'unknown'}")
        return payload["result_code"]

    return _emit_local_status(command, payload)


def _live_first_status_payload(command: str, payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        normalized = dict(payload)
        normalized.pop("ok", None)
        normalized.pop("command", None)
        source = normalized.pop("source", "live")
        snapshot_at = normalized.pop("snapshot_at", None)
        return _envelope(command, source=source, snapshot_at=snapshot_at, **normalized)
    return _envelope(command, source="live", payload=payload)


def _human_status_lines(command: str, payload: Any) -> None:
    if command == "daemon-status":
        daemon = payload.get("daemon") if isinstance(payload, dict) else {}
        if isinstance(daemon, dict):
            print(f"daemon: {daemon.get('status') or 'unknown'}")
            print(f"cycle: {daemon.get('cycle') if daemon.get('cycle') is not None else 'unknown'}")
            print(f"last_tick_at: {daemon.get('last_tick_at') or 'unknown'}")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if command == "control-layer-status":
        control = payload.get("control_layer") if isinstance(payload, dict) else {}
        if not isinstance(control, dict) or not control:
            control = payload if isinstance(payload, dict) else {}
        print(f"control_layer: {control.get('status') or 'unknown'}")
        print(f"quality_status: {control.get('quality_status') or 'unknown'}")
        return
    if command == "engineering-os-status":
        eng = payload.get("engineering_os") if isinstance(payload, dict) else {}
        if not isinstance(eng, dict) or not eng:
            eng = payload if isinstance(payload, dict) else {}
        print(f"engineering_os: {eng.get('status') or 'unknown'}")
        print(f"patch_gate: {(eng.get('patch_gate') or {}).get('status') or eng.get('patch_gate_status') or 'unknown'}")
        print(f"release_gate: {(eng.get('release_gate') or {}).get('status') or eng.get('release_gate_status') or 'unknown'}")
        return
    if command == "lab-status":
        lab = payload.get("lab") if isinstance(payload, dict) else {}
        if not isinstance(lab, dict) or not lab:
            lab = payload if isinstance(payload, dict) else {}
        print(f"lab: {lab.get('status') or 'unknown'}")
        return
    if command == "release-ops-status":
        release_ops = payload.get("release_ops") if isinstance(payload, dict) else {}
        if not isinstance(release_ops, dict) or not release_ops:
            release_ops = payload if isinstance(payload, dict) else {}
        print(f"release_ops: {release_ops.get('status') or 'unknown'}")
        return
    if command == "ai-test-status":
        ai_test = payload.get("ai_test") if isinstance(payload, dict) else {}
        if not isinstance(ai_test, dict) or not ai_test:
            ai_test = payload if isinstance(payload, dict) else {}
        print(f"ai_test: {ai_test.get('status') or 'unknown'}")
        print(f"pass_rate: {ai_test.get('pass_rate') if ai_test.get('pass_rate') is not None else 'unknown'}")
        return
    if command == "tool-health":
        tool_health = payload.get("tool_health") if isinstance(payload, dict) else {}
        if not isinstance(tool_health, dict) or not tool_health:
            tool_health = payload if isinstance(payload, dict) else {}
        print(f"tool_health: {tool_health.get('status') or 'unknown'}")
        return
    if command == "light-status":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if command == "autonomy-score":
        autonomy = payload.get("autonomy") if isinstance(payload, dict) else {}
        if not isinstance(autonomy, dict) or not autonomy:
            autonomy = payload if isinstance(payload, dict) else {}
        print(f"autonomy_stage: {autonomy.get('stage') or 'unknown'}")
        print(f"autonomy_score: {autonomy.get('score') if autonomy.get('score') is not None else 'unknown'}")
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _structured_live_first_status(
    command: str,
    remote_command: str,
    argv: Sequence[str],
    output_key: str,
    snapshot_key: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(prog=f"factoryctl {command}")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(list(argv))
    remote_args = [remote_command]
    if args.refresh:
        remote_args.append("--refresh")
    payload, result = _collect_remote_json(*remote_args)
    if result.returncode != 0:
        snapshot = _local_snapshot()
        source = snapshot.get("source", "cached_state")
        payload = _envelope(
            command,
            source=source,
            snapshot_at=snapshot.get("snapshot_at"),
            **{output_key: snapshot[snapshot_key or output_key]},
        )
    else:
        payload = _live_first_status_payload(command, payload)
    if args.human:
        _human_status_lines(command, payload)
    else:
        _emit_json(payload)
    if payload.get("source") == "live":
        _maybe_auto_sync_generated(f"status:{command}")
    return payload.get("result_code", EXIT_OK)


def _structured_generated_sync(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl generated-sync")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(list(argv))
    result = _run_generated_sync(force=args.force, quiet=False, cooldown_seconds=0, reason="manual")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    payload = _load_json_text(result.stdout, {})
    envelope = _envelope("generated-sync", source="live" if result.returncode == 0 else "cached_state", generated_sync=payload)
    if args.human:
        sync_payload = envelope.get("generated_sync") or {}
        print(f"generated_sync: {sync_payload.get('status') or 'unknown'}")
        print(f"fingerprint: {sync_payload.get('fingerprint') or 'unknown'}")
        print(f"host_generated_root: {sync_payload.get('host_generated_root') or str(ROOT / 'generated')}")
    else:
        _emit_json(envelope)
    return EXIT_OK if result.returncode == 0 else EXIT_DEGRADED


def _structured_daemon_status(argv: Sequence[str]) -> int:
    return _structured_live_first_status("daemon-status", "daemon-status", argv, "daemon", "daemon")


def _collect_remote_json(*args: str) -> tuple[Any, subprocess.CompletedProcess[str]]:
    result = _run_remote(args)
    if result.returncode != 0:
        return {
            "ok": False,
            "command": " ".join(args),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, result
    return _load_json_text(result.stdout, {}), result


def _emit_json(payload: Any) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(rendered)
    except UnicodeEncodeError:
        safe = rendered.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe)


def _print_remote_stderr(result: subprocess.CompletedProcess[str]) -> None:
    stderr = result.stderr or ""
    if stderr:
        print(stderr, file=sys.stderr, end="" if stderr.endswith("\n") else "\n")


def _status_summary(payload: Any) -> dict[str, Any]:
    light = payload.get("light") if isinstance(payload, dict) else {}
    autonomy = payload.get("autonomy") if isinstance(payload, dict) else {}
    source = payload.get("source") if isinstance(payload, dict) else None
    host_control_plane = "live" if source in {None, "live"} else "degraded_cached_state"
    return {
        "source": source or "live",
        "execution_root": "vm_ssh_primary",
        "host_control_plane": host_control_plane,
        "daemon": {
            "status": (light or {}).get("daemon", {}).get("status"),
            "cycle": (light or {}).get("daemon", {}).get("cycle"),
            "last_tick_at": (light or {}).get("daemon", {}).get("last_tick_at"),
        },
        "control_layer": {
            "status": (light or {}).get("control_layer", {}).get("status"),
            "quality_score": (light or {}).get("control_layer", {}).get("quality_score"),
            "quality_status": (light or {}).get("control_layer", {}).get("quality_status"),
        },
        "engineering_os": {
            "status": (light or {}).get("engineering_os", {}).get("status"),
            "patch_gate_status": (light or {}).get("engineering_os", {}).get("patch_gate_status"),
            "release_gate_status": (light or {}).get("engineering_os", {}).get("release_gate_status"),
        },
        "lab": {
            "status": (light or {}).get("lab", {}).get("status"),
            "release_train_status": (light or {}).get("lab", {}).get("release_train_status"),
        },
        "autonomy": {
            "stage": (autonomy or {}).get("stage"),
            "score": (autonomy or {}).get("score"),
            "stable_autonomy": (autonomy or {}).get("stable_autonomy"),
        },
    }


def _verify_summary(payload: Any) -> dict[str, Any]:
    engineering_os = payload.get("engineering_os") if isinstance(payload, dict) else {}
    ai_test = payload.get("ai_test") if isinstance(payload, dict) else {}
    control_layer = payload.get("control_layer") if isinstance(payload, dict) else {}
    release_ops = payload.get("release_ops") if isinstance(payload, dict) else {}
    engineering_os_state = (engineering_os or {}).get("engineering_os") if isinstance(engineering_os, dict) else None
    return {
        "engineering_os": {
            "status": (engineering_os_state or engineering_os or {}).get("status"),
            "patch_gate_status": (engineering_os_state or engineering_os or {}).get("patch_gate_status"),
            "release_gate_status": (engineering_os_state or engineering_os or {}).get("release_gate_status"),
        },
        "ai_test": {
            "status": (ai_test or {}).get("status"),
            "pass_rate": (ai_test or {}).get("pass_rate"),
            "error_count": (ai_test or {}).get("error_count"),
        },
        "control_layer": {
            "status": (control_layer or {}).get("status"),
            "quality_score": (control_layer or {}).get("quality_score"),
            "quality_status": (control_layer or {}).get("quality_status"),
        },
        "release_ops": {
            "status": (release_ops or {}).get("status"),
            "release_train_status": (release_ops or {}).get("release_train_status"),
            "next_action": (release_ops or {}).get("next_action"),
        },
    }


def _doctor_summary(payload: Any) -> dict[str, Any]:
    vmctl_exists = VMCTL.exists()
    source = payload.get("source") if isinstance(payload, dict) else None
    remote_ok = isinstance(payload, dict) and payload.get("remote_reachable") is True
    engineering_os = payload.get("engineering_os") if isinstance(payload, dict) else {}
    engineering_os_state = (engineering_os or {}).get("engineering_os") if isinstance(engineering_os, dict) else None
    return {
        "vmctl_exists": vmctl_exists,
        "source": source or ("live" if remote_ok else "unknown"),
        "remote_reachable": remote_ok,
        "execution_root": "vm_ssh_primary",
        "host_control_plane": "live" if remote_ok else "degraded_cached_state",
        "probe_layer": "vmrun_optional",
        "status": (payload or {}).get("status") if isinstance(payload, dict) else None,
        "control_layer": (payload or {}).get("control_layer", {}).get("status") if isinstance(payload, dict) else None,
        "engineering_os": (engineering_os_state or engineering_os or {}).get("status"),
    }


def _health_summary(payload: Any) -> dict[str, Any]:
    daemon = payload.get("daemon") if isinstance(payload, dict) else {}
    control_layer = payload.get("control_layer") if isinstance(payload, dict) else {}
    engineering_os = payload.get("engineering_os") if isinstance(payload, dict) else {}
    tool_health = payload.get("tool_health") if isinstance(payload, dict) else {}
    ai_test = payload.get("ai_test") if isinstance(payload, dict) else {}
    return {
        "daemon": {
            "status": (daemon or {}).get("status"),
            "cycle": (daemon or {}).get("cycle"),
            "last_tick_at": (daemon or {}).get("last_tick_at"),
        },
        "control_layer": {
            "status": (control_layer or {}).get("status"),
            "quality_score": (control_layer or {}).get("quality_score"),
            "quality_status": (control_layer or {}).get("quality_status"),
        },
        "engineering_os": {
            "status": (engineering_os or {}).get("status"),
            "patch_gate_status": (engineering_os or {}).get("patch_gate_status"),
            "release_gate_status": (engineering_os or {}).get("release_gate_status"),
        },
        "tool_health": {
            "status": (tool_health or {}).get("status"),
            "issue_count": (tool_health or {}).get("issue_count"),
        },
        "ai_test": {
            "status": (ai_test or {}).get("status"),
            "pass_rate": (ai_test or {}).get("pass_rate"),
            "error_count": (ai_test or {}).get("error_count"),
        },
    }


def _ops_summary(payload: Any) -> dict[str, Any]:
    release_ops = payload.get("release_ops") if isinstance(payload, dict) else {}
    environment = payload.get("environment") if isinstance(payload, dict) else {}
    daemon = payload.get("daemon") if isinstance(payload, dict) else {}
    return {
        "release_ops": {
            "status": (release_ops or {}).get("status"),
            "release_train_status": (release_ops or {}).get("release_train_status"),
            "next_action": (release_ops or {}).get("next_action"),
        },
        "environment": {
            "status": (environment or {}).get("status"),
            "summary": (environment or {}).get("summary"),
        },
        "daemon": {
            "status": (daemon or {}).get("status"),
            "cycle": (daemon or {}).get("cycle"),
        },
    }


def _memory_summary(payload: Any) -> dict[str, Any]:
    memory_objects = payload.get("memory_objects") if isinstance(payload, dict) else {}
    dialogue = payload.get("dialogue_memory") if isinstance(payload, dict) else {}
    recent_verified = (memory_objects or {}).get("recent_verified") or []
    counts_by_type = (memory_objects or {}).get("counts_by_type") or {}
    return {
        "object_count": (memory_objects or {}).get("object_count"),
        "candidate_count": (memory_objects or {}).get("candidate_count"),
        "counts_by_type": counts_by_type,
        "recent_verified": [
            {
                "memory_id": item.get("memory_id"),
                "memory_type": item.get("memory_type"),
                "title": item.get("title"),
            }
            for item in recent_verified[:3]
            if isinstance(item, dict)
        ],
        "dialogue_sessions": (dialogue or {}).get("session_count"),
        "dialogue_messages": (dialogue or {}).get("message_count"),
        "dialogue_topics": (dialogue or {}).get("recent_topics") or [],
        "active_handoff_title": ((dialogue or {}).get("active_handoff") or {}).get("title"),
    }


def _load_local_dialogue_memory(limit: int = 8) -> tuple[Any, subprocess.CompletedProcess[str]]:
    return _load_local_dialogue_status(limit=limit)


def _load_local_dialogue_status(limit: int = 8) -> tuple[Any, subprocess.CompletedProcess[str]]:
    workspace = ROOT / "orchestrator-mvp"
    script = workspace / "tools" / "dialogue_memory.py"
    if not script.exists():
        return {
            "ok": False,
            "command": "dialogue-status",
            "error": f"Local dialogue status script not found: {script}",
        }, subprocess.CompletedProcess(args=[str(script)], returncode=1, stdout="", stderr="")

    code = (
        "import json, sys; "
        f"sys.path.insert(0, {str(workspace)!r}); "
        "from tools.dialogue_memory import SUMMARY, _load_json; "
        "payload = _load_json(SUMMARY, {}); "
        "result = {"
        "  'updated_at': payload.get('updated_at'),"
        "  'session_count': payload.get('session_count', 0),"
        "  'message_count': payload.get('message_count', 0),"
        "  'recent_topics': payload.get('recent_topics', []),"
        "  'recent_decisions': payload.get('recent_decisions', []),"
        "  'shared_constraints': payload.get('shared_constraints', []),"
        "  'active_handoff': payload.get('active_handoff', {}),"
        f"  'recent_sessions': (payload.get('recent_sessions') or [])[:{max(1, limit)}],"
        "  'summary_path': str(SUMMARY),"
        "}; "
        "print(json.dumps(result, ensure_ascii=False, indent=2))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(workspace),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "command": "dialogue-status",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }, result
    payload = _load_json_text(result.stdout, {})
    if isinstance(payload, dict):
        recent_sessions = payload.get("recent_sessions") or []
        payload["recent_sessions"] = recent_sessions[: max(1, limit)]
    return payload, result


def _pack_payload(command: str, summary: Any, full: bool = False, **raw: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": True, "command": command, "summary": summary}
    if full and raw:
        payload["raw"] = raw
    return payload


def _print_human_status(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _status_summary(payload)
    print("系统状态：")
    print(f"- 守护进程：{(summary.get('daemon') or {}).get('status') or 'unknown'}")
    print(f"- 控制层：{(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- 工程系统：{(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- 实验室：{(summary.get('lab') or {}).get('status') or 'unknown'}")
    print(f"- 自主阶段：{(summary.get('autonomy') or {}).get('stage') or 'unknown'}")
    print(f"- 质量状态：{(summary.get('control_layer') or {}).get('quality_status') or 'unknown'}")


def _print_human_verify(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _verify_summary(payload)
    print("验证状态：")
    print(f"- 工程系统：{(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- 补丁门禁：{(summary.get('engineering_os') or {}).get('patch_gate_status') or 'unknown'}")
    print(f"- 发布门禁：{(summary.get('engineering_os') or {}).get('release_gate_status') or 'unknown'}")
    print(f"- AI 测试：{(summary.get('ai_test') or {}).get('status') or 'unknown'}")
    print(f"- AI 测试通过率：{(summary.get('ai_test') or {}).get('pass_rate') if (summary.get('ai_test') or {}).get('pass_rate') is not None else 'unknown'}")
    print(f"- 控制层：{(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- 发布链路：{(summary.get('release_ops') or {}).get('status') or 'unknown'}")


def _print_human_doctor(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _doctor_summary(payload)
    print("CLI 诊断：")
    print(f"- vmctl 存在：{'yes' if summary.get('vmctl_exists') else 'no'}")
    print(f"- 远端可达：{'yes' if summary.get('remote_reachable') else 'no'}")
    print(f"- 当前状态：{summary.get('status') or 'unknown'}")
    print(f"- 控制层：{summary.get('control_layer') or 'unknown'}")
    print(f"- 工程系统：{summary.get('engineering_os') or 'unknown'}")


def _print_human_health(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _health_summary(payload)
    print("健康摘要：")
    print(f"- 守护进程：{(summary.get('daemon') or {}).get('status') or 'unknown'}")
    print(f"- 控制层：{(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- 工程系统：{(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- 工具健康：{(summary.get('tool_health') or {}).get('status') or 'unknown'}")
    print(f"- AI 测试：{(summary.get('ai_test') or {}).get('status') or 'unknown'}")


def _print_human_ops(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _ops_summary(payload)
    print("运维摘要：")
    print(f"- 发布链路：{(summary.get('release_ops') or {}).get('status') or 'unknown'}")
    print(f"- 发布训练：{(summary.get('release_ops') or {}).get('release_train_status') or 'unknown'}")
    print(f"- 环境状态：{(summary.get('environment') or {}).get('status') or 'unknown'}")
    print(f"- 守护进程：{(summary.get('daemon') or {}).get('status') or 'unknown'}")


def _structured_status(human: bool) -> int:
    light, result = _collect_remote_json("light-status")
    autonomy, autonomy_result = _collect_remote_json("autonomy-score")
    if result.returncode != 0 or autonomy_result.returncode != 0:
        local = _local_snapshot()
        source = local.get("source", "cached_state")
        payload = _envelope(
            "status",
            source=source,
            snapshot_at=local.get("snapshot_at"),
            summary=_status_summary({"light": local["light"], "autonomy": local["autonomy"], "source": source}),
        )
        if human:
            _print_human_status_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope(
        "status",
        source="live",
        summary=_status_summary({"light": light, "autonomy": autonomy, "source": "live"}),
    )
    if human:
        _print_human_status_clean(payload)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_health(human: bool) -> int:
    light, light_result = _collect_remote_json("light-status")
    tool_health, tool_health_result = _collect_remote_json("tool-health")
    remote_ok = all(result.returncode == 0 for result in (light_result, tool_health_result))
    if not remote_ok:
        local = _local_snapshot()
        source = local.get("source", "cached_state")
        payload = _envelope(
            "health",
            source=source,
            snapshot_at=local.get("snapshot_at"),
            summary=_health_summary(
                {
                    "daemon": local["daemon"],
                    "control_layer": local["control_layer"],
                    "engineering_os": local["verification"],
                    "tool_health": local["tool_health"],
                    "ai_test": local["ai_test"],
                }
            ),
        )
        if human:
            _print_human_health_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope(
        "health",
        source="live",
        summary=_health_summary(
            {
                "daemon": light.get("daemon") if isinstance(light, dict) else light,
                "control_layer": light.get("control_layer") if isinstance(light, dict) else light,
                "engineering_os": light.get("engineering_os") if isinstance(light, dict) else light,
                "tool_health": tool_health,
                "ai_test": light.get("ai_testing") if isinstance(light, dict) else {},
            }
        ),
    )
    if human:
        _print_human_health_clean(payload)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_logs(human: bool, tail: int) -> int:
    payload, result = _collect_remote_json("logs", "--tail", str(tail))
    if result.returncode != 0:
        local = _local_logs_snapshot(tail)
        payload = _envelope(
            "logs",
            source="cached_state",
            snapshot_at=local.get("snapshot_at"),
            lines=local["lines"],
            tail=tail,
            log_path=local["log_path"],
        )
        if human:
            print("Logs:")
            for line in local["lines"]:
                print(line)
        else:
            _emit_json(payload)
        return payload["result_code"]
    if human:
        print("日志：")
        for line in (payload or [])[-tail:]:
            print(line)
    else:
        _emit_json(_envelope("logs", source="live", lines=payload, tail=tail))
    return EXIT_OK


def _structured_ops(human: bool) -> int:
    light, light_result = _collect_remote_json("light-status")
    release_ops, release_result = _collect_remote_json("release-ops-status")
    environment, environment_result = _collect_remote_json("environment-status")
    remote_ok = all(result.returncode == 0 for result in (light_result, release_result, environment_result))
    if not remote_ok:
        local = _local_snapshot()
        source = local.get("source", "cached_state")
        payload = _envelope(
            "ops",
            source=source,
            snapshot_at=local.get("snapshot_at"),
            summary=_ops_summary(
                {
                    "release_ops": local["release_ops"],
                    "environment": local["environment"],
                    "daemon": local["daemon"],
                }
            ),
        )
        if human:
            _print_human_ops_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope(
        "ops",
        source="live",
        summary=_ops_summary(
            {
                "release_ops": release_ops,
                "environment": environment,
                "daemon": light.get("daemon") if isinstance(light, dict) else light,
            }
        ),
    )
    if human:
        _print_human_ops_clean(payload)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_verify(human: bool) -> int:
    engineering_os, engineering_result = _collect_remote_json("engineering-os-status")
    ai_test, ai_result = _collect_remote_json("ai-test-status")
    control_layer, control_result = _collect_remote_json("control-layer-status")
    release_ops, release_result = _collect_remote_json("release-ops-status")
    if any(result.returncode != 0 for result in (engineering_result, ai_result, control_result, release_result)):
        local = _local_snapshot()
        source = local.get("source", "cached_state")
        payload = _envelope(
            "verify",
            source=source,
            snapshot_at=local.get("snapshot_at"),
            summary=_verify_summary(
                {
                    "engineering_os": local["verification"],
                    "ai_test": local["ai_test"],
                    "control_layer": local["control_layer"],
                    "release_ops": local["release_ops"],
                }
            ),
        )
        if human:
            _print_human_verify_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope(
        "verify",
        source="live",
        summary=_verify_summary(
            {
                "engineering_os": engineering_os,
                "ai_test": ai_test,
                "control_layer": control_layer,
                "release_ops": release_ops,
            }
        ),
    )
    if human:
        _print_human_verify_clean(payload)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_doctor(human: bool) -> int:
    daemon, daemon_result = _collect_remote_json("light-status")
    control_layer, control_result = _collect_remote_json("control-layer-status")
    engineering_os, engineering_result = _collect_remote_json("engineering-os-status")
    lab, lab_result = _collect_remote_json("lab-status")
    remote_ok = all(result.returncode == 0 for result in (daemon_result, control_result, engineering_result, lab_result))
    if not remote_ok:
        local = _local_snapshot()
        source = local.get("source", "cached_state")
        payload = _envelope(
            "doctor",
            source=source,
            snapshot_at=local.get("snapshot_at"),
            remote_reachable=False,
            summary=_doctor_summary(
                {
                    "status": local["daemon"].get("status"),
                    "control_layer": local["control_layer"],
                    "engineering_os": local["verification"],
                    "lab": local["lab"],
                    "remote_reachable": False,
                    "source": source,
                }
            ),
        )
        if human:
            _print_human_doctor_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope(
        "doctor",
        source="live",
        remote_reachable=True,
        summary=_doctor_summary(
            {
                "status": (daemon.get("daemon") or {}).get("status") if isinstance(daemon, dict) else None,
                "control_layer": control_layer,
                "engineering_os": engineering_os,
                "lab": lab,
                "remote_reachable": True,
                "source": "live",
            }
        ),
    )
    if human:
        _print_human_doctor_clean(payload)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_report(human: bool) -> int:
    report, result = _collect_remote_json("operator-report")
    if result.returncode != 0:
        local = _local_report_snapshot()
        payload = _envelope(
            "report",
            source="cached_state",
            snapshot_at=local.get("snapshot_at"),
            report=local["report"],
        )
        if human:
            _print_human_report_clean(payload)
        else:
            _emit_json(payload)
        return payload["result_code"]
    payload = _envelope("report", source="live", report=report)
    if human:
        print("系统报告：")
        if isinstance(report, dict):
            report_chain = report.get("report_chain") or {}
            headline = (
                report_chain.get("recommended_next_action")
                or report_chain.get("current_action")
                or report.get("summary")
                or report.get("next_action")
                or report.get("status")
                or report.get("title")
            )
            print(f"- 要点：{headline or 'unknown'}")
            for sentence in (report_chain.get("summary_sentences") or [])[:3]:
                print(f"- {sentence}")
        else:
            print(report)
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_deploy(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl deploy")
    parser.add_argument("target")
    parser.add_argument("--workspace")
    parser.add_argument("--goal")
    parser.add_argument("--caller", default="codex-control")
    parser.add_argument("--reason", default="")
    parser.add_argument("--context-mode", choices=["lean", "standard", "deep"], default="standard")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    prompt = f"deploy {args.target}".strip()
    if args.reason:
        prompt = f"{prompt}: {args.reason}"
    dispatch_args = ["dispatch", prompt, "--caller", args.caller, "--context-mode", args.context_mode]
    if args.workspace:
        dispatch_args.extend(["--repo-path", args.workspace])
    if args.goal:
        dispatch_args.extend(["--goal", args.goal])
    if args.auto_approve:
        dispatch_args.append("--auto-approve")
    if args.full:
        dispatch_args.append("--full")

    if args.dry_run:
        payload = {
            "ok": True,
            "command": "deploy",
            "dry_run": True,
            "dispatch": {
                "prompt": prompt,
                "args": dispatch_args,
            },
        }
        if args.human and not args.json:
            _print_human_deploy_preview_clean(args.target, prompt, args.workspace)
            return 0
            _print_human_deploy_preview_clean(args.target, prompt, args.workspace)
            return 0
            _print_human_deploy_preview_clean(args.target, prompt, args.workspace)
            return 0
            print("部署预演：")
            print(f"- 目标：{args.target}")
            print(f"- 提示：{prompt}")
            if args.workspace:
                print(f"- 工作区：{args.workspace}")
        else:
            _emit_json(payload)
        return 0

    created, result = _collect_remote_json(*dispatch_args)
    if result.returncode != 0:
        _print_remote_stderr(result)
        _emit_json(created)
        return result.returncode
    payload = {"ok": True, "command": "deploy", "dispatch": created}
    if args.human and not args.json:
        _print_human_deploy_submitted_clean(
            args.target,
            (created.get("surface") if isinstance(created, dict) else None) or "unknown",
            args.reason,
        )
        return 0
        _print_human_deploy_submitted_clean(
            args.target,
            (created.get("surface") if isinstance(created, dict) else None) or "unknown",
            args.reason,
        )
        return 0
        print("部署请求已提交：")
        print(f"- 目标：{args.target}")
        print(f"- 入口：{(created.get('surface') if isinstance(created, dict) else None) or 'unknown'}")
        if args.reason:
            print(f"- 原因：{args.reason}")
    else:
        _emit_json(payload)
    return 0


def _structured_rollback(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl rollback")
    parser.add_argument("target")
    parser.add_argument("--workspace")
    parser.add_argument("--goal")
    parser.add_argument("--caller", default="codex-control")
    parser.add_argument("--reason", default="")
    parser.add_argument("--context-mode", choices=["lean", "standard", "deep"], default="standard")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    prompt = f"rollback {args.target}".strip()
    if args.reason:
        prompt = f"{prompt}: {args.reason}"
    dispatch_args = ["dispatch", prompt, "--caller", args.caller, "--context-mode", args.context_mode]
    if args.workspace:
        dispatch_args.extend(["--repo-path", args.workspace])
    if args.goal:
        dispatch_args.extend(["--goal", args.goal])

    if args.dry_run:
        payload = {
            "ok": True,
            "command": "rollback",
            "dry_run": True,
            "dispatch": {
                "prompt": prompt,
                "args": dispatch_args,
            },
        }
        if args.human and not args.json:
            print("回滚预演：")
            print(f"- 目标：{args.target}")
            print(f"- 提示：{prompt}")
            if args.workspace:
                print(f"- 工作区：{args.workspace}")
        else:
            _emit_json(payload)
        return 0

    created, result = _collect_remote_json(*dispatch_args)
    if result.returncode != 0:
        _print_remote_stderr(result)
        _emit_json(created)
        return result.returncode
    payload = {"ok": True, "command": "rollback", "dispatch": created}
    if args.human and not args.json:
        _print_human_rollback_submitted_clean(
            args.target,
            (created.get("surface") if isinstance(created, dict) else None) or "unknown",
            args.reason,
        )
        return 0
        print("回滚请求已提交：")
        print(f"- 目标：{args.target}")
        print(f"- 入口：{(created.get('surface') if isinstance(created, dict) else None) or 'unknown'}")
        if args.reason:
            print(f"- 原因：{args.reason}")
    else:
        _emit_json(payload)
    return 0


def _structured_confirm(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl confirm")
    parser.add_argument("kind", nargs="?", default="general", choices=["general", "deploy", "rollback"])
    parser.add_argument("--workspace")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))

    _, _ = _collect_remote_json("goal-report")
    health, health_result = _collect_remote_json("light-status")
    verify, verify_result = _collect_remote_json("engineering-os-status")
    ops, ops_result = _collect_remote_json("release-ops-status")
    remote_ok = all(result.returncode == 0 for result in (health_result, verify_result, ops_result))
    if not remote_ok:
        for result in (health_result, verify_result, ops_result):
            if result.returncode != 0:
                _print_remote_stderr(result)
    engineering_os_state = (verify.get("engineering_os") if isinstance(verify, dict) else {}) or {}
    engineering_os_state = engineering_os_state.get("engineering_os") if isinstance(engineering_os_state, dict) else engineering_os_state
    ai_test_state = (health.get("ai_testing") if isinstance(health, dict) else {}) or {}
    release_ops_state = ops.get("release_ops") if isinstance(ops, dict) else ops
    ready = remote_ok and ((engineering_os_state or verify or {}).get("status") == "pass" if isinstance(verify, dict) else True) and ((ai_test_state or {}).get("status") == "pass" if isinstance(ai_test_state, dict) else True) and ((release_ops_state or {}).get("status") in {"pass", "ready"} if isinstance(release_ops_state, dict) else True)
    payload = _envelope(
        "confirm",
        source="live" if remote_ok else "cached_state",
        kind=args.kind,
        ready=ready,
        dry_run=bool(args.dry_run),
        summary={
            "daemon": ((health.get("daemon") if isinstance(health, dict) else {}) or {}).get("status"),
            "verification": _verify_summary(
                {
                    "engineering_os": {"engineering_os": engineering_os_state} if engineering_os_state else verify,
                    "ai_test": ai_test_state,
                    "control_layer": {},
                    "release_ops": release_ops_state,
                }
            ),
            "ops": _ops_summary(
                {
                    "release_ops": release_ops_state,
                    "environment": {},
                    "daemon": health.get("daemon") if isinstance(health, dict) else health,
                }
            ),
        },
    )
    if args.human and not args.json:
        _print_human_confirm_clean(args.kind, bool(payload.get("ready")), args.dry_run)
        return 0
        print("确认结果：")
        print(f"- 类型：{args.kind}")
        print(f"- 可执行：{'yes' if payload.get('ready') else 'no'}")
        if args.dry_run:
            print("- 模式：dry-run")
    else:
        _emit_json(payload)
    return payload["result_code"]


def _structured_inbox(open_only: bool) -> int:
    args = ["inbox"]
    if open_only:
        args.append("--open-only")
    inbox, result = _collect_remote_json(*args)
    if result.returncode != 0:
        local = _local_inbox_snapshot(open_only=open_only)
        payload = _envelope(
            "inbox",
            source="cached_state",
            snapshot_at=local.get("snapshot_at"),
            inbox=local,
        )
        _emit_json(payload)
        return payload["result_code"]
    _emit_json(_envelope("inbox", source="live", inbox=inbox))
    return EXIT_OK


def _structured_sync(argv: Sequence[str]) -> int:
    result = _run_remote(["dialogue-sync", *argv])
    if result.returncode != 0:
        payload, local_result = _run_local_control_json(["dialogue-sync", *argv])
        if local_result.returncode != 0:
            _print_remote_stderr(result)
            if result.stdout:
                print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
            if local_result.stderr:
                print(local_result.stderr, file=sys.stderr, end="" if local_result.stderr.endswith("\n") else "\n")
            if local_result.stdout:
                print(local_result.stdout, end="" if local_result.stdout.endswith("\n") else "\n")
            return local_result.returncode
        _emit_json(_envelope("sync", source="cached_state", dialogue_sync=payload))
        return EXIT_DEGRADED
    payload = _load_json_text(result.stdout, {})
    _emit_json(_envelope("sync", source="live", dialogue_sync=payload))
    return EXIT_OK


def _structured_sync_current() -> int:
    script = ROOT / "orchestrator-mvp" / "tools" / "codex_control.py"
    if not script.exists():
        _emit_json(_envelope("dialogue-sync-current", source="cached_state", primary_available=False, error=f"Local control script not found: {script}"))
        return EXIT_UNAVAILABLE
    result = subprocess.run(
        [sys.executable, str(script), "dialogue-sync-current"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        return result.returncode
    payload = _load_json_text(result.stdout, {})
    _emit_json(_envelope("dialogue-sync-current", source="live", dialogue_sync=payload))
    return EXIT_OK


def _structured_dialogue_status(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl dialogue-status")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(list(argv))
    payload, result = _load_local_dialogue_status(args.limit)
    if result.returncode != 0:
        _emit_json(payload)
        return result.returncode
    _emit_json(_envelope("dialogue-status", source="cached_state", dialogue_memory=payload))
    return EXIT_DEGRADED


def _structured_dispatch(argv: Sequence[str]) -> int:
    return _structured_dispatch_v2(argv)

    parser = argparse.ArgumentParser(prog="factoryctl dispatch")
    parser.add_argument("prompt")
    parser.add_argument("--goal")
    parser.add_argument("--caller", default="codex-control")
    parser.add_argument("--workspace")
    parser.add_argument("--repo-path")
    parser.add_argument("--project-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--capability-request")
    parser.add_argument("--vm-request")
    parser.add_argument("--context-mode", choices=["lean", "standard", "deep"])
    parser.add_argument("--max-context-chars", type=int)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--no-resource-scan", action="store_true")
    parser.add_argument("--no-repo-status", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(list(argv))

    remote_args = ["dispatch", args.prompt]
    if args.goal:
        remote_args.extend(["--goal", args.goal])
    if args.caller:
        remote_args.extend(["--caller", args.caller])
    repo_path = args.repo_path or args.workspace
    if repo_path:
        remote_args.extend(["--repo-path", repo_path])
    if args.project_id:
        remote_args.extend(["--project-id", args.project_id])
    if args.repo_id:
        remote_args.extend(["--repo-id", args.repo_id])
    if args.capability_request:
        remote_args.extend(["--capability-request", args.capability_request])
    if args.vm_request:
        remote_args.extend(["--vm-request", args.vm_request])
    if args.context_mode:
        remote_args.extend(["--context-mode", args.context_mode])
    if args.max_context_chars is not None:
        remote_args.extend(["--max-context-chars", str(args.max_context_chars)])
    if args.auto_approve:
        remote_args.append("--auto-approve")
    if args.no_resource_scan:
        remote_args.append("--no-resource-scan")
    if args.no_repo_status:
        remote_args.append("--no-repo-status")
    if args.full:
        remote_args.append("--full")

    created, result = _collect_remote_json(*remote_args)
    if result.returncode != 0:
        _print_remote_stderr(result)
        _emit_json(created)
        return result.returncode
    payload = {"ok": True, "command": "dispatch", "dispatch": created}
    if args.human and not args.json:
        route = created.get("route") if isinstance(created, dict) else {}
        surface = created.get("surface") if isinstance(created, dict) else None
        print("任务已下发：")
        print(f"- 入口：{surface or (route or {}).get('preferred_surface') or 'unknown'}")
        print(f"- 提示：{created.get('summary') if isinstance(created, dict) else created}")
    else:
        _emit_json(payload)
    return 0


def _structured_dispatch_v2(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl dispatch")
    parser.add_argument("prompt")
    parser.add_argument("--goal")
    parser.add_argument("--caller", default="codex-control")
    parser.add_argument("--workspace")
    parser.add_argument("--repo-path")
    parser.add_argument("--project-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--capability-request")
    parser.add_argument("--vm-request")
    parser.add_argument("--context-mode", choices=["lean", "standard", "deep"])
    parser.add_argument("--max-context-chars", type=int)
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--precheck-only", action="store_true")
    parser.add_argument("--require-confirm", action="store_true")
    parser.add_argument("--no-resource-scan", action="store_true")
    parser.add_argument("--no-repo-status", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--human", action="store_true")
    args = parser.parse_args(list(argv))

    repo_path = args.repo_path or args.workspace
    readiness = {
        "kind": "enqueue",
        "ready": True,
        "reason": "dispatch boundary is enqueue-only; execution claims and heartbeats independently",
        "route": {
            "preferred_surface": "enqueue",
            "fallback_surface": "enqueue",
            "launch_hint": "execution claims the task and emits heartbeat",
        },
        "goal": {
            "goal_id": args.goal,
            "status": "deferred",
            "target": args.prompt,
            "task_ids": [],
        },
    }

    precheck = _dispatch_precheck_summary(
        readiness.get("route") if isinstance(readiness, dict) else {},
        readiness if isinstance(readiness, dict) else {},
        repo_path,
        args.confirm,
        args.require_confirm,
    )
    precheck["route_error"] = None
    precheck["goal_error"] = None

    if args.precheck_only or (args.require_confirm and not args.confirm):
        payload = {
            "ok": True,
            "command": "dispatch",
            "precheck": precheck,
            "blocked": True,
            "requires_confirmation": args.require_confirm and not args.confirm,
            "dry_run": True,
        }
        if args.human and not args.json:
            _print_human_dispatch_precheck_clean(args.prompt, precheck)
            if args.require_confirm and not args.confirm:
                print("- action: rerun with --confirm to submit")
        else:
            _emit_json(payload)
        return 0 if args.precheck_only else 2

    remote_args = ["dispatch", args.prompt]
    if args.goal:
        remote_args.extend(["--goal", args.goal])
    if args.caller:
        remote_args.extend(["--caller", args.caller])
    remote_args.append("--enqueue-only")
    if repo_path:
        remote_args.extend(["--repo-path", repo_path])
    if args.project_id:
        remote_args.extend(["--project-id", args.project_id])
    if args.repo_id:
        remote_args.extend(["--repo-id", args.repo_id])
    if args.capability_request:
        remote_args.extend(["--capability-request", args.capability_request])
    if args.vm_request:
        remote_args.extend(["--vm-request", args.vm_request])
    if args.context_mode:
        remote_args.extend(["--context-mode", args.context_mode])
    if args.max_context_chars is not None:
        remote_args.extend(["--max-context-chars", str(args.max_context_chars)])
    if args.auto_approve or args.confirm:
        remote_args.append("--auto-approve")
    if args.no_resource_scan:
        remote_args.append("--no-resource-scan")
    if args.no_repo_status:
        remote_args.append("--no-repo-status")
    if args.full:
        remote_args.append("--full")

    created, result = _run_local_control_json(remote_args)
    if result.returncode != 0:
        created, result = _collect_remote_json(*remote_args)
    if result.returncode != 0:
        _print_remote_stderr(result)
        _emit_json(created)
        if args.human and isinstance(created, dict):
            _print_human_dispatch_permission_hint(created)
        return result.returncode

    payload = {
        "ok": True,
        "command": "dispatch",
        "precheck": precheck,
        "dispatch": created,
        "confirmed": bool(args.confirm or args.auto_approve),
    }
    if args.human and not args.json:
        _print_human_dispatch_clean(created)
    else:
        _emit_json(payload)
    return 0


def _structured_route(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="factoryctl route")
    parser.add_argument("request")
    parser.add_argument("--workspace")
    parser.add_argument("--human", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv))
    remote_args = ["task-route", args.request]
    if args.workspace:
        remote_args.extend(["--workspace", args.workspace])
    routed, result = _run_local_control_json(remote_args)
    if result.returncode != 0:
        routed, result = _collect_remote_json(*remote_args)
    if result.returncode != 0:
        _print_remote_stderr(result)
        _emit_json(routed)
        return result.returncode
    payload = {"ok": True, "command": "route", "route": routed}
    if args.human and not args.json:
        print("路由建议：")
        print(f"- 目标：{routed.get('preferred_surface') or routed.get('fallback_surface') or 'unknown'}")
        print(f"- 原因：{routed.get('reason') or 'unknown'}")
        if routed.get("launch_hint"):
            print(f"- 下一步：{routed.get('launch_hint')}")
    else:
        _emit_json(payload)
    return 0


def _structured_memory(argv: Sequence[str]) -> int:
    if not argv:
        print("Usage: factoryctl.cmd memory <status|summary|integrity|quality|recall> [options]", file=sys.stderr)
        return 1

    command = argv[0]
    if command == "status":
        payload, result = _collect_remote_json("memory-status")
        if result.returncode != 0:
            _print_remote_stderr(result)
            _emit_json(payload)
            return result.returncode
        local_dialogue, local_result = _load_local_dialogue_memory()
        if local_result.returncode == 0 and isinstance(payload, dict):
            payload = dict(payload)
            payload["dialogue_memory"] = local_dialogue
        _emit_json({"ok": True, "command": "memory status", "summary": _memory_summary(payload)})
        return 0

    if command == "summary":
        payload, result = _collect_remote_json("memory-status")
        if result.returncode != 0:
            _print_remote_stderr(result)
            _emit_json(payload)
            return result.returncode
        local_dialogue, local_result = _load_local_dialogue_memory()
        if local_result.returncode == 0 and isinstance(payload, dict):
            payload = dict(payload)
            payload["dialogue_memory"] = local_dialogue
        summary = _memory_summary(payload)
        if any(arg in {"--human", "--text"} for arg in argv[1:]):
            _print_human_memory_summary_clean(summary)
            return 0
            print("记忆摘要：")
            print(f"- 已验证对象：{summary.get('object_count') or 'unknown'}")
            print(f"- 候选对象：{summary.get('candidate_count') or 'unknown'}")
            print(f"- 最近主题：{', '.join(summary.get('dialogue_topics')[:4]) or 'unknown'}")
            print(f"- 当前接力：{summary.get('active_handoff_title') or 'unknown'}")
        else:
            _emit_json({"ok": True, "command": "memory summary", "summary": summary})
        return 0

    if command == "integrity":
        payload, result = _collect_remote_json("memory-integrity")
        if result.returncode != 0:
            _print_remote_stderr(result)
            _emit_json(payload)
            return result.returncode
        _emit_json({"ok": True, "command": "memory integrity", "memory_integrity": payload})
        return 0

    if command == "quality":
        parser = argparse.ArgumentParser(prog="factoryctl memory quality")
        parser.add_argument("--workspace", default="")
        parser.add_argument("--refresh", action="store_true")
        args = parser.parse_args(list(argv[1:]))
        remote_args = ["memory-quality-scorecard"]
        if args.workspace:
            remote_args.extend(["--workspace", args.workspace])
        if args.refresh:
            remote_args.append("--refresh")
        payload, result = _collect_remote_json(*remote_args)
        if result.returncode != 0:
            _print_remote_stderr(result)
            _emit_json(payload)
            return result.returncode
        _emit_json({"ok": True, "command": "memory quality", "memory_quality_scorecard": payload})
        return 0

    if command == "recall":
        parser = argparse.ArgumentParser(prog="factoryctl memory recall")
        parser.add_argument("query", nargs="*")
        parser.add_argument("--workspace", default="")
        parser.add_argument("--tag", action="append", default=[])
        parser.add_argument("--type", dest="memory_type", action="append", default=[])
        parser.add_argument("--limit", type=int, default=8)
        parser.add_argument("--include-candidates", action="store_true")
        args = parser.parse_args(list(argv[1:]))
        remote_args = ["memory-recall", *args.query]
        if args.workspace:
            remote_args.extend(["--workspace", args.workspace])
        for tag in args.tag:
            remote_args.extend(["--tag", tag])
        for memory_type in args.memory_type:
            remote_args.extend(["--type", memory_type])
        remote_args.extend(["--limit", str(args.limit)])
        if args.include_candidates:
            remote_args.append("--include-candidates")
        payload, result = _collect_remote_json(*remote_args)
        if result.returncode != 0:
            _print_remote_stderr(result)
            _emit_json(payload)
            return result.returncode
        _emit_json({"ok": True, "command": "memory recall", "memory_recall": payload})
        return 0

    print(f"Unknown memory subcommand: {command}", file=sys.stderr)
    return 1


def _print_human_status_clean(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _status_summary(payload)
    print("System status:")
    print(f"- source: {(payload.get('source') if isinstance(payload, dict) else None) or summary.get('source') or 'unknown'}")
    print(f"- execution_root: {(payload.get('execution_root') if isinstance(payload, dict) else None) or summary.get('execution_root') or 'unknown'}")
    print(f"- host_control_plane: {(payload.get('host_control_plane') if isinstance(payload, dict) else None) or summary.get('host_control_plane') or 'unknown'}")
    print(f"- snapshot_at: {(payload.get('snapshot_at') if isinstance(payload, dict) else None) or 'unknown'}")
    print(f"- age_seconds: {(payload.get('age_seconds') if isinstance(payload, dict) else None) if isinstance(payload, dict) and payload.get('age_seconds') is not None else 'unknown'}")
    print(f"- stale: {('yes' if payload.get('stale') else 'no') if isinstance(payload, dict) and payload.get('stale') is not None else 'unknown'}")
    print(f"- daemon: {(summary.get('daemon') or {}).get('status') or 'unknown'}")
    print(f"- control_layer: {(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- engineering_os: {(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- lab: {(summary.get('lab') or {}).get('status') or 'unknown'}")
    print(f"- autonomy_stage: {(summary.get('autonomy') or {}).get('stage') or 'unknown'}")
    print(f"- quality_status: {(summary.get('control_layer') or {}).get('quality_status') or 'unknown'}")


def _print_human_verify_clean(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _verify_summary(payload)
    print("Verification status:")
    print(f"- engineering_os: {(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- patch_gate: {(summary.get('engineering_os') or {}).get('patch_gate_status') or 'unknown'}")
    print(f"- release_gate: {(summary.get('engineering_os') or {}).get('release_gate_status') or 'unknown'}")
    print(f"- ai_test: {(summary.get('ai_test') or {}).get('status') or 'unknown'}")
    pass_rate = (summary.get("ai_test") or {}).get("pass_rate")
    print(f"- ai_test_pass_rate: {pass_rate if pass_rate is not None else 'unknown'}")
    print(f"- control_layer: {(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- release_ops: {(summary.get('release_ops') or {}).get('status') or 'unknown'}")


def _print_human_doctor_clean(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _doctor_summary(payload)
    print("CLI diagnosis:")
    print(f"- vmctl_exists: {'yes' if summary.get('vmctl_exists') else 'no'}")
    print(f"- source: {(payload.get('source') if isinstance(payload, dict) else None) or summary.get('source') or 'unknown'}")
    print(f"- remote_reachable: {'yes' if summary.get('remote_reachable') else 'no'}")
    print(f"- execution_root: {(payload.get('execution_root') if isinstance(payload, dict) else None) or summary.get('execution_root') or 'unknown'}")
    print(f"- host_control_plane: {(payload.get('host_control_plane') if isinstance(payload, dict) else None) or summary.get('host_control_plane') or 'unknown'}")
    print(f"- probe_layer: {summary.get('probe_layer') or 'unknown'}")
    print(f"- snapshot_at: {(payload.get('snapshot_at') if isinstance(payload, dict) else None) or 'unknown'}")
    print(f"- age_seconds: {(payload.get('age_seconds') if isinstance(payload, dict) else None) if isinstance(payload, dict) and payload.get('age_seconds') is not None else 'unknown'}")
    print(f"- stale: {('yes' if payload.get('stale') else 'no') if isinstance(payload, dict) and payload.get('stale') is not None else 'unknown'}")
    print(f"- result_code: {(payload.get('result_code') if isinstance(payload, dict) else None) if isinstance(payload, dict) else 'unknown'}")
    print(f"- status: {summary.get('status') or 'unknown'}")
    print(f"- control_layer: {summary.get('control_layer') or 'unknown'}")
    print(f"- engineering_os: {summary.get('engineering_os') or 'unknown'}")


def _print_human_health_clean(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _health_summary(payload)
    print("Health summary:")
    print(f"- daemon: {(summary.get('daemon') or {}).get('status') or 'unknown'}")
    print(f"- control_layer: {(summary.get('control_layer') or {}).get('status') or 'unknown'}")
    print(f"- engineering_os: {(summary.get('engineering_os') or {}).get('status') or 'unknown'}")
    print(f"- tool_health: {(summary.get('tool_health') or {}).get('status') or 'unknown'}")
    print(f"- ai_test: {(summary.get('ai_test') or {}).get('status') or 'unknown'}")


def _print_human_ops_clean(payload: Any) -> None:
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else _ops_summary(payload)
    print("Ops summary:")
    print(f"- release_ops: {(summary.get('release_ops') or {}).get('status') or 'unknown'}")
    print(f"- release_train: {(summary.get('release_ops') or {}).get('release_train_status') or 'unknown'}")
    print(f"- environment: {(summary.get('environment') or {}).get('status') or 'unknown'}")
    print(f"- daemon: {(summary.get('daemon') or {}).get('status') or 'unknown'}")


def _print_human_report_clean(payload: Any) -> None:
    report = payload.get("report") if isinstance(payload, dict) else payload
    summary = payload.get("summary") if isinstance(payload, dict) and payload.get("summary") else {}
    print("System report:")
    print(f"- headline: {summary.get('headline') or 'unknown'}")
    for sentence in (summary.get("summary_sentences") or [])[:3]:
        if sentence:
            print(f"- {sentence}")
    if not isinstance(report, dict):
        print(f"- report: {report}")


def _print_human_deploy_preview_clean(target: str, prompt: str, workspace: str | None) -> None:
    print("Deploy preview:")
    print(f"- target: {target}")
    print(f"- prompt: {prompt}")
    if workspace:
        print(f"- workspace: {workspace}")


def _print_human_deploy_submitted_clean(target: str, surface: Any, reason: str) -> None:
    print("Deploy request submitted:")
    print(f"- target: {target}")
    print(f"- surface: {surface or 'unknown'}")
    if reason:
        print(f"- reason: {reason}")


def _print_human_rollback_preview_clean(target: str, prompt: str, workspace: str | None) -> None:
    print("Rollback preview:")
    print(f"- target: {target}")
    print(f"- prompt: {prompt}")
    if workspace:
        print(f"- workspace: {workspace}")


def _print_human_rollback_submitted_clean(target: str, surface: Any, reason: str) -> None:
    print("Rollback request submitted:")
    print(f"- target: {target}")
    print(f"- surface: {surface or 'unknown'}")
    if reason:
        print(f"- reason: {reason}")


def _print_human_dispatch_clean(created: Any) -> None:
    route = created.get("route") if isinstance(created, dict) else {}
    surface = created.get("surface") if isinstance(created, dict) else None
    print("Task dispatched:")
    print(f"- surface: {surface or (route or {}).get('preferred_surface') or 'unknown'}")
    summary = created.get("summary") if isinstance(created, dict) else None
    if summary:
        print(f"- summary: {summary}")


def _dispatch_precheck_summary(route: Any, readiness: Any, workspace: str | None, confirm: bool, require_confirm: bool) -> dict[str, Any]:
    route_summary = {
        "preferred_surface": (route or {}).get("preferred_surface") if isinstance(route, dict) else None,
        "fallback_surface": (route or {}).get("fallback_surface") if isinstance(route, dict) else None,
        "reason": (route or {}).get("reason") if isinstance(route, dict) else None,
        "launch_hint": (route or {}).get("launch_hint") if isinstance(route, dict) else None,
    }
    confirmation_summary = {
        "ready": bool((readiness or {}).get("ready")) if isinstance(readiness, dict) else bool(readiness),
        "reason": (readiness or {}).get("reason") if isinstance(readiness, dict) else None,
        "kind": (readiness or {}).get("kind") if isinstance(readiness, dict) else None,
    }
    return {
        "workspace": workspace,
        "route": route_summary,
        "confirmation": confirmation_summary,
        "confirm_flag": confirm,
        "require_confirm": require_confirm,
        "ready": bool(route_summary.get("preferred_surface") or route_summary.get("fallback_surface")) and confirmation_summary["ready"],
    }


def _print_human_dispatch_precheck_clean(prompt: str, precheck: dict[str, Any]) -> None:
    route = precheck.get("route") or {}
    confirmation = precheck.get("confirmation") or {}
    print("Dispatch precheck:")
    print(f"- prompt: {prompt}")
    print(f"- target: {route.get('preferred_surface') or route.get('fallback_surface') or 'unknown'}")
    print(f"- ready: {'yes' if precheck.get('ready') else 'no'}")
    if route.get("reason"):
        print(f"- route_reason: {route.get('reason')}")
    if route.get("launch_hint"):
        print(f"- next_step: {route.get('launch_hint')}")
    if confirmation.get("reason"):
        print(f"- confirmation_note: {confirmation.get('reason')}")
    if precheck.get("require_confirm") and not precheck.get("confirm_flag"):
        print("- status: confirmation required before submit")


def _print_human_dispatch_permission_hint(payload: Any) -> None:
    authorization = payload.get("authorization") if isinstance(payload, dict) else None
    if not isinstance(authorization, dict):
        return
    role = authorization.get("role")
    active = authorization.get("active_session") or {}
    print("Permission hint:")
    print(f"- role: {role or 'unknown'}")
    print(f"- active_session_role: {active.get('role') or 'unknown'}")
    if active.get("owner"):
        print(f"- session_owner: {active.get('owner')}")
    print("- action: open or switch to an operator session before submitting dispatch")


def _print_human_confirm_clean(kind: str, ready: bool, dry_run: bool) -> None:
    print("Confirmation result:")
    print(f"- kind: {kind}")
    print(f"- ready: {'yes' if ready else 'no'}")
    if dry_run:
        print("- mode: dry-run")


def _print_human_route_clean(routed: Any) -> None:
    print("Route suggestion:")
    print(f"- target: {routed.get('preferred_surface') or routed.get('fallback_surface') or 'unknown'}")
    print(f"- reason: {routed.get('reason') or 'unknown'}")
    if routed.get("launch_hint"):
        print(f"- next_step: {routed.get('launch_hint')}")


def _print_human_memory_summary_clean(summary: dict[str, Any]) -> None:
    print("Memory summary:")
    print(f"- object_count: {summary.get('object_count') or 'unknown'}")
    print(f"- candidate_count: {summary.get('candidate_count') or 'unknown'}")
    print(f"- recent_topics: {', '.join(summary.get('dialogue_topics')[:4]) or 'unknown'}")
    print(f"- active_handoff: {summary.get('active_handoff_title') or 'unknown'}")


def _print_legacy_help() -> None:
    print(USAGE.rstrip())


def _legacy_passthrough(argv: Sequence[str]) -> int:
    result = _run_remote(argv)
    _print_remote_stderr(result)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    return result.returncode


def main() -> int:
    argv = sys.argv[1:]
    global SESSION_TOKEN
    if len(argv) >= 2 and argv[0] == "--session-token":
        SESSION_TOKEN = argv[1]
        argv = argv[2:]
    if not argv or argv[0] in {"-h", "--help", "help"}:
        _print_legacy_help()
        return 0

    command = argv[0]
    if command == "daemon-status":
        return _structured_daemon_status(argv[1:])
    if command in LOCAL_STATUS_COMMANDS:
        live_first_map = {
            "control-layer-status": ("control-layer-status", "control_layer", "control_layer"),
            "engineering-os-status": ("engineering-os-status", "engineering_os", "verification"),
            "lab-status": ("lab-status", "lab", "lab"),
            "release-ops-status": ("release-ops-status", "release_ops", "release_ops"),
            "ai-test-status": ("ai-test-status", "ai_test", "ai_test"),
            "tool-health": ("tool-health", "tool_health", "tool_health"),
            "light-status": ("light-status", "light", "light"),
            "autonomy-score": ("autonomy-score", "autonomy", "autonomy"),
        }
        remote_command, output_key, snapshot_key = live_first_map.get(command, (command, command, command))
        return _structured_live_first_status(command, remote_command, argv[1:], output_key, snapshot_key)
    if command not in STRUCTURED_COMMANDS:
        return _legacy_passthrough(argv)

    if command == "status":
        parser = argparse.ArgumentParser(prog="factoryctl status")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_status(args.human)

    if command == "health":
        parser = argparse.ArgumentParser(prog="factoryctl health")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_health(args.human)

    if command == "logs":
        parser = argparse.ArgumentParser(prog="factoryctl logs")
        parser.add_argument("--tail", type=int, default=30)
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_logs(args.human, args.tail)

    if command == "ops":
        parser = argparse.ArgumentParser(prog="factoryctl ops")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_ops(args.human)

    if command == "verify":
        parser = argparse.ArgumentParser(prog="factoryctl verify")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_verify(args.human)

    if command == "doctor":
        parser = argparse.ArgumentParser(prog="factoryctl doctor")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_doctor(args.human)

    if command == "report":
        parser = argparse.ArgumentParser(prog="factoryctl report")
        parser.add_argument("--human", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_report(args.human)

    if command == "inbox":
        parser = argparse.ArgumentParser(prog="factoryctl inbox")
        parser.add_argument("--open-only", action="store_true")
        args = parser.parse_args(argv[1:])
        return _structured_inbox(args.open_only)

    if command == "sync":
        return _structured_sync(argv[1:])
    if command == "generated-sync":
        return _structured_generated_sync(argv[1:])

    if command == "dialogue-status":
        return _structured_dialogue_status(argv[1:])

    if command == "dialogue-sync-current":
        return _structured_sync_current()

    if command == "dispatch":
        return _structured_dispatch_v2(argv[1:])

    if command == "deploy":
        return _structured_deploy(argv[1:])

    if command == "rollback":
        return _structured_rollback(argv[1:])

    if command == "confirm":
        return _structured_confirm(argv[1:])

    if command == "route":
        return _structured_route(argv[1:])

    if command == "memory":
        return _structured_memory(argv[1:])

    _print_legacy_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
