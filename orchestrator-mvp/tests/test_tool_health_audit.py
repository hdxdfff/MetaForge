from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.tool_health_audit as audit


def _fake_module(attrs: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(**attrs)


def _fake_import_factory(*, missing: set[tuple[str, str]] | None = None):
    missing = missing or set()

    def _fake_import(name: str):
        specs = {
            'tools.task_state_tools': {
                'resolved_delivery_evidence': lambda task: {},
                'promote_delivery_ready_tasks': lambda *args, **kwargs: {},
                'auto_complete_verified_tasks': lambda *args, **kwargs: {},
            },
            'tools.release_operations': {
                'run_release_operations_status': lambda: {},
            },
            'tools.meta_factory_control': {
                'run_control_layer': lambda *args, **kwargs: {},
            },
            'tools.verification_engine': {
                'run_verification': lambda refresh_control_layer=False: {},
            },
            'tools.quality_system': {
                'run_quality': lambda: {},
            },
            'tools.autonomy_score': {
                'run_autonomy_score': lambda *, quality_snapshot=None: {},
            },
            'tools.ai_testing_compat': {
                'run_ai_test_suite': lambda *args, **kwargs: {},
                'load_ai_test_status': lambda report_path=None: {},
            },
            'tools.company_os': {
                'run_company_os_status': lambda: {},
            },
            'tools.automation_lab': {
                'run_automation_lab_status': lambda: {},
            },
            'tools.rnd_delivery_pipeline': {
                'build_rnd_delivery_pipeline_status': lambda: {},
            },
            'tools.rnd_asset_governance': {
                'build_rnd_asset_governance_status': lambda: {},
            },
            'tools.pipeline_status': {
                'build_pipeline_status': lambda *, write_outputs=True: {},
            },
        }
        if name not in specs:
            raise ImportError(name)
        attrs = {
            attr_name: value
            for attr_name, value in specs[name].items()
            if (name, attr_name) not in missing
        }
        return _fake_module(attrs)

    return _fake_import


def test_module_interface_compatibility_full_family_passes(monkeypatch) -> None:
    monkeypatch.setattr(audit.importlib, 'import_module', _fake_import_factory())

    payload = audit._module_interface_compatibility()

    assert payload['status'] == 'pass'
    assert payload['issues'] == []
    assert len(payload['checks']) == len(audit.MODULE_INTERFACE_SPECS)
    assert all(check['status'] == 'pass' for check in payload['checks'])


def test_module_interface_compatibility_reports_missing_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        audit.importlib,
        'import_module',
        _fake_import_factory(missing={('tools.task_state_tools', 'auto_complete_verified_tasks')}),
    )

    payload = audit._module_interface_compatibility()

    assert payload['status'] == 'attention'
    assert any('tools.task_state_tools:auto_complete_verified_tasks' in item for item in payload['issues'])
    assert any(check['module'] == 'tools.task_state_tools' and check['status'] == 'blocked' for check in payload['checks'])


def test_run_tool_health_audit_includes_module_interface_status(monkeypatch) -> None:
    def fake_load(name: str, default):
        return {
            'factory_daemon_state.json': {'status': 'running', 'cycle': 3, 'last_tick_at': '2026-04-10T00:00:00Z', 'updated_at': '2026-04-10T00:00:00Z'},
            'control_layer_status.json': {'status': 'stable', 'decision_engine': {'decisions': []}, 'updated_at': '2026-04-10T00:00:00Z'},
            'quality_status.json': {'status': 'promote', 'overall_score': 0.95},
            'memory_quality_scorecard.json': {'status': 'pass', 'overall_score': 0.95, 'write_quality': {'status': 'pass'}, 'recall_hit_rate': {'status': 'pass'}, 'behavior_binding': {'status': 'pass'}, 'anti_drift': {'status': 'pass'}},
            'memory_muscle_benchmark.json': {'status': 'pass', 'overall_score': 0.95, 'sediment': {'status': 'pass'}, 'promote': {'status': 'pass'}, 'recall': {'status': 'pass'}, 'binding': {'status': 'pass'}, 'reproduce': {'status': 'pass'}},
            'soak_validation.json': {'confirmed': False, 'status': 'stage4_confirmed'},
            'company_os_status.json': {'status': 'pass', 'score': 1.0},
            'automation_lab_status.json': {'status': 'department', 'score': 1.0},
            'verification_status.json': {'status': 'pass'},
        }.get(name, default)

    monkeypatch.setattr(audit, '_load', fake_load)
    monkeypatch.setattr(audit, 'scan_schema_drift', lambda: {'finding_count': 0})
    monkeypatch.setattr(audit, 'load_effective_autonomy', lambda: {'stage': 'stage4_confirmed', 'score': 0.95})
    monkeypatch.setattr(audit, '_module_interface_compatibility', lambda: {'status': 'pass', 'issues': [], 'checks': []})

    payload = audit.run_tool_health_audit()

    assert payload['status'] == 'pass'
    assert payload['module_interface_compatibility']['status'] == 'pass'
    assert payload['module_interface_compatibility']['checks'] == []
