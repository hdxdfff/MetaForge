from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json
from tools.autonomy_state import autonomy_is_confirmed, load_effective_autonomy
from tools.ai_testing_compat import load_ai_test_status
from tools.rnd_department import build_rnd_department_status
from tools.rnd_delivery_pipeline import build_rnd_delivery_pipeline_status
from tools.rnd_asset_governance import build_rnd_asset_governance_status
from tools.economics_engine import run_economics_engine_status

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
OUT = DATA / 'company_os_status.json'

CONTROL = DATA / 'control_layer_status.json'
LAB = DATA / 'automation_lab_status.json'
GLOBAL_POLICY = DATA / 'global_policy_state.json'
RELEASE_OPS = DATA / 'release_operations_status.json'
ORG = DATA / 'organization_workboard.json'
PROJECT_GRAPH = DATA / 'project_graph.json'


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


def run_company_os_status() -> dict[str, Any]:
    control = _load_json(CONTROL, {})
    lab = _load_json(LAB, {})
    autonomy = load_effective_autonomy()
    policy = _load_json(GLOBAL_POLICY, {})
    release_ops = _load_json(RELEASE_OPS, {})
    org = _load_json(ORG, {})
    project_graph = _load_json(PROJECT_GRAPH, {})
    ai_testing = load_ai_test_status()
    rnd_department = build_rnd_department_status()
    delivery_pipeline = build_rnd_delivery_pipeline_status()
    asset_governance = build_rnd_asset_governance_status()
    economics = run_economics_engine_status()

    strategy_ok = bool(policy.get('focus_capabilities')) and bool(policy.get('resource_budget'))
    organization_ok = org.get('department_count', 0) >= 5
    project_ok = project_graph.get('project_count', 0) >= 3
    engineering_ok = (control.get('engineering_os') or {}).get('status') == 'pass'
    execution_ok = control.get('status') == 'stable' and (control.get('verification_engine') or {}).get('status') == 'pass'
    learning_ok = (lab.get('maturity') or {}).get('status') == 'mature'
    release_ok = release_ops.get('status') == 'pass'
    ai_ok = str(ai_testing.get('release_signal') or '') == 'ready' and float(ai_testing.get('overall_score', 0.0) or 0.0) >= 70.0
    rnd_org_ok = (rnd_department.get('readiness') or {}).get('organization_ready', False)
    pipeline_ok = delivery_pipeline.get('stage') in {'stage2_engineering', 'stage3_platformizing', 'stage4_productized'}
    asset_ok = asset_governance.get('status') == 'managed'
    economics_ok = economics.get('status') in {'active', 'pass'} and float(economics.get('score', 0.0) or 0.0) >= 0.65

    score = min(1.0, round(
        (0.12 if strategy_ok else 0.0)
        + (0.10 if organization_ok else 0.0)
        + (0.08 if project_ok else 0.0)
        + (0.12 if engineering_ok else 0.0)
        + (0.10 if execution_ok else 0.0)
        + (0.10 if learning_ok else 0.0)
        + (0.08 if release_ok else 0.0)
        + (0.08 if ai_ok else 0.0)
        + (0.10 if rnd_org_ok else 0.0)
        + (0.06 if pipeline_ok else 0.0)
        + (0.06 if asset_ok else 0.0)
        + (0.10 if economics_ok else 0.0),
        4,
    ))
    status = 'mature' if score >= 0.85 and autonomy.get('stage') in {'stage4_confirmed', 'stage4_beta'} else 'developing'
    payload = {
        'updated_at': _utc(),
        'status': status,
        'score': score,
        'layers': {
            'strategy': {'status': 'pass' if strategy_ok else 'attention'},
            'organization': {'status': 'pass' if organization_ok else 'attention'},
            'project': {'status': 'pass' if project_ok else 'attention'},
            'engineering': {'status': 'pass' if engineering_ok else 'attention'},
            'execution': {'status': 'pass' if execution_ok else 'attention'},
            'learning': {'status': 'pass' if learning_ok else 'attention'},
            'release_operations': {'status': 'pass' if release_ok else 'attention'},
            'ai_testing': {'status': 'pass' if ai_ok else 'attention'},
            'rnd_organization': {'status': 'pass' if rnd_org_ok else 'attention'},
            'rnd_delivery_pipeline': {'status': 'pass' if pipeline_ok else 'attention'},
            'rnd_asset_governance': {'status': 'pass' if asset_ok else 'attention'},
            'economics_engine': {'status': 'pass' if economics_ok else 'attention'},
        },
        'autonomy': {
            'stage': autonomy.get('stage'),
            'score': autonomy.get('score'),
            'source': autonomy.get('source'),
            'confirmed': autonomy_is_confirmed(autonomy),
        },
        'summary': {
            'focus_capabilities': policy.get('focus_capabilities', []),
            'department_count': org.get('department_count', 0),
            'project_count': project_graph.get('project_count', 0),
            'platform_count': (control.get('platform_runtime') or {}).get('platform_count', 0),
            'release_train_status': (release_ops.get('release_train') or {}).get('status'),
            'ai_testing_status': ai_testing.get('status'),
            'ai_testing_release_signal': ai_testing.get('release_signal'),
            'ai_testing_score': ai_testing.get('overall_score'),
            'ai_testing_pass_rate': ai_testing.get('pass_rate'),
            'ai_testing_error_count': ai_testing.get('error_count'),
            'rnd_group_count': (rnd_department.get('summary') or {}).get('group_count', 0),
            'rnd_delivery_stage': delivery_pipeline.get('stage'),
            'automation_ratio': (asset_governance.get('kpi') or {}).get('automation_ratio'),
            'platform_output': (asset_governance.get('kpi') or {}).get('platform_output'),
            'product_output': (asset_governance.get('kpi') or {}).get('product_output'),
            'economics_status': economics.get('status'),
            'economics_score': economics.get('score'),
            'economics_price_index_mfc': ((economics.get('resource_market') or {}).get('price_index')),
            'economics_gdp_mfc': ((economics.get('ai_gdp') or {}).get('completed_value_mfc')),
        },
        'economics_engine': economics,
        'rnd_department': rnd_department,
        'rnd_delivery_pipeline': delivery_pipeline,
        'rnd_asset_governance': asset_governance,
    }
    _save_json(OUT, payload)
    return payload


if __name__ == '__main__':
    print(json.dumps(run_company_os_status(), ensure_ascii=False, indent=2))

