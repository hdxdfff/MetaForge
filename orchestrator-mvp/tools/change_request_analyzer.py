from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tools.io_utils import atomic_write_json

from tools.code_knowledge_graph import query_code_knowledge_graph
from tools.context_builder import build_context_package
from tools.context_kernel import rebuild as rebuild_context_kernel
from tools.dependency_impact_engine import analyze_dependency_impact
from tools.global_policy_engine import run_global_policy
from tools.goal_registry import list_goals
from tools.module_ownership_graph import merge_policy_for_modules, reviewer_candidates
from tools.project_graph import analyze_project_impact

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
OUT = DATA / 'change_request_analysis.json'
PROJECT_COMPACTION = DATA / 'project_context_compaction.json'


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _normalize(text: str) -> str:
    return ' '.join((text or '').lower().replace('-', ' ').replace('_', ' ').split())


def _classify_change(request: str) -> dict[str, Any]:
    lowered = _normalize(request)
    flags = {
        'architecture_change': any(token in lowered for token in ['architecture', 'refactor', 'restructure', '重构', '架构', '层', '模块边界']),
        'constraint_change': any(token in lowered for token in ['constraint', '限制', '约束', 'policy', '策略', '规则']),
        'goal_change': any(token in lowered for token in ['goal', '目标', '方向', 'priority', '优先级']),
        'bugfix_change': any(token in lowered for token in ['bug', 'fix', '修复', 'error', '错误']),
        'scope_change': any(token in lowered for token in ['add', 'remove', 'replace', '删除', '新增', '替换', '扩展', 'scope']),
    }
    if flags['architecture_change'] or flags['constraint_change']:
        category = 'structural'
    elif flags['goal_change']:
        category = 'strategic'
    elif flags['bugfix_change']:
        category = 'corrective'
    else:
        category = 'incremental'
    return {'category': category, 'flags': flags}


def _match_projects(request: str, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = set(_normalize(request).split())
    matched = []
    for project in projects:
        haystack = ' '.join([
            str(project.get('name') or ''),
            str(project.get('repo_path') or ''),
            str(project.get('summary') or ''),
            ' '.join(project.get('compact_context', {}).get('project_goals', []) or []),
            ' '.join(project.get('compact_context', {}).get('architecture_decisions', []) or []),
        ]).lower()
        score = sum(1 for token in tokens if token and token in haystack)
        if score > 0:
            matched.append({
                'project_id': project.get('project_id'),
                'name': project.get('name'),
                'repo_path': project.get('repo_path'),
                'score': score,
            })
    matched.sort(key=lambda item: (-item['score'], item['name'] or ''))
    return matched[:5]


def _related_goals(matched_projects: list[dict[str, Any]], impact: dict[str, Any]) -> list[dict[str, Any]]:
    goals = list_goals()
    related_projects = {str(item.get('name') or '').lower() for item in matched_projects}
    impacted_modules = {str(item.get('module') or '').lower() for item in impact.get('impacted_modules', [])}
    related = []
    for goal in goals:
        target = str(goal.get('target') or '').lower()
        if any(name and name in target for name in related_projects) or any(module and module.split('.')[-1] in target for module in impacted_modules):
            related.append({
                'goal_id': goal.get('goal_id'),
                'target': goal.get('target'),
                'status': goal.get('status'),
                'type': goal.get('type'),
            })
    return related[:8]


def analyze_change_request(request: str) -> dict[str, Any]:
    rebuild_context_kernel()
    projects = _load_json(PROJECT_COMPACTION, [])
    global_policy = run_global_policy()
    classification = _classify_change(request)
    graph_focus = query_code_knowledge_graph(request, limit=8)
    dependency_impact = analyze_dependency_impact(request, limit=8, max_depth=2)
    project_impact = analyze_project_impact(request, focus_modules=graph_focus.get('module_focus', []))
    matched_projects = _match_projects(request, projects)
    context_package = build_context_package(
        prompt=request,
        goal=request,
        repo_path=matched_projects[0].get('repo_path') if matched_projects else None,
        scheduler_hint={},
        max_modules=6,
        budget_chars=2400,
    )
    related_goals = _related_goals(matched_projects, dependency_impact)
    module_focus = list(dict.fromkeys(
        (graph_focus.get('module_focus') or []) +
        (dependency_impact.get('verification_scope') or [])
    ))[:10]
    owner_teams = sorted({item for item in dependency_impact.get('affected_teams', []) if item})
    ownership_review_scope = {
        'module_focus': module_focus,
        'owner_teams': owner_teams,
        'reviewer_teams': reviewer_candidates(module_focus, owner_teams),
        'merge_policy': merge_policy_for_modules(module_focus, owner_teams),
    }

    risk = 0.15
    if classification['category'] == 'structural':
        risk += 0.25
    if dependency_impact.get('affected_teams'):
        risk += min(0.2, 0.03 * len(dependency_impact.get('affected_teams', [])))
    if project_impact.get('cross_project_count', 0) > 1:
        risk += 0.2
    if related_goals:
        risk += min(0.15, 0.03 * len(related_goals))

    if risk >= 0.7:
        risk_level = 'high'
    elif risk >= 0.4:
        risk_level = 'medium'
    else:
        risk_level = 'low'

    recommendation = {
        'replan_required': classification['category'] in {'structural', 'strategic'} or bool(related_goals),
        'requires_architecture_review': classification['flags']['architecture_change'] or risk_level == 'high',
        'verification_scope': dependency_impact.get('verification_scope', []),
        'focus_capabilities': [item for item in global_policy.get('focus_capabilities', []) if item],
        'next_mode': 'replan' if classification['category'] in {'structural', 'strategic'} else 'direct-execution',
    }

    payload = {
        'updated_at': _utc(),
        'request': request,
        'classification': classification,
        'risk_level': risk_level,
        'risk_score': round(risk, 4),
        'matched_projects': matched_projects,
        'graph_focus': graph_focus,
        'context_package': context_package,
        'dependency_impact': dependency_impact,
        'project_impact': project_impact,
        'ownership_review_scope': ownership_review_scope,
        'related_goals': related_goals,
        'recommendation': recommendation,
    }
    atomic_write_json(OUT, payload)
    return payload


if __name__ == '__main__':
    import sys
    request = ' '.join(sys.argv[1:]).strip() or 'change request'
    print(json.dumps(analyze_change_request(request), ensure_ascii=False, indent=2))
