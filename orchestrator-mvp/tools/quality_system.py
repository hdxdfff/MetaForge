from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.goal_registry import list_goals
from tools.platform_registry import list_platforms
DATA = ROOT / 'data'
FACTORY = ROOT / 'factory'
TASKS = DATA / 'tasks.json'
PLATFORMS = FACTORY / 'platform_registry.json'
CAPABILITIES = FACTORY / 'capability_registry.json'
GUARD = DATA / 'health_status.json'
OUT = DATA / 'quality_status.json'
POLICY = DATA / 'quality_policy.json'
CANDIDATES = DATA / 'self_patch_candidates.json'
ACTIVE_GOAL_STATUSES = {'pending', 'planned', 'running'}
ACTIVE_TASK_STATUSES = {'queued', 'planning', 'running', 'waiting_approval'}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def _parse_ts(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None


def _task_result_payload(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get('result')
    return result if isinstance(result, dict) else {}


def _task_requested_requeue(item: dict[str, Any]) -> bool:
    result = _task_result_payload(item)
    if bool(item.get('requeue_requested')) or bool(result.get('requeue_requested')):
        return True
    if bool(result.get('heartbeat_timeout')):
        return True
    summary = str(result.get('summary') or item.get('result_summary') or '').lower()
    return 'requested requeue' in summary or 'heartbeat exceeded' in summary


def _recovering_goal_ids(tasks: list[dict[str, Any]], *, now: datetime | None = None, window_minutes: int = 20) -> set[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    active_statuses = {'queued', 'planning', 'running', 'waiting_approval'}
    goal_ids: set[str] = set()
    for item in tasks:
        goal_id = str(item.get('goal_id') or '').strip()
        if not goal_id:
            continue
        status = str(item.get('status') or '').strip()
        if status in active_statuses:
            goal_ids.add(goal_id)
            continue
        if status not in {'failed', 'timed_out'} or not _task_requested_requeue(item):
            continue
        ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
        if ts is not None and ts >= cutoff:
            goal_ids.add(goal_id)
    return goal_ids


def _logical_task_key(item: dict[str, Any]) -> str:
    goal_id = str(item.get('goal_id') or '').strip()
    node_id = str(item.get('node_id') or '').strip()
    artifact_id = str((((item.get('scheduler_hint') or {}).get('artifact_spec') or {}).get('artifact_id')) or '').strip()
    title = str(item.get('title') or '').strip()
    prompt = str(item.get('prompt') or '').strip()
    discriminator = artifact_id or node_id or title or prompt or str(item.get('id') or '').strip()
    return f"{goal_id}|{discriminator}"


def _latest_attempts(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in tasks:
        key = _logical_task_key(item)
        current = latest.get(key)
        ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
        current_ts = _parse_ts((current or {}).get('updated_at') or (current or {}).get('created_at'))
        if current is None:
            latest[key] = item
            continue
        if ts is not None and (current_ts is None or ts >= current_ts):
            latest[key] = item
        elif ts is None and current_ts is None:
            latest[key] = item
    return list(latest.values())


def _task_score(tasks: list[dict[str, Any]], active_goal_ids: set[str] | None = None) -> float:
    if not tasks:
        return 1.0
    filtered_tasks = tasks
    if active_goal_ids:
        active_tasks = [item for item in tasks if str(item.get('goal_id') or '').strip() in active_goal_ids]
        if active_tasks:
            filtered_tasks = active_tasks
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=12)
    stale_cutoff = now - timedelta(minutes=20)
    scored_tasks = []
    for item in filtered_tasks:
        ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
        if ts is None or ts >= cutoff:
            scored_tasks.append(item)
    if not scored_tasks:
        scored_tasks = filtered_tasks[-10:]
    scored_tasks = _latest_attempts(scored_tasks)
    open_tasks = [item for item in scored_tasks if item.get('status') in ACTIVE_TASK_STATUSES]
    completed = sum(1 for item in scored_tasks if item.get('status') == 'completed')
    failed = sum(
        1
        for item in scored_tasks
        if item.get('status') in {'failed', 'timed_out'} and not _task_requested_requeue(item)
    )
    recent_recovery_failures = 0
    if active_goal_ids and open_tasks:
        recovery_cutoff = now - timedelta(minutes=20)
        for item in scored_tasks:
            if item.get('status') not in {'failed', 'timed_out'} or _task_requested_requeue(item):
                continue
            goal_id = str(item.get('goal_id') or '').strip()
            ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
            if goal_id in active_goal_ids and ts is not None and ts >= recovery_cutoff:
                recent_recovery_failures += 1
    effective_failed = max(0, failed - recent_recovery_failures)
    stale_active = 0
    for item in scored_tasks:
        if item.get('status') not in {'queued', 'planning', 'running', 'waiting_approval'}:
            continue
        ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
        if ts is not None and ts <= stale_cutoff:
            stale_active += 1
    if not open_tasks:
        recent_closed = completed + effective_failed
        if recent_closed <= 0:
            return 1.0
        # When there is no live queue pressure, treat closed throughput as healthy
        # unless we still have stale active items in the observation window.
        if effective_failed > 0 and completed == 0:
            return 0.85
        closed_ratio = completed / max(1, recent_closed)
        return round(0.85 + min(0.1, closed_ratio * 0.1), 4)
    if active_goal_ids and stale_active == 0 and recent_recovery_failures > 0 and effective_failed == 0:
        return 0.8
    effective_total = completed + effective_failed + stale_active
    if effective_total <= 0:
        return 0.7 if active_goal_ids and filtered_tasks else 1.0
    success = completed / effective_total
    pressure = max(0.0, 1.0 - (stale_active / effective_total))
    failure_penalty = max(0.0, 1.0 - (effective_failed / effective_total))
    return round((success * 0.6) + (pressure * 0.15) + (failure_penalty * 0.25), 4)


def _platform_score(platform: dict[str, Any], capabilities: list[dict[str, Any]], guard: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(platform.get('workspace') or '')
    required = platform.get('required_paths') or []
    existing = 0
    for item in required:
        if (workspace / item).exists():
            existing += 1
    structure_score = existing / max(1, len(required)) if required else 0.8
    cap_count = sum(1 for item in capabilities if item.get('provider_platform_id') == platform.get('platform_id'))
    capability_score = min(1.0, cap_count / 2)
    safety_score = 0.8 if guard.get('status') in {'healthy', 'throttled'} else 0.4
    runtime = platform.get('runtime') or {}
    health = runtime.get('health', 'unknown')
    health_score = 1.0 if health == 'healthy' else 0.7 if health in {'generated', 'unknown'} else 0.35
    score = round(structure_score * 0.45 + capability_score * 0.20 + safety_score * 0.15 + health_score * 0.20, 4)
    return {
        'platform_id': platform.get('platform_id'),
        'name': platform.get('name'),
        'workspace': platform.get('workspace'),
        'required_paths_present': existing,
        'required_paths_total': len(required),
        'capability_count': cap_count,
        'quality_score': score,
        'quality_status': 'promote' if score >= 0.75 else 'candidate' if score >= 0.65 else 'hold',
        'runtime_health': health,
        'runtime_status': runtime.get('status', platform.get('status', 'generated')),
        'last_checked': runtime.get('last_checked'),
    }


def _candidate_score(item: dict[str, Any]) -> dict[str, Any]:
    priority = item.get('priority', 'low')
    base = {'high': 0.82, 'medium': 0.7, 'low': 0.58}.get(priority, 0.58)
    cheap_bonus = 0.08 if item.get('cheap_worker_ok') else -0.1
    sandbox_bonus = 0.05 if item.get('sandbox_required') else 0.0
    score = round(max(0.0, min(1.0, base + cheap_bonus + sandbox_bonus)), 4)
    status = 'promote' if score >= 0.75 else 'candidate' if score >= 0.65 else 'hold'
    enriched = dict(item)
    enriched['quality_score'] = score
    enriched['quality_status'] = status
    return enriched


def _quality_readiness_checks(
    *,
    task_score: float,
    tasks: list[dict[str, Any]],
    platform_scores: list[dict[str, Any]],
    candidate_scores: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    guard: dict[str, Any],
    active_goal_ids: set[str],
) -> list[dict[str, Any]]:
    latest_tasks = _latest_attempts(tasks)
    completed = sum(1 for item in latest_tasks if item.get('status') == 'completed')
    failed = sum(1 for item in latest_tasks if item.get('status') in {'failed', 'timed_out'} and not _task_requested_requeue(item))
    stale_active = 0
    for item in latest_tasks:
        if item.get('status') not in {'queued', 'planning', 'running', 'waiting_approval'}:
            continue
        ts = _parse_ts(item.get('updated_at') or item.get('created_at'))
        if ts is not None and ts <= datetime.now(timezone.utc) - timedelta(minutes=20):
            stale_active += 1

    promote_platforms = [item for item in platform_scores if item['quality_status'] == 'promote']
    hold_platforms = [item for item in platform_scores if item['quality_status'] == 'hold']
    promote_candidates = [item for item in candidate_scores if item['quality_status'] == 'promote']
    capability_score = min(1.0, len(capabilities) / 8)
    safety_ok = guard.get('status') in {'healthy', 'throttled'}

    checks = [
        {
            'name': 'task_throughput',
            'status': 'pass' if task_score >= 0.75 else 'attention',
            'score': task_score,
            'effect': 'quality_routing',
            'affects_runtime': False,
            'affects_release': False,
            'affects_reporting': True,
            'detail': {
                'completed_tasks': completed,
                'failed_tasks': failed,
                'stale_active_tasks': stale_active,
                'open_task_count': sum(1 for item in latest_tasks if item.get('status') in ACTIVE_TASK_STATUSES),
                'active_goal_ids': sorted(active_goal_ids),
            },
            'next_action': 'restore-task-flow' if task_score < 0.75 else 'observe-only',
        },
        {
            'name': 'platform_readiness',
            'status': 'pass' if not hold_platforms else 'attention',
            'score': round(sum(item['quality_score'] for item in platform_scores) / max(1, len(platform_scores)), 4) if platform_scores else 1.0,
            'effect': 'platform_promotion',
            'affects_runtime': False,
            'affects_release': False,
            'affects_reporting': True,
            'detail': {
                'promote_platform_count': len(promote_platforms),
                'hold_platform_count': len(hold_platforms),
                'top_hold_platforms': [
                    {'platform_id': item['platform_id'], 'name': item['name'], 'quality_score': item['quality_score']}
                    for item in hold_platforms[:5]
                ],
            },
            'next_action': 'repair-hold-platforms' if hold_platforms else 'observe-only',
        },
        {
            'name': 'capability_coverage',
            'status': 'pass' if capability_score >= 0.75 else 'attention',
            'score': capability_score,
            'effect': 'capability_gap_tracking',
            'affects_runtime': False,
            'affects_release': False,
            'affects_reporting': True,
            'detail': {
                'capability_count': len(capabilities),
                'target_capability_count': 8,
            },
            'next_action': 'expand-capability-coverage' if capability_score < 0.75 else 'observe-only',
        },
        {
            'name': 'safety_gate',
            'status': 'pass' if safety_ok else 'attention',
            'score': 0.9 if safety_ok else 0.5,
            'effect': 'observe_only',
            'affects_runtime': False,
            'affects_release': False,
            'affects_reporting': True,
            'detail': {
                'guard_status': guard.get('status'),
            },
            'next_action': 'restore-guard-health' if not safety_ok else 'observe-only',
        },
        {
            'name': 'candidate_pipeline',
            'status': 'pass' if promote_candidates else 'attention',
            'score': round(sum(item['quality_score'] for item in candidate_scores) / max(1, len(candidate_scores)), 4) if candidate_scores else 1.0,
            'effect': 'candidate_promotion',
            'affects_runtime': False,
            'affects_release': False,
            'affects_reporting': True,
            'detail': {
                'promote_candidate_count': len(promote_candidates),
                'candidate_count': len(candidate_scores),
            },
            'next_action': 'promote-high-quality-candidates' if promote_candidates else 'observe-only',
        },
    ]
    return checks


def run_quality() -> dict[str, Any]:
    tasks = _load_json(TASKS, [])
    platforms = list_platforms()
    capabilities = _load_json(CAPABILITIES, {}).get('capabilities', [])
    guard = _load_json(GUARD, {'status': 'unknown'})
    policy = _load_json(POLICY, {})
    candidates_payload = _load_json(CANDIDATES, [])
    if isinstance(candidates_payload, dict):
        candidates = candidates_payload.get('candidates', [])
    elif isinstance(candidates_payload, list):
        candidates = candidates_payload
    else:
        candidates = []

    goals = list_goals()
    active_goal_ids = {str(item.get('goal_id') or '').strip() for item in goals if item.get('status') in ACTIVE_GOAL_STATUSES}
    if not active_goal_ids:
        active_goal_ids = _recovering_goal_ids(tasks)
    task_score = _task_score(tasks, active_goal_ids=active_goal_ids)
    platform_scores = [_platform_score(platform, capabilities, guard) for platform in platforms]
    candidate_scores = [_candidate_score(item) for item in candidates]
    promoted_platforms = [item for item in platform_scores if item['quality_status'] == 'promote']
    promoted_candidates = [item for item in candidate_scores if item['quality_status'] == 'promote']
    readiness_checks = _quality_readiness_checks(
        task_score=task_score,
        tasks=tasks,
        platform_scores=platform_scores,
        candidate_scores=candidate_scores,
        capabilities=capabilities,
        guard=guard,
        active_goal_ids=active_goal_ids,
    )

    overall = round(
        task_score * float(policy.get('task_success_weight', 0.4))
        + (sum(item['quality_score'] for item in platform_scores) / max(1, len(platform_scores))) * float(policy.get('platform_structure_weight', 0.35))
        + (min(1.0, len(capabilities) / 8)) * float(policy.get('capability_weight', 0.15))
        + (0.9 if guard.get('status') in {'healthy', 'throttled'} else 0.5) * float(policy.get('safety_weight', 0.10)),
        4,
    )

    payload = {
        'updated_at': _utc(),
        'overall_score': overall,
        'status': 'promote' if overall >= float(policy.get('promotion_threshold', 0.75)) else 'candidate' if overall >= float(policy.get('candidate_threshold', 0.65)) else 'attention',
        'task_score': task_score,
        'platform_scores': platform_scores,
        'candidate_scores': candidate_scores,
        'promoted_platforms': promoted_platforms,
        'promoted_candidates': promoted_candidates,
        'readiness_checks': readiness_checks,
        'readiness_summary': {
            'status': 'pass' if all(item['status'] == 'pass' for item in readiness_checks) else 'attention',
            'failing_checks': [item['name'] for item in readiness_checks if item['status'] != 'pass'],
            'next_action': next((item['next_action'] for item in readiness_checks if item['status'] != 'pass'), 'observe-only'),
        },
        'guard_status': guard.get('status'),
        'capability_count': len(capabilities),
    }
    _save_json(OUT, payload)
    return payload


def _safe_print_json(payload: dict[str, Any]) -> None:
    try:
        print(json.dumps(payload, ensure_ascii=False))
    except OSError:
        # Daemon and embedded runners may execute without a writable stdout handle.
        pass


def main() -> int:
    payload = run_quality()
    _safe_print_json(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())





