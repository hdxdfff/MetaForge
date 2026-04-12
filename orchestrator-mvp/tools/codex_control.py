from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.venv' / 'Lib' / 'site-packages'))
CODEX_ROOT = ROOT.parent
if os.name == "nt":
    PYTHON_EXE = CODEX_ROOT / 'tools' / 'python311-embed' / 'python.exe'
else:
    PYTHON_EXE = Path(sys.executable)
VMCTL = Path(r"D:\codex\vm-entry.cmd")
REMOTE_WORKSPACE = "/srv/orchestrator-mvp"
REMOTE_SCRIPT = "/srv/orchestrator-mvp/tools/codex_control.py"
REMOTE_PYTHON = "/srv/orchestrator-mvp/.venv/bin/python"
DAEMON_STARTER = ROOT / 'tools' / 'start_factory_daemon.py'
CONTRACTS = ROOT / 'contracts'
TOOL_STACK_PATH = CONTRACTS / 'tool_stack.json'

import importlib
from tools.session_guard import authorize, close_session, current_session, list_sessions, open_session
from tools.execution_engine import python_command, run_hidden
from tools.tool_stack import detect_surface_availability, load_tool_stack, recommend_surface, route_task, launch_task


def _lazy_func(module_name: str, attr_name: str):
    def _call(*args, **kwargs):
        module = importlib.import_module(module_name)
        func = getattr(module, attr_name)
        globals()[attr_name] = func
        return func(*args, **kwargs)
    return _call


def _get_client():
    client = globals().get('_client')
    if client is not None:
        return client
    testclient = importlib.import_module('fastapi.testclient').TestClient
    app = importlib.import_module('app.main').app
    client = testclient(app)
    globals()['_client'] = client
    return client


build_snapshot = _lazy_func('tools.brain_snapshot', 'build_snapshot')
run_brain_loop = _lazy_func('tools.brain_loop', 'run_once')
rebuild_memory = _lazy_func('tools.memory_system', 'rebuild_memory')
decide = _lazy_func('tools.privilege_policy', 'decide')
load_policy = _lazy_func('tools.privilege_policy', 'load_policy')
load_control_policy = _lazy_func('tools.control_plane_policy', 'load_control_policy')
run_binary_classification_lab = _lazy_func('tools.binary_classification_lab_runner', 'run_binary_classification_lab')
project_session_policy = _lazy_func('tools.control_plane_policy', 'project_session_policy')
project_tool_policy = _lazy_func('tools.control_plane_policy', 'project_tool_policy')
create_goal = _lazy_func('tools.goal_registry', 'create_goal')
list_goals = _lazy_func('tools.goal_registry', 'list_goals')
goal_report = _lazy_func('tools.goal_registry', 'goal_report')
sync_goal_runtime = _lazy_func('tools.goal_runtime', 'sync_goal_runtime')
run_goal_storage_audit = _lazy_func('tools.goal_storage_audit', 'run_goal_storage_audit')
daemon_status = _lazy_func('tools.factory_daemon', 'daemon_status')
active_goals = _lazy_func('runtime.goal_manager', 'active_goals')
generate_platform = _lazy_func('runtime.platform_generator', 'generate_platform')
list_capabilities = _lazy_func('tools.capability_registry', 'list_capabilities')
rebuild_graph = _lazy_func('tools.capability_registry', 'rebuild_graph')
route_capability = _lazy_func('tools.capability_registry', 'route_capability')
list_tools = _lazy_func('tools.tool_registry', 'list_tools')
route_tool = _lazy_func('tools.tool_registry', 'route_tool')
list_vm_templates = _lazy_func('tools.vm_orchestrator', 'list_templates')
list_vms = _lazy_func('tools.vm_orchestrator', 'list_vms')
vm_status = _lazy_func('tools.vm_orchestrator', 'vm_status')
create_vm = _lazy_func('tools.vm_orchestrator', 'create_vm')
start_vm = _lazy_func('tools.vm_orchestrator', 'start_vm')
stop_vm = _lazy_func('tools.vm_orchestrator', 'stop_vm')
snapshot_vm = _lazy_func('tools.vm_orchestrator', 'snapshot_vm')
choose_template_for_task = _lazy_func('tools.vm_orchestrator', 'choose_template_for_task')
get_vm_logs = _lazy_func('tools.vm_orchestrator', 'get_vm_logs')
list_platforms = _lazy_func('tools.platform_registry', 'list_platforms')
list_templates = _lazy_func('tools.platform_registry', 'list_templates')
run_maintenance = _lazy_func('tools.runtime_maintenance', 'run_maintenance')
run_smoke_hygiene = _lazy_func('tools.runtime_maintenance', 'run_smoke_hygiene')
run_schema_hygiene_smoke = _lazy_func('tools.schema_hygiene', 'run_schema_hygiene_smoke')
run_self_improvement_status = _lazy_func('tools.self_patch_loop', 'self_improvement_status')
run_guard = _lazy_func('tools.ai_guard', 'run_guard')
run_fact_gate_convergence = _lazy_func('tools.fact_gate_convergence', 'run_fact_gate_convergence')
run_control_layer = _lazy_func('tools.meta_factory_control', 'run_control_layer')
run_quality = _lazy_func('tools.quality_system', 'run_quality')
run_autonomy_score = _lazy_func('tools.autonomy_score', 'run_autonomy_score')
run_soak_validation = _lazy_func('tools.soak_validation', 'run_soak_validation')
rebuild_knowledge = _lazy_func('tools.knowledge_engine', 'rebuild_knowledge')
platform_health_summary = _lazy_func('tools.platform_registry', 'platform_health_summary')
run_training = _lazy_func('tools.skill_training_loop', 'run_training')
plan_experiments = _lazy_func('tools.experiment_planner', 'plan_experiments')
run_experiment = _lazy_func('tools.experiment_executor', 'run_experiment')
evaluate_experiment = _lazy_func('tools.experiment_evaluator', 'evaluate_experiment')
build_code_knowledge_graph = _lazy_func('tools.code_knowledge_graph', 'build_code_knowledge_graph')
build_module_ownership_graph = _lazy_func('tools.module_ownership_graph', 'build_module_ownership_graph')
build_review_policy_graph = _lazy_func('tools.module_ownership_graph', 'build_review_policy_graph')
analyze_dependency_impact = _lazy_func('tools.dependency_impact_engine', 'analyze_dependency_impact')
build_project_graph = _lazy_func('tools.project_graph', 'build_project_graph')
run_cross_project_coordination = _lazy_func('tools.cross_project_coordination', 'run_cross_project_coordination')
build_organization_model = _lazy_func('tools.organization_model', 'build_organization_model')
build_organization_workboard = _lazy_func('tools.organization_workboard', 'build_organization_workboard')
run_architecture_validation = _lazy_func('tools.architecture_validator', 'run_architecture_validation')
run_verification = _lazy_func('tools.verification_engine', 'run_verification')
schedule_nodes = _lazy_func('runtime.scheduler', 'schedule_nodes')
ensure_graph = _lazy_func('runtime.taskgraph_engine', 'ensure_graph')
ready_nodes = _lazy_func('runtime.taskgraph_engine', 'ready_nodes')
load_state = _lazy_func('state.store', 'load_state')
list_patch_submissions = _lazy_func('tools.module_ownership', 'list_patch_submissions')
resolve_patch_submission = _lazy_func('tools.module_ownership', 'resolve_patch_submission')
patch_submission_status_summary = _lazy_func('tools.module_ownership', 'patch_submission_status_summary')
run_automation_lab_status = _lazy_func('tools.automation_lab', 'run_automation_lab_status')
run_release_operations_status = _lazy_func('tools.release_operations', 'run_release_operations_status')
run_company_os_status = _lazy_func('tools.company_os', 'run_company_os_status')
run_release_train = _lazy_func('tools.release_train_runtime', 'run_release_train')
run_coordination = _lazy_func('tools.coordination_runtime', 'run_coordination')
rebuild = _lazy_func('tools.context_kernel', 'rebuild')
analyze_change_request = _lazy_func('tools.change_request_analyzer', 'analyze_change_request')
build_replan = _lazy_func('tools.replan_engine', 'build_replan')
summarize_cache = _lazy_func('tools.context_cache', 'summarize_cache')
purge_stale_cache_entries = _lazy_func('tools.context_cache', 'purge_stale_cache_entries')
run_tool_health_audit = _lazy_func('tools.tool_health_audit', 'run_tool_health_audit')
read_tool_health_history = _lazy_func('tools.tool_health_audit', 'read_tool_health_history')
run_environment_repair_lane = _lazy_func('tools.environment_repair_lane', 'run_environment_repair_lane')
build_rnd_department_status = _lazy_func('tools.rnd_department', 'build_rnd_department_status')
build_rnd_delivery_pipeline_status = _lazy_func('tools.rnd_delivery_pipeline', 'build_rnd_delivery_pipeline_status')
build_rnd_asset_governance_status = _lazy_func('tools.rnd_asset_governance', 'build_rnd_asset_governance_status')
build_pipeline_status = _lazy_func('tools.pipeline_status', 'build_pipeline_status')
build_branch_workboard = _lazy_func('tools.branch_workboard', 'build_branch_workboard')
branch_context_summary = _lazy_func('tools.branch_workboard', 'branch_context_summary')
create_branch_goal = _lazy_func('tools.branch_workboard', 'create_branch_goal')
run_ai_test_suite = _lazy_func('tools.ai_testing_compat', 'run_ai_test_suite')
load_ai_test_status = _lazy_func('tools.ai_testing_compat', 'load_ai_test_status')
run_factory_self_report = _lazy_func('tools.factory_self_report', 'run_factory_self_report')
run_report_chain = _lazy_func('tools.report_chain', 'build_report_chain')
build_self_model = _lazy_func('tools.self_model', 'build_self_model')
run_self_model_cycle = _lazy_func('tools.self_model', 'run_self_model_cycle')
scan_github_repositories = _lazy_func('tools.github_learning_engine', 'scan_github_repositories')
clone_learning_target = _lazy_func('tools.github_learning_engine', 'clone_learning_target')
load_github_learning_status = _lazy_func('tools.github_learning_engine', 'github_learning_status')
build_scheduling_snapshot = _lazy_func('tools.scheduling_kernel', 'build_scheduling_snapshot')
run_perplexity_search = _lazy_func('tools.perplexity_search', 'run_perplexity_search')
load_internet_knowledge = _lazy_func('tools.perplexity_search', 'load_internet_knowledge')
load_perplexity_status = _lazy_func('tools.perplexity_search', 'load_perplexity_status')
publish_ai_runtime_state = _lazy_func('tools.ai_runtime_observability', 'publish_ai_runtime_state')
load_ai_runtime_state = _lazy_func('tools.ai_runtime_observability', 'load_ai_runtime_state')
resolve_ai_path = _lazy_func('tools.ai_runtime_observability', 'resolve_ai_path')
load_kernel_mode = _lazy_func('tools.kernel_mode', 'load_kernel_mode')
apply_execution_profile = _lazy_func('tools.kernel_mode', 'apply_execution_profile')
dialogue_status = _lazy_func('tools.dialogue_memory', 'dialogue_status')
sync_dialogue = _lazy_func('tools.dialogue_memory', 'sync_dialogue')
rebuild_dialogue_memory = _lazy_func('tools.dialogue_memory', 'rebuild_dialogue_memory')
repair_dialogue_memory = _lazy_func('tools.dialogue_memory', 'repair_dialogue_memory')
memory_status_report = _lazy_func('tools.memory_objects', 'status_report')
bootstrap_memory_objects = _lazy_func('tools.memory_objects', 'bootstrap_memory_objects')
harvest_memory_candidates = _lazy_func('tools.memory_objects', 'harvest_memory_candidates')
auto_promote_memory_candidates = _lazy_func('tools.memory_objects', 'auto_promote_candidates')
memory_integrity_report = _lazy_func('tools.memory_objects', 'memory_integrity_report')
recall_memory_objects = _lazy_func('tools.memory_objects', 'recall_memory_objects')
promote_memory_candidate = _lazy_func('tools.memory_objects', 'promote_candidate')
memory_quality_scorecard_status = _lazy_func('tools.memory_quality_scorecard', 'memory_quality_scorecard_status')
build_memory_quality_scorecard = _lazy_func('tools.memory_quality_scorecard', 'build_memory_quality_scorecard')
memory_muscle_benchmark_status = _lazy_func('tools.memory_muscle_benchmark', 'memory_muscle_benchmark_status')
build_memory_muscle_benchmark = _lazy_func('tools.memory_muscle_benchmark', 'build_memory_muscle_benchmark')
identity_kernel_status = _lazy_func('tools.identity_kernel', 'identity_kernel_status')
refresh_identity_kernel = _lazy_func('tools.identity_kernel', 'refresh_identity_kernel')
system_identity_status = _lazy_func('tools.identity_kernel', 'system_identity_status')
refresh_system_identity_ssot = _lazy_func('tools.identity_kernel', 'refresh_system_identity_ssot')
DATA = ROOT / 'data'
STATUS_CACHE = DATA / 'status_cache.json'
FACTORY_STATE = DATA / 'factory_state.json'
CONTROL_LAYER_STATUS = DATA / 'control_layer_status.json'


def out(payload):
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(rendered)
    except UnicodeEncodeError:
        safe = rendered.encode('gbk', errors='replace').decode('gbk', errors='replace')
        print(safe)


def require_authorized(command: str, token: str | None):
    ok, reason, details = authorize(command, token)
    if not ok:
        raise SystemExit(json.dumps({'error': reason, 'authorization': details}, ensure_ascii=False, indent=2))
    return details


def _load_json(name: str, default):
    path = DATA / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _read_json_path(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def _read_status_cache():
    return _read_json_path(STATUS_CACHE, {})


def _read_factory_state():
    return _read_json_path(FACTORY_STATE, {})


def _read_control_layer_cache():
    return _read_json_path(CONTROL_LAYER_STATUS, {})


def _read_daemon_state_fallback():
    return _read_json_path(DATA / 'factory_daemon_state.json', {})


def _delivery_summary_from_task_runtime(
    task_runtime: dict[str, Any] | None,
    release_operations: dict[str, Any] | None = None,
) -> dict[str, int]:
    task_runtime = task_runtime or {}
    by_status = task_runtime.get('by_status') or {}
    release_operations = release_operations or {}
    delivery_counts = ((release_operations.get('delivery_ready_state_machine') or {}).get('counts') or {})
    return {
        'completed_tasks': int(by_status.get('completed') or 0) + int(by_status.get('released') or 0),
        'delivery_ready_tasks': int(delivery_counts.get('delivery_ready') or by_status.get('delivery_ready') or 0),
        'released_tasks': int(delivery_counts.get('released') or by_status.get('released') or 0),
        'verification_failed_tasks': int(delivery_counts.get('verification_failed') or by_status.get('verification_failed') or 0),
    }


def _preview_checks(checks: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(checks, list):
        return []
    preview: list[dict[str, Any]] = []
    for item in checks[:limit]:
        if isinstance(item, dict):
            preview.append({
                'name': item.get('name'),
                'status': item.get('status'),
                'effect': item.get('effect'),
                'affects_runtime': item.get('affects_runtime'),
                'affects_release': item.get('affects_release'),
                'affects_reporting': item.get('affects_reporting'),
                'next_action': item.get('next_action'),
            })
    return preview


def _control_layer_cache_is_fresh(max_age_seconds: int = 30) -> bool:
    if not CONTROL_LAYER_STATUS.exists():
        return False
    try:
        age_seconds = time.time() - CONTROL_LAYER_STATUS.stat().st_mtime
    except OSError:
        return False
    return age_seconds <= max_age_seconds


def _read_tool_stack():
    default = {
        'version': 'v1',
        'primary_interactive_surface': 'Aider',
        'control_shells': ['OpenCode', 'Goose'],
        'control_plane': 'MetaForge',
        'long_task_executors': ['OpenHands', 'Plandex'],
        'development_executors': ['Codex'],
        'inspection_surface': 'Continue',
        'final_verification_boundary': ['Verification', 'Artifact'],
        'routing': [],
    }
    return _read_json_path(TOOL_STACK_PATH, default)


def _build_live_tool_stack():
    stack = _read_tool_stack()
    stack['availability'] = detect_surface_availability()
    return stack


def _status_summary_payload():
    cache = _read_status_cache()
    factory_state = _read_factory_state()
    cached_daemon = factory_state.get('daemon') or cache.get('daemon') or {}
    delivery_summary = _delivery_summary_from_task_runtime(factory_state.get('task_runtime') or cache.get('task_runtime'))
    return {
        'mode': 'cached_summary',
        'cached': bool(factory_state or cache),
        'cache_updated_at': factory_state.get('updated_at') or cache.get('updated_at'),
        'daemon': {
            'status': cached_daemon.get('status'),
            'pid': cached_daemon.get('pid'),
            'cycle': cached_daemon.get('cycle'),
            'interval_seconds': cached_daemon.get('interval_seconds'),
            'last_tick_at': cached_daemon.get('last_tick_at'),
            'started_at': cached_daemon.get('started_at'),
            'last_error': cached_daemon.get('last_error'),
        },
        'sessions': {
            'active_count': len(list_sessions()),
            'active': current_session(),
        },
        'task_runtime': factory_state.get('task_runtime', {}),
        'messages': factory_state.get('messages', {}),
        'control_layer': factory_state.get('control_layer') or cache.get('control_layer', {}),
        'engineering_os': factory_state.get('engineering_os') or cache.get('engineering_os', {}),
        'autonomy': factory_state.get('autonomy') or cache.get('autonomy', {}),
        'tool_health': factory_state.get('tool_health') or cache.get('tool_health', {}),
        'release_ops': factory_state.get('release_ops') or cache.get('release_ops', {}),
        'ai_testing': factory_state.get('ai_testing') or cache.get('ai_testing') or load_ai_test_status(),
        'delivery_summary': delivery_summary,
        'consistency': factory_state.get('consistency', {}),
        'hint': 'Use --refresh for live recomputation.',
    }


def _control_layer_summary_payload(payload):
    decision_engine = payload.get('decision_engine') or {}
    quality_system = payload.get('quality_system') or {}
    memory_quality_scorecard = payload.get('memory_quality_scorecard') or {}
    identity_gate = payload.get('identity_gate') or {}
    engineering_os = payload.get('engineering_os') or {}
    tool_health = payload.get('tool_health') or {}
    ai_testing = payload.get('ai_testing') or {}
    release_operations = payload.get('release_operations') or {}
    release_train = release_operations.get('release_train') or {}
    automation_lab = payload.get('automation_lab') or {}
    factory_state = _read_factory_state()
    delivery_summary = _delivery_summary_from_task_runtime(
        payload.get('task_runtime')
        or payload.get('delivery_summary')
        or factory_state.get('task_runtime')
        or {},
        release_operations,
    )
    return {
        'mode': 'cached_summary',
        'updated_at': payload.get('updated_at'),
        'status': payload.get('status'),
        'control_policy': payload.get('control_policy', {}),
        'decision_engine': {
            'mode': decision_engine.get('mode'),
            'decision_count': decision_engine.get('decision_count'),
            'decisions': (decision_engine.get('decisions') or [])[:5],
        },
        'quality_system': {
            'status': quality_system.get('status'),
            'overall_score': quality_system.get('overall_score'),
            'promoted_platform_count': quality_system.get('promoted_platform_count'),
            'promoted_candidate_count': quality_system.get('promoted_candidate_count'),
            'readiness_summary': quality_system.get('readiness_summary') or {},
            'readiness_checks': _preview_checks(quality_system.get('readiness_checks') or []),
        },
        'memory_quality_scorecard': {
            'status': memory_quality_scorecard.get('status'),
            'overall_score': memory_quality_scorecard.get('overall_score'),
            'write_quality': memory_quality_scorecard.get('write_quality'),
            'recall_hit_rate': memory_quality_scorecard.get('recall_hit_rate'),
            'behavior_binding': memory_quality_scorecard.get('behavior_binding'),
            'anti_drift': memory_quality_scorecard.get('anti_drift'),
        },
        'delivery_summary': delivery_summary,
        'identity_gate': {
            'status': identity_gate.get('status'),
            'consistency': identity_gate.get('consistency') or {},
            'memory': identity_gate.get('memory') or {},
            'authority': identity_gate.get('authority') or {},
            'runtime': identity_gate.get('runtime') or {},
            'updated_at': identity_gate.get('updated_at'),
        },
        'engineering_os': {
            'status': engineering_os.get('status'),
            'patch_gate_status': engineering_os.get('patch_gate_status'),
            'delayed_verification_status': engineering_os.get('delayed_verification_status'),
            'release_gate_status': engineering_os.get('release_gate_status'),
            'patch_ready_count': engineering_os.get('patch_ready_count'),
            'patch_blocked_count': engineering_os.get('patch_blocked_count'),
            'active_branch_lane_count': engineering_os.get('active_branch_lane_count'),
        },
        'tool_health': {
            'status': tool_health.get('status'),
            'issue_count': tool_health.get('issue_count'),
            'issues': (tool_health.get('issues') or [])[:5],
        },
        'ai_testing': {
            'status': ai_testing.get('status'),
            'overall_score': ai_testing.get('overall_score'),
            'pass_rate': ai_testing.get('pass_rate'),
            'error_count': ai_testing.get('error_count'),
            'failing_case_ids': (ai_testing.get('failing_case_ids') or [])[:5],
        },
        'release_operations': {
            'status': release_operations.get('status'),
            'release_train_status': release_operations.get('release_train_status') or release_train.get('status'),
            'next_action': release_operations.get('next_action') or release_train.get('next_action'),
            'blocking_enforced': release_operations.get('blocking_enforced'),
            'release_claim_policy': release_operations.get('release_claim_policy') or {},
            'readiness_summary': release_operations.get('readiness_summary') or {},
            'readiness_checks': _preview_checks(release_operations.get('readiness_checks') or []),
            'promotion_gate': release_operations.get('promotion_gate') or {},
            'delivery_ready_state_machine': release_operations.get('delivery_ready_state_machine') or {},
            'promotion_lifecycle': release_operations.get('promotion_lifecycle') or {},
            'lane_pipeline': release_operations.get('lane_pipeline') or {},
        },
        'change_attribution': payload.get('change_attribution') or {},
        'self_repair_playbooks': payload.get('self_repair_playbooks') or {},
        'automation_lab': {
            'status': automation_lab.get('status'),
        },
        'autonomy_score': payload.get('autonomy_score', {}),
        'hint': 'Use --refresh for live recomputation.',
    }


def _engineering_os_summary_payload(payload):
    patch_system = payload.get('patch_system') or {}
    verification_engine = payload.get('verification_engine') or {}
    architecture_validator = payload.get('architecture_validator') or {}
    code_knowledge_graph = payload.get('code_knowledge_graph') or {}
    branch_system = payload.get('branch_system') or {}
    memory_quality_scorecard = payload.get('memory_quality_scorecard') or {}
    identity_gate = payload.get('identity_gate') or payload.get('identity_integrity') or payload.get('identity_kernel') or {}
    return {
        'mode': 'cached_summary',
        'updated_at': payload.get('updated_at'),
        'engineering_os': payload.get('engineering_os', {}),
        'memory_quality_scorecard': {
            'status': memory_quality_scorecard.get('status'),
            'overall_score': memory_quality_scorecard.get('overall_score'),
            'write_quality': memory_quality_scorecard.get('write_quality'),
            'recall_hit_rate': memory_quality_scorecard.get('recall_hit_rate'),
            'behavior_binding': memory_quality_scorecard.get('behavior_binding'),
            'anti_drift': memory_quality_scorecard.get('anti_drift'),
        },
        'identity_gate': {
            'status': identity_gate.get('status'),
            'consistency': identity_gate.get('consistency') or {},
            'memory': identity_gate.get('memory') or {},
            'authority': identity_gate.get('authority') or {},
            'runtime': identity_gate.get('runtime') or {},
            'updated_at': identity_gate.get('updated_at'),
        },
        'patch_system': {
            'submission_count': patch_system.get('submission_count'),
            'open_count': patch_system.get('open_count'),
            'verified_count': patch_system.get('verified_count'),
            'ready_count': patch_system.get('ready_count'),
            'merged_count': patch_system.get('merged_count'),
            'review_pending_count': patch_system.get('review_pending_count'),
            'queue': {
                'ready_count': ((patch_system.get('queue') or {}).get('ready_count')),
                'blocked_count': ((patch_system.get('queue') or {}).get('blocked_count')),
                'review_pending_count': ((patch_system.get('queue') or {}).get('review_pending_count')),
            },
            'recent': [
                {
                    'patch_id': item.get('patch_id'),
                    'status': item.get('status'),
                    'title': item.get('title'),
                    'verification_status': item.get('verification_status'),
                }
                for item in (patch_system.get('recent') or [])[:5]
            ],
        },
        'verification_engine': {
            'status': verification_engine.get('status'),
            'compileall_passed': verification_engine.get('compileall_passed'),
            'patch_gate_status': verification_engine.get('patch_gate_status'),
            'delayed_verification_status': verification_engine.get('delayed_verification_status'),
            'release_gate_status': verification_engine.get('release_gate_status'),
            'runtime_health_status': verification_engine.get('runtime_health_status'),
            'tool_health_status': verification_engine.get('tool_health_status'),
        },
        'architecture_validator': {
            'status': architecture_validator.get('status'),
            'violation_count': architecture_validator.get('violation_count'),
        },
        'code_knowledge_graph': {
            'status': code_knowledge_graph.get('status'),
            'module_count': code_knowledge_graph.get('module_count'),
            'edge_count': code_knowledge_graph.get('edge_count'),
            'domains': (code_knowledge_graph.get('domains') or [])[:8],
        },
        'branch_system': {
            'status': branch_system.get('status'),
            'lane_count': branch_system.get('lane_count'),
            'active_lane_count': branch_system.get('active_lane_count'),
        },
        'hint': 'Use --refresh for live recomputation.',
    }


def cmd_status(args):
    if not args.refresh and (STATUS_CACHE.exists() or FACTORY_STATE.exists()):
        out(_status_summary_payload())
        return
    kernel = rebuild()
    memory = rebuild_memory()
    payload = {
        'mode': 'refreshed',
        'health': _get_client().get('/api/health').json(),
        'control_center': _get_client().get('/api/control-center/status').json(),
        'meta_factory': _get_client().get('/api/meta-factory/status').json(),
        'evolution': _get_client().get('/api/evolution/status').json(),
        'control_layer': run_control_layer(),
        'context_kernel': kernel,
        'memory_kernel': memory,
        'brain_snapshot': build_snapshot().get('summary', {}),
        'ai_testing': load_ai_test_status(),
    }
    out(payload)


def cmd_light_status(_args):
    payload = _status_summary_payload()
    payload['lab'] = _read_status_cache().get('lab', {})
    out(payload)


def cmd_tool_stack_status(args):
    stack = _build_live_tool_stack() if getattr(args, 'refresh', False) else _read_tool_stack()
    registry = _read_json_path(ROOT / 'contracts' / 'executors' / 'executor_registry.json', {})
    policy = _read_json_path(ROOT / 'contracts' / 'executors' / 'routing_policy.json', {})
    verification = _read_json_path(ROOT / 'contracts' / 'executors' / 'verification_policy.json', {})
    out({
        'mode': 'live_summary' if getattr(args, 'refresh', False) else 'cached_summary',
        'updated_at': stack.get('updated_at'),
        'tool_stack': stack,
        'executor_registry_version': registry.get('version'),
        'routing_policy_version': policy.get('version'),
        'verification_policy_version': verification.get('version'),
        'executors': list(registry.get('executors') or []),
        'routing_rules': list(policy.get('rules') or []),
        'verification_levels': list(verification.get('levels') or []),
        'availability': detect_surface_availability(),
    })


def cmd_tool_stack_route(args):
    out(route_task(args.request, workspace=str(CODEX_ROOT)))


def cmd_task_route(args):
    out(route_task(args.request, workspace=str(getattr(args, 'workspace', None) or CODEX_ROOT)))


def cmd_task_launch(args):
    out(
        launch_task(
            args.request,
            workspace=str(getattr(args, 'workspace', None) or CODEX_ROOT),
            prefer=getattr(args, 'prefer', None),
        )
    )


def cmd_live_status(_args):
    daemon = daemon_status()
    kernel = rebuild()
    runtime_state = load_state()
    payload = {
        'brain_loop': {
            'status': daemon.get('status'),
            'running': daemon.get('running'),
            'tick': daemon.get('cycle'),
            'last_tick_at': daemon.get('last_tick_at'),
        },
        'runtime': {
            'active_goals': len(active_goals()),
            'brain_loop_state': runtime_state.get('brain_loop_state', {}),
            'memory_kernel': runtime_state.get('memory_kernel', {}),
        },
        'tasks': {
            'active': kernel.get('hot_context', {}).get('active_task_count', 0),
            'failed': kernel.get('hot_context', {}).get('failed_task_count', 0),
            'open_escalations': kernel.get('hot_context', {}).get('open_escalation_count', 0),
        },
        'active_tasks': kernel.get('hot_context', {}).get('active_tasks', [])[:8],
    }
    out(payload)



def _graph_node_title(goal_id: str | None, node_id: str | None):
    if not goal_id or not node_id:
        return None
    try:
        goals = list_goals()
    except Exception:
        return None
    goal = next((item for item in goals if item.get('goal_id') == goal_id), None)
    if not goal or not goal.get('graph_id'):
        return None
    path = ROOT / 'factory' / 'graphs' / f"{goal['graph_id']}.json"
    if not path.exists():
        return None
    try:
        graph = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return None
    node = next((item for item in graph.get('nodes', []) if item.get('id') == node_id), None)
    return (node or {}).get('title')
def cmd_tasks(args):
    tasks = _load_json('tasks.json', [])
    items = []
    for task in tasks:
        if args.active_only and task.get('status') not in {'queued', 'planning', 'running', 'waiting_approval'}:
            continue
        if args.failed_only and task.get('status') != 'failed':
            continue
        goal_id = task.get('goal_id') or ((task.get('scheduler_hint') or {}).get('goal_id'))
        node_id = task.get('node_id') or ((task.get('scheduler_hint') or {}).get('node_id'))
        title = task.get('title') or ((task.get('scheduler_hint') or {}).get('node_title')) or _graph_node_title(goal_id, node_id)
        items.append({
            'id': task.get('id'),
            'status': task.get('status'),
            'title': title,
            'goal': task.get('goal'),
            'goal_id': goal_id,
            'node_id': node_id,
            'repo_path': task.get('repo_path'),
            'updated_at': task.get('updated_at'),
        })
    out(items[: args.limit])


def cmd_task(args):
    tasks = _load_json('tasks.json', [])
    task = next((item for item in tasks if item.get('id') == args.task_id), None)
    if task is None:
        raise SystemExit('Task not found')
    out(task)


def cmd_agents(_args):
    tasks = _load_json('tasks.json', [])
    agents = []
    for task in tasks:
        if task.get('status') not in {'queued', 'planning', 'running', 'waiting_approval'}:
            continue
        running_steps = [step for step in task.get('plan', []) if step.get('status') == 'running']
        if running_steps:
            for step in running_steps:
                agents.append({
                    'task_id': task.get('id'),
                    'worker': step.get('worker'),
                    'phase': step.get('phase'),
                    'step_title': step.get('title'),
                    'repo_path': task.get('repo_path'),
                })
        else:
            agents.append({
                'task_id': task.get('id'),
                'worker': 'supervisor',
                'phase': task.get('status'),
                'step_title': task.get('goal') or task.get('prompt', '')[:80],
                'repo_path': task.get('repo_path'),
            })
    out(agents)


def cmd_logs(args):
    path = DATA / 'factory_daemon.log'
    if not path.exists():
        out([])
        return
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    out(lines[-args.tail:])


def cmd_taskgraph(args):
    graphs_dir = ROOT / 'factory' / 'graphs'
    graph = None
    if args.graph_id:
        path = graphs_dir / f'{args.graph_id}.json'
        if path.exists():
            graph = json.loads(path.read_text(encoding='utf-8-sig'))
    elif args.goal_id:
        goals = list_goals()
        goal = next((item for item in goals if item.get('goal_id') == args.goal_id), None)
        if goal and goal.get('graph_id'):
            path = graphs_dir / f"{goal['graph_id']}.json"
            if path.exists():
                graph = json.loads(path.read_text(encoding='utf-8-sig'))
    if graph is None:
        raise SystemExit('Taskgraph not found')
    out(graph)


def cmd_inbox(args):
    rebuild()
    payload = json.loads((DATA / 'escalation_inbox.json').read_text(encoding='utf-8'))
    if args.open_only:
        payload = [item for item in payload if item.get('status', 'open') == 'open']
    out(payload)


def cmd_escalations(args):
    messages = _get_client().get('/api/core-messages').json()
    items = messages
    if args.open_only:
        items = [item for item in items if item.get('status', 'open') == 'open']
    if args.severity:
        items = [item for item in items if item.get('severity') == args.severity]
    out(items[: args.limit])


def cmd_patches(args):
    items = list_patch_submissions(status=args.status)
    if args.open_only:
        items = [item for item in items if item.get('status') in {'open', 'proposed'}]
    out(items[: args.limit])


def cmd_patch_approve(args):
    require_authorized('patch-approve', args.session_token)
    out(resolve_patch_submission(args.patch_id, status='approved', resolution=args.resolution))


def cmd_patch_reject(args):
    require_authorized('patch-reject', args.session_token)
    out(resolve_patch_submission(args.patch_id, status='rejected', resolution=args.resolution))


def cmd_patch_status(_args):
    out(patch_submission_status_summary())


def cmd_patch_merge(args):
    require_authorized('patch-merge', args.session_token)
    out(resolve_patch_submission(args.patch_id, status='merged', resolution=args.resolution))


def cmd_branch_workboard(_args):
    out(build_branch_workboard())

def cmd_branch_goal(args):
    source = args.source_session or f"{args.branch_name}-session"
    out(create_branch_goal(
        args.target,
        branch_name=args.branch_name,
        department=args.department,
        goal_type=args.goal_type,
        notes=args.notes,
        source_session=source,
        lane_role=args.lane_role,
    ))


def cmd_mainline_goal(args):
    out(create_goal(
        args.target,
        goal_type=args.goal_type,
        notes=args.notes,
        lane="mainline",
        lane_role="architecture_mainline",
        assigned_department="architecture_department",
        source_session=args.source_session or "mainline-control",
        shares_mainline_context=True,
        upstream_context_refs=["mainline", "global_policy", "knowledge_base", "control_layer", "engineering_os", "automation_lab"],
    ))


def _create_specialized_branch_goal(args, lane_role: str, department: str):
    source = args.source_session or f"{args.branch_name}-session"
    out(create_branch_goal(
        args.target,
        branch_name=args.branch_name,
        department=args.department or department,
        goal_type=args.goal_type,
        notes=args.notes,
        source_session=source,
        lane_role=lane_role,
    ))


def cmd_branch_capability_goal(args):
    _create_specialized_branch_goal(args, "capability_branch", "engineering_department")


def cmd_branch_test_goal(args):
    _create_specialized_branch_goal(args, "testing_branch", "qa_department")


def cmd_branch_production_goal(args):
    _create_specialized_branch_goal(args, "production_instance_branch", "operations_department")


def cmd_branch_context(args):
    out(branch_context_summary(args.branch_name))

def cmd_branch_status(_args):
    workboard = build_branch_workboard()
    out({
        'updated_at': workboard.get('updated_at'),
        'lane_count': workboard.get('lane_count', 0),
        'active_lane_count': workboard.get('active_lane_count', 0),
        'department_priority_map': workboard.get('department_priority_map', {}),
        'active_lanes': workboard.get('active_lanes', []),
    })

def cmd_release_ops_status(_args):
    out(run_release_operations_status())


def cmd_company_os_status(_args):
    out(run_company_os_status())


def cmd_rnd_status(_args):
    out(build_rnd_department_status())


def cmd_rnd_pipeline_status(_args):
    payload = dict(build_rnd_delivery_pipeline_status())
    payload['pipeline_status'] = build_pipeline_status()
    out(payload)


def cmd_rnd_assets_status(_args):
    out(build_rnd_asset_governance_status())


def cmd_release_train(_args):
    release_ops = run_release_operations_status()
    out(run_release_train(
        runtime_ok=(release_ops.get('operations_readiness') or {}).get('runtime_ok', False),
        verification_ok=(release_ops.get('operations_readiness') or {}).get('verification_ok', False),
        control_ok=(release_ops.get('operations_readiness') or {}).get('control_ok', False),
        blocked_patch_count=(release_ops.get('release_train') or {}).get('blocked_patch_count', 0),
    ))


def cmd_coordinate_projects(args):
    coordination = run_cross_project_coordination(limit=args.limit)
    out(run_coordination(coordination.get('selected') or [], target=args.target, limit=args.limit))


def cmd_dispatch(args):
    require_authorized('dispatch', args.session_token)
    payload = {
        'prompt': args.prompt,
        'goal': args.goal,
        'caller': args.caller,
        'repo_path': args.repo_path,
        'project_id': args.project_id,
        'repo_id': args.repo_id,
        'auto_approve': args.auto_approve,
        'enqueue_only': args.enqueue_only,
        'allow_resource_scan': not args.no_resource_scan,
        'allow_repo_status': not args.no_repo_status,
    }
    if args.capability_request:
        payload['capability_request'] = args.capability_request
    if args.vm_request:
        payload['vm_request'] = args.vm_request
    if args.context_mode:
        payload['context_mode'] = args.context_mode
    if args.max_context_chars:
        payload['max_context_chars'] = args.max_context_chars
    created = _get_client().post('/api/dispatch', json=payload).json()
    task_id = str(created.get('id') or '').strip()
    if task_id:
        refreshed = _get_client().get(f'/api/tasks/{task_id}').json()
        if isinstance(refreshed, dict):
            created['executor_id'] = refreshed.get('executor_id', created.get('executor_id'))
            created['executor_route'] = refreshed.get('executor_route', created.get('executor_route'))
            created['surface_route'] = (refreshed.get('executor_route') or {}).get('surface_route')
            created['task_status'] = refreshed.get('status')
    if getattr(args, 'full', False):
        out(created)
        return
    executor_route = created.get('executor_route') or {}
    surface_route = created.get('surface_route') or executor_route.get('surface_route') or {}
    compact = {
        'task_id': created.get('id'),
        'executor_id': created.get('executor_id'),
        'surface_route': surface_route.get('preferred_surface') if isinstance(surface_route, dict) else surface_route,
        'status': created.get('task_status') or created.get('status'),
    }
    out(compact)


def cmd_task_publish(args):
    require_authorized('dispatch', args.session_token)
    path = Path(args.file).expanduser()
    if not path.exists():
        raise SystemExit(f'publish file not found: {path}')
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    created = _get_client().post('/api/task-publish', json=payload).json()
    task_id = str(created.get('id') or '').strip()
    if task_id:
        refreshed = _get_client().get(f'/api/tasks/{task_id}').json()
        if isinstance(refreshed, dict):
            created['executor_id'] = refreshed.get('executor_id', created.get('executor_id'))
            created['executor_route'] = refreshed.get('executor_route', created.get('executor_route'))
            created['surface_route'] = (refreshed.get('executor_route') or {}).get('surface_route')
            created['task_status'] = refreshed.get('status')
    if getattr(args, 'full', False):
        out(created)
        return
    executor_route = created.get('executor_route') or {}
    surface_route = created.get('surface_route') or executor_route.get('surface_route') or {}
    compact = {
        'task_id': created.get('id'),
        'executor_id': created.get('executor_id'),
        'surface_route': surface_route.get('preferred_surface') if isinstance(surface_route, dict) else surface_route,
        'status': created.get('task_status') or created.get('status'),
    }
    out(compact)


def cmd_task_publish_draft(args):
    require_authorized('dispatch', args.session_token)
    path = Path(args.file).expanduser()
    if not path.exists():
        raise SystemExit(f'publish file not found: {path}')
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    created = _get_client().post('/api/task-publish/draft', json=payload).json()
    if getattr(args, 'full', False):
        out(created)
        return
    out({
        'publication_id': created.get('publication_id'),
        'status': created.get('status'),
        'title': created.get('title'),
        'task_type': created.get('task_type'),
        'verification_level': created.get('verification_level'),
    })


def cmd_task_publish_approve(args):
    require_authorized('dispatch', args.session_token)
    payload = {
        'approved_by': args.approved_by,
        'notes': args.notes,
    }
    record = _get_client().post(f'/api/task-publish/{args.publication_id}/approve', json=payload).json()
    if getattr(args, 'full', False):
        out(record)
        return
    out({
        'publication_id': record.get('publication_id'),
        'status': record.get('status'),
        'approved_by': record.get('approved_by'),
        'approved_at': record.get('approved_at'),
    })


def cmd_task_publish_commit(args):
    require_authorized('dispatch', args.session_token)
    payload = {
        'published_by': args.published_by,
        'notes': args.notes,
    }
    task = _get_client().post(f'/api/task-publish/{args.publication_id}/publish', json=payload).json()
    if getattr(args, 'full', False):
        out(task)
        return
    out({
        'task_id': task.get('id'),
        'status': task.get('status'),
        'title': task.get('title'),
        'executor_id': task.get('executor_id'),
    })


def cmd_task_publications(args):
    records = _get_client().get('/api/task-publications').json()
    if getattr(args, 'status', None):
        records = [item for item in records if item.get('status') == args.status]
    if getattr(args, 'task_id', None):
        records = [item for item in records if item.get('task_id') == args.task_id]
    out(records[: args.limit])


def cmd_approve(args):
    require_authorized('approve', args.session_token)
    payload = {
        'resolution': args.resolution,
        'status': 'approved',
    }
    out(_get_client().post(f'/api/core-messages/{args.message_id}/resolve', json=payload).json())


def cmd_reject(args):
    require_authorized('reject', args.session_token)
    payload = {
        'resolution': args.resolution,
        'status': 'rejected',
    }
    out(_get_client().post(f'/api/core-messages/{args.message_id}/resolve', json=payload).json())


def cmd_resolve_escalation(args):
    require_authorized('resolve-escalation', args.session_token)
    payload = {
        'resolution': args.resolution,
        'status': args.status,
    }
    out(_get_client().post(f'/api/core-messages/{args.message_id}/resolve', json=payload).json())


def cmd_reopen_escalation(args):
    require_authorized('reopen-escalation', args.session_token)
    payload = {'reason': args.reason}
    out(_get_client().post(f'/api/core-messages/{args.message_id}/reopen', json=payload).json())


def cmd_quality_status(_args):
    forwarded = _forward_codex_command_to_container('quality-status', [], session_token=None)
    if forwarded is not None:
        out(forwarded)
        return
    path = DATA / 'quality_status.json'
    if not path.exists():
        raise SystemExit('quality_status.json not found; run meta-factory or quality system first')
    out(json.loads(path.read_text(encoding='utf-8-sig')))


def cmd_evolution_control(_args):
    path = DATA / 'evolution_control.json'
    if not path.exists():
        raise SystemExit('evolution_control.json not found; run meta-factory or evolution control first')
    out(json.loads(path.read_text(encoding='utf-8-sig')))


def cmd_guard_status(_args):
    payload = run_guard()
    payload['fact_gate_convergence'] = run_fact_gate_convergence()
    out(payload)


def cmd_fact_gate_convergence(_args):
    out(run_fact_gate_convergence())


def cmd_control_layer_status(args):
    forwarded_args = ['--refresh'] if args.refresh else []
    forwarded = _forward_codex_command_to_container('control-layer-status', forwarded_args, session_token=None)
    if forwarded is not None:
        out(forwarded)
        return
    if args.refresh:
        quality_payload = run_quality()
        verification_payload = run_verification()
        payload = run_control_layer(
            verification_snapshot=verification_payload,
            quality_snapshot=quality_payload,
            refresh_autonomy=True,
            refresh_tool_health=True,
            refresh_release_operations=True,
        )
    elif not _control_layer_cache_is_fresh():
        payload = run_control_layer()
    else:
        payload = _read_control_layer_cache()
    summary = _control_layer_summary_payload(payload)
    summary['identity_kernel'] = identity_kernel_status()
    summary['identity_integrity'] = _identity_integrity_snapshot(refresh=args.refresh)
    out(summary)


def cmd_engineering_os_status(args):
    forwarded_args = ['--refresh'] if args.refresh else []
    forwarded = _forward_codex_command_to_container('engineering-os-status', forwarded_args, session_token=None)
    if forwarded is not None:
        out(forwarded)
        return
    if args.refresh:
        quality_payload = run_quality()
        verification_payload = run_verification()
        payload = run_control_layer(
            verification_snapshot=verification_payload,
            quality_snapshot=quality_payload,
            refresh_autonomy=True,
            refresh_tool_health=True,
            refresh_release_operations=True,
        )
    else:
        payload = run_control_layer()
    summary = _engineering_os_summary_payload(payload)
    summary['identity_kernel'] = identity_kernel_status()
    summary['identity_integrity'] = _identity_integrity_snapshot(refresh=args.refresh)
    out(summary)


def cmd_lab_status(_args):
    forwarded = _forward_codex_command_to_container('lab-status', [], session_token=None)
    if forwarded is not None:
        out(forwarded)
        return
    payload = run_automation_lab_status()
    payload['identity_kernel'] = identity_kernel_status()
    payload['identity_integrity'] = _identity_integrity_snapshot(refresh=False)
    payload['identity_gate'] = payload['identity_integrity']
    out(payload)


def cmd_autonomy_score(args):
    forwarded_args = ['--refresh'] if args.refresh else []
    forwarded = _forward_codex_command_to_container('autonomy-score', forwarded_args, session_token=None)
    if forwarded is not None:
        out(forwarded)
        return
    if args.refresh:
        quality_payload = run_quality()
        run_verification()
        release_ops = run_release_operations_status()
        out(run_autonomy_score(
            quality_snapshot=quality_payload,
            release_operations_snapshot=release_ops,
        ))
        return
    out(run_autonomy_score())


def cmd_execution_kernel_smoke(args):
    workspace = args.workspace or str(ROOT / 'generated' / 'execution-kernel-smoke')
    payload = run_binary_classification_lab(
        workspace=workspace,
        output_name=args.output_name,
        metrics_name=args.metrics_name,
        source_template=args.source_template,
    )
    out({
        'mode': 'direct_execution_kernel',
        'bypassed_layers': ['planner', 'reviewer', 'control_layer', 'daemon'],
        'workspace': workspace,
        'result': payload,
    })


def cmd_task_delivery_smoke(args):
    from app.orchestrator import Orchestrator
    from app.models import ExecutionMode, StepSpec, TaskCreate, WorkerType

    async def _create_task() -> tuple[Orchestrator, object]:
        orch = Orchestrator()
        orch._launch_task_runner = lambda _task: None  # type: ignore[method-assign]
        task = await orch.create_task(TaskCreate(
            prompt='Create a deterministic smoke result, verify it, and promote it to delivery-ready.',
            title='Delivery smoke verification flow',
            execution_mode=ExecutionMode.governance,
            scheduled_by='factory-daemon.recovery',
            auto_approve=True,
            verification_level='L1',
            task_type='build_fix',
            plan=[
                StepSpec(
                    title='Create smoke evidence',
                    worker=WorkerType.coder,
                    instructions='Create a deterministic smoke artifact and record evidence.',
                    command='internal://recovery/write-smoke-file',
                    phase='build',
                ),
            ],
        ))
        await orch._run_task(task.id)
        return orch, task

    async def _get_task(orch: Orchestrator, task_id: str):
        return await orch.get_task(task_id)

    async def _get_stats(orch: Orchestrator):
        return await orch.stats()

    orch, task = asyncio.run(_create_task())

    try:
        orch._persist()
    except Exception:
        pass

    fresh_orch = Orchestrator()
    final = asyncio.run(_get_task(fresh_orch, task.id)) or asyncio.run(_get_task(orch, task.id)) or final
    stats = asyncio.run(_get_stats(fresh_orch))
    payload = {
        'task_id': final.id,
        'status': final.status.value if hasattr(final.status, 'value') else str(final.status),
        'delivery_state': (final.result or {}).get('delivery_state') if isinstance(final.result, dict) else None,
        'verification_status': ((final.result or {}).get('verification_result') or {}).get('status') if isinstance(final.result, dict) else None,
        'verification_passed': ((final.result or {}).get('verification_result') or {}).get('passed') if isinstance(final.result, dict) else None,
        'result': final.result,
        'stats': stats.model_dump(mode='json'),
    }
    out(payload)

def cmd_kernel_mode_status(_args):
    out(load_kernel_mode())


def cmd_lean_mode_enable(args):
    require_authorized('lean-mode-enable', args.session_token)
    out(apply_execution_profile('lean_execution', reason=args.reason, operator=args.operator))


def cmd_interaction_mode_enable(args):
    require_authorized('interaction-mode-enable', args.session_token)
    out(apply_execution_profile('interaction_only', reason=args.reason, operator=args.operator))


def cmd_soak_status(_args):
    out(run_soak_validation())


def cmd_approval_status(_args):
    control_policy = load_control_policy()
    approval_policy = load_policy()
    sample = {
        'dispatch_low_risk_goal_nodes': decide('dispatch_low_risk_goal_nodes').__dict__,
        'resolve_warning_escalations': decide('resolve_warning_escalations').__dict__,
        'resolve_error_escalations': decide('resolve_error_escalations').__dict__,
        'filesystem.write_workspace': decide('filesystem.write_workspace', target_path=str(ROOT / 'workspace' / 'demo')).__dict__,
        'git.push': decide('git.push', remote='origin').__dict__,
        'install_package': decide('install_package', package='pytest').__dict__,
        'docker.run': decide('docker.run', image='python:3.11').__dict__,
    }
    out({
        'control_policy': control_policy,
        'approval_policy': approval_policy,
        'session_policy': project_session_policy(control_policy),
        'tool_policy': project_tool_policy(control_policy),
        'sample_decisions': sample,
    })


def cmd_capabilities(_args):
    out(list_capabilities())


def cmd_capability_route(args):
    out(route_capability(args.request))


def cmd_capability_graph(_args):
    out(rebuild_graph())


def cmd_tools(_args):
    out(list_tools())


def cmd_tool_route(args):
    out(route_tool(args.request))


def cmd_vm_templates(_args):
    out(list_vm_templates())

def cmd_vm_policy(_args):
    path = DATA / 'worker_vm_policy.json'
    out(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {})



def cmd_vms(_args):
    out(list_vms())


def cmd_vm_status(_args):
    out(vm_status())


def cmd_vm_logs(args):
    out(get_vm_logs(args.vm_id))


def cmd_vm_create(args):
    require_authorized('vm-create', args.session_token)
    out(create_vm(args.name, args.template_id, purpose=args.purpose))


def cmd_vm_start(args):
    require_authorized('vm-start', args.session_token)
    out(start_vm(args.vm_id))


def cmd_vm_stop(args):
    require_authorized('vm-stop', args.session_token)
    out(stop_vm(args.vm_id))


def cmd_vm_snapshot(args):
    require_authorized('vm-snapshot', args.session_token)
    out(snapshot_vm(args.vm_id, name=args.name))


def cmd_upgrade_policy(_args):
    path = ROOT / 'runtime' / 'policy' / 'upgrade_policy.json'
    out(json.loads(path.read_text(encoding='utf-8-sig')))


def cmd_usage_status(_args):
    path = ROOT / 'data' / 'usage_tracker.json'
    if not path.exists():
        raise SystemExit('usage_tracker.json not found; run meta-factory or usage tracker first')
    out(json.loads(path.read_text(encoding='utf-8-sig')))


def cmd_skills(_args):
    out(run_training())


def cmd_platform_templates(_args):
    out(list_templates())


def cmd_platforms(_args):
    out(list_platforms())


def cmd_platform_health(_args):
    out(platform_health_summary())


def cmd_knowledge_status(_args):
    out(rebuild_knowledge())


def cmd_experiment_plan(_args):
    out(plan_experiments())


def cmd_experiment_run(_args):
    out(run_experiment())


def cmd_experiment_evaluate(_args):
    out(evaluate_experiment())


def cmd_experiment_status(_args):
    out({
        'plan': _load_json('experiment_plan.json', {}),
        'run': _load_json('experiment_run.json', {}),
        'evaluation': _load_json('experiment_evaluation.json', {}),
    })


def cmd_github_learning_scan(args):
    out(scan_github_repositories(topics=args.topics, limit=args.limit))


def cmd_github_learning_clone(args):
    out(clone_learning_target(full_name=args.repo, limit=args.limit))


def cmd_github_learning_status(_args):
    out(load_github_learning_status())


def cmd_knowledge_graph(_args):
    out(build_code_knowledge_graph())


def cmd_module_ownership_graph(_args):
    out(build_module_ownership_graph())


def cmd_dependency_impact(args):
    out(analyze_dependency_impact(args.request))


def cmd_project_graph(_args):
    out(build_project_graph())


def cmd_organization_model(_args):
    out(build_organization_model())

def cmd_organization_workboard(_args):
    out(build_organization_workboard())


def cmd_review_policy_graph(_args):
    out(build_review_policy_graph())


def cmd_cross_project_coordination(_args):
    out(run_cross_project_coordination())


def cmd_architecture_validate(_args):
    out(run_architecture_validation())


def cmd_verify_engine(_args):
    out(run_verification())


def cmd_platform_build(args):
    goal = {
        'goal_id': args.goal_id or f'manual-{args.name}',
        'target': args.name,
        'type': args.goal_type,
    }
    out(generate_platform(goal))


def cmd_runtime_maintenance(_args):
    out(run_maintenance())


def cmd_smoke_hygiene(_args):
    out(run_smoke_hygiene())


def cmd_schema_hygiene_smoke(_args):
    out(run_schema_hygiene_smoke())


def cmd_self_improvement_status(_args):
    out(run_self_improvement_status())


def cmd_runtime_status(_args):
    report_chain = run_report_chain(write_outputs=True)
    try:
        daemon = daemon_status()
        daemon_source = 'live'
    except Exception as exc:
        daemon = _read_daemon_state_fallback()
        if isinstance(daemon, dict):
            daemon = dict(daemon)
            daemon['fallback_reason'] = str(exc)
            daemon['source'] = 'cached_state'
        daemon_source = 'cached_state'
    out({
        'daemon': daemon,
        'daemon_source': daemon_source,
        'state': load_state(),
        'active_goals': active_goals(),
        'report_chain': report_chain['system_report'],
        'report_chain_outputs': report_chain['delivery'],
    })


def cmd_runtime_plan(_args):
    plans = []
    kernel_inputs = []
    for goal in active_goals():
        graph = ensure_graph(goal)
        nodes = ready_nodes(graph)
        capability = route_capability(goal.get('target') or '')
        vm_template = choose_template_for_task(goal.get('target'), goal=goal.get('target'))
        kernel_inputs.append({'goal': goal, 'graph': graph, 'ready_nodes': nodes})
        plans.append({
            'goal_id': goal.get('goal_id'),
            'target': goal.get('target'),
            'graph_id': graph.get('graph_id'),
            'capability_route': capability,
            'vm_template': vm_template,
            'ready_nodes': schedule_nodes(nodes, capability_route=capability, vm_template=vm_template, repo_path=goal.get('repo_path')),
        })
    out({
        'goals': plans,
        'kernel': build_scheduling_snapshot(kernel_inputs, dispatch_budget=3, persist=False),
    })


def cmd_operator_report(_args):
    kernel = rebuild()
    inbox = json.loads((DATA / 'escalation_inbox.json').read_text(encoding='utf-8'))
    failures = json.loads((DATA / 'failure_patterns.json').read_text(encoding='utf-8'))
    report_chain = run_report_chain(write_outputs=True)
    report = {
        'runtime': {
            'control_center': _get_client().get('/api/control-center/status').json(),
            'health': _get_client().get('/api/health').json(),
        },
        'failures': failures[:8],
        'escalations': inbox[:8],
        'next_actions': [
            'Resolve or reopen open escalations from the Codex inbox.',
            'Run meta-factory or evolution loops only when control center is active.',
            'Use auto-debug for reproducible local failures and keep manual approval for risky execution.',
        ],
        'context_kernel': kernel,
        'ai_testing': load_ai_test_status(),
        'report_chain': report_chain['system_report'],
    }
    out(report)


def cmd_self_report(args):
    out(run_factory_self_report(
        trigger=args.trigger,
        cycle=args.cycle,
        send_notifications=not args.no_notify,
        write_opencode=not args.no_opencode,
    ))


def cmd_report_chain(_args):
    out(run_report_chain(write_outputs=True))


def cmd_self_model(_args):
    out(build_self_model())

def cmd_self_model_run(_args):
    out(run_self_model_cycle())


def cmd_pause(args):
    require_authorized('pause', args.session_token)
    out(_get_client().post('/api/control-center/pause', json={'reason': args.reason}).json())


def cmd_resume(args):
    require_authorized('resume', args.session_token)
    out(_get_client().post('/api/control-center/resume', json={'reason': args.reason}).json())


def cmd_run_meta(args):
    require_authorized('run-meta', args.session_token)
    out(_get_client().post('/api/meta-factory/run').json())


def cmd_run_evolution(args):
    require_authorized('run-evolution', args.session_token)
    out(_get_client().post('/api/evolution/run').json())


def cmd_auto_debug(args):
    require_authorized('auto-debug', args.session_token)
    payload = {
        'error_text': args.error_text,
        'workspace': args.workspace,
        'repo_path': args.repo_path,
        'goal': args.goal,
        'prompt': args.prompt,
        'failing_command': args.failing_command,
        'failing_output': args.failing_output,
        'auto_approve': args.auto_approve,
    }
    out(_get_client().post('/api/debug/auto', json=payload).json())


def cmd_refresh_context(_args):
    out(rebuild())


def cmd_memory_status(_args):
    out(rebuild_memory())


def cmd_context_compaction(_args):
    rebuild()
    path = DATA / 'project_context_compaction.json'
    out(json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else [])


def cmd_change_request(args):
    out(analyze_change_request(args.request))


def cmd_replan(args):
    if args.apply:
        require_authorized('replan', args.session_token)
    out(build_replan(args.request, apply=args.apply))


def cmd_context_cache_status(args):
    out(summarize_cache(limit=args.limit))


def cmd_context_cache_purge_stale(_args):
    out(purge_stale_cache_entries())


def cmd_dialogue_status(args):
    out(dialogue_status(limit=args.limit, rebuild=args.rebuild))


def cmd_memory_object_status(_args):
    out(memory_status_report())


def cmd_memory_bootstrap(_args):
    out(bootstrap_memory_objects())


def cmd_memory_harvest(_args):
    out(harvest_memory_candidates())


def cmd_memory_auto_promote(args):
    out(auto_promote_memory_candidates(min_confidence=args.min_confidence, limit=args.limit))


def cmd_memory_integrity(_args):
    out(memory_integrity_report())


def cmd_memory_recall(args):
    out(
        recall_memory_objects(
            ' '.join(args.query).strip(),
            workspace=args.workspace or None,
            tags=args.tag,
            memory_types=args.memory_type,
            limit=args.limit,
            include_candidates=args.include_candidates,
        )
    )


def cmd_memory_promote(args):
    out(promote_memory_candidate(candidate_id=args.candidate_id))


def cmd_memory_quality_scorecard(args):
    out(memory_quality_scorecard_status(workspace=args.workspace or None, refresh=args.refresh))


def cmd_memory_muscle_benchmark(args):
    out(memory_muscle_benchmark_status(workspace=args.workspace or None, refresh=args.refresh))


def cmd_dialogue_sync(args):
    out(sync_dialogue(
        session_id=args.session_id,
        source=args.source,
        title=args.title,
        workspace=args.workspace,
        summary=args.summary,
        topics=args.topic,
        constraints=args.constraint,
        decisions=args.decision,
        tags=args.tag,
        artifacts=args.artifact,
        user_messages=args.user_message,
        assistant_messages=args.assistant_message,
        transcript_path=args.transcript_path,
    ))


def cmd_dialogue_sync_current(_args):
    session_id = os.environ.get('CODEX_DIALOGUE_SESSION_ID') or os.environ.get('CODEX_DIALOGUE_ID') or ''
    transcript_path = (
        os.environ.get('CODEX_DIALOGUE_TRANSCRIPT_PATH')
        or os.environ.get('CODEX_TRANSCRIPT_PATH')
        or ''
    )
    summary = os.environ.get('CODEX_DIALOGUE_SUMMARY') or ''
    if not session_id and not transcript_path and not summary:
        out({
            'status': 'skipped',
            'reason': 'no current dialogue transcript or summary was provided',
        })
        return
    if not session_id:
        session_id = 'current-live-dialogue'
    payload = sync_dialogue(
        session_id=session_id,
        source=os.environ.get('CODEX_DIALOGUE_SOURCE') or 'codex-live',
        title=os.environ.get('CODEX_DIALOGUE_TITLE') or 'Current live dialogue',
        workspace=os.environ.get('CODEX_DIALOGUE_WORKSPACE') or '',
        summary=summary,
        topics=[value for value in (os.environ.get('CODEX_DIALOGUE_TOPICS') or '').split(';') if value.strip()],
        constraints=[value for value in (os.environ.get('CODEX_DIALOGUE_CONSTRAINTS') or '').split(';') if value.strip()],
        decisions=[value for value in (os.environ.get('CODEX_DIALOGUE_DECISIONS') or '').split(';') if value.strip()],
        tags=[value for value in (os.environ.get('CODEX_DIALOGUE_TAGS') or '').split(';') if value.strip()],
        artifacts=[value for value in (os.environ.get('CODEX_DIALOGUE_ARTIFACTS') or '').split(';') if value.strip()],
        user_messages=[value for value in (os.environ.get('CODEX_DIALOGUE_USER_MESSAGES') or '').split('\n') if value.strip()],
        assistant_messages=[value for value in (os.environ.get('CODEX_DIALOGUE_ASSISTANT_MESSAGES') or '').split('\n') if value.strip()],
        transcript_path=transcript_path or None,
    )
    out(payload)


def cmd_dialogue_repair(_args):
    out(repair_dialogue_memory())

def cmd_tool_health(_args):
    payload = run_tool_health_audit()
    payload['memory_quality_scorecard'] = {
        'status': (payload.get('memory_quality_scorecard') or {}).get('status'),
        'overall_score': (payload.get('memory_quality_scorecard') or {}).get('overall_score'),
        'write_quality': (payload.get('memory_quality_scorecard') or {}).get('write_quality'),
        'recall_hit_rate': (payload.get('memory_quality_scorecard') or {}).get('recall_hit_rate'),
        'behavior_binding': (payload.get('memory_quality_scorecard') or {}).get('behavior_binding'),
        'anti_drift': (payload.get('memory_quality_scorecard') or {}).get('anti_drift'),
    }
    out(payload)


def cmd_tool_health_history(args):
    out(read_tool_health_history(limit=args.limit))


def cmd_environment_repair(args):
    out(run_environment_repair_lane(workspace=args.workspace, mode=args.mode))


def cmd_environment_status(_args):
    path = DATA / 'environment_repair_status.json'
    if not path.exists():
        raise SystemExit('environment_repair_status.json not found; run environment-repair first')
    out(json.loads(path.read_text(encoding='utf-8-sig')))


def cmd_ai_test_run(args):
    out(run_ai_test_suite(suite_path=args.suite, report_path=args.report, model_override=args.model, timeout_seconds=args.timeout, max_retries=args.retries, backoff_seconds=args.backoff))


def cmd_ai_test_status(args):
    out(load_ai_test_status(args.report))


def cmd_brain_snapshot(_args):
    rebuild()
    out(build_snapshot())


def cmd_goal_new(args):
    require_authorized('goal-new', args.session_token)
    out(create_goal(args.target, goal_type=args.goal_type, notes=args.notes))


def cmd_goals(_args):
    out(list_goals())


def cmd_goal_report(args):
    out(goal_report(top_n=args.limit))


def cmd_goal_sync(_args):
    out(sync_goal_runtime())


def cmd_goal_audit(_args):
    out(run_goal_storage_audit())


def cmd_compile_goal(args):
    require_authorized('compile-goal', args.session_token)
    from tools.taskgraph_compiler import compile_goal
    goals = list_goals()
    goal = next((item for item in goals if item.get('goal_id') == args.goal_id), None)
    if goal is None:
        raise SystemExit('Goal not found')
    out(compile_goal(goal))


def cmd_brain_loop(args):
    require_authorized('brain-loop', args.session_token)
    out(run_brain_loop())



def cmd_aips(args):
    payload = load_ai_runtime_state(refresh=args.refresh)
    out(((payload.get('tasks') or {}).get('rows') or [])[: args.limit])


def cmd_aitop(args):
    payload = load_ai_runtime_state(refresh=args.refresh)
    agents = ((payload.get('agents') or {}).get('rows') or [])
    agent_load = {}
    for agent in agents:
        name = agent.get('name') or 'worker'
        agent_load[name] = agent_load.get(name, 0) + (1 if agent.get('status') == 'running' else 0)
    out({
        'updated_at': payload.get('updated_at'),
        'agent_load': agent_load,
        'tasks': payload.get('tasks'),
        'metrics': payload.get('metrics'),
        'system': payload.get('system'),
    })


def cmd_aijournal(args):
    payload = load_ai_runtime_state(refresh=args.refresh)
    out(((payload.get('traces') or {}).get('recent') or [])[: args.limit])


def cmd_aitrace(args):
    payload = load_ai_runtime_state(refresh=args.refresh)
    out({
        'task': resolve_ai_path(f"/ai/tasks/{args.task_id}", refresh=args.refresh),
        'reasoning': ((payload.get('reasoning') or {}).get('rows') or [])[: args.limit],
        'journal': ((payload.get('traces') or {}).get('recent') or [])[: args.limit],
    })


def cmd_aihealth(args):
    payload = load_ai_runtime_state(refresh=args.refresh)
    out({
        'updated_at': payload.get('updated_at'),
        'metrics': payload.get('metrics'),
        'system': payload.get('system'),
    })


def cmd_aicat(args):
    out(resolve_ai_path(args.path, refresh=args.refresh))
def cmd_daemon_status(args):
    forwarded_args: list[str] = []
    forwarded = _forward_codex_command_to_container('daemon-status', forwarded_args, session_token=args.session_token)
    if forwarded is not None:
        out(forwarded)
        return
    ok, reason, details = authorize('daemon-status', args.session_token)
    identity_kernel = identity_kernel_status()
    out({
        'daemon': daemon_status(),
        'identity_kernel': identity_kernel,
        'identity_gate': identity_kernel,
        'memory_integrity': memory_integrity_report(),
        'memory_quality_scorecard': memory_quality_scorecard_status(workspace=str(ROOT), refresh=False),
        'tool_health_history': read_tool_health_history(limit=5),
        'authorization': details,
        'allowed': ok,
        'reason': reason,
    })


def cmd_identity_kernel_status(args):
    out(identity_kernel_status(refresh=args.refresh))


def cmd_identity_kernel_refresh(_args):
    out(refresh_identity_kernel())


def cmd_system_identity_status(args):
    out(system_identity_status(refresh=args.refresh))


def cmd_system_identity_refresh(_args):
    out(refresh_system_identity_ssot())


def _identity_integrity_snapshot(*, refresh: bool = False) -> dict[str, Any]:
    kernel = identity_kernel_status(refresh=refresh)
    return {
        'status': kernel.get('status'),
        'consistency': kernel.get('consistency') or {},
        'memory': kernel.get('memory') or {},
        'authority': kernel.get('authority') or {},
        'runtime': kernel.get('runtime') or {},
        'updated_at': kernel.get('updated_at'),
    }


def cmd_identity_integrity(args):
    out(_identity_integrity_snapshot(refresh=args.refresh))


def cmd_research(args):
    out(run_perplexity_search(args.query, focus=args.focus))

def cmd_internet_knowledge(_args):
    out({
        'status': load_perplexity_status(),
        'knowledge': load_internet_knowledge(),
    })

def cmd_session_status(_args):
    out({
        "active": current_session(),
        "sessions": list_sessions(),
    })


def cmd_session_open(args):
    out(open_session(args.owner, role=args.role, scope=args.scope))


def cmd_session_close(args):
    out(close_session(args.session_token))


def _terminate_process(pid: int) -> dict[str, Any]:
    pid = int(pid or 0)
    if pid <= 0:
        return {"terminated": False, "reason": "invalid pid"}
    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
        )
        return {
            "terminated": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "mode": "taskkill",
        }
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"terminated": False, "reason": "process-not-found", "mode": "os.kill"}
    except PermissionError as exc:
        return {"terminated": False, "reason": str(exc), "mode": "os.kill"}
    deadline = time.time() + 3.0
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return {"terminated": True, "mode": "os.kill", "signal": "SIGTERM"}
        except PermissionError:
            break
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return {"terminated": True, "mode": "os.kill", "signal": "SIGKILL"}
    except PermissionError as exc:
        return {"terminated": False, "reason": str(exc), "mode": "os.kill"}
    return {"terminated": True, "mode": "os.kill", "signal": "SIGKILL"}


def _running_in_container() -> bool:
    if os.name == "nt":
        return False
    cgroup_path = Path("/proc/1/cgroup")
    if not cgroup_path.exists():
        return False
    try:
        text = cgroup_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    lowered = text.lower()
    return any(token in lowered for token in ("docker", "containerd", "kubepods"))


def _discover_daemon_container() -> str | None:
    if os.name == "nt" or _running_in_container():
        return None
    try:
        completed = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]

    def _has_control_workspace(name: str) -> bool:
        try:
            probe = subprocess.run(
                ["docker", "exec", name, "test", "-f", "/workspace/tools/codex_control.py"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            return False
        return probe.returncode == 0

    preferred_names = [
        "orchestrator-mvp-orchestrator-1",
        "orchestrator-mvp-controller-api-1",
        "orchestrator-mvp-model-gateway-1",
    ]
    for preferred_name in preferred_names:
        if preferred_name in names and _has_control_workspace(preferred_name):
            return preferred_name

    for name in names:
        lowered = name.lower()
        if "orchestrator" in lowered and "mvp" in lowered and _has_control_workspace(name):
            return name
    return None


def _forward_codex_command_to_vm(subcommand: str, args: list[str], *, session_token: str | None) -> dict[str, Any] | None:
    if os.name != "nt" or not VMCTL.exists():
        return None
    forwarded_args: list[str] = []
    if session_token:
        forwarded_args.extend(["--session-token", session_token])
    forwarded_args.append(subcommand)
    forwarded_args.extend(args)
    completed = subprocess.run(
        [str(VMCTL), "ssh", REMOTE_PYTHON, REMOTE_SCRIPT, *forwarded_args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(CODEX_ROOT),
    )
    payload: dict[str, Any]
    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except Exception:
        payload = {
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
            "returncode": completed.returncode,
        }
    payload["forwarded_to_vm"] = True
    payload["vmctl_path"] = str(VMCTL)
    payload["vm_returncode"] = completed.returncode
    if completed.stderr and "stderr" not in payload:
        payload["stderr"] = completed.stderr.strip()
    return payload


def _forward_codex_command_to_container(subcommand: str, args: list[str], *, session_token: str | None) -> dict[str, Any] | None:
    vm_forwarded = _forward_codex_command_to_vm(subcommand, args, session_token=session_token)
    if vm_forwarded is not None:
        return vm_forwarded
    container_name = _discover_daemon_container()
    if not container_name:
        return None
    forwarded_args: list[str] = []
    if session_token:
        forwarded_args.extend(["--session-token", session_token])
    forwarded_args.append(subcommand)
    forwarded_args.extend(args)
    inner = " ".join(shlex.quote(part) for part in ("python", "tools/codex_control.py", *forwarded_args))
    completed = subprocess.run(
        ["docker", "exec", container_name, "sh", "-lc", f"cd /workspace && {inner}"],
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict[str, Any]
    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except Exception:
        payload = {
            "stdout": stdout,
            "stderr": (completed.stderr or "").strip(),
            "returncode": completed.returncode,
        }
    payload["forwarded_to_container"] = True
    payload["container_name"] = container_name
    payload["container_returncode"] = completed.returncode
    if completed.stderr and "stderr" not in payload:
        payload["stderr"] = completed.stderr.strip()
    return payload


def _forward_daemon_command_to_container(subcommand: str, args: list[str], *, session_token: str | None) -> dict[str, Any] | None:
    return _forward_codex_command_to_container(subcommand, args, session_token=session_token)


def _observer_only_host_payload(action: str) -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    return {
        "ok": False,
        "action": action,
        "status": "observer_only_host",
        "message": "Windows host is observer/recovery only. Run this action against the VM runtime root.",
        "authority_root": REMOTE_WORKSPACE,
        "host_role": "backup_sync_observer",
        "next_step": f"Use vmctl/factoryctl to reach {REMOTE_WORKSPACE} and retry.",
    }


def cmd_daemon_start(args):
    require_authorized('daemon-start', args.session_token)
    forwarded = _forward_daemon_command_to_container(
        "daemon-start",
        [
            "--interval",
            str(args.interval),
            "--meta-every",
            str(args.meta_every),
            "--evolution-every",
            str(args.evolution_every),
        ],
        session_token=args.session_token,
    )
    if forwarded is not None:
        out(forwarded)
        return
    observer_only = _observer_only_host_payload("daemon-start")
    if observer_only is not None:
        out(observer_only)
        return
    prior_status = daemon_status()
    prior_pid = prior_status.get('pid')
    prior_started_at = prior_status.get('started_at')
    prior_status_value = str(prior_status.get('status') or '').strip().lower()
    if prior_pid and prior_status_value in {'stale', 'stopped', 'error'}:
        _terminate_process(int(prior_pid))
    command = python_command(
        DAEMON_STARTER,
        '--interval',
        str(args.interval),
        '--meta-every',
        str(args.meta_every),
        '--evolution-every',
        str(args.evolution_every),
        interpreter=PYTHON_EXE,
    )
    completed = run_hidden(command, cwd=ROOT.parent)
    started_pid = None
    try:
        started_pid = int((completed.stdout or '').strip())
    except Exception:
        started_pid = None
    status = daemon_status()
    deadline = time.time() + 15.0
    while completed.returncode == 0 and time.time() < deadline:
        status = daemon_status()
        status_pid = status.get('pid')
        status_started_at = status.get('started_at')
        status_running = bool(status.get('running'))
        same_instance = bool(
            prior_pid
            and status_pid == prior_pid
            and prior_started_at
            and status_started_at == prior_started_at
        )
        if status_running and status_pid:
            if prior_status_value == 'running' and (started_pid is None or status_pid == started_pid):
                break
            if prior_status_value in {'stale', 'stopped', 'error'} and not same_instance:
                break
            if prior_pid is None:
                break
        time.sleep(0.5)
    out({
        'started': completed.returncode == 0,
        'returncode': completed.returncode,
        'stdout': completed.stdout.strip(),
        'stderr': completed.stderr.strip(),
        'prior_status': prior_status,
        'status': status,
    })


def cmd_daemon_stop(args):
    require_authorized('daemon-stop', args.session_token)
    forwarded = _forward_daemon_command_to_container("daemon-stop", [], session_token=args.session_token)
    if forwarded is not None:
        out(forwarded)
        return
    observer_only = _observer_only_host_payload("daemon-stop")
    if observer_only is not None:
        out(observer_only)
        return
    status = daemon_status()
    pid = status.get('pid')
    if not pid or not status.get('running'):
        out({'stopped': False, 'reason': 'daemon not running', 'status': status})
        return
    out({
        'status': status,
        **_terminate_process(int(pid)),
    })


def build_parser():
    parser = argparse.ArgumentParser(description='Codex-first control for the local resident automation platform.')
    parser.add_argument('--session-token')
    sub = parser.add_subparsers(dest='command', required=True)

    p_status = sub.add_parser('status')
    p_status.add_argument('--refresh', action='store_true')
    sub.add_parser('light-status')
    p_tool_stack_status = sub.add_parser('tool-stack-status')
    p_tool_stack_status.add_argument('--refresh', action='store_true')
    p_tool_stack_route = sub.add_parser('tool-stack-route')
    p_tool_stack_route.add_argument('request')
    p_task_route = sub.add_parser('task-route')
    p_task_route.add_argument('request')
    p_task_route.add_argument('--workspace')
    p_task_launch = sub.add_parser('task-launch')
    p_task_launch.add_argument('request')
    p_task_launch.add_argument('--workspace')
    p_task_launch.add_argument('--prefer')
    sub.add_parser('live-status')
    sub.add_parser('runtime-status')
    sub.add_parser('runtime-plan')
    sub.add_parser('branch-workboard')
    sub.add_parser('branch-status')
    p_branch_context = sub.add_parser('branch-context')
    p_branch_context.add_argument('branch_name')
    p_branch_goal = sub.add_parser('branch-goal')
    p_branch_goal.add_argument('branch_name')
    p_branch_goal.add_argument('target')
    p_branch_goal.add_argument('--department', default=None)
    p_branch_goal.add_argument('--goal-type', default='build_product')
    p_branch_goal.add_argument('--notes', default='')
    p_branch_goal.add_argument('--source-session', default=None)
    p_branch_goal.add_argument('--lane-role', default='capability_branch', choices=['capability_branch', 'testing_branch', 'production_instance_branch'])
    p_mainline_goal = sub.add_parser('mainline-goal')
    p_mainline_goal.add_argument('target')
    p_mainline_goal.add_argument('--goal-type', default='architecture_upgrade')
    p_mainline_goal.add_argument('--notes', default='')
    p_mainline_goal.add_argument('--source-session', default='mainline-control')
    p_branch_cap = sub.add_parser('branch-capability-goal')
    p_branch_cap.add_argument('branch_name')
    p_branch_cap.add_argument('target')
    p_branch_cap.add_argument('--department', default=None)
    p_branch_cap.add_argument('--goal-type', default='capability_upgrade')
    p_branch_cap.add_argument('--notes', default='')
    p_branch_cap.add_argument('--source-session', default=None)
    p_branch_test = sub.add_parser('branch-test-goal')
    p_branch_test.add_argument('branch_name')
    p_branch_test.add_argument('target')
    p_branch_test.add_argument('--department', default=None)
    p_branch_test.add_argument('--goal-type', default='verification_upgrade')
    p_branch_test.add_argument('--notes', default='')
    p_branch_test.add_argument('--source-session', default=None)
    p_branch_prod = sub.add_parser('branch-production-goal')
    p_branch_prod.add_argument('branch_name')
    p_branch_prod.add_argument('target')
    p_branch_prod.add_argument('--department', default=None)
    p_branch_prod.add_argument('--goal-type', default='production_instance')
    p_branch_prod.add_argument('--notes', default='')
    p_branch_prod.add_argument('--source-session', default=None)
    sub.add_parser('tool-health')
    p_tool_history = sub.add_parser('tool-health-history')
    p_tool_history.add_argument('--limit', type=int, default=20)
    p_cache = sub.add_parser('context-cache-status')
    p_cache.add_argument('--limit', type=int, default=10)
    sub.add_parser('context-cache-purge-stale')
    sub.add_parser('runtime-maintenance')
    sub.add_parser('smoke-hygiene')
    sub.add_parser('schema-hygiene-smoke')
    sub.add_parser('self-improvement-status')
    sub.add_parser('upgrade-policy')
    sub.add_parser('usage-status')
    sub.add_parser('skills')
    sub.add_parser('platform-templates')
    sub.add_parser('platforms')
    sub.add_parser('platform-health')
    sub.add_parser('knowledge-status')
    sub.add_parser('knowledge-graph')
    sub.add_parser('module-ownership-graph')
    p_impact = sub.add_parser('dependency-impact')
    p_impact.add_argument('request')
    sub.add_parser('project-graph')
    sub.add_parser('organization-model')
    sub.add_parser('organization-workboard')
    sub.add_parser('rnd-status')
    sub.add_parser('rnd-pipeline-status')
    sub.add_parser('rnd-assets-status')
    sub.add_parser('review-policy-graph')
    sub.add_parser('cross-project-coordination')
    sub.add_parser('architecture-validate')
    sub.add_parser('verify-engine')
    sub.add_parser('experiment-plan')
    sub.add_parser('experiment-run')
    sub.add_parser('experiment-evaluate')
    sub.add_parser('experiment-status')
    p_gh_scan = sub.add_parser('github-learning-scan')
    p_gh_scan.add_argument('--topics', nargs='*')
    p_gh_scan.add_argument('--limit', type=int, default=12)
    p_gh_clone = sub.add_parser('github-learning-clone')
    p_gh_clone.add_argument('--repo')
    p_gh_clone.add_argument('--limit', type=int, default=1)
    sub.add_parser('github-learning-status')
    sub.add_parser('capabilities')
    sub.add_parser('tools')
    sub.add_parser('vm-templates')
    sub.add_parser('vm-policy')
    sub.add_parser('vms')
    sub.add_parser('vm-status')
    p_vm_logs = sub.add_parser('vm-logs')
    p_vm_logs.add_argument('--vm-id')
    p_vm_create = sub.add_parser('vm-create')
    p_vm_create.add_argument('name')
    p_vm_create.add_argument('--template-id', required=True)
    p_vm_create.add_argument('--purpose', default='general')
    p_vm_start = sub.add_parser('vm-start')
    p_vm_start.add_argument('vm_id')
    p_vm_stop = sub.add_parser('vm-stop')
    p_vm_stop.add_argument('vm_id')
    p_vm_snapshot = sub.add_parser('vm-snapshot')
    p_vm_snapshot.add_argument('vm_id')
    p_vm_snapshot.add_argument('--name')
    sub.add_parser('capability-graph')
    p_capability_route = sub.add_parser('capability-route')
    p_capability_route.add_argument('request')
    p_tool_route = sub.add_parser('tool-route')
    p_tool_route.add_argument('request')
    p_platform_build = sub.add_parser('platform-build')
    p_platform_build.add_argument('name')
    p_platform_build.add_argument('--goal-id')
    p_platform_build.add_argument('--goal-type', default='build_platform')
    p_tasks = sub.add_parser('tasks')
    p_tasks.add_argument('--active-only', action='store_true')
    p_tasks.add_argument('--failed-only', action='store_true')
    p_tasks.add_argument('--limit', type=int, default=20)
    p_task = sub.add_parser('task')
    p_task.add_argument('task_id')
    sub.add_parser('agents')
    p_aips = sub.add_parser('aips')
    p_aips.add_argument('--limit', type=int, default=20)
    p_aips.add_argument('--refresh', action='store_true')
    p_aitop = sub.add_parser('aitop')
    p_aitop.add_argument('--refresh', action='store_true')
    p_aijournal = sub.add_parser('aijournal')
    p_aijournal.add_argument('--limit', type=int, default=30)
    p_aijournal.add_argument('--refresh', action='store_true')
    p_aitrace = sub.add_parser('aitrace')
    p_aitrace.add_argument('task_id')
    p_aitrace.add_argument('--limit', type=int, default=20)
    p_aitrace.add_argument('--refresh', action='store_true')
    p_aihealth = sub.add_parser('aihealth')
    p_aihealth.add_argument('--refresh', action='store_true')
    p_aicat = sub.add_parser('aicat')
    p_aicat.add_argument('path', nargs='?', default='/ai')
    p_aicat.add_argument('--refresh', action='store_true')
    p_logs = sub.add_parser('logs')
    p_logs.add_argument('--tail', type=int, default=30)
    p_env_repair = sub.add_parser('environment-repair')
    p_env_repair.add_argument('--workspace')
    p_env_repair.add_argument('--mode', default='full', choices=['full', 'light'])
    sub.add_parser('environment-status')
    p_ai_test_run = sub.add_parser('ai-test-run')
    p_ai_test_run.add_argument('--suite', default=str(ROOT / 'data' / 'ai_test_suite.json'))
    p_ai_test_run.add_argument('--report', default=str(ROOT / 'data' / 'ai_test_report.json'))
    p_ai_test_run.add_argument('--model', default='')
    p_ai_test_run.add_argument('--timeout', type=float, default=45.0)
    p_ai_test_run.add_argument('--retries', type=int, default=2)
    p_ai_test_run.add_argument('--backoff', type=float, default=2.0)
    p_ai_test_status = sub.add_parser('ai-test-status')
    p_ai_test_status.add_argument('--report', default=str(ROOT / 'data' / 'ai_test_report.json'))
    p_taskgraph = sub.add_parser('taskgraph')
    p_taskgraph.add_argument('--goal-id')
    p_taskgraph.add_argument('--graph-id')
    p_inbox = sub.add_parser('inbox')
    p_inbox.add_argument('--open-only', action='store_true')
    p_escalations = sub.add_parser('escalations')
    p_escalations.add_argument('--open-only', action='store_true')
    p_escalations.add_argument('--severity', choices=['info', 'warning', 'error'])
    p_escalations.add_argument('--limit', type=int, default=20)
    p_patches = sub.add_parser('patches')
    p_patches.add_argument('--open-only', action='store_true')
    p_patches.add_argument('--status')
    p_patches.add_argument('--limit', type=int, default=20)
    sub.add_parser('patch-status')
    p_patch_merge = sub.add_parser('patch-merge')
    p_patch_merge.add_argument('patch_id')
    p_patch_merge.add_argument('--resolution', default='Merged by Codex operator console.')
    sub.add_parser('lab-status')
    sub.add_parser('release-ops-status')
    sub.add_parser('company-os-status')
    coord = sub.add_parser('coordinate-projects')
    coord.add_argument('--target')
    coord.add_argument('--limit', type=int, default=3)
    sub.add_parser('release-train')
    p_dispatch = sub.add_parser('dispatch')
    p_dispatch.add_argument('prompt')
    p_dispatch.add_argument('--goal')
    p_dispatch.add_argument('--caller', default='codex-control')
    p_dispatch.add_argument('--repo-path')
    p_dispatch.add_argument('--project-id')
    p_dispatch.add_argument('--repo-id')
    p_dispatch.add_argument('--capability-request')
    p_dispatch.add_argument('--vm-request')
    p_dispatch.add_argument('--context-mode', choices=['lean', 'standard', 'deep'])
    p_dispatch.add_argument('--max-context-chars', type=int)
    p_dispatch.add_argument('--auto-approve', action='store_true')
    p_dispatch.add_argument('--enqueue-only', action='store_true')
    p_dispatch.add_argument('--no-resource-scan', action='store_true')
    p_dispatch.add_argument('--no-repo-status', action='store_true')
    p_dispatch.add_argument('--full', action='store_true')
    p_task_publish = sub.add_parser('task-publish')
    p_task_publish.add_argument('--file', required=True)
    p_task_publish.add_argument('--full', action='store_true')
    p_task_publish_draft = sub.add_parser('task-publish-draft')
    p_task_publish_draft.add_argument('--file', required=True)
    p_task_publish_draft.add_argument('--full', action='store_true')
    p_task_publish_approve = sub.add_parser('task-publish-approve')
    p_task_publish_approve.add_argument('publication_id')
    p_task_publish_approve.add_argument('--approved-by', default='')
    p_task_publish_approve.add_argument('--notes', default='')
    p_task_publish_approve.add_argument('--full', action='store_true')
    p_task_publish_commit = sub.add_parser('task-publish-commit')
    p_task_publish_commit.add_argument('publication_id')
    p_task_publish_commit.add_argument('--published-by', default='')
    p_task_publish_commit.add_argument('--notes', default='')
    p_task_publish_commit.add_argument('--full', action='store_true')
    p_task_publications = sub.add_parser('task-publications')
    p_task_publications.add_argument('--status', default='')
    p_task_publications.add_argument('--task-id', default='')
    p_task_publications.add_argument('--limit', type=int, default=20)
    sub.add_parser('refresh-context')
    sub.add_parser('memory-status')
    sub.add_parser('context-compaction')
    p_dialogue_status = sub.add_parser('dialogue-status')
    p_dialogue_status.add_argument('--limit', type=int, default=8)
    p_dialogue_status.add_argument('--rebuild', action='store_true')
    p_dialogue_sync = sub.add_parser('dialogue-sync')
    p_dialogue_sync.add_argument('--session-id', required=True)
    p_dialogue_sync.add_argument('--source', default='codex')
    p_dialogue_sync.add_argument('--title', default='')
    p_dialogue_sync.add_argument('--workspace', default='')
    p_dialogue_sync.add_argument('--summary', default='')
    p_dialogue_sync.add_argument('--topic', action='append', default=[])
    p_dialogue_sync.add_argument('--constraint', action='append', default=[])
    p_dialogue_sync.add_argument('--decision', action='append', default=[])
    p_dialogue_sync.add_argument('--tag', action='append', default=[])
    p_dialogue_sync.add_argument('--artifact', action='append', default=[])
    p_dialogue_sync.add_argument('--user-message', action='append', default=[])
    p_dialogue_sync.add_argument('--assistant-message', action='append', default=[])
    p_dialogue_sync.add_argument('--transcript-path', default='')
    sub.add_parser('dialogue-sync-current')
    sub.add_parser('dialogue-repair')
    sub.add_parser('memory-object-status')
    sub.add_parser('memory-bootstrap')
    sub.add_parser('memory-harvest')
    p_memory_auto_promote = sub.add_parser('memory-auto-promote')
    p_memory_auto_promote.add_argument('--min-confidence', type=float, default=None)
    p_memory_auto_promote.add_argument('--limit', type=int, default=None)
    sub.add_parser('memory-integrity')
    p_memory_quality_scorecard = sub.add_parser('memory-quality-scorecard')
    p_memory_quality_scorecard.add_argument('--workspace', default='')
    p_memory_quality_scorecard.add_argument('--refresh', action='store_true')
    p_memory_muscle_benchmark = sub.add_parser('memory-muscle-benchmark')
    p_memory_muscle_benchmark.add_argument('--workspace', default='')
    p_memory_muscle_benchmark.add_argument('--refresh', action='store_true')
    p_identity_kernel_status = sub.add_parser('identity-kernel-status')
    p_identity_kernel_status.add_argument('--refresh', action='store_true')
    sub.add_parser('identity-kernel-refresh')
    p_system_identity_status = sub.add_parser('system-identity-status')
    p_system_identity_status.add_argument('--refresh', action='store_true')
    sub.add_parser('system-identity-refresh')
    p_identity_integrity = sub.add_parser('identity-integrity')
    p_identity_integrity.add_argument('--refresh', action='store_true')
    p_memory_recall = sub.add_parser('memory-recall')
    p_memory_recall.add_argument('query', nargs='*', default=[])
    p_memory_recall.add_argument('--workspace', default='')
    p_memory_recall.add_argument('--tag', action='append', default=[])
    p_memory_recall.add_argument('--type', dest='memory_type', action='append', default=[])
    p_memory_recall.add_argument('--limit', type=int, default=8)
    p_memory_recall.add_argument('--include-candidates', action='store_true')
    p_memory_promote = sub.add_parser('memory-promote')
    p_memory_promote.add_argument('--candidate-id')
    p_change_request = sub.add_parser('change-request')
    p_change_request.add_argument('request')
    p_replan = sub.add_parser('replan')
    p_replan.add_argument('request')
    p_replan.add_argument('--apply', action='store_true')
    sub.add_parser('quality-status')
    sub.add_parser('evolution-control')
    sub.add_parser('guard-status')
    sub.add_parser('fact-gate-convergence')
    p_control_layer_status = sub.add_parser('control-layer-status')
    p_control_layer_status.add_argument('--refresh', action='store_true')
    p_engineering_os_status = sub.add_parser('engineering-os-status')
    p_engineering_os_status.add_argument('--refresh', action='store_true')
    p_autonomy_score = sub.add_parser('autonomy-score')
    p_autonomy_score.add_argument('--refresh', action='store_true')
    p_kernel_smoke = sub.add_parser('execution-kernel-smoke')
    p_kernel_smoke.add_argument('--workspace', default='')
    p_kernel_smoke.add_argument('--output-name', default='BINARY_CLASSIFICATION_AUTORUN_RESULT.md')
    p_kernel_smoke.add_argument('--metrics-name', default='binary_classification_metrics.json')
    p_kernel_smoke.add_argument('--source-template', default='')
    p_delivery_smoke = sub.add_parser('task-delivery-smoke')
    p_delivery_smoke.add_argument('--timeout', type=int, default=180)
    sub.add_parser('kernel-mode-status')
    p_lean_mode = sub.add_parser('lean-mode-enable')
    p_lean_mode.add_argument('--reason', default='Reduce runtime complexity to the execution kernel.')
    p_lean_mode.add_argument('--operator', default='codex')
    p_interaction_mode = sub.add_parser('interaction-mode-enable')
    p_interaction_mode.add_argument('--reason', default='Route instructions through external executors and avoid direct self-repair.')
    p_interaction_mode.add_argument('--operator', default='codex')
    p_research = sub.add_parser('research')
    p_research.add_argument('query')
    p_research.add_argument('--focus', default='general')
    sub.add_parser('internet-knowledge')
    sub.add_parser('soak-status')
    sub.add_parser('approval-status')
    sub.add_parser('control-policy-status')
    sub.add_parser('brain-snapshot')
    p_goal_new = sub.add_parser('goal-new')
    p_goal_new.add_argument('target')
    p_goal_new.add_argument('--goal-type', default='build_platform')
    p_goal_new.add_argument('--notes', default='')
    sub.add_parser('goals')
    p_goal_report = sub.add_parser('goal-report')
    p_goal_report.add_argument('--limit', type=int, default=8)
    sub.add_parser('goal-sync')
    sub.add_parser('goal-audit')
    p_compile = sub.add_parser('compile-goal')
    p_compile.add_argument('goal_id')
    sub.add_parser('brain-loop')
    sub.add_parser('daemon-status')
    p_session_open = sub.add_parser('session-open')
    p_session_open.add_argument('--owner', required=True)
    p_session_open.add_argument('--role', default='operator', choices=['operator', 'planner', 'observer'])
    p_session_open.add_argument('--scope', default='global')
    sub.add_parser('session-status')
    sub.add_parser('session-close')
    p_daemon_start = sub.add_parser('daemon-start')
    p_daemon_start.add_argument('--interval', type=float, default=1.0)
    p_daemon_start.add_argument('--meta-every', type=int, default=5)
    p_daemon_start.add_argument('--evolution-every', type=int, default=10)
    sub.add_parser('daemon-stop')
    p_resolve = sub.add_parser('resolve-escalation')
    p_resolve.add_argument('message_id')
    p_resolve.add_argument('--resolution', default='Resolved from Codex operator console.')
    p_resolve.add_argument('--status', default='resolved')
    p_approve = sub.add_parser('approve')
    p_approve.add_argument('message_id')
    p_approve.add_argument('--resolution', default='Approved from Codex operator console.')
    p_reject = sub.add_parser('reject')
    p_reject.add_argument('message_id')
    p_reject.add_argument('--resolution', default='Rejected from Codex operator console.')
    p_reopen = sub.add_parser('reopen-escalation')
    p_reopen.add_argument('message_id')
    p_reopen.add_argument('--reason', default='Reopened from Codex operator console.')
    p_patch_approve = sub.add_parser('patch-approve')
    p_patch_approve.add_argument('patch_id')
    p_patch_approve.add_argument('--resolution', default='Approved from Codex operator console.')
    p_patch_reject = sub.add_parser('patch-reject')
    p_patch_reject.add_argument('patch_id')
    p_patch_reject.add_argument('--resolution', default='Rejected from Codex operator console.')
    sub.add_parser('operator-report')
    p_self_report = sub.add_parser('self-report')
    p_self_report.add_argument('--trigger', default='manual')
    p_self_report.add_argument('--cycle', type=int)
    p_self_report.add_argument('--no-notify', action='store_true')
    p_self_report.add_argument('--no-opencode', action='store_true')
    sub.add_parser('report-chain')
    sub.add_parser('self-model')
    sub.add_parser('self-model-run')
    p_pause = sub.add_parser('pause')
    p_pause.add_argument('--reason', default='Paused from Codex control.')
    p_resume = sub.add_parser('resume')
    p_resume.add_argument('--reason', default='Resumed from Codex control.')
    sub.add_parser('run-meta')
    sub.add_parser('run-evolution')
    p_debug = sub.add_parser('auto-debug')
    p_debug.add_argument('--error-text', required=True)
    p_debug.add_argument('--workspace')
    p_debug.add_argument('--repo-path')
    p_debug.add_argument('--goal')
    p_debug.add_argument('--prompt')
    p_debug.add_argument('--failing-command')
    p_debug.add_argument('--failing-output')
    p_debug.add_argument('--auto-approve', action='store_true')
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    mapping = {
        'status': cmd_status,
        'light-status': cmd_light_status,
        'tool-stack-status': cmd_tool_stack_status,
        'tool-stack-route': cmd_tool_stack_route,
        'task-route': cmd_task_route,
        'task-launch': cmd_task_launch,
        'live-status': cmd_live_status,
        'runtime-status': cmd_runtime_status,
        'runtime-plan': cmd_runtime_plan,
        'runtime-maintenance': cmd_runtime_maintenance,
        'smoke-hygiene': cmd_smoke_hygiene,
        'schema-hygiene-smoke': cmd_schema_hygiene_smoke,
        'self-improvement-status': cmd_self_improvement_status,
        'upgrade-policy': cmd_upgrade_policy,
        'usage-status': cmd_usage_status,
        'skills': cmd_skills,
        'platform-templates': cmd_platform_templates,
        'platforms': cmd_platforms,
        'platform-health': cmd_platform_health,
        'knowledge-status': cmd_knowledge_status,
        'knowledge-graph': cmd_knowledge_graph,
        'module-ownership-graph': cmd_module_ownership_graph,
        'dependency-impact': cmd_dependency_impact,
        'project-graph': cmd_project_graph,
        'organization-model': cmd_organization_model,
        'organization-workboard': cmd_organization_workboard,
        'rnd-status': cmd_rnd_status,
        'rnd-pipeline-status': cmd_rnd_pipeline_status,
        'rnd-assets-status': cmd_rnd_assets_status,
        'review-policy-graph': cmd_review_policy_graph,
        'cross-project-coordination': cmd_cross_project_coordination,
        'architecture-validate': cmd_architecture_validate,
        'verify-engine': cmd_verify_engine,
        'experiment-plan': cmd_experiment_plan,
        'experiment-run': cmd_experiment_run,
        'experiment-evaluate': cmd_experiment_evaluate,
        'experiment-status': cmd_experiment_status,
        'github-learning-scan': cmd_github_learning_scan,
        'github-learning-clone': cmd_github_learning_clone,
        'github-learning-status': cmd_github_learning_status,
        'platform-build': cmd_platform_build,
        'capabilities': cmd_capabilities,
        'tools': cmd_tools,
        'vm-templates': cmd_vm_templates,
        'vm-policy': cmd_vm_policy,
        'vms': cmd_vms,
        'vm-status': cmd_vm_status,
        'vm-logs': cmd_vm_logs,
        'vm-create': cmd_vm_create,
        'vm-start': cmd_vm_start,
        'vm-stop': cmd_vm_stop,
        'vm-snapshot': cmd_vm_snapshot,
        'capability-route': cmd_capability_route,
        'tool-route': cmd_tool_route,
        'capability-graph': cmd_capability_graph,
        'tasks': cmd_tasks,
        'task': cmd_task,
        'agents': cmd_agents,
        'aips': cmd_aips,
        'aitop': cmd_aitop,
        'aijournal': cmd_aijournal,
        'aitrace': cmd_aitrace,
        'aihealth': cmd_aihealth,
        'aicat': cmd_aicat,
        'logs': cmd_logs,
        'environment-repair': cmd_environment_repair,
        'environment-status': cmd_environment_status,
        'ai-test-run': cmd_ai_test_run,
        'ai-test-status': cmd_ai_test_status,
        'taskgraph': cmd_taskgraph,
        'inbox': cmd_inbox,
        'escalations': cmd_escalations,
        'patches': cmd_patches,
        'patch-status': cmd_patch_status,
        'patch-merge': cmd_patch_merge,
        'lab-status': cmd_lab_status,
        'release-ops-status': cmd_release_ops_status,
        'release-train': cmd_release_train,
        'coordinate-projects': cmd_coordinate_projects,
        'company-os-status': cmd_company_os_status,
        'dispatch': cmd_dispatch,
        'task-publish': cmd_task_publish,
        'task-publish-draft': cmd_task_publish_draft,
        'task-publish-approve': cmd_task_publish_approve,
        'task-publish-commit': cmd_task_publish_commit,
        'task-publications': cmd_task_publications,
        'brain-snapshot': cmd_brain_snapshot,
        'goal-new': cmd_goal_new,
        'goals': cmd_goals,
        'goal-report': cmd_goal_report,
        'goal-sync': cmd_goal_sync,
        'goal-audit': cmd_goal_audit,
        'compile-goal': cmd_compile_goal,
        'brain-loop': cmd_brain_loop,
        'daemon-status': cmd_daemon_status,
        'session-open': cmd_session_open,
        'session-status': cmd_session_status,
        'session-close': cmd_session_close,
        'daemon-start': cmd_daemon_start,
        'daemon-stop': cmd_daemon_stop,
        'resolve-escalation': cmd_resolve_escalation,
        'approve': cmd_approve,
        'reject': cmd_reject,
        'reopen-escalation': cmd_reopen_escalation,
        'patch-approve': cmd_patch_approve,
        'patch-reject': cmd_patch_reject,
        'operator-report': cmd_operator_report,
        'self-report': cmd_self_report,
        'report-chain': cmd_report_chain,
        'self-model': cmd_self_model,
        'self-model-run': cmd_self_model_run,
        'pause': cmd_pause,
        'resume': cmd_resume,
        'run-meta': cmd_run_meta,
        'run-evolution': cmd_run_evolution,
        'auto-debug': cmd_auto_debug,
        'refresh-context': cmd_refresh_context,
        'memory-status': cmd_memory_status,
        'context-compaction': cmd_context_compaction,
        'dialogue-status': cmd_dialogue_status,
        'dialogue-sync': cmd_dialogue_sync,
        'dialogue-sync-current': cmd_dialogue_sync_current,
        'dialogue-repair': cmd_dialogue_repair,
        'branch-workboard': cmd_branch_workboard,
        'branch-status': cmd_branch_status,
        'branch-context': cmd_branch_context,
        'branch-goal': cmd_branch_goal,
        'mainline-goal': cmd_mainline_goal,
        'branch-capability-goal': cmd_branch_capability_goal,
        'branch-test-goal': cmd_branch_test_goal,
        'branch-production-goal': cmd_branch_production_goal,
        'tool-health': cmd_tool_health,
        'tool-health-history': cmd_tool_health_history,
        'context-cache-status': cmd_context_cache_status,
        'context-cache-purge-stale': cmd_context_cache_purge_stale,
        'change-request': cmd_change_request,
        'replan': cmd_replan,
        'quality-status': cmd_quality_status,
        'evolution-control': cmd_evolution_control,
        'guard-status': cmd_guard_status,
        'fact-gate-convergence': cmd_fact_gate_convergence,
        'control-layer-status': cmd_control_layer_status,
        'engineering-os-status': cmd_engineering_os_status,
        'autonomy-score': cmd_autonomy_score,
        'execution-kernel-smoke': cmd_execution_kernel_smoke,
        'task-delivery-smoke': cmd_task_delivery_smoke,
    'kernel-mode-status': cmd_kernel_mode_status,
    'lean-mode-enable': cmd_lean_mode_enable,
    'interaction-mode-enable': cmd_interaction_mode_enable,
    'research': cmd_research,
        'internet-knowledge': cmd_internet_knowledge,
        'soak-status': cmd_soak_status,
        'approval-status': cmd_approval_status,
        'control-policy-status': cmd_approval_status,
        'memory-object-status': cmd_memory_object_status,
        'memory-bootstrap': cmd_memory_bootstrap,
        'memory-harvest': cmd_memory_harvest,
        'memory-auto-promote': cmd_memory_auto_promote,
        'memory-integrity': cmd_memory_integrity,
        'memory-quality-scorecard': cmd_memory_quality_scorecard,
        'memory-muscle-benchmark': cmd_memory_muscle_benchmark,
        'identity-kernel-status': cmd_identity_kernel_status,
        'identity-kernel-refresh': cmd_identity_kernel_refresh,
        'system-identity-status': cmd_system_identity_status,
        'system-identity-refresh': cmd_system_identity_refresh,
        'identity-integrity': cmd_identity_integrity,
        'memory-recall': cmd_memory_recall,
        'memory-promote': cmd_memory_promote,
    }
    mapping[args.command](args)


if __name__ == '__main__':
    main()
