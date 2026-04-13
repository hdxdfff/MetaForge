from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import faulthandler
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import hashlib

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
LOG_PATH = DATA / 'factory_daemon.log'
BOOT_LOG_PATH = DATA / 'factory_daemon.out.log'
ERR_LOG_PATH = DATA / 'factory_daemon.err.log'
TICK_TRACE_PATH = DATA / 'factory_daemon.tick.log'
STATUS_PATH = DATA / 'factory_daemon_state.json'
STATUS_CACHE_PATH = DATA / 'status_cache.json'
PID_PATH = DATA / 'factory_daemon.pid'
WATCHDOG_PATH = DATA / 'runtime_watchdog.json'
FACTORY_TASK_ENGINE_STATUS_PATH = DATA / 'factory_task_engine_status.json'
CONTINUITY_DURABLE_CHECKPOINT_PATH = DATA / 'continuity_durable_checkpoint.json'
GOAL_REGISTRY_PATH = ROOT / 'factory' / 'goals' / 'goal_registry.json'
TOYOS_GOAL_COMPLETION_NOTIFY_PATH = DATA / 'toyos_goal_completion_notification.json'
METAFORGE_SOAK_MILESTONE_NOTIFY_PATH = DATA / 'metaforge_soak_milestone_notification.json'
RUNTIME_EPOCH_PATH = DATA / 'runtime_epoch.json'
METAFORGE_MILESTONE_LEDGER_PATH = DATA / 'metaforge_milestone_ledger.json'
TOYOS_COMPLETION_BUNDLE_ID = 'toyos_mainline_kernel_bundle'
TOYOS_COMPLETION_GOAL_IDS = [
    'goal_1444215208',
    'goal_acacbe6381',
    'goal_040b928e04',
    'goal_0fb542f1e0',
]
METAFORGE_SOAK_MILESTONE_HOURS = (6, 12, 24, 72, 168)
CONTINUITY_SCHEMA_VERSION = 'continuity.v2'
CONTINUITY_RECOVERY_WINDOW_SECONDS = 120
CONTINUITY_EVIDENCE_DEGRADED_THRESHOLD = 1
CONTINUITY_EVIDENCE_BROKEN_THRESHOLD = 5
CONTINUITY_DURABLE_CHECKPOINT_STALE_SECONDS = 300
ATOMIC_WRITE_RETRY_ATTEMPTS = 6
ATOMIC_WRITE_RETRY_DELAY_SECONDS = 0.2
MAX_LOG_BYTES = 1_500_000
KEEP_LOG_FILES = 4
STALE_MULTIPLIER = 3
AI_TEST_ALERT_THRESHOLD = 3
DAEMON_ERROR_RESTART_THRESHOLD = 3
DEFAULT_MIN_ACTIVE_TASKS = 3
DEFAULT_MAX_ACTIVE_TASKS = 12
TICK_STACK_DUMP_SECONDS = 90
SELF_MODEL_TIMEOUT_SECONDS = 20
RECOVERY_TIMEOUT_SECONDS = 15
DEFAULT_BRAIN_STEP_TASK_LIMIT = 1
DEFAULT_BRAIN_STEP_BUDGET_MS = 5000
DEFAULT_MAINTENANCE_EVERY = 10
DEFAULT_AI_TESTING_EVERY = 300
DEFAULT_GUARD_EVERY = 15
DEFAULT_RECOVERY_EVERY = 30
DEFAULT_ECONOMICS_EVERY = 30
DEFAULT_AUTONOMY_EVERY = 30
DEFAULT_TOOL_HEALTH_EVERY = 30
DEFAULT_SCHEMA_HYGIENE_EVERY = 30
DEFAULT_PUBLISH_EVERY = 15
DEFAULT_GLOBAL_POLICY_EVERY = 20
DEFAULT_ENGINEERING_OS_EVERY = 20
DEFAULT_CONTROL_LAYER_EVERY = 20
DEFAULT_RELEASE_OPS_EVERY = 20
DEFAULT_COMPANY_OS_EVERY = 20
DEFAULT_INLINE_GOVERNANCE = False
DEFAULT_SHADOW_PIPELINE_EVERY = 30

if os.name == 'nt':
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _QUERY_FULL_PROCESS_IMAGE_NAME = 0x0400

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


def _windows_process_exists(pid: int) -> bool:
    handle = _windows_process_handle(pid)
    if not handle:
        return False
    try:
        return True
    finally:
        _KERNEL32.CloseHandle(handle)


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
            'Id': int(pid),
            'ProcessName': Path(image_path).name if image_path else f'pid_{pid}',
            'ImagePath': image_path,
        }
    finally:
        _KERNEL32.CloseHandle(handle)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.venv' / 'Lib' / 'site-packages'))

from fastapi.testclient import TestClient
from app.main import app, orchestrator
from tools.brain_loop import brain_step as run_brain_step
from tools.runtime_maintenance import run_maintenance
from tools.runtime_maintenance import run_smoke_hygiene
from tools.ai_guard import run_guard
from tools.meta_factory_control import run_control_layer
from tools.autonomy_score import run_autonomy_score
from tools.autonomy_state import autonomy_is_confirmed
from tools.signal_policy import is_runtime_blocker_state, runtime_blocker_codes_from_error, summarize_signal_policy
from tools.experiment_planner import plan_experiments
from tools.experiment_executor import run_experiment
from tools.experiment_evaluator import evaluate_experiment
from tools.code_knowledge_graph import build_code_knowledge_graph
from tools.architecture_validator import run_architecture_validation
from tools.verification_engine import run_verification
from tools.global_policy_engine import run_global_policy
from tools.module_ownership import auto_merge_ready_submissions
from tools.release_operations import run_release_operations_status
from tools.release_train_runtime import run_release_train
from tools.cross_project_coordination import run_cross_project_coordination
from tools.coordination_runtime import run_coordination
from tools.company_os import run_company_os_status
from tools.tool_health_audit import run_tool_health_audit, append_tool_health_history
from tools.environment_repair_lane import run_environment_repair_lane
from tools.economics_engine import run_economics_engine_status
from tools.schema_hygiene import run_schema_hygiene
from tools.ai_testing_compat import run_ai_test_suite, load_ai_test_status
from tools.factory_self_report import run_factory_self_report, send_factory_notification, should_emit_self_report
from tools.self_model import run_self_model_cycle
from tools.factory_event_log import append_event
from tools.governance_contract import load_governance_contract, summarize_governance_contract
from app.config import settings, strategic_llm_api_style

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional runtime dependency
    OpenAI = None

def _ensure_execution_recovery_direct() -> dict:
    return asyncio.run(orchestrator.ensure_execution_recovery())


def _ensure_execution_recovery_bounded(
    *,
    timeout_seconds: int = RECOVERY_TIMEOUT_SECONDS,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='recovery_cycle')
    future = executor.submit(_ensure_execution_recovery_direct)
    try:
        return future.result(timeout=max(1, int(timeout_seconds)))
    except concurrent.futures.TimeoutError:
        payload = dict(fallback or {})
        payload.setdefault('status', 'timeout')
        payload['recovery_mode'] = bool(payload.get('recovery_mode', True))
        payload['timed_out'] = True
        payload['timeout_seconds'] = int(timeout_seconds)
        return payload
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _normalize_recovery_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(payload or {})
    active_recovery_task_ids = list(normalized.get('active_recovery_task_ids') or [])
    status = str(normalized.get('status') or 'unknown')
    recovery_mode = bool(normalized.get('recovery_mode'))
    timed_out = bool(normalized.get('timed_out'))
    if status == 'timeout' and not active_recovery_task_ids:
        normalized['recovery_mode'] = False
        normalized['status'] = 'degraded'
        normalized['timed_out'] = timed_out
        normalized['degraded_reason'] = 'recovery_timeout_without_active_tasks'
    else:
        normalized['recovery_mode'] = recovery_mode
    normalized['active_recovery_task_ids'] = active_recovery_task_ids
    return normalized

from tools.factory_state import publish_factory_state
from tools.ai_runtime_observability import publish_ai_runtime_state
from tools.identity_kernel import identity_kernel_status, refresh_identity_kernel
from tools.kernel_mode import is_component_enabled, load_kernel_mode
from tools.shadow_pipeline_bridge import pending_shadow_work_count, run_shadow_pipeline_bridge
from tools.risk_scan import run_risk_branch

client = TestClient(app)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def rotate_logs() -> None:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size < MAX_LOG_BYTES:
        return
    for idx in range(KEEP_LOG_FILES - 1, 0, -1):
        src = DATA / f'factory_daemon.log.{idx}'
        dst = DATA / f'factory_daemon.log.{idx + 1}'
        if src.exists():
            if dst.exists():
                dst.unlink()
            src.replace(dst)
    first = DATA / 'factory_daemon.log.1'
    if first.exists():
        first.unlink()
    LOG_PATH.replace(first)


def log(message: str) -> None:
    rotate_logs()
    DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(f'[{stamp}] {message}\n')


def bootstrap_log(message: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with BOOT_LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(f'[{stamp}] {message}\n')


def bootstrap_err(message: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with ERR_LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(f'[{stamp}] {message}\n')


def tick_trace(stage: str, *, cycle: int | None = None, **payload) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    record = {
        'at': utc(),
        'pid': os.getpid(),
        'cycle': cycle,
        'stage': stage,
    }
    record.update(payload)
    with TICK_TRACE_PATH.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        handle.flush()


def _start_tick_watchdog(cycle: int) -> object | None:
    DATA.mkdir(parents=True, exist_ok=True)
    handle = ERR_LOG_PATH.open('a', encoding='utf-8')
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    handle.write(f'[{stamp}] tick_watchdog start cycle={cycle} timeout={TICK_STACK_DUMP_SECONDS}s\n')
    handle.flush()
    try:
        faulthandler.dump_traceback_later(TICK_STACK_DUMP_SECONDS, file=handle, exit=False)
    except Exception as exc:
        handle.write(f'[{stamp}] tick_watchdog scheduling failed cycle={cycle}: {type(exc).__name__}: {exc}\n')
        handle.flush()
        handle.close()
        return None
    return handle


def _stop_tick_watchdog(cycle: int, handle: object | None, *, completed: bool) -> None:
    try:
        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
    if handle is None:
        return
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        handle.write(f'[{stamp}] tick_watchdog stop cycle={cycle} completed={str(completed).lower()}\n')
        handle.flush()
    finally:
        handle.close()


def _atomic_write_text(path: Path, content: str, *, encoding: str = 'utf-8') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f'{path.name}.{os.getpid()}.{time.time_ns()}.tmp')
    try:
        tmp_path.write_text(content, encoding=encoding)
        last_error: Exception | None = None
        for attempt in range(max(1, ATOMIC_WRITE_RETRY_ATTEMPTS)):
            try:
                os.replace(tmp_path, path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt >= max(1, ATOMIC_WRITE_RETRY_ATTEMPTS) - 1:
                    raise
                time.sleep(ATOMIC_WRITE_RETRY_DELAY_SECONDS * (attempt + 1))
        if last_error is not None:
            raise last_error
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _freshness_seconds(value: str | None) -> int | None:
    parsed = _parse_utc(value)
    if parsed is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))


def _runtime_epoch_id() -> str | None:
    epoch = _read_json_file(RUNTIME_EPOCH_PATH, {})
    return epoch.get('epoch_id')


def write_status(**payload) -> None:
    current = {}
    if STATUS_PATH.exists():
        try:
            current = json.loads(STATUS_PATH.read_text(encoding='utf-8-sig'))
        except Exception:
            current = {}
    current.update(payload)
    if payload.get('status') == 'running':
        current.pop('stopped_at', None)
        current.pop('stale_reason', None)
    current['updated_at'] = utc()
    current['source_component'] = 'factory_daemon'
    current['state_version'] = int(current.get('state_version') or 0) + 1
    current['epoch_id'] = payload.get('epoch_id') or current.get('epoch_id') or _runtime_epoch_id()
    current['freshness_seconds'] = 0
    _atomic_write_text(STATUS_PATH, json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')


def _read_status_file() -> dict:
    if not STATUS_PATH.exists():
        return {}
    try:
        state = json.loads(STATUS_PATH.read_text(encoding='utf-8-sig'))
        state['freshness_seconds'] = _freshness_seconds(state.get('updated_at'))
        return state
    except Exception:
        return {}


def _read_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None


def _epoch_runtime_ready(previous_epoch: dict) -> bool:
    if not previous_epoch:
        return False
    if previous_epoch.get('epoch_status') not in {None, 'active'}:
        return False
    last_alive_at = _parse_utc(previous_epoch.get('last_alive_at'))
    if last_alive_at is None:
        return False
    return (datetime.now(timezone.utc) - last_alive_at) <= timedelta(seconds=CONTINUITY_RECOVERY_WINDOW_SECONDS)


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _file_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except Exception:
        return None


def _directory_digest(path: Path) -> str | None:
    if not path.exists() or not path.is_dir():
        return None
    try:
        items: list[str] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            stamp = ''
            try:
                stamp = str(int(child.stat().st_mtime))
            except Exception:
                stamp = '0'
            items.append(f"{child.name}:{stamp}")
        return _sha256_text('\n'.join(items))
    except Exception:
        return None


def _tail_log_lines(path: Path, max_lines: int = 400) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
        return lines[-max_lines:]
    except Exception:
        return []


def _parse_log_timestamp(line: str) -> datetime | None:
    if not line.startswith('['):
        return None
    closing = line.find(']')
    if closing <= 1:
        return None
    stamp = line[1:closing]
    try:
        naive = datetime.strptime(stamp, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    return naive.replace(tzinfo=local_tz).astimezone(timezone.utc)


def _recent_permission_error_stats(max_lines: int = 400) -> dict[str, int]:
    lines = _tail_log_lines(LOG_PATH, max_lines=max_lines)
    now = datetime.now(timezone.utc)
    recent_hour: list[str] = []
    recent_day: list[str] = []
    last_write_error_at: str | None = None
    last_state_write_error_at: str | None = None
    for line in lines:
        parsed = _parse_log_timestamp(line)
        if parsed is None:
            continue
        age = now - parsed
        if age <= timedelta(hours=24):
            recent_day.append(line)
            if 'PermissionError' in line:
                last_write_error_at = parsed.isoformat().replace('+00:00', 'Z')
        if age <= timedelta(hours=1):
            recent_hour.append(line)
            if 'PermissionError' in line and 'factory_daemon_state.json' in line:
                last_state_write_error_at = parsed.isoformat().replace('+00:00', 'Z')
    return {
        'last_window_lines': len(lines),
        'write_permission_errors_tail': sum(1 for line in recent_day if 'PermissionError' in line),
        'state_write_permission_errors_tail': sum(1 for line in recent_hour if 'PermissionError' in line and 'factory_daemon_state.json' in line),
        'last_write_permission_error_at': last_write_error_at,
        'last_state_write_permission_error_at': last_state_write_error_at,
    }


def _control_semantic_versions(control_layer: dict, engineering_os: dict) -> dict[str, str]:
    quality_status = str((control_layer.get('quality_system') or {}).get('status') or 'unknown')
    patch_gate = str((engineering_os.get('engineering_os') or {}).get('patch_gate_status') or 'unknown')
    release_gate = str((engineering_os.get('engineering_os') or {}).get('release_gate_status') or 'unknown')
    return {
        'control_contract_version': 'v3',
        'policy_semantic_version': 'v2',
        'tool_policy_version': f"patch-{patch_gate}",
        'router_profile_version': f"quality-{quality_status}-release-{release_gate}",
    }


def _load_continuity_durable_checkpoint() -> dict[str, Any]:
    return _read_json_file(CONTINUITY_DURABLE_CHECKPOINT_PATH, {})


def _runtime_tasks_summary() -> dict[str, Any]:
    tasks_root = ROOT / 'factory' / 'runtime' / 'tasks'
    queue_item_count = 0
    task_ids: list[str] = []
    if tasks_root.exists():
        try:
            for child in sorted(tasks_root.iterdir(), key=lambda item: item.name):
                if not child.is_dir():
                    continue
                queue_item_count += 1
                task_ids.append(child.name)
        except Exception:
            task_ids = []
    active_task_count = None
    active_task_ids: list[str] = []
    engine_status = _read_json_file(FACTORY_TASK_ENGINE_STATUS_PATH, {})
    for candidate in (
        ((engine_status.get('supply_after_seed') or {}).get('active_task_count')),
        ((engine_status.get('supply_before_seed') or {}).get('active_task_count')),
        engine_status.get('active_task_count'),
    ):
        try:
            if candidate is not None:
                active_task_count = int(candidate)
                break
        except Exception:
            continue
    for candidate in (
        ((engine_status.get('supply_after_seed') or {}).get('active_task_ids')),
        ((engine_status.get('supply_before_seed') or {}).get('active_task_ids')),
        engine_status.get('active_task_ids'),
    ):
        if isinstance(candidate, list):
            active_task_ids = [str(item) for item in candidate if str(item).strip()]
            break
    return {
        'queue_item_count': queue_item_count,
        'queue_task_ids_preview': task_ids[:20],
        'active_task_count': active_task_count,
        'active_task_ids_preview': active_task_ids[:20],
    }


def _build_continuity_durable_checkpoint(
    *,
    previous_checkpoint: dict[str, Any] | None,
    epoch_id: str | None,
    pid: int | None,
    cycle: int | None,
    last_tick_at: str | None,
) -> dict[str, Any]:
    runtime_summary = _runtime_tasks_summary()
    log_stats = _recent_permission_error_stats()
    checkpoint = {
        'state_version': 1,
        'generated_at': utc(),
        'source_component': 'factory_daemon',
        'checkpoint_kind': 'continuity_durable',
        'epoch_id': epoch_id,
        'current_daemon_pid': pid,
        'last_cycle': cycle,
        'last_tick_at': last_tick_at,
        'queue_digest': _directory_digest(ROOT / 'factory' / 'runtime' / 'tasks'),
        'queue_item_count': runtime_summary.get('queue_item_count'),
        'queue_task_ids_preview': runtime_summary.get('queue_task_ids_preview'),
        'inflight_digest': _file_digest(FACTORY_TASK_ENGINE_STATUS_PATH),
        'active_task_count': runtime_summary.get('active_task_count'),
        'active_task_ids_preview': runtime_summary.get('active_task_ids_preview'),
        'artifact_registry_digest': _file_digest(DATA / 'artifact_registry.json'),
        'verification_digest': _file_digest(DATA / 'verification_status.json'),
        'milestone_ledger_digest': _file_digest(METAFORGE_MILESTONE_LEDGER_PATH),
        'runtime_state_digest': _file_digest(STATUS_PATH),
        'task_checkpoint_digest': _file_digest(DATA / 'task_checkpoints.json'),
        'llm_checkpoint_digest': _file_digest(DATA / 'llm_checkpoints.json'),
        'evidence_write_failures_last_hour': log_stats['state_write_permission_errors_tail'],
        'evidence_write_failures_last_24h': log_stats['write_permission_errors_tail'],
        'freshness_seconds': 0,
    }
    regression_signals: list[str] = []
    previous_checkpoint = previous_checkpoint or {}
    same_epoch = bool(previous_checkpoint) and previous_checkpoint.get('epoch_id') == epoch_id
    if same_epoch:
        previous_queue_count = int(previous_checkpoint.get('queue_item_count') or 0)
        current_queue_count = int(checkpoint.get('queue_item_count') or 0)
        if previous_queue_count > 0 and current_queue_count == 0:
            regression_signals.append('queue_loss_detected')
        if previous_checkpoint.get('inflight_digest') and not checkpoint.get('inflight_digest'):
            regression_signals.append('inflight_loss_detected')
        if previous_checkpoint.get('artifact_registry_digest') and not checkpoint.get('artifact_registry_digest'):
            regression_signals.append('artifact_registry_regression')
        if previous_checkpoint.get('verification_digest') and not checkpoint.get('verification_digest'):
            regression_signals.append('verification_state_regression')
        if previous_checkpoint.get('milestone_ledger_digest') and not checkpoint.get('milestone_ledger_digest'):
            regression_signals.append('ledger_regression_detected')
    checkpoint['regression_signals'] = sorted(set(regression_signals))
    checkpoint['state_regression_detected'] = bool(regression_signals)
    checkpoint['durable_checkpoint_health'] = (
        'healthy'
        if all(
            checkpoint.get(key)
            for key in (
                'queue_digest',
                'inflight_digest',
                'artifact_registry_digest',
                'verification_digest',
                'milestone_ledger_digest',
            )
        )
        else 'degraded'
    )
    return checkpoint


def _write_continuity_durable_checkpoint(
    *,
    epoch_id: str | None,
    pid: int | None,
    cycle: int | None,
    last_tick_at: str | None,
) -> dict[str, Any]:
    current = _load_continuity_durable_checkpoint()
    checkpoint = _build_continuity_durable_checkpoint(
        previous_checkpoint=current,
        epoch_id=epoch_id,
        pid=pid,
        cycle=cycle,
        last_tick_at=last_tick_at,
    )
    checkpoint['state_version'] = int(current.get('state_version') or 0) + 1
    _atomic_write_text(
        CONTINUITY_DURABLE_CHECKPOINT_PATH,
        json.dumps(checkpoint, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return checkpoint


def evaluate_continuity_v2(
    *,
    previous_epoch: dict,
    epoch_id: str,
    pid: int,
    started_at: str,
    cycle: int,
    last_tick_at: str,
    task_pipeline_alive: bool | None,
) -> dict[str, Any]:
    verification = _load_verification_snapshot()
    artifact_registry = _load_artifact_registry_snapshot()
    control_layer = _load_control_layer_snapshot()
    engineering_os = _load_engineering_os_snapshot()
    log_stats = _recent_permission_error_stats()
    durable_checkpoint = _load_continuity_durable_checkpoint()
    checkpoint_epoch_id = durable_checkpoint.get('epoch_id')
    checkpoint_matches_epoch = bool(durable_checkpoint) and checkpoint_epoch_id in {None, epoch_id}
    queue_digest = (durable_checkpoint.get('queue_digest') if checkpoint_matches_epoch else None) or _directory_digest(ROOT / 'factory' / 'runtime' / 'tasks')
    inflight_digest = (durable_checkpoint.get('inflight_digest') if checkpoint_matches_epoch else None) or _file_digest(FACTORY_TASK_ENGINE_STATUS_PATH)
    artifact_digest = (durable_checkpoint.get('artifact_registry_digest') if checkpoint_matches_epoch else None) or _file_digest(DATA / 'artifact_registry.json')
    verification_digest = (durable_checkpoint.get('verification_digest') if checkpoint_matches_epoch else None) or _file_digest(DATA / 'verification_status.json')
    milestone_digest = (durable_checkpoint.get('milestone_ledger_digest') if checkpoint_matches_epoch else None) or _file_digest(METAFORGE_MILESTONE_LEDGER_PATH)
    runtime_digest = (durable_checkpoint.get('runtime_state_digest') if checkpoint_matches_epoch else None) or _file_digest(STATUS_PATH)
    versions = _control_semantic_versions(control_layer, engineering_os)
    runtime_continuity = 'preserved'
    if not _epoch_runtime_ready(previous_epoch) and previous_epoch:
        runtime_continuity = 'broken'
    elif previous_epoch and cycle < int(previous_epoch.get('last_cycle') or 0):
        runtime_continuity = 'degraded'
    elif task_pipeline_alive is False:
        runtime_continuity = 'degraded'
    state_continuity = 'preserved'
    if not queue_digest or not artifact_digest or not verification_digest:
        state_continuity = 'degraded'
    regression_signals = list(durable_checkpoint.get('regression_signals') or []) if checkpoint_matches_epoch else []
    if regression_signals:
        state_continuity = 'broken'
    control_semantic_continuity = 'preserved'
    previous_router = previous_epoch.get('router_profile_version')
    if previous_router and previous_router != versions['router_profile_version']:
        control_semantic_continuity = 'compatible_changed'
    evidence_continuity = 'preserved'
    continuity_risk_reasons: list[str] = []
    durable_checkpoint_generated_at = durable_checkpoint.get('generated_at') if checkpoint_matches_epoch else None
    durable_checkpoint_available = bool(checkpoint_matches_epoch and durable_checkpoint_generated_at)
    if log_stats['state_write_permission_errors_tail'] >= CONTINUITY_EVIDENCE_BROKEN_THRESHOLD:
        evidence_continuity = 'broken'
        continuity_risk_reasons.append('state_write_permission_denied')
    elif log_stats['state_write_permission_errors_tail'] >= CONTINUITY_EVIDENCE_DEGRADED_THRESHOLD:
        evidence_continuity = 'degraded'
        continuity_risk_reasons.append('state_write_permission_denied')
    if not durable_checkpoint_available:
        evidence_continuity = 'degraded' if evidence_continuity == 'preserved' else evidence_continuity
        continuity_risk_reasons.append('durable_checkpoint_missing')
    if not runtime_digest:
        evidence_continuity = 'broken' if evidence_continuity == 'preserved' else evidence_continuity
        continuity_risk_reasons.append('evidence_sink_unavailable')
    last_successful = durable_checkpoint_generated_at or previous_epoch.get('last_successful_durable_checkpoint_at')
    if durable_checkpoint_available and evidence_continuity != 'broken':
        last_successful = durable_checkpoint_generated_at
    last_state_write_error_at = _parse_utc(log_stats.get('last_state_write_permission_error_at'))
    last_successful_dt = _parse_utc(last_successful)
    compensated_state_write_error = bool(
        last_state_write_error_at is not None
        and last_successful_dt is not None
        and last_successful_dt >= last_state_write_error_at
    )
    if compensated_state_write_error and 'state_write_permission_denied' in continuity_risk_reasons:
        continuity_risk_reasons = [
            item for item in continuity_risk_reasons if item != 'state_write_permission_denied'
        ]
        if evidence_continuity == 'degraded':
            evidence_continuity = 'preserved'
    checkpoint_age = _freshness_seconds(last_successful)
    if checkpoint_age is not None and checkpoint_age > CONTINUITY_DURABLE_CHECKPOINT_STALE_SECONDS:
        evidence_continuity = 'broken'
        continuity_risk_reasons.append('ssot_stale')
    continuity_risk_reasons.extend(regression_signals)
    break_reason = None
    if runtime_continuity == 'broken':
        break_reason = 'tick_gap_exceeded'
    elif state_continuity == 'broken':
        break_reason = regression_signals[0] if regression_signals else 'state_loss_detected'
    elif control_semantic_continuity == 'incompatible':
        break_reason = 'control_contract_changed'
    elif evidence_continuity == 'broken' and not runtime_digest:
        break_reason = 'continuity_unknown_due_to_missing_evidence'
    continuity_mode = 'new' if break_reason else 'preserved'
    if break_reason or runtime_continuity == 'broken' or state_continuity == 'broken' or control_semantic_continuity == 'incompatible' or evidence_continuity == 'broken':
        epoch_health = 'broken'
    elif any(level in {'degraded', 'compatible_changed'} for level in (runtime_continuity, state_continuity, control_semantic_continuity, evidence_continuity)):
        epoch_health = 'degraded'
    else:
        epoch_health = 'healthy'
    if break_reason or evidence_continuity == 'broken':
        claim_scope = 'unclaimable' if state_continuity in {'broken', 'unknown'} else 'runtime_only'
    elif runtime_continuity == 'preserved' and state_continuity == 'preserved' and control_semantic_continuity in {'preserved', 'compatible_changed'} and evidence_continuity == 'preserved':
        claim_scope = 'full_service_semantic'
    elif runtime_continuity == 'preserved' and state_continuity in {'preserved', 'degraded'} and control_semantic_continuity != 'incompatible' and evidence_continuity != 'broken':
        claim_scope = 'runtime_plus_state'
    else:
        claim_scope = 'runtime_only'
    if epoch_health == 'broken':
        continuity_confidence = 'low'
    elif epoch_health == 'healthy':
        continuity_confidence = 'high'
    else:
        continuity_confidence = 'medium'
    continuity_notes = [f'runtime continuity {runtime_continuity}']
    if continuity_risk_reasons:
        continuity_notes.append(f"risks: {', '.join(sorted(set(continuity_risk_reasons)))}")
    return {
        'schema_version': CONTINUITY_SCHEMA_VERSION,
        'runtime_continuity': runtime_continuity,
        'state_continuity': state_continuity,
        'control_semantic_continuity': control_semantic_continuity,
        'evidence_continuity': evidence_continuity,
        'epoch_health': epoch_health,
        'claim_scope': claim_scope,
        'continuity_confidence': continuity_confidence,
        'continuity_mode': continuity_mode,
        'continuity_break_reason': break_reason,
        'continuity_risk_reasons': sorted(set(continuity_risk_reasons)),
        'last_verified_queue_digest': queue_digest,
        'last_verified_inflight_digest': inflight_digest,
        'last_verified_memory_digest': None,
        'last_verified_artifact_registry_digest': artifact_digest,
        'last_verified_verification_digest': verification_digest,
        'last_verified_milestone_ledger_digest': milestone_digest,
        'durable_checkpoint_path': str(CONTINUITY_DURABLE_CHECKPOINT_PATH),
        'durable_checkpoint_generated_at': durable_checkpoint_generated_at,
        'durable_checkpoint_regression_signals': regression_signals,
        'evidence_write_failures_last_hour': log_stats['state_write_permission_errors_tail'],
        'evidence_write_failures_last_24h': log_stats['write_permission_errors_tail'],
        'last_successful_durable_checkpoint_at': last_successful,
        'durable_checkpoint_interval_seconds': CONTINUITY_DURABLE_CHECKPOINT_STALE_SECONDS,
        'durable_checkpoint_health': 'healthy' if evidence_continuity == 'preserved' else ('degraded' if evidence_continuity == 'degraded' else 'broken'),
        'continuity_notes': continuity_notes,
        **versions,
    }


def _update_runtime_epoch(*, pid: int, started_at: str, cycle: int | None = None, last_tick_at: str | None = None, task_pipeline_alive: bool | None = None) -> dict:
    epoch = _read_json_file(RUNTIME_EPOCH_PATH, {})
    now = utc()
    previous_pid = epoch.get('current_daemon_pid')
    continuity_mode = 'new'
    restart_count = int(epoch.get('restart_count_within_epoch') or 0)
    epoch_cycle_offset = int(epoch.get('epoch_cycle_offset') or 0)
    local_cycle = int(cycle or 0)
    pid_changed_within_epoch = False
    if _epoch_runtime_ready(epoch):
        epoch_id = str(epoch.get('epoch_id') or started_at)
        continuity_mode = 'preserved'
        if previous_pid and int(previous_pid) != int(pid):
            restart_count += 1
            pid_changed_within_epoch = True
    else:
        epoch_id = started_at
        restart_count = 0
        epoch_cycle_offset = 0
    active_last_tick = last_tick_at or started_at
    prior_cycle = 0
    if epoch.get('epoch_id') == epoch_id:
        try:
            prior_cycle = int(epoch.get('last_cycle') or 0)
        except Exception:
            prior_cycle = 0
    if pid_changed_within_epoch:
        epoch_cycle_offset = prior_cycle + 1
    active_cycle = epoch_cycle_offset + local_cycle
    tick_monotonic_ok = True
    if epoch.get('epoch_id') == epoch_id:
        try:
            tick_monotonic_ok = active_cycle >= prior_cycle
        except Exception:
            tick_monotonic_ok = True
    continuity = evaluate_continuity_v2(
        previous_epoch=epoch,
        epoch_id=epoch_id,
        pid=pid,
        started_at=started_at,
        cycle=active_cycle,
        last_tick_at=active_last_tick,
        task_pipeline_alive=task_pipeline_alive,
    )
    epoch_payload = {
        'state_version': int(epoch.get('state_version') or 0) + 1,
        'generated_at': now,
        'source_component': 'factory_daemon',
        'epoch_id': epoch_id,
        'schema_version': CONTINUITY_SCHEMA_VERSION,
        'epoch_status': 'active',
        'epoch_started_at': epoch.get('epoch_started_at') if epoch.get('epoch_id') == epoch_id else started_at,
        'last_alive_at': active_last_tick,
        'accumulated_uptime_seconds': max(
            0,
            int(((_parse_utc(active_last_tick) or datetime.now(timezone.utc)) - (_parse_utc(epoch.get('epoch_started_at') if epoch.get('epoch_id') == epoch_id else started_at) or datetime.now(timezone.utc))).total_seconds()),
        ),
        'restart_count_within_epoch': restart_count,
        'epoch_cycle_offset': epoch_cycle_offset,
        'continuity_mode': continuity.get('continuity_mode') if continuity_mode == 'preserved' else 'new',
        'continuity_break_reason': continuity.get('continuity_break_reason') if continuity_mode == 'preserved' else ('new_epoch' if epoch else None),
        'current_daemon_pid': int(pid),
        'daemon_started_at': started_at,
        'last_cycle': active_cycle,
        'last_tick_at': active_last_tick,
        'tick_monotonic_ok': tick_monotonic_ok,
        'task_pipeline_alive': bool(task_pipeline_alive) if task_pipeline_alive is not None else None,
        'freshness_seconds': 0,
        **continuity,
    }
    _atomic_write_text(RUNTIME_EPOCH_PATH, json.dumps(epoch_payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return epoch_payload


def _write_milestone_report(*, epoch_id: str, milestone_hours: int, runtime: dict) -> str:
    report_dir = DATA / 'milestone_reports'
    safe_epoch = str(epoch_id).replace(':', '').replace('-', '')
    report_path = report_dir / f'metaforge_soak_report_{milestone_hours}h_{safe_epoch}.json'
    payload = {
        'state_version': 1,
        'generated_at': utc(),
        'source_component': 'factory_daemon',
        'epoch_id': epoch_id,
        'milestone_hours': milestone_hours,
        'runtime_snapshot': runtime,
        'incident_classification': runtime.get('incident_classification') or {},
    }
    _atomic_write_text(report_path, json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(report_path)


def _update_milestone_ledger(*, epoch_id: str, milestone_hours: int, status: str, runtime: dict, report_path: str | None = None, notification: dict | None = None, eligible_at: str | None = None) -> dict:
    ledger = _read_json_file(METAFORGE_MILESTONE_LEDGER_PATH, {})
    milestones = ledger.setdefault('milestones', {})
    key = f'{milestone_hours}h'
    current = milestones.get(key) or {}
    if status == 'pending':
        current = {}
    notification = notification or {}
    qq_delivery = (notification.get('delivery') or {}).get('qq_mail') or {}
    effective_report_path = report_path or current.get('report_path')
    report_exists = bool(effective_report_path and Path(effective_report_path).exists())
    record = {
        **current,
        'eligible_at': eligible_at or current.get('eligible_at'),
        'uptime_hours': runtime.get('uptime_hours'),
        'report_path': effective_report_path,
        'report_generated': report_exists,
        'report_verified': report_exists,
        'notification_channel': 'qq_mail',
        'notification_sent': bool(notification) if notification else bool(current.get('notification_sent')),
        'notification_delivery_confirmed': bool(qq_delivery.get('delivered')) if notification else bool(current.get('notification_delivery_confirmed')),
        'status': status,
        'claim_scope': runtime.get('claim_scope'),
        'continuity_confidence': runtime.get('continuity_confidence'),
        'runtime_continuity': runtime.get('runtime_continuity'),
        'state_continuity': runtime.get('state_continuity'),
        'control_semantic_continuity': runtime.get('control_semantic_continuity'),
        'evidence_continuity': runtime.get('evidence_continuity'),
        'continuity_risk_reasons': runtime.get('continuity_risk_reasons') or [],
        'incident_classification': runtime.get('incident_classification') or {},
        'last_updated_at': utc(),
    }
    if status == 'committed':
        record['committed_at'] = utc()
    milestones[key] = record
    ledger.update(
        {
            'state_version': int(ledger.get('state_version') or 0) + 1,
            'generated_at': utc(),
            'source_component': 'factory_daemon',
            'epoch_id': epoch_id,
            'freshness_seconds': 0,
            'milestones': milestones,
        }
    )
    _atomic_write_text(METAFORGE_MILESTONE_LEDGER_PATH, json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
    return record


def _bundle_retry_due(last_attempt_at: str | None, *, retry_minutes: int = 15) -> bool:
    if not last_attempt_at:
        return True
    attempted_at = _parse_utc(last_attempt_at)
    if attempted_at is None:
        return True
    return datetime.now(timezone.utc) - attempted_at >= timedelta(minutes=retry_minutes)


def _toyos_bundle_progress() -> dict:
    goals = _read_json_file(GOAL_REGISTRY_PATH, [])
    goals_by_id = {str(goal.get('goal_id') or ''): goal for goal in goals if goal.get('goal_id')}
    items: list[dict] = []
    completed_count = 0
    for goal_id in TOYOS_COMPLETION_GOAL_IDS:
        goal = goals_by_id.get(goal_id) or {}
        status = str(goal.get('status') or 'missing')
        if status == 'completed':
            completed_count += 1
        items.append({
            'goal_id': goal_id,
            'target': goal.get('target') or goal_id,
            'status': status,
            'updated_at': goal.get('updated_at'),
            'graph_id': goal.get('graph_id'),
        })
    return {
        'bundle_id': TOYOS_COMPLETION_BUNDLE_ID,
        'goal_ids': list(TOYOS_COMPLETION_GOAL_IDS),
        'completed_count': completed_count,
        'goal_count': len(TOYOS_COMPLETION_GOAL_IDS),
        'ready': completed_count == len(TOYOS_COMPLETION_GOAL_IDS),
        'goals': items,
    }


def _build_toyos_completion_message(progress: dict) -> tuple[str, str, str]:
    subject = 'ToyOS mainline bundle completed'
    lines = [
        'ToyOS mainline goals all reached completed status.',
        '',
    ]
    for item in progress.get('goals') or []:
        lines.append(f"- [{item.get('status')}] {item.get('target')} ({item.get('goal_id')})")
    lines.extend([
        '',
        'Artifacts root: D:\\codex\\generated\\toy-os-demo',
        'Audit root: D:\\codex\\orchestrator-mvp\\data\\reality_dashboard.json',
    ])
    text = '\n'.join(lines)
    markdown = '# ToyOS mainline bundle completed\n\n' + '\n'.join(lines) + '\n'
    return subject, text, markdown


def _load_autonomy_score_snapshot() -> dict:
    return _read_json_file(DATA / 'autonomy_score.json', {})


def _load_soak_monitor_snapshot() -> dict:
    return _read_json_file(DATA / 'soak_monitor_state.json', {})


def _load_verification_snapshot() -> dict:
    return _read_json_file(DATA / 'verification_status.json', {})


def _load_artifact_registry_snapshot() -> dict:
    return _read_json_file(DATA / 'artifact_registry.json', {})


def _load_reality_dashboard_snapshot() -> dict:
    return _read_json_file(DATA / 'reality_dashboard.json', {})


def _load_ai_test_snapshot() -> dict:
    return _read_json_file(DATA / 'ai_test_status.json', {})


def _load_control_layer_snapshot() -> dict:
    return _read_json_file(DATA / 'control_layer_status.json', {})


def _load_engineering_os_snapshot() -> dict:
    return _read_json_file(DATA / 'engineering_os_status.json', {})


def _derive_release_readiness(*, control_layer: dict, ai_testing: dict, verification: dict) -> str:
    quality_status = str(((control_layer.get('quality_system') or {}).get('status')) or '').strip().lower()
    ai_status = str(ai_testing.get('status') or '').strip().lower()
    pending_checks = list(((verification.get('delayed_verification') or {}).get('pending_checks')) or [])
    if quality_status in {'pass', 'ready', 'promote'} and ai_status in {'', 'pass'} and not pending_checks:
        return 'ready'
    if ai_status == 'degraded' or quality_status in {'candidate', 'attention', 'degraded'}:
        return 'candidate'
    if pending_checks:
        return 'degraded'
    return 'candidate'


def _classify_quality_plane_incident(*, runtime: dict, last_error: str | None = None) -> dict[str, Any]:
    runtime_state = str(runtime.get('runtime_continuity') or '').strip().lower() or 'unknown'
    ai_testing = runtime.get('ai_testing') or {}
    verification = runtime.get('verification') or {}
    control_layer = runtime.get('control_layer') or {}
    self_model_health = str(runtime.get('self_model_health') or 'unknown')
    release_readiness = str(runtime.get('release_readiness') or 'candidate')
    failing_case_ids = [str(item) for item in (ai_testing.get('failing_case_ids') or []) if str(item).strip()]
    pending_checks = [str(item) for item in (verification.get('pending_checks') or []) if str(item).strip()]
    runtime_blockers: list[str] = []
    maturity_signals: list[str] = []
    release_gate_signals: list[str] = []
    runtime_blockers.extend(runtime_blocker_codes_from_error(last_error))
    if runtime_state not in {'preserved', 'stable'} and runtime_blocker_codes_from_error(last_error):
        runtime_blockers.append('daemon_unhealthy')
    if is_runtime_blocker_state(control_layer.get('status')):
        runtime_blockers.append('control_layer_unstable')
    if self_model_health not in {'', 'unknown', 'healthy', 'pass'}:
        maturity_signals.append('quality_attention')
    if failing_case_ids:
        maturity_signals.append('ai_testing_degraded')
    if pending_checks:
        release_gate_signals.append('verification_delay')
    if release_readiness != 'ready':
        release_gate_signals.append('release_gate_not_confirmed')
    signal_policy = summarize_signal_policy(
        runtime_blockers=runtime_blockers,
        maturity_signals=maturity_signals,
        release_gate_signals=release_gate_signals,
        advisory_signals=[],
        source='factory_daemon',
    )
    trigger_signal = None
    root_cause_bucket = None
    concurrent_contributors: list[str] = []
    runtime_blocker_items = signal_policy.get('runtime_blockers') or []
    if runtime_blocker_items:
        trigger_signal = f"{runtime_blocker_items[0].get('category')}.{runtime_blocker_items[0].get('code')}"
        root_cause_bucket = 'runtime_blocker'
    elif failing_case_ids:
        trigger_signal = f"ai_testing.{failing_case_ids[0]}"
        root_cause_bucket = 'quality_plane_observation'
    elif pending_checks:
        trigger_signal = f"verification.{pending_checks[0]}"
        root_cause_bucket = 'release_readiness_observation'
    if pending_checks:
        concurrent_contributors.append(f"verification.pending_checks={','.join(pending_checks)}")
    if self_model_health not in {'', 'unknown', 'healthy', 'pass'}:
        concurrent_contributors.append(f"self_model.health={self_model_health}")
    if release_readiness != 'ready':
        concurrent_contributors.append(f"release_readiness={release_readiness}")
    active = bool(runtime_blocker_items)
    return {
        'active': active,
        'incident_type': 'runtime_blocker' if active else None,
        'runtime': runtime_state or 'unknown',
        'release_readiness': release_readiness,
        'self_model_health': self_model_health,
        'milestone_invalidated': False,
        'service_continuity_lost': False,
        'trigger_signal': trigger_signal,
        'root_cause_bucket': root_cause_bucket,
        'failing_case_ids': failing_case_ids,
        'concurrent_contributors': concurrent_contributors,
        'signal_policy': signal_policy,
        'signal_dashboard': signal_policy.get('dashboard') or {},
        'summary': (
            'Runtime blocker detected.'
            if active
            else 'No runtime blocker detected; remaining signals are maturity or release readiness only.'
        ),
    }


def _metaforge_runtime_snapshot(*, daemon_started_at: str | None) -> dict:
    runtime_epoch = _read_json_file(RUNTIME_EPOCH_PATH, {})
    started = _parse_utc(daemon_started_at)
    now = datetime.now(timezone.utc)
    uptime_hours = 0.0
    accumulated_uptime_seconds = runtime_epoch.get('accumulated_uptime_seconds')
    if accumulated_uptime_seconds is not None:
        try:
            uptime_hours = max(0.0, float(accumulated_uptime_seconds) / 3600.0)
        except Exception:
            uptime_hours = 0.0
    elif started is not None:
        uptime_hours = max(0.0, (now - started).total_seconds() / 3600.0)
    daemon_state = _read_status_file()
    autonomy = _load_autonomy_score_snapshot()
    soak_state = _load_soak_monitor_snapshot()
    verification = _load_verification_snapshot()
    artifact_registry = _load_artifact_registry_snapshot()
    reality_dashboard = _load_reality_dashboard_snapshot()
    ai_test = _load_ai_test_snapshot()
    control_layer = _load_control_layer_snapshot()
    engineering_os = _load_engineering_os_snapshot()
    self_model = _read_json_file(DATA / 'self_model_runtime.json', {})
    governance_contract = load_governance_contract()
    focus = ((soak_state.get('last_sample') or {}).get('focus_artifact')) or {}
    soak_summary = soak_state.get('summary') or {}
    runtime = {
        'epoch_id': runtime_epoch.get('epoch_id') or daemon_started_at,
        'epoch_status': runtime_epoch.get('epoch_status'),
        'schema_version': runtime_epoch.get('schema_version'),
        'runtime_continuity': runtime_epoch.get('runtime_continuity'),
        'state_continuity': runtime_epoch.get('state_continuity'),
        'control_semantic_continuity': runtime_epoch.get('control_semantic_continuity'),
        'evidence_continuity': runtime_epoch.get('evidence_continuity'),
        'epoch_health': runtime_epoch.get('epoch_health'),
        'claim_scope': runtime_epoch.get('claim_scope'),
        'continuity_confidence': runtime_epoch.get('continuity_confidence'),
        'continuity_mode': runtime_epoch.get('continuity_mode'),
        'continuity_break_reason': runtime_epoch.get('continuity_break_reason'),
        'continuity_risk_reasons': runtime_epoch.get('continuity_risk_reasons') or [],
        'accumulated_uptime_seconds': runtime_epoch.get('accumulated_uptime_seconds'),
        'restart_count_within_epoch': runtime_epoch.get('restart_count_within_epoch'),
        'last_successful_durable_checkpoint_at': runtime_epoch.get('last_successful_durable_checkpoint_at'),
        'evidence_write_failures_last_hour': runtime_epoch.get('evidence_write_failures_last_hour'),
        'evidence_write_failures_last_24h': runtime_epoch.get('evidence_write_failures_last_24h'),
        'last_verified_queue_digest': runtime_epoch.get('last_verified_queue_digest'),
        'last_verified_inflight_digest': runtime_epoch.get('last_verified_inflight_digest'),
        'last_verified_artifact_registry_digest': runtime_epoch.get('last_verified_artifact_registry_digest'),
        'last_verified_verification_digest': runtime_epoch.get('last_verified_verification_digest'),
        'durable_checkpoint_path': runtime_epoch.get('durable_checkpoint_path'),
        'durable_checkpoint_generated_at': runtime_epoch.get('durable_checkpoint_generated_at'),
        'durable_checkpoint_regression_signals': runtime_epoch.get('durable_checkpoint_regression_signals') or [],
        'control_contract_version': runtime_epoch.get('control_contract_version'),
        'policy_semantic_version': runtime_epoch.get('policy_semantic_version'),
        'tool_policy_version': runtime_epoch.get('tool_policy_version'),
        'router_profile_version': runtime_epoch.get('router_profile_version'),
        'daemon_started_at': daemon_started_at,
        'uptime_hours': round(uptime_hours, 2),
        'daemon_pid': daemon_state.get('pid'),
        'daemon_cycle': daemon_state.get('cycle'),
        'daemon_running': bool(daemon_state.get('running', str(daemon_state.get('status') or '').lower() == 'running')),
        'daemon_last_tick_at': daemon_state.get('last_tick_at'),
        'soak_label': soak_state.get('label'),
        'soak_status': soak_state.get('status'),
        'soak_started_at': soak_state.get('started_at'),
        'soak_last_updated_at': soak_state.get('last_updated_at'),
        'soak_samples_collected': soak_state.get('samples_collected'),
        'soak_report_path': soak_state.get('report_path'),
        'soak_passed': soak_summary.get('passed'),
        'verification': {
            'status': verification.get('status'),
            'runtime_health_status': ((verification.get('runtime_health') or {}).get('status')),
            'delayed_verification_status': ((verification.get('delayed_verification') or {}).get('status')),
            'patch_gate_status': ((verification.get('patch_gate') or {}).get('status')),
            'pending_checks': ((verification.get('delayed_verification') or {}).get('pending_checks') or []),
        },
        'artifact_registry': {
            'status': artifact_registry.get('status'),
            'artifact_count': artifact_registry.get('artifact_count'),
            'real_artifact_count': artifact_registry.get('real_artifact_count'),
            'valuable_artifact_count': artifact_registry.get('valuable_artifact_count'),
            'issue_count': artifact_registry.get('issue_count'),
        },
        'reality_dashboard': {
            'status': reality_dashboard.get('status'),
            'products_real': reality_dashboard.get('products_real'),
            'artifacts_produced_last_24h': reality_dashboard.get('artifacts_produced_last_24h'),
            'tasks_completed_last_24h': reality_dashboard.get('tasks_completed_last_24h'),
            'conversion_rate': reality_dashboard.get('conversion_rate'),
        },
        'ai_testing': {
            'status': ai_test.get('status'),
            'release_signal': ai_test.get('release_signal'),
            'pass_rate': ai_test.get('pass_rate'),
            'error_count': ai_test.get('error_count'),
            'failing_case_ids': ai_test.get('failing_case_ids') or [],
        },
        'control_layer': {
            'status': control_layer.get('status'),
            'quality_status': ((control_layer.get('quality_system') or {}).get('status')),
            'overall_score': ((control_layer.get('quality_system') or {}).get('overall_score')),
        },
        'engineering_os': {
            'status': ((engineering_os.get('engineering_os') or {}).get('status')),
            'patch_gate_status': ((engineering_os.get('engineering_os') or {}).get('patch_gate_status')),
            'delayed_verification_status': ((engineering_os.get('engineering_os') or {}).get('delayed_verification_status')),
            'release_gate_status': ((engineering_os.get('engineering_os') or {}).get('release_gate_status')),
        },
        'release_readiness': _derive_release_readiness(
            control_layer=control_layer,
            ai_testing=ai_test,
            verification=verification,
        ),
        'focus_artifact': {
            'artifact_id': focus.get('artifact_id') or 'toy-os-demo',
            'required_present': focus.get('required_present'),
            'required_total': focus.get('required_total'),
            'verification_status': focus.get('verification_status'),
            'verification_pending_checks': focus.get('verification_pending_checks') or [],
            'artifact_audit_passed': focus.get('artifact_audit_passed'),
            'artifact_issue_count': focus.get('artifact_issue_count'),
            'permission_error_count_tail200': focus.get('permission_error_count_tail200'),
            'provider_error_count_tail200': focus.get('provider_error_count_tail200'),
            'build_success': focus.get('build_success'),
            'build_ready': focus.get('build_ready'),
            'manifest_reproducible': focus.get('manifest_reproducible'),
        },
        'autonomy_stage': autonomy.get('stage'),
        'autonomy_score': autonomy.get('score'),
        'stable_autonomy': autonomy_is_confirmed(autonomy),
        'needs_more_soak': ((autonomy.get('decision') or {}).get('needs_more_soak')),
        'self_model_health': self_model.get('state', {}).get('health') or self_model.get('health'),
        'self_model_blockers': ((self_model.get('state') or {}).get('blockers')) or self_model.get('blockers') or [],
        'governance_contract': summarize_governance_contract(governance_contract),
    }
    runtime['incident_classification'] = _classify_quality_plane_incident(runtime=runtime)
    return runtime

def _build_metaforge_soak_milestone_message(*, milestone_hours: int, runtime: dict) -> tuple[str, str, str]:
    focus = runtime.get('focus_artifact') or {}
    verification = runtime.get('verification') or {}
    artifact_registry = runtime.get('artifact_registry') or {}
    reality_dashboard = runtime.get('reality_dashboard') or {}
    ai_testing = runtime.get('ai_testing') or {}
    control_layer = runtime.get('control_layer') or {}
    engineering_os = runtime.get('engineering_os') or {}
    incident = runtime.get('incident_classification') or {}
    pending_checks = focus.get('verification_pending_checks') or []
    system_pending_checks = verification.get('pending_checks') or []
    raw_lines = [
        f'MetaForge system milestone reached: {milestone_hours}h.',
        '',
        f"- daemon_running: {runtime.get('daemon_running')}",
        f"- epoch_id: {runtime.get('epoch_id')}",
        f"- epoch_status: {runtime.get('epoch_status')}",
        f"- runtime_continuity: {runtime.get('runtime_continuity')}",
        f"- state_continuity: {runtime.get('state_continuity')}",
        f"- control_semantic_continuity: {runtime.get('control_semantic_continuity')}",
        f"- evidence_continuity: {runtime.get('evidence_continuity')}",
        f"- epoch_health: {runtime.get('epoch_health')}",
        f"- claim_scope: {runtime.get('claim_scope')}",
        f"- continuity_confidence: {runtime.get('continuity_confidence')}",
        f"- continuity_mode: {runtime.get('continuity_mode')}",
        f"- continuity_break_reason: {runtime.get('continuity_break_reason')}",
        f"- continuity_risk_reasons: {', '.join(runtime.get('continuity_risk_reasons') or []) if (runtime.get('continuity_risk_reasons') or []) else 'none'}",
        f"- incident_type: {incident.get('incident_type') or 'none'}",
        f"- incident_active: {incident.get('active')}",
        f"- incident_trigger_signal: {incident.get('trigger_signal') or 'none'}",
        f"- incident_release_readiness: {incident.get('release_readiness') or runtime.get('release_readiness')}",
        f"- incident_self_model_health: {incident.get('self_model_health') or runtime.get('self_model_health')}",
        f"- incident_root_cause_bucket: {incident.get('root_cause_bucket') or 'none'}",
        f"- incident_concurrent_contributors: {', '.join(incident.get('concurrent_contributors') or []) if (incident.get('concurrent_contributors') or []) else 'none'}",
        f"- accumulated_uptime_seconds: {runtime.get('accumulated_uptime_seconds')}",
        f"- restart_count_within_epoch: {runtime.get('restart_count_within_epoch')}",
        f"- last_successful_durable_checkpoint_at: {runtime.get('last_successful_durable_checkpoint_at')}",
        f"- evidence_write_failures_last_hour: {runtime.get('evidence_write_failures_last_hour')}",
        f"- evidence_write_failures_last_24h: {runtime.get('evidence_write_failures_last_24h')}",
        f"- daemon_started_at: {runtime.get('daemon_started_at')}",
        f"- uptime_hours: {runtime.get('uptime_hours')}",
        f"- daemon_pid: {runtime.get('daemon_pid')}",
        f"- daemon_cycle: {runtime.get('daemon_cycle')}",
        f"- daemon_last_tick_at: {runtime.get('daemon_last_tick_at')}",
        f"- soak_status: {runtime.get('soak_status')}",
        f"- soak_label: {runtime.get('soak_label')}",
        f"- soak_started_at: {runtime.get('soak_started_at')}",
        f"- soak_last_updated_at: {runtime.get('soak_last_updated_at')}",
        f"- soak_samples_collected: {runtime.get('soak_samples_collected')}",
        f"- soak_report_path: {runtime.get('soak_report_path')}",
        '',
        f"- control_layer_status: {control_layer.get('status')}",
        f"- control_layer_quality_status: {control_layer.get('quality_status')}",
        f"- control_layer_overall_score: {control_layer.get('overall_score')}",
        f"- release_readiness: {runtime.get('release_readiness')}",
        f"- engineering_os_status: {engineering_os.get('status')}",
        f"- engineering_patch_gate_status: {engineering_os.get('patch_gate_status')}",
        f"- engineering_delayed_verification_status: {engineering_os.get('delayed_verification_status')}",
        f"- engineering_release_gate_status: {engineering_os.get('release_gate_status')}",
        f"- verification_status: {verification.get('status')}",
        f"- verification_runtime_health_status: {verification.get('runtime_health_status')}",
        f"- verification_pending_checks: {', '.join(system_pending_checks) if system_pending_checks else 'none'}",
        f"- artifact_registry_status: {artifact_registry.get('status')}",
        f"- artifact_count: {artifact_registry.get('artifact_count')}",
        f"- real_artifact_count: {artifact_registry.get('real_artifact_count')}",
        f"- valuable_artifact_count: {artifact_registry.get('valuable_artifact_count')}",
        f"- artifact_issue_count: {artifact_registry.get('issue_count')}",
        f"- reality_status: {reality_dashboard.get('status')}",
        f"- products_real: {reality_dashboard.get('products_real')}",
        f"- artifacts_produced_last_24h: {reality_dashboard.get('artifacts_produced_last_24h')}",
        f"- tasks_completed_last_24h: {reality_dashboard.get('tasks_completed_last_24h')}",
        f"- conversion_rate: {reality_dashboard.get('conversion_rate')}",
        f"- ai_testing_status: {ai_testing.get('status')}",
        f"- ai_release_signal: {ai_testing.get('release_signal')}",
        f"- ai_pass_rate: {ai_testing.get('pass_rate')}",
        f"- ai_error_count: {ai_testing.get('error_count')}",
        f"- ai_failing_case_ids: {', '.join(ai_testing.get('failing_case_ids') or []) if (ai_testing.get('failing_case_ids') or []) else 'none'}",
        '',
        'Current focus artifact snapshot:',
        f"- focus_required_artifacts: {focus.get('required_present')}/{focus.get('required_total')}",
        f"- build_success: {focus.get('build_success')}",
        f"- build_ready: {focus.get('build_ready')}",
        f"- manifest_reproducible: {focus.get('manifest_reproducible')}",
        f"- verification_status: {focus.get('verification_status')}",
        f"- verification_pending_checks: {', '.join(pending_checks) if pending_checks else 'none'}",
        f"- artifact_audit_passed: {focus.get('artifact_audit_passed')}",
        f"- artifact_issue_count: {focus.get('artifact_issue_count')}",
        f"- permission_error_count_tail200: {focus.get('permission_error_count_tail200')}",
        f"- provider_error_count_tail200: {focus.get('provider_error_count_tail200')}",
        f"- autonomy_stage: {runtime.get('autonomy_stage')}",
        f"- autonomy_score: {runtime.get('autonomy_score')}",
        f"- stable_autonomy: {runtime.get('stable_autonomy')}",
        f"- needs_more_soak: {runtime.get('needs_more_soak')}",
        f"- self_model_health: {runtime.get('self_model_health')}",
        f"- self_model_blockers: {', '.join(runtime.get('self_model_blockers') or []) if (runtime.get('self_model_blockers') or []) else 'none'}",
        f"- governance_contract_status: {(runtime.get('governance_contract') or {}).get('status')}",
        f"- governance_contract_schema_version: {(runtime.get('governance_contract') or {}).get('schema_version')}",
        f"- governance_orchestrator_responsibility_count: {(runtime.get('governance_contract') or {}).get('orchestrator_responsibility_count')}",
        f"- governance_harness_responsibility_count: {(runtime.get('governance_contract') or {}).get('harness_responsibility_count')}",
        f"- governance_context_separation: {(runtime.get('governance_contract') or {}).get('context_separation')}",
        '',
        'Workspace root: D:\\codex',
        f"Notification state: {METAFORGE_SOAK_MILESTONE_NOTIFY_PATH}",
    ]
    human_summary = _render_human_friendly_metaforge_summary(
        milestone_hours=milestone_hours,
        runtime=runtime,
    )
    lines = []
    if human_summary:
        lines.extend(
            [
                f'Human-friendly summary ({human_summary.get("source")}):',
                human_summary.get('text') or '',
                '',
            ]
        )
    lines.extend(
        [
            'Structured facts:',
            *raw_lines,
        ]
    )
    subject = f'MetaForge system milestone {milestone_hours}h'
    text = '\n'.join(lines)
    markdown = f'# MetaForge system milestone {milestone_hours}h\n\n' + '\n'.join(lines) + '\n'
    return subject, text, markdown


def _fallback_human_summary(*, milestone_hours: int, runtime: dict) -> str:
    verification = runtime.get('verification') or {}
    ai_testing = runtime.get('ai_testing') or {}
    focus = runtime.get('focus_artifact') or {}
    risks: list[str] = []
    if verification.get('status') not in {None, 'pass'}:
        risks.append(f"verification={verification.get('status')}")
    if verification.get('runtime_health_status') not in {None, 'pass'}:
        risks.append(f"runtime_health={verification.get('runtime_health_status')}")
    if int(focus.get('permission_error_count_tail200') or 0) > 0:
        risks.append(f"permission_error_tail200={focus.get('permission_error_count_tail200')}")
    if int(focus.get('provider_error_count_tail200') or 0) > 0:
        risks.append(f"provider_error_tail200={focus.get('provider_error_count_tail200')}")
    if ai_testing.get('status') not in {None, 'pass'}:
        risks.append(f"ai_testing={ai_testing.get('status')}")
    risk_text = '；'.join(risks) if risks else '未发现新的阻塞风险。'
    next_step = '继续运行到下一个里程碑并观察 runtime_health、权限错误和邮件投递是否保持稳定。'
    return (
        f"结论：MetaForge 已连续运行 {runtime.get('uptime_hours')} 小时，达到 {milestone_hours} 小时里程碑。"
        f" 当前 daemon pid={runtime.get('daemon_pid')}，cycle={runtime.get('daemon_cycle')}，"
        f"AI 测试={ai_testing.get('status')}，artifact audit={((runtime.get('artifact_registry') or {}).get('status'))}。"
        f"\n风险：{risk_text}"
        f"\n下一步：{next_step}"
    )


def _render_human_friendly_metaforge_summary(*, milestone_hours: int, runtime: dict) -> dict[str, Any] | None:
    fallback_text = _fallback_human_summary(milestone_hours=milestone_hours, runtime=runtime)
    if OpenAI is None:
        return {'source': 'fallback', 'text': fallback_text}
    api_key = (settings.openai_api_key or '').strip()
    if not api_key:
        return {'source': 'fallback', 'text': fallback_text}
    payload = {
        'milestone_hours': milestone_hours,
        'runtime': runtime,
    }
    prompt = (
        '你是 MetaForge 系统运维汇报助手。'
        '请严格只基于给定 JSON 事实生成面向人类的简明中文汇报。'
        '禁止补充 JSON 之外的事实，禁止猜测，禁止夸张。'
        '输出固定三行：'
        '第一行以“结论：”开头；'
        '第二行以“风险：”开头；'
        '第三行以“下一步：”开头。'
        '每行一句，简洁明确。'
    )
    try:
        client = OpenAI(api_key=api_key, base_url=settings.openai_base_url)
        if strategic_llm_api_style() == 'responses':
            response = client.responses.create(
                model=settings.default_publish_check_model or settings.cheap_summary_model or settings.planner_model,
                input=[
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
                ],
                max_output_tokens=220,
            )
            text = getattr(response, 'output_text', '') or ''
        else:
            response = client.chat.completions.create(
                model=settings.default_publish_check_model or settings.cheap_summary_model or settings.planner_model,
                messages=[
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
                ],
                max_tokens=220,
            )
            text = (((response.choices or [None])[0] or {}).message.content if response.choices else '') or ''
        text = str(text).strip()
        if not text:
            return {'source': 'fallback', 'text': fallback_text}
        return {'source': 'llm', 'text': text}
    except Exception as exc:
        return {'source': f'fallback:{type(exc).__name__}', 'text': fallback_text}


def _maybe_emit_metaforge_soak_milestone_notification(*, cycle: int, daemon_started_at: str | None) -> dict:
    runtime = _metaforge_runtime_snapshot(daemon_started_at=daemon_started_at)
    state = _read_json_file(METAFORGE_SOAK_MILESTONE_NOTIFY_PATH, {'runs': {}})
    runs = state.setdefault('runs', {})
    run_key = str(daemon_started_at or 'unknown')
    run_state = runs.setdefault(run_key, {'daemon_started_at': daemon_started_at, 'milestones': {}})
    run_state['last_evaluated_at'] = utc()
    run_state['last_cycle'] = cycle
    run_state['last_runtime'] = runtime
    uptime_hours = float(runtime.get('uptime_hours') or 0.0)
    epoch_id = str(runtime.get('epoch_id') or daemon_started_at or 'unknown')
    events: list[dict] = []
    for milestone_hours in METAFORGE_SOAK_MILESTONE_HOURS:
        key = str(milestone_hours)
        milestone_state = (run_state.get('milestones') or {}).get(key) or {}
        if uptime_hours < float(milestone_hours):
            _update_milestone_ledger(epoch_id=epoch_id, milestone_hours=milestone_hours, status='pending', runtime=runtime)
            record = {
                'milestone_hours': milestone_hours,
                'status': 'waiting',
                'cycle': cycle,
                'daemon_started_at': daemon_started_at,
                'uptime_hours': runtime.get('uptime_hours'),
                'last_checked_at': utc(),
                'report_path': runtime.get('soak_report_path'),
            }
            run_state.setdefault('milestones', {})[key] = {**milestone_state, **record}
            events.append({'milestone_hours': milestone_hours, 'status': 'waiting'})
            continue
        if milestone_state.get('delivered'):
            _update_milestone_ledger(epoch_id=epoch_id, milestone_hours=milestone_hours, status='committed', runtime=runtime, report_path=milestone_state.get('report_path'))
            milestone_state['status'] = 'delivered'
            milestone_state['last_checked_at'] = utc()
            milestone_state['uptime_hours'] = runtime.get('uptime_hours')
            milestone_state['cycle'] = cycle
            run_state.setdefault('milestones', {})[key] = milestone_state
            events.append({'milestone_hours': milestone_hours, 'status': 'already-delivered', 'notification': milestone_state})
            continue
        if not _bundle_retry_due(milestone_state.get('last_attempt_at')):
            _update_milestone_ledger(epoch_id=epoch_id, milestone_hours=milestone_hours, status='partial', runtime=runtime, report_path=milestone_state.get('report_path'))
            milestone_state['status'] = 'retry-deferred'
            milestone_state['last_checked_at'] = utc()
            milestone_state['uptime_hours'] = runtime.get('uptime_hours')
            milestone_state['cycle'] = cycle
            run_state.setdefault('milestones', {})[key] = milestone_state
            events.append({'milestone_hours': milestone_hours, 'status': 'retry-deferred', 'notification': milestone_state})
            continue
        eligible_at = utc()
        report_path = _write_milestone_report(epoch_id=epoch_id, milestone_hours=milestone_hours, runtime=runtime)
        _update_milestone_ledger(
            epoch_id=epoch_id,
            milestone_hours=milestone_hours,
            status='reporting',
            runtime=runtime,
            report_path=report_path,
            eligible_at=eligible_at,
        )
        subject, text_message, markdown = _build_metaforge_soak_milestone_message(milestone_hours=milestone_hours, runtime=runtime)
        _update_milestone_ledger(
            epoch_id=epoch_id,
            milestone_hours=milestone_hours,
            status='notifying',
            runtime=runtime,
            report_path=report_path,
            eligible_at=eligible_at,
        )
        notification = send_factory_notification(subject, text_message, markdown=markdown, send_serverchan=False, send_qq_mail=True)
        qq_delivery = (notification.get('delivery') or {}).get('qq_mail') or {}
        delivered = bool(qq_delivery.get('delivered'))
        attempt_count = int(milestone_state.get('attempt_count') or 0) + 1
        record = {
            'milestone_hours': milestone_hours,
            'status': 'delivered' if delivered else 'attempted',
            'cycle': cycle,
            'daemon_started_at': daemon_started_at,
            'uptime_hours': runtime.get('uptime_hours'),
            'last_attempt_at': notification.get('reported_at'),
            'last_checked_at': utc(),
            'attempt_count': attempt_count,
            'delivered': delivered,
            'delivery': notification.get('delivery') or {},
            'subject': subject,
            'report_path': report_path,
        }
        if delivered:
            record['delivered_at'] = notification.get('reported_at')
        run_state.setdefault('milestones', {})[key] = record
        ledger_status = 'committed' if delivered and Path(report_path).exists() else ('partial' if delivered or Path(report_path).exists() else 'failed')
        ledger_record = _update_milestone_ledger(
            epoch_id=epoch_id,
            milestone_hours=milestone_hours,
            status=ledger_status,
            runtime=runtime,
            report_path=report_path,
            notification=notification,
            eligible_at=eligible_at,
        )
        events.append({'milestone_hours': milestone_hours, 'status': 'delivered' if delivered else 'attempted', 'notification': record})
    runs[run_key] = run_state
    state['updated_at'] = utc()
    _atomic_write_text(METAFORGE_SOAK_MILESTONE_NOTIFY_PATH, json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'runtime': runtime, 'events': events, 'run_key': run_key}


def _maybe_emit_toyos_completion_notification(*, cycle: int) -> dict:
    progress = _toyos_bundle_progress()
    notification_state = _read_json_file(TOYOS_GOAL_COMPLETION_NOTIFY_PATH, {'bundles': {}})
    bundles = notification_state.setdefault('bundles', {})
    bundle_state = bundles.get(TOYOS_COMPLETION_BUNDLE_ID) or {}
    if bundle_state.get('delivered'):
        return {'status': 'already-delivered', 'progress': progress, 'notification': bundle_state}
    if not progress.get('ready'):
        return {'status': 'waiting', 'progress': progress, 'notification': bundle_state}
    if not _bundle_retry_due(bundle_state.get('last_attempt_at')):
        return {'status': 'retry-deferred', 'progress': progress, 'notification': bundle_state}
    subject, text_message, markdown = _build_toyos_completion_message(progress)
    notification = send_factory_notification(subject, text_message, markdown=markdown, send_serverchan=False, send_qq_mail=True)
    qq_delivery = (notification.get('delivery') or {}).get('qq_mail') or {}
    delivered = bool(qq_delivery.get('delivered'))
    attempt_count = int(bundle_state.get('attempt_count') or 0) + 1
    bundle_record = {
        'bundle_id': TOYOS_COMPLETION_BUNDLE_ID,
        'goal_ids': list(TOYOS_COMPLETION_GOAL_IDS),
        'cycle': cycle,
        'completed_count': progress.get('completed_count'),
        'goal_count': progress.get('goal_count'),
        'last_attempt_at': notification.get('reported_at'),
        'attempt_count': attempt_count,
        'delivered': delivered,
        'delivery': notification.get('delivery') or {},
        'subject': subject,
    }
    if delivered:
        bundle_record['delivered_at'] = notification.get('reported_at')
    bundles[TOYOS_COMPLETION_BUNDLE_ID] = bundle_record
    notification_state['updated_at'] = utc()
    _atomic_write_text(TOYOS_GOAL_COMPLETION_NOTIFY_PATH, json.dumps(notification_state, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'status': 'delivered' if delivered else 'attempted', 'progress': progress, 'notification': bundle_record}


def _ai_testing_failure_state(ai_testing: dict, previous_state: dict | None = None) -> dict:
    previous_state = previous_state or {}
    previous = int(previous_state.get('ai_testing_consecutive_failures', 0) or 0)
    status = str(ai_testing.get('status') or 'missing')
    release_signal = str(ai_testing.get('release_signal') or 'signal_only')
    errors = int(ai_testing.get('error_count', 0) or 0)
    failing_case_ids = [str(item) for item in (ai_testing.get('failing_case_ids') or []) if str(item).strip()]
    failed_release_blocker_case_ids = [
        str(item)
        for item in (ai_testing.get('failed_release_blocker_case_ids') or []) if str(item).strip()
    ]
    layers = ai_testing.get('layers') or {}
    smoke_status = str((layers.get('smoke') or {}).get('status') or '')
    stability_status = str((layers.get('stability') or {}).get('status') or '')
    signal_only = bool(ai_testing.get('signal_only')) or release_signal in {'signal_only', 'sampled_async'} or ai_testing.get('mode') == 'sampled_async'
    runtime_unstable = (
        not signal_only and (
            errors > 0
            or smoke_status in {'degraded', 'missing'}
            or stability_status in {'degraded', 'missing'}
            or status in {'missing', 'degraded', 'attention', 'warning'}
            or release_signal != 'ready'
            or bool(failed_release_blocker_case_ids)
            or bool(failing_case_ids)
        )
    )
    if status in {'disabled', 'skipped'} or signal_only:
        consecutive = 0
    elif not runtime_unstable:
        consecutive = 0
    else:
        consecutive = previous + 1
    alert = consecutive >= AI_TEST_ALERT_THRESHOLD
    return {
        'consecutive_failures': consecutive,
        'alert': alert,
        'threshold': AI_TEST_ALERT_THRESHOLD,
    }


def _run_self_model_summary(*, trigger: str = 'cycle_end') -> dict[str, object]:
    payload = run_self_model_cycle(persist=True)
    state = payload.get('state') or {}
    goal = payload.get('goal') or {}
    execution = payload.get('execution') or {}
    results = execution.get('results') or []
    reflection = payload.get('reflection') or {}
    strategy_review = payload.get('strategy_review') or {}
    return {
        'updated_at': payload.get('updated_at'),
        'health': state.get('health'),
        'goal': goal.get('primary'),
        'mode': goal.get('mode'),
        'priority': goal.get('priority'),
        'blockers': state.get('blockers') or [],
        'blocker_count': len(state.get('blockers') or []),
        'active_task_count': ((state.get('tasks') or {}).get('active_count')),
        'stalled_active_count': ((state.get('tasks') or {}).get('stalled_active_count')),
        'control_status': state.get('control_status'),
        'daemon_running': ((state.get('daemon') or {}).get('running')),
        'executed_action_count': execution.get('executed_action_count', len(results)),
        'executed_actions': [
            {
                'action': item.get('action'),
                'status': item.get('status'),
            }
            for item in results
        ],
        'next_actions': [item.get('action') for item in (payload.get('next_actions') or [])],
        'reflection_summary': reflection.get('summary'),
        'reflection_hypothesis': reflection.get('hypothesis') or [],
        'strategy_review': {
            'reviewed_pattern_count': strategy_review.get('reviewed_pattern_count', 0),
            'active_pattern_count': strategy_review.get('active_pattern_count', 0),
            'reinforced_count': strategy_review.get('reinforced_count', 0),
            'pruned_count': strategy_review.get('pruned_count', 0),
            'reuse_success_rate': strategy_review.get('reuse_success_rate', 0.0),
        },
        'trigger': trigger,
    }


def _run_self_model_summary_best_effort(*, trigger: str = 'cycle_end', timeout_seconds: int = SELF_MODEL_TIMEOUT_SECONDS) -> dict[str, object]:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='self_model_cycle')
    future = executor.submit(_run_self_model_summary, trigger=trigger)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        return _static_self_model_summary(
            health='degraded',
            goal='self_model_timeout',
            mode='operator_attention',
            priority='normal',
            summary=f'Self-model cycle timed out after {timeout_seconds}s; execution state was persisted without it.',
            blockers=[f'self_model_timeout:{timeout_seconds}s'],
            trigger=trigger,
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)



def _self_model_summary_from_state(state: dict | None) -> dict[str, object]:
    state = state or {}
    blockers = list(state.get('last_self_model_blockers') or [])
    return {
        'updated_at': state.get('last_self_model_at') or state.get('updated_at') or utc(),
        'health': state.get('last_self_model_health') or 'pending',
        'goal': state.get('last_self_model_goal') or 'self_model_pending',
        'mode': state.get('last_self_model_mode') or 'normal_execution',
        'priority': 'normal',
        'blockers': blockers,
        'blocker_count': len(blockers),
        'active_task_count': None,
        'stalled_active_count': None,
        'executed_action_count': int(state.get('last_self_model_action_count') or 0),
        'executed_actions': [],
        'next_actions': [],
        'reflection_summary': 'Using the most recent completed self-model snapshot; next review runs asynchronously.',
        'reflection_hypothesis': [],
        'strategy_review': {
            'reviewed_pattern_count': 0,
            'active_pattern_count': 0,
            'reinforced_count': 0,
            'pruned_count': 0,
            'reuse_success_rate': 0.0,
        },
        'trigger': state.get('last_self_model_trigger') or 'restored',
    }


def _collect_self_model_summary(
    future: concurrent.futures.Future | None,
) -> tuple[dict[str, object] | None, concurrent.futures.Future | None]:
    if future is None or not future.done():
        return None, future
    try:
        return future.result(), None
    except Exception as exc:
        return (
            _static_self_model_summary(
                health='error',
                goal='self_model_failure',
                mode='operator_attention',
                priority='high',
                summary=str(exc),
                blockers=[f'self_model_error:{type(exc).__name__}'],
                hypothesis=[f'{type(exc).__name__}: {exc}'],
                trigger='background',
            ),
            None,
        )


def _schedule_self_model_summary(
    executor: concurrent.futures.ThreadPoolExecutor,
    future: concurrent.futures.Future | None,
    *,
    trigger: str,
) -> concurrent.futures.Future:
    if future is not None and not future.done():
        return future
    return executor.submit(_run_self_model_summary, trigger=trigger)


def _run_ai_testing_summary() -> dict[str, object]:
    try:
        report = run_ai_test_suite()
        payload = {
            **load_ai_test_status(),
            'suite_passed': report.get('all_passed', False),
            'run_skipped': False,
            'run_pending': False,
            'signal_only': True,
        }
    except Exception as exc:
        payload = {
            **load_ai_test_status(),
            'status': 'degraded',
            'run_error': str(exc),
            'run_skipped': False,
            'run_pending': False,
            'signal_only': True,
        }
    payload['release_signal'] = payload.get('release_signal') or 'sampled_async'
    payload['mode'] = payload.get('mode') or 'sampled_async'
    return payload


def _collect_ai_testing_summary(
    future: concurrent.futures.Future | None,
) -> tuple[dict[str, object] | None, concurrent.futures.Future | None]:
    if future is None or not future.done():
        return None, future
    try:
        payload = future.result()
    except Exception as exc:
        payload = {
            **load_ai_test_status(),
            'status': 'degraded',
            'run_error': f'{type(exc).__name__}: {exc}',
            'run_skipped': False,
            'run_pending': False,
            'signal_only': True,
            'release_signal': 'sampled_async',
            'mode': 'sampled_async',
        }
    return payload, None


def _schedule_ai_testing_summary(
    executor: concurrent.futures.ThreadPoolExecutor,
    future: concurrent.futures.Future | None,
) -> concurrent.futures.Future:
    if future is not None and not future.done():
        return future
    return executor.submit(_run_ai_testing_summary)


def _static_maintenance_lane(*, mode: str, reason: str, pending: bool = False) -> dict[str, object]:
    return {
        'maintenance': {
            'status': 'signal-only' if pending else 'skipped',
            'reason': reason,
            'mode': mode,
            'run_pending': pending,
            'smoke_hygiene': {
                'status': 'signal-only' if pending else 'skipped',
                'reason': reason,
                'mode': mode,
                'run_pending': pending,
                'reconciled_smoke': {'completed_smoke_tasks': 0, 'task_ids': []},
                'archived_smoke_noise': [],
                'smoke_noise_cleanup_count': 0,
            },
            'schema_hygiene': {
                'status': 'signal-only' if pending else 'skipped',
                'reason': reason,
                'mode': mode,
                'run_pending': pending,
                'scan_finding_count': 0,
                'post_repair_finding_count': 0,
                'fixed_file_count': 0,
            },
        },
        'environment_repair': {
            'status': 'signal-only' if pending else 'skipped',
            'reason': reason,
            'mode': mode,
            'run_pending': pending,
        },
    }


def _run_maintenance_lane(*, mode: str, run_environment_lane: bool, observer_enabled: bool, governance_enabled: bool) -> dict[str, object]:
    payload = {
        'maintenance': run_maintenance(mode=mode),
        'environment_repair': None,
    }
    if run_environment_lane and (observer_enabled or governance_enabled):
        payload['environment_repair'] = run_environment_repair_lane(mode=mode)
    elif not (observer_enabled or governance_enabled):
        payload['environment_repair'] = {'status': 'disabled', 'reason': 'lean_execution', 'mode': mode}
    else:
        payload['environment_repair'] = {'status': 'skipped', 'reason': 'maintenance cadence hold', 'mode': mode}
    return payload


def _collect_maintenance_lane(
    future: concurrent.futures.Future | None,
) -> tuple[dict[str, object] | None, concurrent.futures.Future | None]:
    if future is None or not future.done():
        return None, future
    try:
        payload = future.result()
    except Exception as exc:
        payload = _static_maintenance_lane(mode='light', reason=f'maintenance_lane_error:{type(exc).__name__}', pending=False)
        payload['maintenance']['status'] = 'error'
        payload['maintenance']['error'] = f'{type(exc).__name__}: {exc}'
        payload['environment_repair']['status'] = 'error'
        payload['environment_repair']['error'] = f'{type(exc).__name__}: {exc}'
    return payload, None


def _schedule_maintenance_lane(
    executor: concurrent.futures.ThreadPoolExecutor,
    future: concurrent.futures.Future | None,
    *,
    mode: str,
    run_environment_lane: bool,
    observer_enabled: bool,
    governance_enabled: bool,
) -> concurrent.futures.Future:
    if future is not None and not future.done():
        return future
    return executor.submit(
        _run_maintenance_lane,
        mode=mode,
        run_environment_lane=run_environment_lane,
        observer_enabled=observer_enabled,
        governance_enabled=governance_enabled,
    )


def _static_self_model_summary(
    *,
    health: str,
    goal: str,
    mode: str,
    priority: str,
    summary: str,
    blockers: list[str] | None = None,
    hypothesis: list[str] | None = None,
    trigger: str = 'cycle_end',
) -> dict[str, object]:
    blockers = list(blockers or [])
    return {
        'updated_at': utc(),
        'health': health,
        'goal': goal,
        'mode': mode,
        'priority': priority,
        'blockers': blockers,
        'blocker_count': len(blockers),
        'active_task_count': None,
        'stalled_active_count': None,
        'executed_action_count': 0,
        'executed_actions': [],
        'next_actions': [],
        'reflection_summary': summary,
        'reflection_hypothesis': list(hypothesis or []),
        'trigger': trigger,
    }


def _status_cache_payload(result: dict | None, *, cycle: int, interval: int, meta_every: int, evolution_every: int, policy_schedule: dict | None = None, last_error: str | None = None) -> dict:
    result = result or {}
    control = result.get('control_layer') or {}
    autonomy = result.get('autonomy_score') or {}
    tool_health = result.get('tool_health') or {}
    ai_testing = result.get('ai_testing') or {}
    economics = result.get('economics_engine') or (control.get('economics_engine') or {})
    engineering = control.get('engineering_os') or {}
    patch_system = control.get('patch_system') or {}
    verification = control.get('verification_engine') or {}
    queue = patch_system.get('queue') or {}
    quality_system = control.get('quality_system') or {}
    company = result.get('company_os') or {}
    automation_lab = result.get('automation_lab') or company.get('automation_lab') or {}
    automation_lab_maturity = automation_lab.get('maturity') or {}
    release_ops = result.get('release_operations') or {}
    release_train = release_ops.get('release_train') or {}
    operations_readiness = release_ops.get('operations_readiness') or {}
    self_model = result.get('self_model') or {}
    maintenance = result.get('maintenance') or {}
    schema_hygiene = maintenance.get('schema_hygiene') or {}
    ai_failure_state = {
        'consecutive_failures': ai_testing.get('consecutive_failures'),
        'alert': ai_testing.get('alert'),
        'threshold': ai_testing.get('threshold'),
    }
    if ai_failure_state['consecutive_failures'] is None or ai_failure_state['alert'] is None or ai_failure_state['threshold'] is None:
        ai_failure_state = _ai_testing_failure_state(ai_testing)
    incident_classification = _classify_quality_plane_incident(
        runtime={
            'runtime_continuity': 'broken' if last_error else 'preserved',
            'ai_testing': ai_testing,
            'verification': {
                'pending_checks': (verification.get('pending_checks') or verification.get('reasons') or []),
            },
            'control_layer': {
                'status': control.get('status'),
            },
            'self_model_health': self_model.get('health'),
            'self_model_blockers': self_model.get('blockers') or [],
            'release_readiness': (
                'ready'
                if str(quality_system.get('status') or '').strip().lower() in {'pass', 'ready', 'promote'}
                and str(ai_testing.get('status') or '').strip().lower() in {'', 'pass'}
                else 'candidate'
            ),
        },
        last_error=last_error,
    )
    now = utc()
    return {
        'updated_at': now,
        'cycle': cycle,
        'interval_seconds': interval,
        'meta_every': meta_every,
        'evolution_every': evolution_every,
        'policy_schedule': policy_schedule or {},
        'daemon': {
            'status': 'error' if last_error else 'running',
            'pid': os.getpid(),
            'cycle': cycle,
            'interval_seconds': interval,
            'started_at': now,
            'last_tick_at': now,
            'last_error': last_error,
        },
        'control_layer': {
            'status': control.get('status'),
            'quality_score': control.get('quality_score', quality_system.get('overall_score')),
            'quality_status': quality_system.get('status'),
        },
        'autonomy': {
            'stage': autonomy.get('stage'),
            'score': autonomy.get('score'),
            'stable_autonomy': autonomy_is_confirmed(autonomy),
        },
        'engineering_os': {
            'status': engineering.get('status'),
            'patch_gate_status': verification.get('patch_gate_status'),
            'patch_ready_count': queue.get('ready_count'),
            'patch_blocked_count': queue.get('blocked_count'),
        },
        'lab': {
            'status': automation_lab_maturity.get('status'),
            'score': automation_lab_maturity.get('score'),
        },
        'tool_health': {
            'status': tool_health.get('status'),
            'blocking_issues': (tool_health.get('blocking_issues') or tool_health.get('issues') or [])[:5],
            'issue_count': len(tool_health.get('issues') or []),
            'updated_at': tool_health.get('updated_at'),
        },
        'economics': {
            'status': economics.get('status'),
            'score': economics.get('score'),
            'price_index_mfc': economics.get('price_index_mfc', ((economics.get('resource_market') or {}).get('price_index'))),
            'reward_pool_mfc': economics.get('reward_pool_mfc', ((economics.get('task_market') or {}).get('reward_pool_mfc'))),
            'total_budget_mfc': economics.get('total_budget_mfc', ((economics.get('agent_budget_system') or {}).get('total_budget_mfc'))),
            'completed_value_mfc': economics.get('completed_value_mfc', ((economics.get('ai_gdp') or {}).get('completed_value_mfc'))),
        },
        'ai_testing': {
            'status': ai_testing.get('status'),
            'release_signal': ai_testing.get('release_signal'),
            'overall_score': ai_testing.get('overall_score'),
            'pass_rate': ai_testing.get('pass_rate'),
            'error_count': ai_testing.get('error_count'),
            'stability_status': ((ai_testing.get('layers') or {}).get('stability') or {}).get('status'),
            'updated_at': ai_testing.get('updated_at'),
            'failing_case_ids': (ai_testing.get('failing_case_ids') or [])[:5],
            'consecutive_failures': ai_failure_state.get('consecutive_failures'),
            'alert': ai_failure_state.get('alert', False),
            'threshold': ai_failure_state.get('threshold', AI_TEST_ALERT_THRESHOLD),
        },
        'incident_classification': incident_classification,
        'release_ops': {
            'status': release_ops.get('status', operations_readiness.get('status')),
            'release_train_status': release_train.get('status'),
        },
        'self_model': {
            'updated_at': self_model.get('updated_at'),
            'health': self_model.get('health'),
            'goal': self_model.get('goal'),
            'mode': self_model.get('mode'),
            'priority': self_model.get('priority'),
            'trigger': self_model.get('trigger'),
            'blockers': self_model.get('blockers') or [],
            'blocker_count': self_model.get('blocker_count', len(self_model.get('blockers') or [])),
            'active_task_count': self_model.get('active_task_count'),
            'stalled_active_count': self_model.get('stalled_active_count'),
            'executed_action_count': self_model.get('executed_action_count'),
        },
        'maintenance': {
            'status': maintenance.get('status'),
            'mode': maintenance.get('mode'),
            'run_pending': maintenance.get('run_pending'),
            'schema_hygiene_status': schema_hygiene.get('status'),
            'schema_hygiene_findings': schema_hygiene.get('post_repair_finding_count', schema_hygiene.get('scan_finding_count', schema_hygiene.get('finding_count'))),
            'schema_hygiene_fixed_files': schema_hygiene.get('fixed_file_count'),
        },
    }

def _compact_last_result(result: dict | None) -> dict:
    result = result or {}
    guard = result.get('guard') or {}
    guard_usage = guard.get('usage') or {}
    economics = result.get('economics_engine') or {}
    execution_recovery = result.get('execution_recovery') or {}
    smoke_hygiene = result.get('smoke_hygiene') or {}
    tool_health = result.get('tool_health') or {}
    autonomy = result.get('autonomy_score') or {}
    control = result.get('control_layer') or {}
    quality_system = control.get('quality_system') or {}
    control_policy = control.get('control_policy') or {}
    identity_gate = control.get('identity_gate') or identity_kernel_status()
    self_model = result.get('self_model') or {}
    ai_testing = result.get('ai_testing') or {}
    incident = result.get('incident_classification') or _classify_quality_plane_incident(
        runtime={
            'runtime_continuity': 'preserved',
            'ai_testing': ai_testing,
            'verification': {
                'pending_checks': (((control.get('verification_engine') or {}).get('delayed_verification') or {}).get('pending_checks') or []),
            },
            'control_layer': {
                'status': control.get('status'),
            },
            'self_model_health': self_model.get('health'),
            'self_model_blockers': self_model.get('blockers') or [],
            'release_readiness': (
                'ready'
                if str(control.get('quality_status', quality_system.get('status')) or '').strip().lower() in {'pass', 'ready', 'promote'}
                and str(ai_testing.get('status') or '').strip().lower() in {'', 'pass'}
                else 'candidate'
            ),
        }
    )
    governance_contract = summarize_governance_contract(
        result.get('governance_contract')
        or (result.get('control_layer') or {}).get('governance_contract')
    )
    maintenance = result.get('maintenance') or {}
    schema_hygiene = maintenance.get('schema_hygiene') or {}
    return {
        'top_level_keys': sorted(result.keys())[:30],
        'guard': {
            'status': guard.get('status'),
            'allow_brain_loop': guard.get('allow_brain_loop'),
            'usage': {
                'recent_window': guard_usage.get('recent_window') or {},
            },
        },
        'economics_engine': {
            'status': economics.get('status'),
            'score': economics.get('score'),
        },
        'execution_recovery': {
            'status': execution_recovery.get('status'),
            'recovery_mode': execution_recovery.get('recovery_mode'),
            'active_recovery_task_ids': (execution_recovery.get('active_recovery_task_ids') or [])[:10],
        },
        'smoke_hygiene': {
            'status': smoke_hygiene.get('status'),
            'mode': smoke_hygiene.get('mode'),
            'smoke_noise_cleanup_count': smoke_hygiene.get('smoke_noise_cleanup_count'),
            'archived_smoke_noise': (smoke_hygiene.get('archived_smoke_noise') or [])[:10],
            'reconciled_smoke': smoke_hygiene.get('reconciled_smoke') or {},
        },
        'tool_health': {
            'status': tool_health.get('status'),
            'issues': (tool_health.get('issues') or [])[:10],
            'updated_at': tool_health.get('updated_at'),
        },
        'autonomy_score': {
            'stage': autonomy.get('stage'),
            'score': autonomy.get('score'),
            'stable_autonomy': autonomy_is_confirmed(autonomy),
        },
        'control_layer': {
            'status': control.get('status'),
            'cached': control.get('cached'),
            'reason': control.get('reason'),
            'execution': control.get('execution') or control_policy.get('execution'),
            'quality_score': control.get('quality_score', quality_system.get('overall_score')),
            'quality_status': control.get('quality_status', quality_system.get('status')),
        },
        'identity_gate': {
            'status': identity_gate.get('status'),
            'consistency': identity_gate.get('consistency') or {},
            'memory': identity_gate.get('memory') or {},
            'authority': identity_gate.get('authority') or {},
            'runtime': identity_gate.get('runtime') or {},
            'updated_at': identity_gate.get('updated_at'),
        },
        'self_model': {
            'updated_at': self_model.get('updated_at'),
            'health': self_model.get('health'),
            'goal': self_model.get('goal'),
            'mode': self_model.get('mode'),
            'blocker_count': self_model.get('blocker_count'),
        },
        'ai_testing': {
            'status': ai_testing.get('status'),
            'release_signal': ai_testing.get('release_signal'),
            'error_count': ai_testing.get('error_count'),
            'failing_case_ids': (ai_testing.get('failing_case_ids') or [])[:5],
            'consecutive_failures': ai_testing.get('consecutive_failures'),
            'alert': ai_testing.get('alert'),
        },
        'incident_classification': {
            'active': incident.get('active'),
            'incident_type': incident.get('incident_type'),
            'trigger_signal': incident.get('trigger_signal'),
            'release_readiness': incident.get('release_readiness'),
            'self_model_health': incident.get('self_model_health'),
        },
        'governance_contract': governance_contract,
        'signal_dashboard': incident.get('signal_dashboard') or {},
        'maintenance': {
            'status': maintenance.get('status'),
            'mode': maintenance.get('mode'),
            'schema_hygiene': {
                'status': schema_hygiene.get('status'),
                'scan_finding_count': schema_hygiene.get('scan_finding_count', schema_hygiene.get('finding_count')),
                'post_repair_finding_count': schema_hygiene.get('post_repair_finding_count', schema_hygiene.get('finding_count')),
                'fixed_file_count': schema_hygiene.get('fixed_file_count'),
            },
        },
    }


def write_status_cache(result: dict | None, *, cycle: int, interval: int, meta_every: int, evolution_every: int, policy_schedule: dict | None = None, last_error: str | None = None) -> None:
    payload = _status_cache_payload(result, cycle=cycle, interval=interval, meta_every=meta_every, evolution_every=evolution_every, policy_schedule=policy_schedule, last_error=last_error)
    _atomic_write_text(STATUS_CACHE_PATH, json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _runtime_pressure_snapshot(result: dict | None, policy_schedule: dict | None = None) -> dict:
    control = (result or {}).get('control_layer') or {}
    state_kernel = control.get('state_kernel') or {}
    min_active_tasks = int((policy_schedule or {}).get('min_active_tasks') or DEFAULT_MIN_ACTIVE_TASKS)
    max_active_tasks = int((policy_schedule or {}).get('max_active_tasks') or DEFAULT_MAX_ACTIVE_TASKS)
    active_task_count = None
    active_task_ids: list[str] = []
    task_state_counts = {
        'true_running_task_count': 0,
        'execution_finishing_task_count': 0,
        'pending_task_count': 0,
        'blocked_task_count': 0,
        'recovery_running_task_count': 0,
        'mainline_running_task_count': 0,
    }
    tasks = []
    tasks_path = DATA / 'tasks.json'
    if tasks_path.exists():
        try:
            tasks = json.loads(tasks_path.read_text(encoding='utf-8-sig'))
        except Exception:
            tasks = []
    if FACTORY_TASK_ENGINE_STATUS_PATH.exists():
        try:
            engine_status = json.loads(FACTORY_TASK_ENGINE_STATUS_PATH.read_text(encoding='utf-8-sig'))
        except Exception:
            engine_status = {}
        for candidate in (
            ((engine_status.get('supply_after_seed') or {}).get('active_task_count')),
            ((engine_status.get('supply_before_seed') or {}).get('active_task_count')),
        ):
            try:
                if candidate is not None:
                    active_task_count = int(candidate)
                    break
            except Exception:
                continue
    if active_task_count is None:
        cache = _read_status_cache()
        try:
            active_task_count = int((((cache.get('runtime') or {}).get('tasks') or {}).get('active_count')))
        except Exception:
            active_task_count = None
    if active_task_count is None:
        true_running_statuses = {'planning', 'running', 'verification_pending', 'verification_running'}
        finishing_statuses = {'execution_finished'}
        pending_statuses = {'queued', 'waiting_approval'}
        blocked_statuses = {'blocked', 'failed', 'timed_out', 'cancelled', 'verification_failed'}
        active_task_items = [item for item in tasks if str(item.get('status') or '') in true_running_statuses]
        active_task_count = len(active_task_items)
        active_task_ids = [item.get('id') for item in active_task_items[:12] if item.get('id')]
    if tasks:
        true_running_statuses = {'planning', 'running', 'verification_pending', 'verification_running'}
        finishing_statuses = {'execution_finished'}
        pending_statuses = {'queued', 'waiting_approval'}
        blocked_statuses = {'blocked', 'failed', 'timed_out', 'cancelled', 'verification_failed'}
        active_task_items = [item for item in tasks if str(item.get('status') or '') in true_running_statuses]
        if active_task_count is None:
            active_task_count = len(active_task_items)
        if not active_task_ids:
            active_task_ids = [item.get('id') for item in active_task_items[:12] if item.get('id')]
        for item in tasks:
            status = str(item.get('status') or '').strip().lower()
            corpus = ' '.join(
                str(part or '')
                for part in [
                    item.get('title'),
                    item.get('goal'),
                    item.get('prompt'),
                    item.get('repo_path'),
                    (item.get('scheduler_hint') or {}).get('goal_target'),
                    (item.get('scheduler_hint') or {}).get('node_title'),
                    ' '.join(str(value) for value in ((item.get('scheduler_hint') or {}).get('required_artifacts') or []) if value),
                ]
            ).lower()
            scheduler_hint = item.get('scheduler_hint') or {}
            if status in true_running_statuses:
                task_state_counts['true_running_task_count'] += 1
                if any(marker in corpus for marker in ('recovery', 'execution recovery', 'recover stable execution output')) or bool(scheduler_hint.get('recovery_task')):
                    task_state_counts['recovery_running_task_count'] += 1
                if any(marker in corpus for marker in ('toyos', 'toy-os', 'generated/toy-os-demo')) or str(item.get('execution_mode') or '').strip().lower() == 'production':
                    task_state_counts['mainline_running_task_count'] += 1
            elif status in finishing_statuses:
                task_state_counts['execution_finishing_task_count'] += 1
            elif status in pending_statuses:
                task_state_counts['pending_task_count'] += 1
            elif status in blocked_statuses:
                task_state_counts['blocked_task_count'] += 1
    return {
        'active_tasks': active_task_count,
        'active_task_ids': active_task_ids,
        'agents_running': int(state_kernel.get('agents_running') or 0),
        'min_active_tasks': min_active_tasks,
        'max_active_tasks': max_active_tasks,
        'needs_pressure': int(active_task_count or 0) < min_active_tasks,
        **task_state_counts,
        'active_tasks_including_finishing': int(task_state_counts['true_running_task_count']) + int(task_state_counts['execution_finishing_task_count']),
    }


def _maintenance_pressure_overview(previous_state: dict | None, pressure: dict | None = None) -> dict[str, object]:
    previous_state = previous_state or {}
    last_result = previous_state.get('last_result') or {}
    brain_loop_state = (
        _read_json_file(ROOT / 'factory' / 'logs' / 'brain_loop_latest.json', {})
        or _read_json_file(DATA / 'brain_loop_state.json', {})
        or _read_json_file(DATA / 'brain_loop_latest.json', {})
    )
    pressure = pressure or (
        brain_loop_state.get('runtime_pressure')
        or (last_result.get('brain_loop') or {}).get('runtime_pressure')
        or last_result.get('runtime_pressure')
        or previous_state.get('runtime_pressure')
        or {}
    )
    goal_backlog = (
        _read_json_file(DATA / 'goal_backlog_status.json', {})
        or
        brain_loop_state.get('goal_backlog')
        or (last_result.get('brain_loop') or {}).get('goal_backlog')
        or last_result.get('goal_backlog')
        or previous_state.get('goal_backlog')
        or {}
    )
    execution_recovery = last_result.get('execution_recovery') or previous_state.get('execution_recovery') or {}
    true_running = int(
        pressure.get('true_running_task_count')
        or pressure.get('active_task_count_after')
        or pressure.get('active_tasks')
        or 0
    )
    min_active = int(pressure.get('min_active_tasks') or DEFAULT_MIN_ACTIVE_TASKS)
    backlog_starved = str(goal_backlog.get('goal_health') or '').strip().lower() == 'starved'
    replenishment_failed = str(goal_backlog.get('last_replenishment_result') or '').strip().lower() == 'replenishment_failed'
    dispatch_failed = str(goal_backlog.get('replenishment_block_reason') or '').strip().lower().startswith('dispatch_failed') or 'dispatch_precheck_failed' in str(goal_backlog.get('replenishment_block_reason') or '').strip().lower()
    recovery_degraded = str(execution_recovery.get('status') or '').strip().lower() == 'degraded'
    recovery_mode = bool(execution_recovery.get('recovery_mode'))
    force_full = (
        true_running < min_active
        and (backlog_starved or replenishment_failed or dispatch_failed or recovery_degraded or recovery_mode)
    )
    reason = 'maintenance_pressure_floor_breach' if force_full else 'maintenance_cadence_hold'
    return {
        'force_full': force_full,
        'mode': 'full' if force_full else 'light',
        'reason': reason,
        'true_running_task_count': true_running,
        'min_active_tasks': min_active,
        'goal_health': goal_backlog.get('goal_health'),
        'last_replenishment_result': goal_backlog.get('last_replenishment_result'),
        'replenishment_block_reason': goal_backlog.get('replenishment_block_reason'),
        'recovery_status': execution_recovery.get('status'),
        'recovery_mode': recovery_mode,
    }


def _write_watchdog_snapshot(*, daemon_state: dict | None = None, result: dict | None = None, policy_schedule: dict | None = None, last_error: str | None = None) -> dict:
    daemon_state = daemon_state or _read_status_file()
    pressure = _runtime_pressure_snapshot(result, policy_schedule=policy_schedule)
    consecutive_error_count = int(daemon_state.get('consecutive_error_count', 0) or 0)
    payload = {
        'updated_at': utc(),
        'daemon_status': daemon_state.get('status'),
        'cycle': daemon_state.get('cycle'),
        'last_error': last_error if last_error is not None else daemon_state.get('last_error'),
        'consecutive_error_count': consecutive_error_count,
        'restart_recommended': bool(
            daemon_state.get('restart_requested')
            or daemon_state.get('status') == 'error'
            or consecutive_error_count >= DAEMON_ERROR_RESTART_THRESHOLD
        ),
        'runtime_pressure': pressure,
    }
    _atomic_write_text(WATCHDOG_PATH, json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def is_pid_running(pid: int) -> bool:
    try:
        if os.name == 'nt':
            return _windows_process_exists(pid)
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def daemon_status() -> dict:
    state = {}
    if STATUS_PATH.exists():
        try:
            state = json.loads(STATUS_PATH.read_text(encoding='utf-8-sig'))
        except Exception:
            state = {'status': 'corrupt-state'}
    pid = None
    if PID_PATH.exists():
        try:
            pid = int(PID_PATH.read_text(encoding='utf-8').strip())
        except Exception:
            pid = None
    status_pid = state.get('pid')
    if not pid and isinstance(status_pid, int):
        pid = status_pid
    elif pid and isinstance(status_pid, int) and pid != status_pid and is_pid_running(status_pid) and not is_pid_running(pid):
        pid = status_pid
    running = bool(pid and is_pid_running(pid))
    stale = False
    last_tick = state.get('last_tick_at')
    interval = int(state.get('interval_seconds') or 60)
    if last_tick:
        try:
            tick_at = datetime.fromisoformat(str(last_tick).replace('Z', '+00:00'))
            stale = datetime.now(timezone.utc) - tick_at > timedelta(seconds=max(interval * STALE_MULTIPLIER, 120))
        except Exception:
            stale = False
    state['pid'] = pid
    state['running'] = running and not stale
    if stale and state.get('status') == 'running':
        state['status'] = 'stale'
        state['stale_reason'] = 'last tick heartbeat expired'
    elif not running and state.get('status') == 'running':
        state['status'] = 'stopped'
    state['log_path'] = str(LOG_PATH)
    state['status_path'] = str(STATUS_PATH)
    return state




def _load_policy_state() -> dict:
    policy_path = DATA / 'global_policy_state.json'
    if not policy_path.exists():
        return {}
    try:
        return json.loads(policy_path.read_text(encoding='utf-8-sig'))
    except Exception:
        return {}


def _budget_interval(weight: float, default: int, minimum: int) -> int:
    try:
        value = float(weight)
    except Exception:
        value = 0.0
    if value <= 0:
        return max(default, minimum)
    computed = round(1.0 / max(value, 0.05))
    return max(minimum, computed)


def _cadence_value(cadence: dict, key: str, fallback: int) -> int:
    value = cadence.get(key)
    if value is None:
        return int(fallback)
    return int(value)


def _policy_schedule(policy_state: dict, base_meta_every: int, base_evolution_every: int) -> dict:
    budget = policy_state.get('resource_budget') or {}
    cadence = policy_state.get('cadence_policy') or {}
    kernel_mode = policy_state.get('kernel_mode') or load_kernel_mode()
    meta_every = int(cadence.get('meta_every') or _budget_interval(budget.get('capability_building', 0.2), base_meta_every, 2))
    evolution_every = int(cadence.get('experiment_every') or _budget_interval(budget.get('experiments', 0.3), base_evolution_every, 2))
    capability_every = int(cadence.get('capability_building_every') or _budget_interval(budget.get('capability_building', 0.2), 6, 3))
    maintenance_every = int(cadence.get('maintenance_every') or _budget_interval(budget.get('maintenance', 0.1), 10, 4))
    risk_scan_every = int(cadence.get('risk_scan_every') or 5)
    runtime_weight = float(budget.get('runtime_tasks', 0.4) or 0.4)
    runtime_dispatch_limit = int(cadence.get('runtime_dispatch_limit') or (1 if runtime_weight < 0.35 else 2 if runtime_weight < 0.55 else 3))
    goal_generation_every = int(cadence.get('goal_generation_every') or _budget_interval(runtime_weight, 4, 2))
    ai_testing_every = int(cadence.get('ai_testing_every') or max(_budget_interval(budget.get('maintenance', 0.1), 12, 4), 24))
    maintenance_mode = str(cadence.get('maintenance_mode') or ('full' if budget.get('maintenance', 0.1) >= 0.2 else 'light'))

    if kernel_mode.get('profile') in {'lean_execution', 'interaction_only'}:
        return {
            'meta_every': 0,
            'evolution_every': 0,
            'capability_building_every': 0,
            'maintenance_bias_every': max(maintenance_every, 4),
            'maintenance_mode': 'light',
            'risk_scan_every': max(risk_scan_every, 10),
            'runtime_dispatch_limit': max(runtime_dispatch_limit, 4),
            'goal_generation_every': 1,
            'ai_testing_every': max(ai_testing_every, 24),
            'min_active_tasks': max(int(cadence.get('min_active_tasks') or DEFAULT_MIN_ACTIVE_TASKS), 4),
            'max_active_tasks': max(int(cadence.get('max_active_tasks') or DEFAULT_MAX_ACTIVE_TASKS), 12),
            'min_active_goals': max(int(cadence.get('min_active_goals') or 3), 2),
            'resource_budget': budget,
            'kernel_mode': kernel_mode,
            'run_github_learning': False,
            'run_global_policy': False,
            'run_coordination': False,
            'run_release_train': False,
            'inline_governance': False,
        }

    return {
        'meta_every': meta_every,
        'evolution_every': evolution_every,
        'capability_building_every': capability_every,
        'maintenance_bias_every': maintenance_every,
        'maintenance_mode': maintenance_mode,
        'risk_scan_every': max(risk_scan_every, 1),
        'runtime_dispatch_limit': runtime_dispatch_limit,
        'goal_generation_every': goal_generation_every,
        'ai_testing_every': ai_testing_every,
        'min_active_tasks': int(cadence.get('min_active_tasks') or DEFAULT_MIN_ACTIVE_TASKS),
        'max_active_tasks': int(cadence.get('max_active_tasks') or DEFAULT_MAX_ACTIVE_TASKS),
        'min_active_goals': int(cadence.get('min_active_goals') or 3),
        'resource_budget': budget,
        'kernel_mode': kernel_mode,
        'run_github_learning': True,
        'run_global_policy': False,
        'run_coordination': False,
        'run_release_train': False,
        'inline_governance': False,
    }


def _risk_scan_due(cycle: int, risk_scan_every: int, verification_triggered: bool) -> bool:
    if verification_triggered:
        return True
    if cycle <= 1:
        return True
    if risk_scan_every <= 1:
        return True
    return cycle % risk_scan_every == 0


def _execution_priority_mode(*, recovery_mode: bool, run_meta: bool, run_evolution: bool) -> bool:
    if recovery_mode:
        return True
    return not any((run_meta, run_evolution))


def tick(run_meta: bool, run_evolution: bool, policy_schedule: dict | None = None) -> dict:
    cycle = int((policy_schedule or {}).get('cycle') or 0)
    risk_scan_every = int((policy_schedule or {}).get('risk_scan_every') or 5)
    risk_scan_ran = False
    watchdog_handle = _start_tick_watchdog(cycle)
    completed = False
    tick_trace('tick.start', cycle=cycle, run_meta=run_meta, run_evolution=run_evolution)
    try:
        previous_state = _read_status_file()
        previous_result = previous_state.get('last_result') or {}
        guard_every = int((policy_schedule or {}).get('guard_every') or DEFAULT_GUARD_EVERY)
        guard_cached = cycle > 1 and guard_every > 1 and cycle % guard_every != 0 and bool(previous_result.get('guard'))
        tick_trace('tick.before_guard', cycle=cycle, cached=guard_cached)
        guard = (previous_result.get('guard') or {}) if guard_cached else run_guard()
        tick_trace(
            'tick.after_guard',
            cycle=cycle,
            cached=guard_cached,
            guard_status=guard.get('status'),
            allow_brain_loop=guard.get('allow_brain_loop'),
            allow_meta=guard.get('allow_meta'),
            allow_evolution=guard.get('allow_evolution'),
        )
        kernel_mode = (policy_schedule or {}).get('kernel_mode') or load_kernel_mode()
        governance_enabled = is_component_enabled('governance', kernel_mode)
        observer_enabled = is_component_enabled('observer', kernel_mode)
        experiments_enabled = is_component_enabled('experiments', kernel_mode)
        maintenance_every = int((policy_schedule or {}).get('maintenance_bias_every') or DEFAULT_MAINTENANCE_EVERY)
        preferred_mode = (policy_schedule or {}).get('maintenance_mode') or 'light'
        maintenance_force_run = bool((policy_schedule or {}).get('maintenance_force_run'))
        run_maintenance_cycle = maintenance_force_run or maintenance_every <= 1 or (cycle and cycle % maintenance_every == 0)
        maintenance_mode = 'full' if maintenance_force_run else preferred_mode if run_maintenance_cycle else 'light'
        run_environment_lane = run_maintenance_cycle and (observer_enabled or governance_enabled)
        maintenance_pending = bool((policy_schedule or {}).get('maintenance_pending', False))
        maintenance_lane_status = dict((policy_schedule or {}).get('maintenance_lane_status') or _static_maintenance_lane(mode=preferred_mode, reason='maintenance cadence hold'))
        run_ai_testing = bool((policy_schedule or {}).get('run_ai_testing', False)) and observer_enabled
        ai_testing_pending = bool((policy_schedule or {}).get('ai_testing_pending', False))
        ai_testing_snapshot = dict((policy_schedule or {}).get('ai_testing_status') or load_ai_test_status())
        tick_trace(
            'tick.after_kernel_mode',
            cycle=cycle,
            governance_enabled=governance_enabled,
            observer_enabled=observer_enabled,
            experiments_enabled=experiments_enabled,
            maintenance_mode=maintenance_mode,
            run_maintenance_cycle=run_maintenance_cycle,
            maintenance_force_run=maintenance_force_run,
            run_environment_lane=run_environment_lane,
            maintenance_pending=maintenance_pending,
            run_ai_testing=run_ai_testing,
            ai_testing_pending=ai_testing_pending,
        )
        recovery_payload = {'status': 'unavailable', 'recovery_mode': False}
        recovery_every = int((policy_schedule or {}).get('recovery_every') or DEFAULT_RECOVERY_EVERY)
        recovery_cached = cycle > 1 and recovery_every > 1 and cycle % recovery_every != 0 and bool(previous_result.get('execution_recovery'))
        tick_trace('tick.before_recovery', cycle=cycle, cached=recovery_cached)
        if recovery_cached:
            recovery_payload = previous_result.get('execution_recovery') or recovery_payload
        else:
            try:
                recovery_payload = _ensure_execution_recovery_bounded(
                    fallback=previous_result.get('execution_recovery') or {'recovery_mode': True}
                )
            except Exception as exc:
                recovery_payload = {'status': 'error', 'error': str(exc), 'recovery_mode': False}
        recovery_payload = _normalize_recovery_payload(recovery_payload)
        tick_trace(
            'tick.after_recovery',
            cycle=cycle,
            cached=recovery_cached,
            recovery_status=recovery_payload.get('status'),
            recovery_mode=recovery_payload.get('recovery_mode'),
            recovery_active_count=len(recovery_payload.get('active_recovery_task_ids') or []),
            recovery_timed_out=bool(recovery_payload.get('timed_out')),
        )
        execution_priority_mode = _execution_priority_mode(
            recovery_mode=bool(recovery_payload.get('recovery_mode')),
            run_meta=run_meta,
            run_evolution=run_evolution,
        )
        global_policy_every = int((policy_schedule or {}).get('global_policy_every') or DEFAULT_GLOBAL_POLICY_EVERY)
        global_policy_due = global_policy_every <= 1 or cycle % global_policy_every == 0
        engineering_os_every = int((policy_schedule or {}).get('engineering_os_every') or DEFAULT_ENGINEERING_OS_EVERY)
        engineering_os_due = engineering_os_every <= 1 or cycle % engineering_os_every == 0
        control_layer_every = int((policy_schedule or {}).get('control_layer_every') or DEFAULT_CONTROL_LAYER_EVERY)
        control_layer_due = control_layer_every <= 1 or cycle % control_layer_every == 0
        release_ops_every = int((policy_schedule or {}).get('release_ops_every') or DEFAULT_RELEASE_OPS_EVERY)
        release_ops_due = release_ops_every <= 1 or cycle % release_ops_every == 0
        company_os_every = int((policy_schedule or {}).get('company_os_every') or DEFAULT_COMPANY_OS_EVERY)
        company_os_due = company_os_every <= 1 or cycle % company_os_every == 0
        tick_trace(
            'tick.execution_mode',
            cycle=cycle,
            execution_priority_mode=execution_priority_mode,
            inline_governance=bool((policy_schedule or {}).get('inline_governance', DEFAULT_INLINE_GOVERNANCE)),
            global_policy_due=global_policy_due,
            engineering_os_due=engineering_os_due,
            control_layer_due=control_layer_due,
            release_ops_due=release_ops_due,
            company_os_due=company_os_due,
        )
        smoke_hygiene_payload = run_smoke_hygiene(mode='auto')
        if recovery_payload.get('recovery_mode'):
            tick_trace('tick.recovery_short_circuit', cycle=cycle)
            recovery_autonomy = previous_result.get('autonomy_score') or {}
            recovery_tool_health = previous_result.get('tool_health') or {}
            result = {
                'guard': guard,
                'maintenance': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'environment_repair': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'smoke_hygiene': smoke_hygiene_payload,
                'ai_testing': {'status': 'signal-only', 'run_skipped': True, 'reason': 'execution_recovery_mode'},
                'control_layer': {'status': 'signal-only', 'reason': 'execution_recovery_mode', 'recovery': recovery_payload},
                'autonomy_score': recovery_autonomy if recovery_autonomy else {'status': 'signal-only', 'reason': 'execution_recovery_mode'},
                'tool_health': recovery_tool_health if recovery_tool_health else {'status': 'signal-only', 'reason': 'execution_recovery_mode'},
                'brain_loop': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'meta_factory': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'evolution': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'experiments': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'engineering_os': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'global_policy': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'coordination': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'release_train': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'release_operations': {'status': 'signal-only', 'reason': 'execution_recovery_mode'},
                'economics_engine': (previous_result.get('economics_engine') or {}) if previous_result.get('economics_engine') else run_economics_engine_status(),
                'company_os': {'status': 'skipped', 'reason': 'execution_recovery_mode'},
                'execution_recovery': recovery_payload,
                'execution_priority_mode': True,
                'policy_schedule': {**(policy_schedule or {}), 'maintenance_mode': maintenance_mode},
                'kernel_mode': kernel_mode,
                'smoke_hygiene': smoke_hygiene_payload,
            }
            result['tool_health_history'] = previous_result.get('tool_health_history') or {'history_count': 0, 'latest': None}
            shadow_pipeline_every = int((policy_schedule or {}).get('shadow_pipeline_every') or DEFAULT_SHADOW_PIPELINE_EVERY)
            shadow_pending_count = pending_shadow_work_count()
            run_shadow_pipeline_now = observer_enabled and (
                shadow_pending_count > 0 or shadow_pipeline_every <= 1 or cycle % shadow_pipeline_every == 0
            )
            if run_shadow_pipeline_now:
                tick_trace(
                    'tick.before_shadow_pipeline',
                    cycle=cycle,
                    cadence_every=shadow_pipeline_every,
                    pending_count=shadow_pending_count,
                    recovery_mode=True,
                )
                result['shadow_pipeline'] = run_shadow_pipeline_bridge(max_tasks=1)
                tick_trace(
                    'tick.after_shadow_pipeline',
                    cycle=cycle,
                    status=(result.get('shadow_pipeline') or {}).get('status'),
                    processed_count=(result.get('shadow_pipeline') or {}).get('processed_count'),
                    pending_count=(result.get('shadow_pipeline') or {}).get('pending_count'),
                    recovery_mode=True,
                )
            else:
                result['shadow_pipeline'] = {
                    'status': 'idle',
                    'reason': 'cadence hold',
                    'processed_count': 0,
                    'pending_count': shadow_pending_count,
                    'recovery_mode': True,
                }
                tick_trace(
                    'tick.shadow_pipeline_skipped',
                    cycle=cycle,
                    cadence_every=shadow_pipeline_every,
                    pending_count=shadow_pending_count,
                    recovery_mode=True,
                )
            tick_trace('tick.before_return', cycle=cycle, result_keys=sorted(result.keys()))
            completed = True
            return result
        result = {
            'guard': guard,
            'execution_recovery': recovery_payload,
            'execution_priority_mode': execution_priority_mode,
            'shadow_pipeline': None,
            'maintenance': None,
            'environment_repair': None,
            'smoke_hygiene': smoke_hygiene_payload,
            'ai_testing': None,
            'control_layer': None,
            'autonomy_score': None,
            'tool_health': None,
            'brain_loop': None,
            'meta_factory': None,
            'evolution': None,
            'experiments': None,
            'engineering_os': None,
            'global_policy': None,
            'policy_schedule': {**(policy_schedule or {}), 'maintenance_mode': maintenance_mode},
            'kernel_mode': kernel_mode,
        }
        tick_trace('tick.before_maintenance', cycle=cycle, maintenance_mode=maintenance_mode, run_maintenance_cycle=run_maintenance_cycle)
        result['maintenance'] = {
            **(maintenance_lane_status.get('maintenance') or {}),
            'mode': maintenance_mode,
            'run_pending': maintenance_pending,
            'run_skipped': not run_maintenance_cycle,
        }
        tick_trace('tick.after_maintenance', cycle=cycle, maintenance_status=(result.get('maintenance') or {}).get('status'))
        result['environment_repair'] = {
            **(maintenance_lane_status.get('environment_repair') or {}),
            'mode': maintenance_mode,
            'run_pending': maintenance_pending,
            'run_skipped': not run_environment_lane,
        }
        if not (observer_enabled or governance_enabled):
            result['environment_repair'] = {
                'status': 'disabled',
                'reason': 'lean_execution',
                'mode': maintenance_mode,
                'run_pending': False,
                'run_skipped': True,
            }
            tick_trace('tick.environment_repair_disabled', cycle=cycle, reason='lean_execution')
        else:
            tick_trace(
                'tick.maintenance_async',
                cycle=cycle,
                requested=run_maintenance_cycle,
                pending=maintenance_pending,
                maintenance_status=(result.get('maintenance') or {}).get('status'),
                environment_status=(result.get('environment_repair') or {}).get('status'),
            )
            if run_environment_lane:
                tick_trace('tick.environment_repair_async', cycle=cycle, requested=True, pending=maintenance_pending)
            else:
                tick_trace('tick.environment_repair_skipped', cycle=cycle, reason='maintenance cadence hold')
        if not observer_enabled:
            result['ai_testing'] = {'status': 'disabled', 'run_skipped': True, 'error_count': 0, 'failing_case_ids': [], 'signal_only': True}
            tick_trace('tick.ai_testing_disabled', cycle=cycle)
        else:
            result['ai_testing'] = {
                **ai_testing_snapshot,
                'run_skipped': not run_ai_testing,
                'run_pending': ai_testing_pending,
                'signal_only': True,
                'release_signal': ai_testing_snapshot.get('release_signal') or 'sampled_async',
                'mode': ai_testing_snapshot.get('mode') or 'sampled_async',
            }
            tick_trace(
                'tick.ai_testing_async',
                cycle=cycle,
                requested=run_ai_testing,
                pending=ai_testing_pending,
                status=(result.get('ai_testing') or {}).get('status'),
            )
        brain_loop_schedule = dict(policy_schedule or {})
        brain_loop_schedule['kernel_mode'] = kernel_mode
        brain_loop_schedule.setdefault('run_experiments', bool(run_evolution and experiments_enabled))
        capability_every = int((policy_schedule or {}).get('capability_building_every') or 0)
        brain_loop_schedule.setdefault('run_capability_building', governance_enabled and capability_every > 0 and capability_every <= 1)
        brain_loop_schedule['run_github_learning'] = bool((policy_schedule or {}).get('run_github_learning', governance_enabled))
        brain_loop_schedule['run_global_policy'] = bool((policy_schedule or {}).get('run_global_policy', governance_enabled))
        brain_loop_schedule['brain_step_budget_ms'] = int((policy_schedule or {}).get('brain_step_budget_ms') or DEFAULT_BRAIN_STEP_BUDGET_MS)
        brain_loop_schedule['brain_step_task_limit'] = int((policy_schedule or {}).get('brain_step_task_limit') or DEFAULT_BRAIN_STEP_TASK_LIMIT)
        brain_loop_schedule['brain_step_goal_scan_limit'] = int((policy_schedule or {}).get('brain_step_goal_scan_limit') or max(3, brain_loop_schedule['brain_step_task_limit'] * 2))
        brain_loop_schedule['runtime_dispatch_limit'] = brain_loop_schedule['brain_step_task_limit']
        brain_loop_schedule['min_active_goals'] = int((policy_schedule or {}).get('min_active_goals') or 1)
        brain_loop_schedule['min_active_tasks'] = int((policy_schedule or {}).get('min_active_tasks') or 1)
        brain_loop_schedule['task_engine_every'] = int((policy_schedule or {}).get('task_engine_every') or 5)
        brain_loop_schedule['brain_runtime_sync_every'] = int((policy_schedule or {}).get('brain_runtime_sync_every') or 5)
        brain_loop_schedule['goal_refresh_every'] = int((policy_schedule or {}).get('goal_refresh_every') or 5)
        brain_loop_schedule['run_github_learning'] = False
        if guard.get('allow_brain_loop', True):
            tick_trace('tick.before_brain_loop', cycle=cycle, execution_priority_mode=execution_priority_mode, brain_step_budget_ms=brain_loop_schedule['brain_step_budget_ms'], brain_step_task_limit=brain_loop_schedule['brain_step_task_limit'])
            result['brain_loop'] = run_brain_step(policy_schedule=brain_loop_schedule)
            tick_trace('tick.after_brain_loop', cycle=cycle, status=(result.get('brain_loop') or {}).get('status'), duration_ms=((result.get('brain_loop') or {}).get('step_metrics') or {}).get('duration_ms'))
        else:
            result['brain_loop'] = {'status': 'skipped', 'reason': guard.get('reasons', [])}
            tick_trace('tick.brain_loop_skipped', cycle=cycle)
        if run_meta and governance_enabled and guard.get('allow_meta', True):
            tick_trace('tick.before_meta_factory', cycle=cycle)
            response = client.post('/api/meta-factory/run')
            result['meta_factory'] = {'status_code': response.status_code, 'body': response.json()}
            tick_trace('tick.after_meta_factory', cycle=cycle, status_code=response.status_code)
        elif run_meta:
            result['meta_factory'] = {'status': 'skipped', 'reason': 'lean_execution' if not governance_enabled else guard.get('reasons', [])}
            tick_trace('tick.meta_factory_skipped', cycle=cycle)
        allow_evolution = bool(guard.get('allow_evolution', True)) and str(guard.get('status') or '').strip().lower() == 'healthy'
        if run_evolution and experiments_enabled and allow_evolution:
            tick_trace('tick.before_evolution', cycle=cycle)
            response = client.post('/api/evolution/run')
            result['evolution'] = {'status_code': response.status_code, 'body': response.json()}
            result['experiments'] = {
                'plan': plan_experiments(),
                'run': run_experiment(),
                'evaluation': evaluate_experiment(),
            }
            tick_trace('tick.after_evolution', cycle=cycle, status_code=response.status_code)
        elif run_evolution:
            reason = 'lean_execution' if not experiments_enabled else 'guard_throttled' if not allow_evolution else guard.get('reasons', [])
            result['evolution'] = {'status': 'skipped', 'reason': reason}
            result['experiments'] = {'status': 'skipped', 'reason': reason}
            tick_trace('tick.evolution_skipped', cycle=cycle, reason=str(reason))
        if execution_priority_mode:
            result['global_policy'] = {'status': 'signal-only', 'reason': 'execution_priority_mode'}
            tick_trace('tick.global_policy_signal_only', cycle=cycle)
        elif not global_policy_due:
            result['global_policy'] = {'status': 'signal-only', 'reason': 'governance cadence hold'}
            tick_trace('tick.global_policy_cached', cycle=cycle, cadence_every=global_policy_every)
        elif governance_enabled and bool((policy_schedule or {}).get('run_global_policy', True)):
            tick_trace('tick.before_global_policy', cycle=cycle)
            result['global_policy'] = run_global_policy()
            tick_trace('tick.after_global_policy', cycle=cycle, status=(result.get('global_policy') or {}).get('status'))
        else:
            result['global_policy'] = {'status': 'skipped', 'reason': 'lean_execution'}
            tick_trace('tick.global_policy_skipped', cycle=cycle)
        result['policy_schedule'] = policy_schedule or {}
        if (run_meta or run_evolution) and observer_enabled and engineering_os_due:
            tick_trace('tick.before_engineering_os', cycle=cycle)
            verification_snapshot = run_verification(refresh_control_layer=False)
            result['engineering_os'] = {
                'knowledge_graph': {
                    'module_count': ((verification_snapshot.get('code_graph') or {}).get('module_count', 0)),
                    'edge_count': ((verification_snapshot.get('code_graph') or {}).get('edge_count', 0)),
                    'layers': ((verification_snapshot.get('code_graph') or {}).get('layers', [])),
                    'status': 'pass' if ((verification_snapshot.get('code_graph') or {}).get('passed')) else 'attention',
                },
                'architecture': verification_snapshot.get('architecture') or {},
                'verification': verification_snapshot,
            }
            tick_trace('tick.after_engineering_os', cycle=cycle)
            if _risk_scan_due(cycle, risk_scan_every, verification_triggered=True):
                tick_trace('tick.before_risk_branch', cycle=cycle, source='verification')
                result['risk_branch'] = run_risk_branch(source='verification', apply_repairs=False).get('status') or {'scan_status': 'unknown'}
                risk_scan_ran = True
                tick_trace('tick.after_risk_branch', cycle=cycle, source='verification', status=(result.get('risk_branch') or {}).get('scan_status'))
        elif (run_meta or run_evolution) and observer_enabled:
            result['engineering_os'] = {'status': 'signal-only', 'reason': 'governance cadence hold'}
            tick_trace('tick.engineering_os_cached', cycle=cycle, cadence_every=engineering_os_every)
        else:
            result['engineering_os'] = {'status': 'skipped', 'reason': 'lean_execution' if not observer_enabled else 'meta-and-evolution-idle'}
            tick_trace('tick.engineering_os_skipped', cycle=cycle)
        latest_control_layer = _load_control_layer_snapshot()
        if execution_priority_mode:
            result['control_layer'] = (
                {
                    **latest_control_layer,
                    'cached': True,
                    'reason': 'execution_priority_mode',
                }
                if latest_control_layer
                else {'status': 'signal-only', 'reason': 'execution_priority_mode'}
            )
            result['patch_merge'] = {'merged': [], 'merged_count': 0, 'status': 'skipped', 'reason': 'execution_priority_mode'}
            tick_trace('tick.control_layer_cached_execution_priority', cycle=cycle)
        elif not control_layer_due:
            result['control_layer'] = (
                {
                    **latest_control_layer,
                    'cached': True,
                    'reason': 'governance cadence hold',
                }
                if latest_control_layer
                else {'status': 'signal-only', 'reason': 'governance cadence hold'}
            )
            result['patch_merge'] = {'merged': [], 'merged_count': 0, 'status': 'skipped', 'reason': 'governance cadence hold'}
            tick_trace('tick.control_layer_cached', cycle=cycle, cadence_every=control_layer_every)
        else:
            tick_trace('tick.before_control_layer', cycle=cycle)
            verification = (result.get('engineering_os') or {}).get('verification') or None
            result['control_layer'] = run_control_layer(verification_snapshot=verification)
            tick_trace('tick.after_control_layer', cycle=cycle, status=(result.get('control_layer') or {}).get('status'))
            patch_queue = (((result.get('control_layer') or {}).get('patch_system') or {}).get('queue') or {})
            if int(patch_queue.get('ready_count') or 0) > 0:
                tick_trace('tick.before_patch_merge', cycle=cycle, ready_count=int(patch_queue.get('ready_count') or 0))
                result['patch_merge'] = auto_merge_ready_submissions(limit=int(patch_queue.get('ready_count') or 1))
                result['control_layer'] = run_control_layer(verification_snapshot=verification)
                tick_trace('tick.after_patch_merge', cycle=cycle, merged_count=(result.get('patch_merge') or {}).get('merged_count'))
            else:
                result['patch_merge'] = {'merged': [], 'merged_count': 0}
                tick_trace('tick.patch_merge_skipped', cycle=cycle)
        release_ops = {
            'status': 'signal-only' if execution_priority_mode else 'disabled',
            'release_train': {'status': 'signal-only' if execution_priority_mode else 'disabled', 'blocked_patch_count': 0},
            'operations_readiness': {'runtime_ok': True, 'verification_ok': True, 'control_ok': True},
            'reason': 'execution_priority_mode' if execution_priority_mode else 'lean_execution',
        }
        if not execution_priority_mode and governance_enabled and release_ops_due:
            tick_trace('tick.before_release_operations', cycle=cycle)
            release_ops = run_release_operations_status()
            tick_trace('tick.after_release_operations', cycle=cycle, status=release_ops.get('status'))
        elif not execution_priority_mode and governance_enabled:
            release_ops = {
                'status': 'signal-only',
                'release_train': {'status': 'signal-only', 'blocked_patch_count': 0},
                'operations_readiness': {'runtime_ok': True, 'verification_ok': True, 'control_ok': True},
                'reason': 'governance cadence hold',
            }
            tick_trace('tick.release_operations_cached', cycle=cycle, cadence_every=release_ops_every)
        if execution_priority_mode:
            result['coordination'] = {'status': 'signal-only', 'reason': 'execution_priority_mode'}
            tick_trace('tick.coordination_signal_only', cycle=cycle)
        elif governance_enabled and bool((policy_schedule or {}).get('run_coordination', True)):
            tick_trace('tick.before_coordination', cycle=cycle)
            coordination_candidates = run_cross_project_coordination()
            result['coordination'] = run_coordination(
                coordination_candidates.get('selected') or [],
                limit=int((policy_schedule or {}).get('runtime_dispatch_limit') or 3),
            )
            tick_trace('tick.after_coordination', cycle=cycle, status=(result.get('coordination') or {}).get('status'))
        else:
            result['coordination'] = {'status': 'skipped', 'reason': 'lean_execution'}
            tick_trace('tick.coordination_skipped', cycle=cycle)
        if execution_priority_mode:
            result['release_train'] = {'status': 'signal-only', 'reason': 'execution_priority_mode'}
            tick_trace('tick.release_train_signal_only', cycle=cycle)
        elif governance_enabled and bool((policy_schedule or {}).get('run_release_train', True)):
            tick_trace('tick.before_release_train', cycle=cycle)
            result['release_train'] = run_release_train(
                runtime_ok=(release_ops.get('operations_readiness') or {}).get('runtime_ok', False),
                verification_ok=(release_ops.get('operations_readiness') or {}).get('verification_ok', False),
                control_ok=(release_ops.get('operations_readiness') or {}).get('control_ok', False),
                blocked_patch_count=(release_ops.get('release_train') or {}).get('blocked_patch_count', 0),
            )
            tick_trace('tick.after_release_train', cycle=cycle, status=(result.get('release_train') or {}).get('status'))
        else:
            result['release_train'] = {'status': 'skipped', 'reason': 'lean_execution'}
            tick_trace('tick.release_train_skipped', cycle=cycle)
        result['release_operations'] = release_ops
        economics_every = int((policy_schedule or {}).get('economics_every') or DEFAULT_ECONOMICS_EVERY)
        economics_cached = cycle > 1 and economics_every > 1 and cycle % economics_every != 0 and bool(previous_result.get('economics_engine'))
        tick_trace('tick.before_economics', cycle=cycle, cached=economics_cached)
        result['economics_engine'] = (previous_result.get('economics_engine') or {}) if economics_cached else run_economics_engine_status()
        tick_trace('tick.after_economics', cycle=cycle, cached=economics_cached, status=(result.get('economics_engine') or {}).get('status'))
        if execution_priority_mode:
            result['company_os'] = {'status': 'signal-only', 'reason': 'execution_priority_mode'}
            tick_trace('tick.company_os_signal_only', cycle=cycle)
        elif not company_os_due:
            result['company_os'] = {'status': 'signal-only', 'reason': 'governance cadence hold'}
            tick_trace('tick.company_os_cached', cycle=cycle, cadence_every=company_os_every)
        else:
            tick_trace('tick.before_company_os', cycle=cycle)
            result['company_os'] = run_company_os_status() if (observer_enabled or governance_enabled) else {'status': 'disabled', 'reason': 'lean_execution'}
            tick_trace('tick.after_company_os', cycle=cycle, status=(result.get('company_os') or {}).get('status'))
        autonomy_every = int((policy_schedule or {}).get('autonomy_every') or DEFAULT_AUTONOMY_EVERY)
        autonomy_cached = cycle > 1 and autonomy_every > 1 and cycle % autonomy_every != 0 and bool(previous_result.get('autonomy_score'))
        tick_trace('tick.before_autonomy_score', cycle=cycle, cached=autonomy_cached)
        result['autonomy_score'] = (previous_result.get('autonomy_score') or {}) if autonomy_cached else run_autonomy_score()
        tick_trace('tick.after_autonomy_score', cycle=cycle, cached=autonomy_cached, autonomy_stage=(result.get('autonomy_score') or {}).get('stage'))
        tool_health_every = int((policy_schedule or {}).get('tool_health_every') or DEFAULT_TOOL_HEALTH_EVERY)
        tool_health_cached = cycle > 1 and tool_health_every > 1 and cycle % tool_health_every != 0 and bool(previous_result.get('tool_health'))
        tick_trace('tick.before_tool_health', cycle=cycle, cached=tool_health_cached)
        result['tool_health'] = (previous_result.get('tool_health') or {}) if tool_health_cached else run_tool_health_audit()
        result['tool_health_history'] = append_tool_health_history(result['tool_health']) if not tool_health_cached else previous_result.get('tool_health_history')
        tick_trace('tick.after_tool_health', cycle=cycle, cached=tool_health_cached, status=(result.get('tool_health') or {}).get('status'))
        shadow_pipeline_every = int((policy_schedule or {}).get('shadow_pipeline_every') or DEFAULT_SHADOW_PIPELINE_EVERY)
        shadow_pending_count = pending_shadow_work_count()
        run_shadow_pipeline_now = observer_enabled and (
            shadow_pending_count > 0 or shadow_pipeline_every <= 1 or cycle % shadow_pipeline_every == 0
        )
        if run_shadow_pipeline_now:
            tick_trace('tick.before_shadow_pipeline', cycle=cycle, cadence_every=shadow_pipeline_every, pending_count=shadow_pending_count, recovery_mode=False)
            result['shadow_pipeline'] = run_shadow_pipeline_bridge(max_tasks=1)
            tick_trace(
                'tick.after_shadow_pipeline',
                cycle=cycle,
                status=(result.get('shadow_pipeline') or {}).get('status'),
                processed_count=(result.get('shadow_pipeline') or {}).get('processed_count'),
                pending_count=(result.get('shadow_pipeline') or {}).get('pending_count'),
                recovery_mode=False,
            )
        else:
            result['shadow_pipeline'] = {
                'status': 'idle',
                'reason': 'cadence hold',
                'processed_count': 0,
                'pending_count': shadow_pending_count,
            }
            tick_trace('tick.shadow_pipeline_skipped', cycle=cycle, cadence_every=shadow_pipeline_every, pending_count=shadow_pending_count, recovery_mode=False)
        tick_trace('tick.before_return', cycle=cycle, result_keys=sorted(result.keys()))
        completed = True
        return result
    except Exception as exc:
        tick_trace('tick.exception', cycle=cycle, error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        tick_trace('tick.finally', cycle=cycle, completed=completed)
        _stop_tick_watchdog(cycle, watchdog_handle, completed=completed)

def run_forever(interval: float, meta_every: int, evolution_every: int) -> int:
    pid = os.getpid()
    now = utc()
    epoch_state = _update_runtime_epoch(pid=pid, started_at=now, cycle=0, last_tick_at=now, task_pipeline_alive=True)
    epoch_id = epoch_state.get('epoch_id')
    bootstrap_log(f'bootstrap pid={pid} interval={interval}s meta_every={meta_every} evolution_every={evolution_every}')
    bootstrap_log('startup step=pidfile')
    _atomic_write_text(PID_PATH, str(pid), encoding='utf-8')
    bootstrap_log('startup step=write_status')
    write_status(
        status='running',
        pid=pid,
        epoch_id=epoch_id,
        started_at=now,
        heartbeat_at=now,
        last_tick_at=None,
        cycle=0,
        last_result=None,
        last_error=None,
        interval_seconds=interval,
        meta_every=meta_every,
        evolution_every=evolution_every,
    )
    write_status_cache(None, cycle=0, interval=interval, meta_every=meta_every, evolution_every=evolution_every, policy_schedule={'meta_every': meta_every, 'evolution_every': evolution_every}, last_error=None)
    bootstrap_log('startup step=status_cache')
    try:
        publish_factory_state()
        bootstrap_log('startup step=factory_state')
    except Exception as exc:
        bootstrap_err(f'startup publish_factory_state failed: {type(exc).__name__}: {exc}')
        bootstrap_log('startup step=factory_state_failed')
    try:
        publish_ai_runtime_state()
        bootstrap_log('startup step=ai_runtime_state')
    except Exception as exc:
        bootstrap_err(f'startup publish_ai_runtime_state failed: {type(exc).__name__}: {exc}')
        bootstrap_log('startup step=ai_runtime_state_failed')
    try:
        append_event(
        'daemon.started',
        source='factory_daemon',
        summary=f'Factory daemon started pid={pid}',
        payload={'pid': pid, 'interval_seconds': interval, 'meta_every': meta_every, 'evolution_every': evolution_every},
        refs={'status_path': str(STATUS_PATH), 'factory_state_path': str(DATA / 'factory_state.json')},
    )
    except Exception as exc:
        bootstrap_err(f'startup append_event failed: {type(exc).__name__}: {exc}')
        bootstrap_log('startup step=event_log_failed')
    else:
        bootstrap_log('startup step=event_log')
    try:
        _write_continuity_durable_checkpoint(epoch_id=epoch_id, pid=pid, cycle=0, last_tick_at=now)
        bootstrap_log('startup step=continuity_durable_checkpoint')
    except Exception as exc:
        bootstrap_err(f'startup continuity durable checkpoint failed: {type(exc).__name__}: {exc}')
        bootstrap_log('startup step=continuity_durable_checkpoint_failed')
    log(f'Factory daemon started pid={pid} interval={interval}s')
    bootstrap_log('startup step=runtime_log')
    cycle = 0
    previous_state = _read_status_file()
    self_model_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='self_model_cycle')
    self_model_future: concurrent.futures.Future | None = None
    ai_testing_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='ai_testing_cycle')
    ai_testing_future: concurrent.futures.Future | None = None
    maintenance_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='maintenance_cycle')
    maintenance_future: concurrent.futures.Future | None = None
    last_self_model_summary = _self_model_summary_from_state(_read_status_file())
    last_ai_testing_status = {
        **load_ai_test_status(),
        'release_signal': (load_ai_test_status().get('release_signal') or 'sampled_async'),
        'mode': (load_ai_test_status().get('mode') or 'sampled_async'),
        'signal_only': True,
        'run_pending': False,
    }
    last_maintenance_lane = _static_maintenance_lane(mode='light', reason='maintenance cadence hold', pending=False)
    try:
        while True:
            risk_scan_ran = False
            cycle += 1
            policy_state = _load_policy_state()
            schedule = _policy_schedule(policy_state, meta_every, evolution_every)
            maintenance_pressure = _maintenance_pressure_overview(previous_state)
            maintenance_force_run = bool(maintenance_pressure.get('force_full'))
            if maintenance_force_run:
                schedule['maintenance_mode'] = 'full'
                schedule['maintenance_force_run'] = True
                schedule['maintenance_pressure'] = maintenance_pressure
            else:
                schedule['maintenance_force_run'] = False
                schedule['maintenance_pressure'] = maintenance_pressure
            effective_meta_every = schedule.get('meta_every', meta_every)
            effective_evolution_every = schedule.get('evolution_every', evolution_every)
            inline_governance = bool(schedule.get('inline_governance', DEFAULT_INLINE_GOVERNANCE))
            run_meta = inline_governance and effective_meta_every > 0 and cycle % effective_meta_every == 0
            run_evolution = inline_governance and effective_evolution_every > 0 and cycle % effective_evolution_every == 0
            schedule['run_experiments'] = run_evolution
            schedule['inline_governance'] = inline_governance
            schedule['cycle'] = cycle
            capability_every = int(schedule.get('capability_building_every') or 0)
            schedule['run_capability_building'] = capability_every > 0 and (capability_every <= 1 or cycle % capability_every == 0)
            goal_generation_every = int(schedule.get('goal_generation_every') or 5)
            schedule['allow_goal_generation'] = goal_generation_every > 0 and (goal_generation_every <= 1 or cycle % goal_generation_every == 0)
            risk_scan_every = int(schedule.get('risk_scan_every') or 5)
            schedule['risk_scan_every'] = risk_scan_every
            harvested_ai_testing, ai_testing_future = _collect_ai_testing_summary(ai_testing_future)
            if harvested_ai_testing is not None:
                last_ai_testing_status = harvested_ai_testing
            harvested_maintenance_lane, maintenance_future = _collect_maintenance_lane(maintenance_future)
            if harvested_maintenance_lane is not None:
                last_maintenance_lane = harvested_maintenance_lane
            ai_testing_every = int(schedule.get('ai_testing_every') or DEFAULT_AI_TESTING_EVERY)
            schedule['run_ai_testing'] = ai_testing_every <= 1 or cycle % ai_testing_every == 0 or last_ai_testing_status.get('status') == 'missing'
            schedule['ai_testing_status'] = last_ai_testing_status
            schedule['ai_testing_pending'] = bool(ai_testing_future is not None and not ai_testing_future.done())
            schedule['maintenance_lane_status'] = last_maintenance_lane
            schedule['maintenance_pending'] = bool(maintenance_future is not None and not maintenance_future.done())
            schedule['maintenance_force_run'] = bool(schedule.get('maintenance_force_run') or maintenance_force_run)
            cycle_started_monotonic = time.perf_counter()
            harvested_summary, self_model_future = _collect_self_model_summary(self_model_future)
            if harvested_summary is not None:
                last_self_model_summary = harvested_summary
            try:
                cycle_started_at = utc()
                write_status(
                    status='running',
                    pid=os.getpid(),
                    epoch_id=epoch_id,
                    cycle=cycle,
                    heartbeat_at=cycle_started_at,
                    last_cycle_started_at=cycle_started_at,
                    meta_every=effective_meta_every,
                    evolution_every=effective_evolution_every,
                    last_error=None,
                )
                tick_trace('run_forever.before_tick', cycle=cycle, run_meta=run_meta, run_evolution=run_evolution)
                result = tick(run_meta=run_meta, run_evolution=run_evolution, policy_schedule=schedule)
                risk_branch = result.get('risk_branch') or {}
                if isinstance(risk_branch, dict):
                    branch_status = str(risk_branch.get('scan_status') or risk_branch.get('status') or '').strip().lower()
                    risk_scan_ran = branch_status not in {'', 'skipped', 'signal-only'}
                risk_scan_every = int(schedule.get('risk_scan_every') or 5)
                kernel_mode = schedule.get('kernel_mode') or load_kernel_mode()
                if is_component_enabled('observer', kernel_mode) and bool(schedule.get('run_ai_testing')):
                    ai_testing_future = _schedule_ai_testing_summary(ai_testing_executor, ai_testing_future)
                    result['ai_testing'] = {
                        **(result.get('ai_testing') or {}),
                        'run_pending': True,
                        'queued_async': True,
                        'signal_only': True,
                        'release_signal': ((result.get('ai_testing') or {}).get('release_signal') or 'sampled_async'),
                        'mode': ((result.get('ai_testing') or {}).get('mode') or 'sampled_async'),
                    }
                    tick_trace('tick.ai_testing_enqueued', cycle=cycle, future_done=bool(ai_testing_future.done()))
                if bool(schedule.get('maintenance_force_run')) or (bool(schedule.get('maintenance_bias_every')) and bool(schedule.get('cycle')) and (schedule.get('maintenance_bias_every') <= 1 or cycle % int(schedule.get('maintenance_bias_every')) == 0)):
                    maintenance_future = _schedule_maintenance_lane(
                        maintenance_executor,
                        maintenance_future,
                        mode=str(schedule.get('maintenance_mode') or 'light'),
                        run_environment_lane=bool(is_component_enabled('observer', kernel_mode) or is_component_enabled('governance', kernel_mode)),
                        observer_enabled=is_component_enabled('observer', kernel_mode),
                        governance_enabled=is_component_enabled('governance', kernel_mode),
                    )
                    result['maintenance'] = {
                        **(result.get('maintenance') or {}),
                        'run_pending': True,
                        'queued_async': True,
                    }
                    result['environment_repair'] = {
                        **(result.get('environment_repair') or {}),
                        'run_pending': True,
                        'queued_async': True,
                    }
                    tick_trace('tick.maintenance_enqueued', cycle=cycle, future_done=bool(maintenance_future.done()))
                tick_trace('run_forever.after_tick', cycle=cycle, execution_priority_mode=result.get('execution_priority_mode'))
                risk_scan_ran = bool(result.get('risk_scan_ran'))
                previous_state = _read_status_file()
                ai_failure = _ai_testing_failure_state(result.get('ai_testing') or {}, previous_state)
                if result.get('ai_testing') is not None:
                    result['ai_testing'] = {**(result.get('ai_testing') or {}), **ai_failure}
                execution_priority_mode = bool(result.get('execution_priority_mode'))
                tick_trace('tick.before_self_model', cycle=cycle)
                harvested_summary, self_model_future = _collect_self_model_summary(self_model_future)
                self_model_harvested = harvested_summary is not None
                if harvested_summary is not None:
                    last_self_model_summary = harvested_summary
                if is_component_enabled('observer', kernel_mode):
                    self_model_future = _schedule_self_model_summary(
                        self_model_executor,
                        self_model_future,
                        trigger='cycle_end',
                    )
                    self_model_summary = last_self_model_summary
                    tick_trace(
                        'tick.self_model_enqueued',
                        cycle=cycle,
                        harvested=self_model_harvested,
                        future_done=bool(self_model_future.done()),
                    )
                else:
                    self_model_summary = _static_self_model_summary(
                        health='disabled',
                        goal='interaction_only' if kernel_mode.get('profile') == 'interaction_only' else 'lean_execution',
                        mode='interaction_only' if kernel_mode.get('profile') == 'interaction_only' else 'lean_execution',
                        priority='normal',
                        summary='Observer loop disabled by interaction only profile.' if kernel_mode.get('profile') == 'interaction_only' else 'Observer loop disabled by lean execution profile.',
                        trigger='cycle_end',
                    )
                    self_model_harvested = False
                tick_trace('tick.after_self_model', cycle=cycle, self_model_mode=self_model_summary.get('mode'), harvested=self_model_harvested)
                result['self_model'] = self_model_summary
                result['risk_scan_ran'] = risk_scan_ran
                if not risk_scan_ran:
                    if _risk_scan_due(cycle, risk_scan_every, verification_triggered=False):
                        tick_trace('tick.before_risk_branch', cycle=cycle, source='daemon_tick', cadence_every=risk_scan_every)
                        result['risk_branch'] = run_risk_branch(source='daemon_tick', apply_repairs=False).get('status') or {'scan_status': 'unknown'}
                        tick_trace('tick.after_risk_branch', cycle=cycle, source='daemon_tick', status=(result.get('risk_branch') or {}).get('scan_status'))
                    else:
                        result['risk_branch'] = {
                            'scan_status': 'skipped',
                            'source': 'daemon_tick',
                            'reason': 'cadence hold',
                            'cadence_every': risk_scan_every,
                        }
                compact_result = _compact_last_result(result)
                self_model_attention = bool(self_model_harvested and self_model_summary.get('mode') == 'operator_attention')
                daemon_status_value = 'running' if kernel_mode.get('profile') in {'lean_execution', 'interaction_only'} else 'operator_attention' if ai_failure.get('alert') or self_model_attention else 'running'
                tick_trace('tick.before_status_write', cycle=cycle)
                write_status(
                    status=daemon_status_value,
                    pid=os.getpid(),
                    epoch_id=epoch_id,
                    cycle=cycle,
                    last_tick_at=utc(),
                    heartbeat_at=utc(),
                    meta_every=effective_meta_every,
                    evolution_every=effective_evolution_every,
                    last_error=None,
                    consecutive_error_count=0,
                    restart_requested=False,
                    last_traceback=None,
                    last_result=compact_result,
                    ai_testing_consecutive_failures=ai_failure.get('consecutive_failures'),
                    ai_testing_alert=ai_failure.get('alert'),
                    ai_testing_threshold=ai_failure.get('threshold'),
                    last_self_model_at=self_model_summary.get('updated_at'),
                    last_self_model_goal=self_model_summary.get('goal'),
                    last_self_model_mode=self_model_summary.get('mode'),
                    last_self_model_health=self_model_summary.get('health'),
                    last_self_model_blockers=self_model_summary.get('blockers'),
                    last_self_model_action_count=self_model_summary.get('executed_action_count'),
                    last_self_model_trigger=self_model_summary.get('trigger'),
                )
                status_after_write = _read_status_file()
                epoch_state = _update_runtime_epoch(
                    pid=os.getpid(),
                    started_at=now,
                    cycle=cycle,
                    last_tick_at=status_after_write.get('last_tick_at'),
                    task_pipeline_alive=True,
                )
                epoch_id = epoch_state.get('epoch_id')
                tick_trace('tick.after_status_write', cycle=cycle)
                tick_trace('tick.before_status_cache', cycle=cycle)
                write_status_cache(result, cycle=cycle, interval=interval, meta_every=effective_meta_every, evolution_every=effective_evolution_every, policy_schedule=schedule, last_error=None)
                tick_trace('tick.after_status_cache', cycle=cycle)
                daemon_state = _read_status_file()
                status_cache = _status_cache_payload(result, cycle=cycle, interval=interval, meta_every=effective_meta_every, evolution_every=effective_evolution_every, policy_schedule=schedule, last_error=None)
                publish_every = int(schedule.get('publish_every') or DEFAULT_PUBLISH_EVERY)
                should_publish_runtime = cycle <= 1 or publish_every <= 1 or cycle % publish_every == 0
                tick_trace('tick.before_factory_state', cycle=cycle, should_publish_runtime=should_publish_runtime)
                if should_publish_runtime:
                    factory_state = publish_factory_state(daemon_state=daemon_state, status_cache=status_cache, last_result=compact_result)
                    tick_trace('tick.after_factory_state', cycle=cycle, should_publish_runtime=should_publish_runtime)
                    _write_watchdog_snapshot(daemon_state=daemon_state, result=result, policy_schedule=schedule, last_error=None)
                    tick_trace('tick.after_watchdog_snapshot', cycle=cycle, should_publish_runtime=should_publish_runtime)
                    publish_ai_runtime_state()
                    tick_trace('tick.after_ai_runtime_state', cycle=cycle, should_publish_runtime=should_publish_runtime)
                    refresh_identity_kernel()
                    tick_trace('tick.after_identity_refresh', cycle=cycle, should_publish_runtime=should_publish_runtime)
                    _write_continuity_durable_checkpoint(
                        epoch_id=epoch_id,
                        pid=os.getpid(),
                        cycle=cycle,
                        last_tick_at=daemon_state.get('last_tick_at'),
                    )
                    tick_trace('tick.after_continuity_durable_checkpoint', cycle=cycle, should_publish_runtime=should_publish_runtime)
                else:
                    factory_state = {}
                    tick_trace('tick.factory_state_skipped', cycle=cycle, should_publish_runtime=should_publish_runtime)
                append_event(
                    'daemon.tick',
                    source='factory_daemon',
                    summary=f'tick={cycle} meta={run_meta} evolution={run_evolution} daemon={daemon_status_value}',
                    payload={
                        'cycle': cycle,
                        'run_meta': run_meta,
                        'run_evolution': run_evolution,
                        'meta_every': effective_meta_every,
                        'evolution_every': effective_evolution_every,
                        'ai_testing_alert': ai_failure.get('alert'),
                        'ai_testing_failures': ai_failure.get('consecutive_failures'),
                        'control_status': (status_cache.get('control_layer') or {}).get('status'),
                        'self_model_goal': self_model_summary.get('goal'),
                        'self_model_mode': self_model_summary.get('mode'),
                        'self_model_blocker_count': self_model_summary.get('blocker_count'),
                        'factory_consistency': (factory_state.get('consistency') or {}).get('status'),
                    },
                    refs={
                        'factory_state_path': str(DATA / 'factory_state.json'),
                        'status_cache_path': str(STATUS_CACHE_PATH),
                        'self_model_runtime_path': str(DATA / 'self_model_runtime.json'),
                    },
                )
                if self_model_summary.get('blocker_count') or self_model_summary.get('mode') not in {'steady_state', 'normal_execution', 'recovery', 'execution_priority_mode', 'lean_execution', 'interaction_only'}:
                    append_event(
                        'self_model.tick',
                        source='factory_daemon',
                        summary=f"self_model goal={self_model_summary.get('goal')} mode={self_model_summary.get('mode')}",
                        payload={
                            'cycle': cycle,
                            'health': self_model_summary.get('health'),
                            'goal': self_model_summary.get('goal'),
                            'mode': self_model_summary.get('mode'),
                            'priority': self_model_summary.get('priority'),
                            'blockers': self_model_summary.get('blockers') or [],
                            'executed_actions': self_model_summary.get('executed_actions') or [],
                        },
                        refs={'self_model_runtime_path': str(DATA / 'self_model_runtime.json')},
                    )
                if not execution_priority_mode and should_emit_self_report(cycle=cycle, ai_testing_alert=bool(ai_failure.get('alert')), control_status=daemon_status_value):
                    report = run_factory_self_report(trigger='daemon', cycle=cycle, send_notifications=True, write_opencode=True)
                    report_schedule = report.get('report_schedule') or {}
                    write_status(
                        last_self_report_at=report.get('reported_at'),
                        last_self_report_next_at=report_schedule.get('next_report_at'),
                        last_self_report_interval_minutes=report_schedule.get('interval_minutes'),
                        last_self_report_mode=report_schedule.get('mode'),
                        last_self_report_kind=report_schedule.get('fired_report_kind'),
                        last_self_report_next_kind=report_schedule.get('next_report_kind'),
                        last_self_report_overall_status=report.get('overall_status'),
                        last_self_report_notifications={'serverchan': report.get('delivery', {}).get('serverchan', {}), 'qq_mail': report.get('delivery', {}).get('qq_mail', {})},
                    )
                    publish_factory_state()
                    refresh_identity_kernel()
                    append_event(
                        'self_report.emitted',
                        source='factory_daemon',
                        summary=f"self_report overall={report.get('overall_status')}",
                        payload={
                            'cycle': cycle,
                            'overall_status': report.get('overall_status'),
                            'serverchan_delivered': report.get('delivery', {}).get('serverchan', {}).get('delivered'),
                            'qq_mail_delivered': report.get('delivery', {}).get('qq_mail', {}).get('delivered'),
                        },
                        refs={'report_path': str(DATA / 'factory_self_report.json')},
                    )
                    log(f"self_report cycle={cycle} overall={report.get('overall_status')} serverchan_delivered={report.get('delivery', {}).get('serverchan', {}).get('delivered')} qq_mail_delivered={report.get('delivery', {}).get('qq_mail', {}).get('delivered')}")
                toyos_completion_notification = _maybe_emit_toyos_completion_notification(cycle=cycle)
                if toyos_completion_notification.get('status') in {'attempted', 'delivered'}:
                    notification = toyos_completion_notification.get('notification') or {}
                    write_status(
                        last_toyos_bundle_notification_at=notification.get('last_attempt_at') or notification.get('delivered_at'),
                        last_toyos_bundle_notification_status=toyos_completion_notification.get('status'),
                        last_toyos_bundle_notification_delivery=(notification.get('delivery') or {}).get('qq_mail', {}),
                    )
                    append_event(
                        'toyos_bundle.notification',
                        source='factory_daemon',
                        summary=f"toyos bundle notification status={toyos_completion_notification.get('status')}",
                        payload={
                            'cycle': cycle,
                            'status': toyos_completion_notification.get('status'),
                            'completed_count': (toyos_completion_notification.get('progress') or {}).get('completed_count'),
                            'goal_count': (toyos_completion_notification.get('progress') or {}).get('goal_count'),
                            'qq_mail_delivered': ((notification.get('delivery') or {}).get('qq_mail') or {}).get('delivered'),
                        },
                        refs={'notification_path': str(TOYOS_GOAL_COMPLETION_NOTIFY_PATH)},
                    )
                    log(f"toyos_bundle_notification cycle={cycle} status={toyos_completion_notification.get('status')} qq_mail_delivered={((notification.get('delivery') or {}).get('qq_mail') or {}).get('delivered')}")
                metaforge_soak_milestones = _maybe_emit_metaforge_soak_milestone_notification(cycle=cycle, daemon_started_at=now)
                delivered_events = [item for item in (metaforge_soak_milestones.get('events') or []) if item.get('status') in {'attempted', 'delivered'}]
                if delivered_events:
                    latest_event = delivered_events[-1]
                    notification = latest_event.get('notification') or {}
                    write_status(
                        last_metaforge_milestone_notification_at=notification.get('last_attempt_at') or notification.get('delivered_at'),
                        last_metaforge_milestone_notification_status=latest_event.get('status'),
                        last_metaforge_milestone_notification_hours=latest_event.get('milestone_hours'),
                        last_metaforge_milestone_notification_delivery=(notification.get('delivery') or {}).get('qq_mail', {}),
                    )
                    append_event(
                        'metaforge_milestone.notification',
                        source='factory_daemon',
                        summary=f"metaforge milestone={latest_event.get('milestone_hours')}h status={latest_event.get('status')}",
                        payload={
                            'cycle': cycle,
                            'milestone_hours': latest_event.get('milestone_hours'),
                            'status': latest_event.get('status'),
                            'uptime_hours': (metaforge_soak_milestones.get('runtime') or {}).get('uptime_hours'),
                            'qq_mail_delivered': ((notification.get('delivery') or {}).get('qq_mail') or {}).get('delivered'),
                        },
                        refs={'notification_path': str(METAFORGE_SOAK_MILESTONE_NOTIFY_PATH)},
                    )
                    log(
                        f"metaforge_milestone_notification cycle={cycle} milestone={latest_event.get('milestone_hours')}h "
                        f"status={latest_event.get('status')} qq_mail_delivered={((notification.get('delivery') or {}).get('qq_mail') or {}).get('delivered')}"
                    )
                log(f'tick={cycle} meta={run_meta} evolution={run_evolution} execution_priority={execution_priority_mode} meta_every={effective_meta_every} evolution_every={effective_evolution_every} ai_testing_alert={ai_failure.get("alert")} ai_testing_failures={ai_failure.get("consecutive_failures")}')
            except Exception as exc:
                tick_trace('run_forever.tick_exception', cycle=cycle, error_type=type(exc).__name__, error=str(exc))
                previous_state = _read_status_file()
                consecutive_error_count = int(previous_state.get('consecutive_error_count', 0) or 0) + 1
                traceback_text = traceback.format_exc()
                restart_requested = consecutive_error_count >= DAEMON_ERROR_RESTART_THRESHOLD
                write_status(
                    status='error',
                    pid=os.getpid(),
                    epoch_id=epoch_id,
                    cycle=cycle,
                    last_error=str(exc),
                    last_tick_at=utc(),
                    heartbeat_at=utc(),
                    consecutive_error_count=consecutive_error_count,
                    restart_requested=restart_requested,
                    last_traceback=traceback_text,
                )
                failure_kernel_mode = schedule.get('kernel_mode') or load_kernel_mode()
                harvested_summary, self_model_future = _collect_self_model_summary(self_model_future)
                if harvested_summary is not None:
                    last_self_model_summary = harvested_summary
                if is_component_enabled('observer', failure_kernel_mode):
                    self_model_future = _schedule_self_model_summary(
                        self_model_executor,
                        self_model_future,
                        trigger='failure',
                    )
                    self_model_summary = last_self_model_summary
                    append_event(
                        'self_model.failure_enqueued',
                        source='factory_daemon',
                        summary='Queued asynchronous self-model review after daemon failure.',
                        payload={'cycle': cycle, 'trigger': 'failure'},
                        refs={'self_model_runtime_path': str(DATA / 'self_model_runtime.json')},
                    )
                else:
                    self_model_summary = _static_self_model_summary(
                        health='disabled',
                        goal='lean_execution',
                        mode='lean_execution',
                        priority='normal',
                        summary='Observer loop disabled by lean execution profile.',
                        trigger='failure',
                    )
                write_status(
                    epoch_id=epoch_id,
                    last_self_model_at=self_model_summary.get('updated_at'),
                    last_self_model_goal=self_model_summary.get('goal'),
                    last_self_model_mode=self_model_summary.get('mode'),
                    last_self_model_health=self_model_summary.get('health'),
                    last_self_model_blockers=self_model_summary.get('blockers'),
                    last_self_model_action_count=self_model_summary.get('executed_action_count'),
                    last_self_model_trigger=self_model_summary.get('trigger'),
                )
                write_status_cache({'self_model': self_model_summary}, cycle=cycle, interval=interval, meta_every=effective_meta_every, evolution_every=effective_evolution_every, policy_schedule=schedule, last_error=str(exc))
                daemon_state = _read_status_file()
                publish_factory_state()
                _write_watchdog_snapshot(daemon_state=daemon_state, result=None, policy_schedule=schedule, last_error=str(exc))
                publish_ai_runtime_state()
                refresh_identity_kernel()
                append_event(
                    'daemon.error',
                    source='factory_daemon',
                    summary=f'{type(exc).__name__}: {exc}',
                    payload={'cycle': cycle, 'error_type': type(exc).__name__, 'error': str(exc), 'consecutive_error_count': consecutive_error_count, 'restart_requested': restart_requested},
                    severity='error',
                    refs={'status_path': str(STATUS_PATH), 'status_cache_path': str(STATUS_CACHE_PATH)},
                )
                log(f'error tick={cycle}: {type(exc).__name__}: {exc}')
                bootstrap_err(f'tick={cycle} {type(exc).__name__}: {exc}\n{traceback_text}')
            sleep_seconds = max(0.0, float(interval) - (time.perf_counter() - cycle_started_monotonic))
            if sleep_seconds:
                time.sleep(sleep_seconds)
    finally:
        self_model_executor.shutdown(wait=False, cancel_futures=True)
        ai_testing_executor.shutdown(wait=False, cancel_futures=True)
        maintenance_executor.shutdown(wait=False, cancel_futures=True)
        write_status(status='stopped', pid=os.getpid(), epoch_id=epoch_id, stopped_at=utc())
        publish_factory_state()
        publish_ai_runtime_state()
        refresh_identity_kernel()
        append_event(
            'daemon.stopped',
            source='factory_daemon',
            summary=f'Factory daemon stopped pid={os.getpid()}',
            payload={'pid': os.getpid()},
            refs={'status_path': str(STATUS_PATH)},
        )
        if PID_PATH.exists():
            PID_PATH.unlink()
        log('Factory daemon stopped')

def main() -> int:
    parser = argparse.ArgumentParser(description='Resident factory daemon')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--meta-every', type=int, default=5)
    parser.add_argument('--evolution-every', type=int, default=10)
    args = parser.parse_args()
    if args.status:
        print(json.dumps(daemon_status(), ensure_ascii=False, indent=2))
        return 0
    return run_forever(interval=args.interval, meta_every=args.meta_every, evolution_every=args.evolution_every)


if __name__ == '__main__':
    bootstrap_log('factory_daemon.py main entry')
    raise SystemExit(main())













