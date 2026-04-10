from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json
from tools.kernel_mode import load_kernel_mode

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FACTORY = ROOT / "factory"
POLICY = DATA / "guard_policy.json"
TASKS = DATA / "tasks.json"
CORE_MESSAGES = DATA / "core_messages.json"
PLATFORMS = FACTORY / "platform_registry.json"
USAGE = DATA / "usage_tracker.json"
HEALTH = DATA / "health_status.json"
STATE = DATA / "guard_state.json"
MIN_RATIO_SAMPLE_CALLS = 5


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def load_policy() -> dict[str, Any]:
    default = {
        'max_tasks_per_hour': 20,
        'max_platforms_per_day': 3,
        'max_active_tasks': 8,
        'max_queue_tasks': 20,
        'max_reasoning_model_ratio': 0.6,
        'max_strong_model_ratio': 0.15,
        'max_error_escalations': 5,
        'protect_core_paths': [str(ROOT / 'app'), str(ROOT / 'runtime'), str(ROOT / 'tools'), str(ROOT / 'brain'), str(ROOT / 'state')],
        'workspace_paths': [str(ROOT / 'workspace'), str(ROOT / 'factory' / 'workspace')],
        'deny_learning_keywords': ['miner', 'botnet', 'ransomware', 'keylogger', 'exploit', 'payload', 'credential stealer'],
    }
    current = _load_json(POLICY, default)
    merged = dict(default)
    merged.update(current)
    return merged


def _is_internal_runtime_task(task: dict[str, Any]) -> bool:
    scheduler_hint = task.get('scheduler_hint') or {}
    scheduled_by = str(task.get('scheduled_by') or scheduler_hint.get('scheduled_by') or '').strip().lower()
    return scheduled_by.startswith('runtime.') or scheduled_by in {'brain-loop', 'factory-daemon', 'codex-control'}


def _task_metrics(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    last_hour = now - timedelta(hours=1)
    active_statuses = {'queued', 'planning', 'running', 'waiting_approval'}
    terminal_statuses = {'completed', 'failed', 'timed_out', 'cancelled'}
    active = [task for task in tasks if task.get('status') in active_statuses]
    queued = [task for task in tasks if task.get('status') == 'queued']
    recent = []
    ignored_internal_terminal = []
    for task in tasks:
        created = _parse_time(task.get('created_at'))
        if not created or created < last_hour:
            continue
        status = str(task.get('status') or '').strip().lower()
        if _is_internal_runtime_task(task) and status in terminal_statuses:
            ignored_internal_terminal.append(task.get('id'))
            continue
        recent.append(task)
    return {
        'total': len(tasks),
        'active': len(active),
        'queued': len(queued),
        'created_last_hour': len(recent),
        'ignored_internal_terminal_last_hour': len([item for item in ignored_internal_terminal if item]),
    }


def _platform_metrics(platforms: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    last_day = now - timedelta(days=1)
    recent = []
    for platform in platforms:
        created = _parse_time(platform.get('created_at'))
        if created and created >= last_day:
            recent.append(platform)
    return {
        'total': len(platforms),
        'created_last_day': len(recent),
    }


def _usage_metrics() -> dict[str, Any]:
    usage = _load_json(
        USAGE,
        {
            'cheap_calls': 0,
            'reasoning_calls': 0,
            'strong_calls': 0,
            'reasoning_ratio': 0.0,
            'strong_ratio': 0.0,
            'reasoning_allowed': True,
            'strong_allowed': True,
        },
    )
    recent_window = usage.get('recent_window') or {}
    recent_total_calls = int(recent_window.get('total_calls', 0) or 0)
    min_ratio_sample_calls = int(usage.get('ratio_sample_min_calls', MIN_RATIO_SAMPLE_CALLS) or MIN_RATIO_SAMPLE_CALLS)
    use_recent_window = recent_total_calls >= min_ratio_sample_calls
    usage['recent_window_sample_sufficient'] = use_recent_window
    usage['ratio_sample_min_calls'] = min_ratio_sample_calls
    if use_recent_window:
        usage['recent_window_hours'] = int(recent_window.get('hours', 1) or 1)
        usage['reasoning_ratio'] = float(recent_window.get('reasoning_ratio', usage.get('reasoning_ratio', 0.0)) or 0.0)
        usage['strong_ratio'] = float(recent_window.get('strong_ratio', usage.get('strong_ratio', 0.0)) or 0.0)
        usage['cheap_calls'] = int(recent_window.get('cheap_calls', usage.get('cheap_calls', 0)) or 0)
        usage['reasoning_calls'] = int(recent_window.get('reasoning_calls', usage.get('reasoning_calls', 0)) or 0)
        usage['strong_calls'] = int(recent_window.get('strong_calls', usage.get('strong_calls', 0)) or 0)
        usage['total_calls'] = recent_total_calls
    else:
        usage['reasoning_ratio'] = float(usage.get('effective_reasoning_ratio', usage.get('reasoning_ratio', 0.0)) or 0.0)
        usage['strong_ratio'] = float(usage.get('effective_strong_ratio', usage.get('strong_ratio', 0.0)) or 0.0)
        usage['total_calls'] = int(usage.get('total_calls', 0) or 0)
    return usage


def _message_metrics(messages: list[dict[str, Any]]) -> dict[str, Any]:
    open_errors = [item for item in messages if item.get('status', 'open') == 'open' and item.get('severity') == 'error']
    open_warnings = [item for item in messages if item.get('status', 'open') == 'open' and item.get('severity') == 'warning']
    return {
        'open_errors': len(open_errors),
        'open_warnings': len(open_warnings),
    }


def is_workspace_path(target_path: str | None) -> bool:
    if not target_path:
        return False
    target = str(Path(target_path))
    for prefix in load_policy().get('workspace_paths', []):
        if target.startswith(str(Path(prefix))):
            return True
    return False


def is_core_path(target_path: str | None) -> bool:
    if not target_path:
        return False
    target = str(Path(target_path))
    for prefix in load_policy().get('protect_core_paths', []):
        if target.startswith(str(Path(prefix))):
            return True
    return False


def allow_platform_generation() -> tuple[bool, str]:
    policy = load_policy()
    platforms = _load_json(PLATFORMS, {}).get('platforms', [])
    metrics = _platform_metrics(platforms)
    if metrics['created_last_day'] >= int(policy.get('max_platforms_per_day', 3)):
        return False, 'platform generation throttled by daily limit'
    return True, ''


def guard_snapshot() -> dict[str, Any]:
    policy = load_policy()
    kernel_mode = load_kernel_mode()
    lean_execution = str(kernel_mode.get("profile") or "") in {"lean_execution", "interaction_only"}
    tasks = _load_json(TASKS, [])
    messages = _load_json(CORE_MESSAGES, [])
    platforms = _load_json(PLATFORMS, {}).get('platforms', [])
    task_metrics = _task_metrics(tasks)
    platform_metrics = _platform_metrics(platforms)
    usage_metrics = _usage_metrics()
    message_metrics = _message_metrics(messages)

    reasons = []
    allow_brain_loop = True
    allow_meta = True
    allow_evolution = True

    if task_metrics['created_last_hour'] >= int(policy.get('max_tasks_per_hour', 20)):
        max_active_tasks = int(policy.get('max_active_tasks', 8))
        max_queue_tasks = int(policy.get('max_queue_tasks', 20))
        # Burst creation should throttle orchestration, but only hard-block when the queue is already under pressure.
        if not (lean_execution and task_metrics['active'] <= max_active_tasks and task_metrics['queued'] < max_queue_tasks):
            reasons.append('task creation rate exceeded')
            allow_brain_loop = False
            allow_meta = False
    if task_metrics['active'] >= int(policy.get('max_active_tasks', 8)):
        reasons.append('active task limit exceeded')
        allow_brain_loop = False
    if task_metrics['queued'] >= int(policy.get('max_queue_tasks', 20)):
        reasons.append('queue length limit exceeded')
        allow_brain_loop = False
    if not bool(usage_metrics.get('reasoning_allowed', True)) and usage_metrics.get('reasoning_ratio', 0.0) > float(policy.get('max_reasoning_model_ratio', 0.6)):
        reasons.append('reasoning model ratio exceeded')
        allow_meta = False
        allow_evolution = False
    if not bool(usage_metrics.get('strong_allowed', True)) and usage_metrics.get('strong_ratio', 0.0) > float(policy.get('max_strong_model_ratio', 0.15)):
        reasons.append('strong model ratio exceeded')
        allow_meta = False
        allow_evolution = False
    if message_metrics['open_errors'] >= int(policy.get('max_error_escalations', 5)):
        reasons.append('too many open error escalations')
        allow_meta = False
        allow_evolution = False

    status = 'healthy'
    if reasons and (allow_brain_loop or allow_meta or allow_evolution):
        status = 'throttled'
    if reasons and not allow_brain_loop and not allow_meta and not allow_evolution:
        status = 'blocked'

    snapshot = {
        'updated_at': _utc(),
        'status': status,
        'reasons': reasons,
        'allow_brain_loop': allow_brain_loop,
        'allow_meta': allow_meta,
        'allow_evolution': allow_evolution,
        'tasks': task_metrics,
        'platforms': platform_metrics,
        'usage': usage_metrics,
        'messages': message_metrics,
        'policy': policy,
        'kernel_mode': {'profile': kernel_mode.get('profile'), 'enabled_components': kernel_mode.get('enabled_components', [])},
        'workspace_paths': policy.get('workspace_paths', []),
        'core_paths': policy.get('protect_core_paths', []),
    }
    return snapshot


def run_guard() -> dict[str, Any]:
    snapshot = guard_snapshot()
    _save_json(HEALTH, snapshot)
    _save_json(STATE, snapshot)
    return snapshot


if __name__ == '__main__':
    print(json.dumps(run_guard(), ensure_ascii=False, indent=2))

