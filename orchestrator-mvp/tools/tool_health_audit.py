from __future__ import annotations

import json
import importlib
from pathlib import Path
from tools.io_utils import atomic_write_json

from tools.autonomy_state import load_effective_autonomy
from tools.schema_hygiene import scan_schema_drift

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
HISTORY = DATA / 'tool_health_history.json'
MODULE_INTERFACE_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('tools.task_state_tools', ('resolved_delivery_evidence', 'promote_delivery_ready_tasks', 'auto_complete_verified_tasks')),
    ('tools.release_operations', ('run_release_operations_status',)),
    ('tools.meta_factory_control', ('run_control_layer',)),
    ('tools.verification_engine', ('run_verification',)),
    ('tools.quality_system', ('run_quality',)),
    ('tools.autonomy_score', ('run_autonomy_score',)),
    ('tools.ai_testing_compat', ('run_ai_test_suite', 'load_ai_test_status')),
    ('tools.company_os', ('run_company_os_status',)),
    ('tools.automation_lab', ('run_automation_lab_status',)),
    ('tools.rnd_delivery_pipeline', ('build_rnd_delivery_pipeline_status',)),
    ('tools.rnd_asset_governance', ('build_rnd_asset_governance_status',)),
    ('tools.pipeline_status', ('build_pipeline_status',)),
)


def _load(name: str, default):
    path = DATA / name
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        return {'status': 'error', 'error': str(exc), 'path': str(path)}


def _module_interface_compatibility() -> dict[str, object]:
    checks: list[dict[str, object]] = []
    issues: list[str] = []
    for module_name, required_attrs in MODULE_INTERFACE_SPECS:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            checks.append(
                {
                    'module': module_name,
                    'status': 'blocked',
                    'missing': list(required_attrs),
                    'error': f'{type(exc).__name__}: {exc}',
                }
            )
            issues.append(f'{module_name}:import-failed')
            continue
        missing = [attr for attr in required_attrs if not hasattr(module, attr)]
        checks.append(
            {
                'module': module_name,
                'status': 'pass' if not missing else 'blocked',
                'missing': missing,
            }
        )
        if missing:
            issues.append(f"{module_name}:{','.join(missing)}")
    return {
        'status': 'pass' if not issues else 'attention',
        'issues': issues,
        'checks': checks,
    }


def run_tool_health_audit() -> dict:
    daemon = _load('factory_daemon_state.json', {})
    control = _load('control_layer_status.json', {})
    quality = _load('quality_status.json', {})
    memory_quality = _load('memory_quality_scorecard.json', {})
    memory_muscle = _load('memory_muscle_benchmark.json', {})
    autonomy = load_effective_autonomy()
    soak = _load('soak_validation.json', {})
    company = _load('company_os_status.json', {})
    lab = _load('automation_lab_status.json', {})
    verification = _load('verification_status.json', {})
    module_interface = _module_interface_compatibility()
    schema_hygiene = scan_schema_drift()
    issues = []
    daemon_cycle = int(daemon.get('cycle') or 0)
    daemon_status = str(daemon.get('status') or '').strip().lower()
    daemon_running = daemon_status in {'running', 'operator_attention'}
    startup_grace = daemon_running and daemon_cycle <= 1

    if not daemon_running:
        issues.append('daemon-not-running')
    if not daemon.get('last_tick_at') and not startup_grace:
        issues.append('daemon-no-heartbeat')
    autonomy_soak_mismatch = bool(soak.get('confirmed') and autonomy.get('stage') != soak.get('status'))
    decision_engine = control.get('decision_engine') or {}
    decisions = decision_engine.get('decisions') or []
    only_patch_gate_hold = (
        control.get('status') == 'constrained'
        and bool(decisions)
        and all(item.get('decision') in {'hold-promotion', 'allow-evolution-candidates'} for item in decisions)
        and any(
            item.get('decision') == 'hold-promotion'
            and 'patch gate status=attention' in str(item.get('reason', ''))
            for item in decisions
        )
    )
    governance_throttle_only = (
        control.get('status') == 'constrained'
        and bool(decisions)
        and all(
            item.get('decision') in {
                'throttle-runtime',
                'throttle-meta',
                'throttle-evolution',
                'allow-evolution-candidates',
            }
            for item in decisions
        )
        and any(item.get('decision') in {'throttle-runtime', 'throttle-meta', 'throttle-evolution'} for item in decisions)
    )
    control_status = str(control.get('status') or '').strip().lower()
    if (
        quality.get('status') == 'promote'
        and control_status in {'constrained', 'operator_attention'}
        and not only_patch_gate_hold
        and not governance_throttle_only
    ):
        issues.append('control-layer-lags-quality')
    if memory_quality.get('status') in {'attention', 'degraded'}:
        issues.append('memory-quality-attention')
    if memory_muscle.get('status') in {'attention', 'degraded'}:
        issues.append('memory-muscle-benchmark-attention')
    if verification.get('status') not in {'pass', 'attention'}:
        issues.append('verification-invalid-state')
    if module_interface.get('status') != 'pass':
        issues.extend(str(item) for item in module_interface.get('issues', []) if str(item).strip())
    if schema_hygiene.get('finding_count', 0):
        issues.append('schema-drift-low-level')

    return {
        'updated_at': daemon.get('updated_at') or control.get('updated_at'),
        'status': 'attention' if issues else 'pass',
        'issues': issues,
        'daemon': {
            'status': daemon.get('status'),
            'pid': daemon.get('pid'),
            'cycle': daemon.get('cycle'),
            'last_tick_at': daemon.get('last_tick_at'),
        },
        'control_layer': {
            'status': control.get('status'),
            'quality_score': (control.get('quality_system') or {}).get('overall_score'),
            'only_patch_gate_hold': only_patch_gate_hold,
            'governance_throttle_only': governance_throttle_only,
        },
        'quality': {
            'status': quality.get('status'),
            'overall_score': quality.get('overall_score'),
        },
        'memory_quality_scorecard': {
            'status': memory_quality.get('status'),
            'overall_score': memory_quality.get('overall_score'),
            'write_quality': (memory_quality.get('write_quality') or {}).get('status'),
            'recall_hit_rate': (memory_quality.get('recall_hit_rate') or {}).get('status'),
            'behavior_binding': (memory_quality.get('behavior_binding') or {}).get('status'),
            'anti_drift': (memory_quality.get('anti_drift') or {}).get('status'),
        },
        'memory_muscle_benchmark': {
            'status': memory_muscle.get('status'),
            'overall_score': memory_muscle.get('overall_score'),
            'sediment': (memory_muscle.get('sediment') or {}).get('status'),
            'promote': (memory_muscle.get('promote') or {}).get('status'),
            'recall': (memory_muscle.get('recall') or {}).get('status'),
            'binding': (memory_muscle.get('binding') or {}).get('status'),
            'reproduce': (memory_muscle.get('reproduce') or {}).get('status'),
        },
        'autonomy': {
            'stage': autonomy.get('stage'),
            'score': autonomy.get('score'),
        },
        'autonomy_soak_mismatch': autonomy_soak_mismatch,
        'soak': {
            'status': soak.get('status'),
            'confirmed': soak.get('confirmed'),
        },
        'company_os': {
            'status': company.get('status'),
            'score': company.get('score'),
        },
        'automation_lab': {
            'status': lab.get('status'),
            'score': lab.get('score'),
        },
        'verification': {
            'status': verification.get('status'),
        },
        'module_interface_compatibility': module_interface,
        'schema_hygiene': schema_hygiene,
        'startup_grace': startup_grace,
    }

def append_tool_health_history(entry: dict, keep: int = 200) -> dict:
    history = []
    if HISTORY.exists():
        try:
            history = json.loads(HISTORY.read_text(encoding='utf-8-sig'))
        except Exception:
            history = []
    history.append({
        'updated_at': entry.get('updated_at'),
        'status': entry.get('status'),
        'issues': list(entry.get('issues', [])),
        'daemon': {
            'status': (entry.get('daemon') or {}).get('status'),
            'cycle': (entry.get('daemon') or {}).get('cycle'),
            'last_tick_at': (entry.get('daemon') or {}).get('last_tick_at'),
        },
        'control_layer_status': (entry.get('control_layer') or {}).get('status'),
        'quality_status': (entry.get('quality') or {}).get('status'),
        'memory_quality_status': (entry.get('memory_quality_scorecard') or {}).get('status'),
        'memory_muscle_status': (entry.get('memory_muscle_benchmark') or {}).get('status'),
        'autonomy_stage': (entry.get('autonomy') or {}).get('stage'),
        'module_interface_status': (entry.get('module_interface_compatibility') or {}).get('status'),
    })
    history = history[-keep:]
    atomic_write_json(HISTORY, history)
    return {
        'history_count': len(history),
        'latest': history[-1] if history else None,
    }


def read_tool_health_history(limit: int = 20) -> dict:
    history = []
    if HISTORY.exists():
        try:
            history = json.loads(HISTORY.read_text(encoding='utf-8-sig'))
        except Exception:
            history = []
    recent = history[-max(limit, 1):]
    failures = [item for item in recent if item.get('status') != 'pass']
    issue_counter: dict[str, int] = {}
    for item in recent:
        for issue in item.get('issues', []) or []:
            issue_counter[issue] = issue_counter.get(issue, 0) + 1
    return {
        'history_count': len(history),
        'recent_count': len(recent),
        'recent': recent,
        'recent_failures': failures,
        'recent_failure_count': len(failures),
        'pass_ratio': round(((len(recent) - len(failures)) / len(recent)), 4) if recent else 1.0,
        'issue_frequency': issue_counter,
    }


if __name__ == '__main__':
    print(json.dumps(run_tool_health_audit(), ensure_ascii=False, indent=2))
