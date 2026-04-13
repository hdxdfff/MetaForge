from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.change_request_analyzer import analyze_change_request
from tools.goal_registry import create_goal, list_goals, update_goal
from tools.module_ownership import create_patch_submission

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
OUT = DATA / 'replan_status.json'
TASKS = DATA / 'tasks.json'


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _propose_new_goals(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    request = analysis.get('request') or 'change request'
    classification = ((analysis.get('classification') or {}).get('category') or 'incremental')
    dependency = analysis.get('dependency_impact') or {}
    verification_scope = dependency.get('verification_scope', [])
    focus_capabilities = ((analysis.get('recommendation') or {}).get('focus_capabilities') or [])[:3]
    proposals = [
        {
            'target': f"Apply change request: {request}",
            'goal_type': 'build_product' if classification != 'strategic' else 'build_platform',
            'notes': 'Auto-generated replan goal created from change request analysis.',
        }
    ]
    if verification_scope:
        proposals.append({
            'target': 'Run change impact verification sweep',
            'goal_type': 'verify_platforms',
            'notes': 'Auto-generated verification sweep for modules affected by a change request.',
        })
    for capability_id in focus_capabilities:
        proposals.append({
            'target': f'Strengthen {capability_id.replace("_", " ")} after change request',
            'goal_type': 'build_product',
            'notes': 'Auto-generated capability follow-up aligned with the current global policy.',
        })
    unique = []
    seen = set()
    for item in proposals:
        key = item['target'].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:4]


def _hold_candidates(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    related_goals = analysis.get('related_goals') or []
    hold = []
    for item in related_goals:
        if item.get('status') in {'pending', 'planned', 'running'}:
            hold.append({
                'goal_id': item.get('goal_id'),
                'target': item.get('target'),
                'reason': 'Potentially invalidated by new change request.',
            })
    return hold[:8]


def build_replan(request: str, *, apply: bool = False) -> dict[str, Any]:
    analysis = analyze_change_request(request)
    hold_candidates = _hold_candidates(analysis)
    new_goals = _propose_new_goals(analysis)
    tasks = _load_json(TASKS, [])
    impacted_task_ids = []
    verification_scope = set((analysis.get('dependency_impact') or {}).get('verification_scope', []))
    for task in tasks:
        hint = task.get('scheduler_hint') or {}
        modules = set(hint.get('module_focus') or [])
        if modules & verification_scope:
            impacted_task_ids.append(task.get('id'))

    patch_queue_preview = analysis.get('ownership_review_scope') or {}
    applied = {'held_goal_ids': [], 'created_goals': [], 'created_patch_submissions': []}
    if apply:
        for item in hold_candidates:
            goal_id = item.get('goal_id')
            if not goal_id:
                continue
            try:
                update_goal(goal_id, status='on_hold', notes=item.get('reason'))
                applied['held_goal_ids'].append(goal_id)
            except KeyError:
                continue
        existing_targets = {str(goal.get('target') or '').strip().lower() for goal in list_goals()}
        for item in new_goals:
            key = item['target'].strip().lower()
            if key in existing_targets:
                continue
            goal = create_goal(item['target'], goal_type=item['goal_type'], notes=item['notes'])
            applied['created_goals'].append(goal)
            existing_targets.add(key)
        review_scope = analysis.get('ownership_review_scope') or {}
        if analysis.get('recommendation', {}).get('requires_architecture_review') or analysis.get('risk_level') in {'medium', 'high'}:
            patch = create_patch_submission(
                task_id=None,
                node_id=f"replan-{analysis.get('updated_at', '').replace(':', '').replace('-', '')}",
                title=f"Review change request impact: {request[:80]}",
                team='architecture',
                owner_teams=review_scope.get('owner_teams') or [],
                module_focus=review_scope.get('module_focus') or [],
                reason='Auto-created review submission from change request replan.',
                repo_path=(analysis.get('matched_projects') or [{}])[0].get('repo_path'),
            )
            applied['created_patch_submissions'].append({
                'patch_id': patch.get('patch_id'),
                'status': patch.get('status'),
            })

    payload = {
        'updated_at': _utc(),
        'request': request,
        'analysis': analysis,
        'context_package': analysis.get('context_package', {}),
        'ownership_review_scope': analysis.get('ownership_review_scope', {}),
        'patch_queue_preview': patch_queue_preview,
        'hold_candidates': hold_candidates,
        'new_goal_proposals': new_goals,
        'impacted_task_ids': [item for item in impacted_task_ids if item],
        'apply': apply,
        'applied': applied,
        'status': 'applied' if apply else 'planned',
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('request')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build_replan(args.request, apply=args.apply), ensure_ascii=False, indent=2))
