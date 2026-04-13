from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace
from module_ownership import create_patch_submission, find_patch_submission, record_patch_artifacts, resolve_patch_submission
from privilege_policy import decide

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = DATA / 'self_patch_candidates.json'
BACKLOG = DATA / 'self_improvement_backlog.json'
PLAN = DATA / 'self_improvement_plan.json'
STATUS = DATA / 'self_improvement_status.json'
HANDOFF = DATA / 'self_improvement_handoff.json'
VERIFY = DATA / 'verification_status.json'
FAILURES = DATA / 'failure_patterns.json'
RELEASE = DATA / 'release_operations_status.json'
GRAPH = DATA / 'code_knowledge_graph.json'
IMMUTABILITY = DATA / 'core_immutability_policy.json'
APPROVED_PATCH = DATA / 'approved_patch_policy.json'
APPROVED_PATCH_RECORDS = DATA / 'approved_patch_records.json'
PATCH_SUBMISSIONS = DATA / 'patch_submissions.json'
ARTIFACTS = DATA / 'self_patch_artifacts.json'
BUNDLES = DATA / 'self_patch_bundles'
BUNDLE_INDEX = DATA / 'self_patch_bundle_index.json'
CONTROL = DATA / 'control_layer_status.json'
AI_TEST = DATA / 'ai_test_status.json'
TELEMETRY = DATA / 'telemetry_events.json'
QUALITY = DATA / 'quality_status.json'
TOOL_HEALTH_HISTORY = DATA / 'tool_health_history.json'

IMMUTABLE_TOOL_MODULES = {
    'tools.codex_control',
    'tools.meta_factory_control',
    'tools.factory_daemon',
    'tools.session_guard',
    'tools.privilege_policy',
    'tools.decision_engine',
}
SMALL_FEATURE_MAX_TARGET_FILES = 2
SMALL_FEATURE_MAX_VALIDATION_STEPS = 3

ISSUE_MAP: dict[str, dict[str, Any]] = {
    'control-layer-lags-quality': {
        'title': 'Align control layer with quality gate',
        'summary': 'Control remains constrained while quality has already promoted readiness.',
        'target_files': ['tools/decision_engine.py', 'tools/tool_health_audit.py', 'tools/release_operations.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'tool_health': {
        'title': 'Stabilize tool health signal quality',
        'summary': 'Tool health reports require bounded remediation and clearer merge gating.',
        'target_files': ['tools/tool_health_audit.py', 'tools/verification_engine.py'],
        'priority': 'medium',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'verification-compileall-failure': {
        'title': 'Repair verification compileall failure',
        'summary': 'Verification compileall failed and should generate a concrete remediation candidate.',
        'target_files': ['tools/verification_engine.py', 'tools/self_patch_loop.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'verification-architecture-violation': {
        'title': 'Resolve architecture validation failure',
        'summary': 'Architecture validation is failing and should produce a bounded remediation candidate tied to the violating modules.',
        'target_files': ['tools/architecture_validator.py', 'tools/code_knowledge_graph.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'verification-tool-health-blocker': {
        'title': 'Repair blocking tool health issue',
        'summary': 'A blocking tool health issue is preventing verification from passing and should become a first-class remediation target.',
        'target_files': ['tools/tool_health_audit.py', 'tools/verification_engine.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'verification-runtime-health-failure': {
        'title': 'Repair runtime health verification failure',
        'summary': 'Runtime health failed verification and should be converted into a bounded self-improvement candidate.',
        'target_files': ['tools/runtime_maintenance.py', 'tools/goal_runtime.py', 'tools/task_state_tools.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
    'release-train-blocked': {
        'title': 'Harden self-improvement release handoff templates',
        'summary': 'Release train remains blocked; improve low-risk handoff artifacts before touching core control flow.',
        'target_files': ['templates/reports/lab-report.md.tpl'],
        'priority': 'medium',
        'validation': ['file presence check', 'static review'],
    },
    'self-improvement-bootstrap-gap': {
        'title': 'Complete self-improvement support loop assets',
        'summary': 'Self-improvement support artifacts were missing and need bounded loop support.',
        'target_files': ['tools/self_patch_loop.py', 'tools/prepare_self_patch_branch.py', 'tools/sandbox_upgrade_runner.py'],
        'priority': 'medium',
        'validation': ['python -m compileall tools', 'artifact generation check'],
    },
    'ai-test-provider-fallback': {
        'title': 'Stabilize primary AI test provider path',
        'summary': 'AI test automation required fallback because the primary provider failed before the suite could complete normally.',
        'target_files': ['tools/ai_test_automation.py', 'app/config.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state'],
    },
    'ai-test-suite-regression': {
        'title': 'Repair failing AI behavior regression cases',
        'summary': 'AI test suite contains failing cases or runtime errors and should feed bounded remediation work.',
        'target_files': ['tools/ai_test_automation.py', 'data/ai_test_suite.json'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state'],
    },
    'telemetry-low-success-rate': {
        'title': 'Improve runtime success-rate remediation intake',
        'summary': 'Runtime telemetry shows weak task throughput and should generate concrete self-improvement candidates.',
        'target_files': ['tools/telemetry_store.py', 'tools/self_patch_loop.py'],
        'priority': 'medium',
        'validation': ['python -m compileall tools'],
    },
    'quality-low-task-throughput': {
        'title': 'Raise quality task-throughput score',
        'summary': 'Quality scoring is being dragged down by low recent task throughput and should produce bounded remediation work.',
        'target_files': ['tools/quality_system.py', 'tools/goal_runtime.py', 'tools/telemetry_store.py'],
        'priority': 'medium',
        'validation': ['python -m compileall tools'],
    },
    'daemon-health-flapping': {
        'title': 'Stabilize daemon health flapping',
        'summary': 'Tool health history shows repeated daemon instability that should stay visible as a core remediation candidate.',
        'target_files': ['tools/factory_daemon.py', 'tools/tool_health_audit.py'],
        'priority': 'high',
        'validation': ['python -m compileall app runtime tools state', 'refresh verification status'],
    },
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def ensure_supporting_policy_files() -> None:
    if not IMMUTABILITY.exists():
        save_json(IMMUTABILITY, {
            'updated_at': utc_iso(),
            'immutable_roots': ['app', 'runtime', 'state'],
            'immutable_tool_modules': sorted(IMMUTABLE_TOOL_MODULES),
            'rule': 'Core Modules Immutable',
        })
    if not APPROVED_PATCH.exists():
        save_json(APPROVED_PATCH, {
            'updated_at': utc_iso(),
            'action': 'approved_patch',
            'required_fields': ['reviewer', 'reason', 'target_files', 'validation', 'rollback_note'],
            'mode': 'MANUAL',
        })
    if not APPROVED_PATCH_RECORDS.exists():
        save_json(APPROVED_PATCH_RECORDS, {'updated_at': utc_iso(), 'records': []})


def module_index() -> dict[str, dict[str, Any]]:
    payload = load_json(GRAPH, {})
    return {item.get('module'): item for item in payload.get('modules', []) if item.get('module')}


def path_to_module(rel_path: str, index: dict[str, dict[str, Any]]) -> str | None:
    normalized = str((ROOT / rel_path).resolve())
    for module, item in index.items():
        if str(item.get('path')) == normalized:
            return module
    if rel_path.endswith('.py'):
        return rel_path[:-3].replace('\\', '.').replace('/', '.')
    return None


def is_core_target(rel_path: str, module_name: str | None) -> bool:
    path_str = rel_path.replace('\\', '/').lower()
    if path_str.startswith('app/') or path_str.startswith('runtime/') or path_str.startswith('state/'):
        return True
    if module_name and module_name in IMMUTABLE_TOOL_MODULES:
        return True
    return False


def upgrade_lane_for_target_files(target_files: list[str]) -> str:
    if not target_files:
        return 'metadata'
    if len(target_files) <= SMALL_FEATURE_MAX_TARGET_FILES:
        return 'small_feature'
    return 'bounded_self_improvement'


VERIFICATION_REASON_TARGETS: dict[str, dict[str, Any]] = {
    'compileall': ISSUE_MAP['verification-compileall-failure'],
    'architecture': ISSUE_MAP['verification-architecture-violation'],
    'tool_health': ISSUE_MAP['verification-tool-health-blocker'],
    'runtime_health': ISSUE_MAP['verification-runtime-health-failure'],
}


def _recent_tail(items: list[str], limit: int = 4) -> str:
    if not items:
        return 'none'
    return ' | '.join(str(item) for item in items[-limit:])


def add_verification_findings(findings: list[dict[str, Any]], seen: set[str], verification: dict[str, Any], index: dict[str, dict[str, Any]]) -> None:
    compileall_block = verification.get('compileall') or {}
    if compileall_block.get('passed') is False:
        template = dict(VERIFICATION_REASON_TARGETS['compileall'])
        stderr_tail = _recent_tail(compileall_block.get('stderr_tail') or [])
        stdout_tail = _recent_tail(compileall_block.get('stdout_tail') or [])
        template['summary'] = f"{template['summary']} returncode={compileall_block.get('returncode')} stderr_tail={stderr_tail} stdout_tail={stdout_tail}"
        add_item(findings, seen, 'verification:compileall-failure', 'verification_status', 'verification-compileall-failure', index, template=template)

    architecture = verification.get('architecture') or {}
    if architecture.get('status') not in {None, 'pass'}:
        template = dict(VERIFICATION_REASON_TARGETS['architecture'])
        violations = []
        for item in (architecture.get('rule_results') or []):
            if item.get('passed') is False:
                violations.append(str(item.get('rule') or 'unknown-rule'))
        template['summary'] = f"{template['summary']} violation_count={architecture.get('violation_count', 0)} rules={','.join(violations[:4]) or 'unknown'}"
        add_item(findings, seen, 'verification:architecture-failure', 'verification_status', 'verification-architecture-violation', index, template=template)

    tool_health = verification.get('tool_health') or {}
    blocking_issues = list(tool_health.get('blocking_issues') or tool_health.get('issues') or [])
    if tool_health.get('passed') is False and blocking_issues:
        template = dict(VERIFICATION_REASON_TARGETS['tool_health'])
        template['summary'] = f"{template['summary']} blocking_issues={','.join(str(item) for item in blocking_issues[:5])}"
        add_item(findings, seen, 'verification:tool-health-blocker', 'verification_status', 'verification-tool-health-blocker', index, template=template)

    runtime_health = verification.get('runtime_health') or {}
    task_runtime = verification.get('task_runtime') or {}
    if runtime_health.get('passed') is False:
        template = dict(VERIFICATION_REASON_TARGETS['runtime_health'])
        template['summary'] = (
            f"{template['summary']} active_tasks={task_runtime.get('active_tasks', 0)} "
            f"failed_tasks={task_runtime.get('failed_tasks', 0)} "
            f"open_error_escalations={task_runtime.get('open_error_escalations', 0)}"
        )
        add_item(findings, seen, 'verification:runtime-health-failure', 'verification_status', 'verification-runtime-health-failure', index, template=template)


def issue_template(kind: str) -> dict[str, Any]:
    return ISSUE_MAP.get(kind, {
        'title': f'Remediate {kind}',
        'summary': f'Bounded remediation for {kind}.',
        'target_files': ['tools/self_patch_loop.py'],
        'priority': 'low',
        'validation': ['python -m compileall tools'],
    })


def patch_submission_index() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    payload = load_json(PATCH_SUBMISSIONS, {'submissions': []})
    by_node: dict[str, dict[str, Any]] = {}
    by_patch: dict[str, dict[str, Any]] = {}
    for item in payload.get('submissions', []):
        node_id = item.get('node_id')
        patch_id = item.get('patch_id')
        if node_id:
            by_node[node_id] = item
        if patch_id:
            by_patch[patch_id] = item
    return by_node, by_patch


def approved_patch_record(plan_item: dict[str, Any]) -> dict[str, Any] | None:
    payload = load_json(APPROVED_PATCH_RECORDS, {'records': []})
    required_fields = set((load_json(APPROVED_PATCH, {}) or {}).get('required_fields', []))
    candidate_id = plan_item['candidate_id']
    patch_id = plan_item.get('existing_patch_id')
    for record in payload.get('records', []):
        if record.get('status') != 'approved':
            continue
        record_candidate = record.get('candidate_id')
        record_patch = record.get('patch_id')
        if record_candidate != candidate_id and (not patch_id or record_patch != patch_id):
            continue
        if required_fields.issubset(set(record.keys())):
            return record
    return None


def make_backlog_item(source: str, kind: str, template: dict[str, Any], index: dict[str, dict[str, Any]], existing_submission: dict[str, Any] | None = None) -> dict[str, Any]:
    target_files = template.get('target_files', [])
    modules = [path_to_module(path, index) for path in target_files]
    modules = [item for item in modules if item]
    if not modules and existing_submission:
        modules = list(existing_submission.get('module_focus') or [])
    owner_teams = sorted({(index.get(module) or {}).get('owner_team') for module in modules if (index.get(module) or {}).get('owner_team')})
    if not owner_teams and existing_submission:
        owner_teams = list(existing_submission.get('owner_teams') or [])
    approved_patch_required = any(is_core_target(path, path_to_module(path, index)) for path in target_files)
    upgrade_lane = upgrade_lane_for_target_files(target_files)
    if approved_patch_required:
        upgrade_lane = 'guarded_core'
    if existing_submission and existing_submission.get('status') not in {'merged'}:
        approved_patch_required = approved_patch_required or existing_submission.get('merge_policy', {}).get('requires_architecture_validation', False)
    candidate_id = hashlib.sha1(f"{source}::{kind}::{','.join(target_files)}".encode('utf-8')).hexdigest()[:12]
    if existing_submission:
        node_id = str(existing_submission.get('node_id') or '')
        if node_id.startswith('self_improvement::'):
            candidate_id = node_id.split('self_improvement::', 1)[1] or candidate_id
    status = 'queued'
    if existing_submission and existing_submission.get('status') in {'approved'}:
        status = 'approved'
    if existing_submission and existing_submission.get('status') in {'merged'}:
        status = 'merged'
    return {
        'finding_id': candidate_id,
        'created_at': utc_iso(),
        'source': source,
        'kind': kind,
        'title': template['title'],
        'summary': template['summary'],
        'priority': template.get('priority', 'low'),
        'target_files': target_files,
        'module_focus': modules,
        'owner_teams': owner_teams,
        'validation': template.get('validation', []),
        'approved_patch_required': approved_patch_required,
        'safe_to_auto_merge': not approved_patch_required,
        'upgrade_lane': upgrade_lane,
        'small_feature_upgrade': upgrade_lane == 'small_feature' and not approved_patch_required,
        'status': status,
        'existing_patch_id': (existing_submission or {}).get('patch_id'),
        'existing_patch_status': (existing_submission or {}).get('status'),
    }


def add_item(findings: list[dict[str, Any]], seen: set[str], key: str, source: str, kind: str, index: dict[str, dict[str, Any]], template: dict[str, Any] | None = None, existing_submission: dict[str, Any] | None = None) -> None:
    if key in seen:
        return
    seen.add(key)
    findings.append(make_backlog_item(source, kind, template or issue_template(kind), index, existing_submission=existing_submission))


def build_backlog() -> list[dict[str, Any]]:
    ensure_supporting_policy_files()
    verification = load_json(VERIFY, {})
    control = load_json(CONTROL, {})
    release = load_json(RELEASE, {})
    failures = load_json(FAILURES, [])
    ai_test = load_json(AI_TEST, {})
    telemetry = load_json(TELEMETRY, {})
    quality = load_json(QUALITY, {})
    tool_health_history = load_json(TOOL_HEALTH_HISTORY, [])
    index = module_index()
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    submission_by_node, _ = patch_submission_index()

    current_tool_health = ((control.get('tool_health') or {}).get('issues') or [])
    for issue in current_tool_health:
        add_item(findings, seen, f'control-tool-health:{issue}', 'control_layer', issue, index)

    for decision in ((control.get('decision_engine') or {}).get('decisions') or []):
        reason = str(decision.get('reason') or '')
        if 'patch gate status=attention' in reason and 'control-layer-lags-quality' not in current_tool_health:
            issue = 'control-layer-lags-quality'
            add_item(findings, seen, f'decision:{issue}', 'decision_engine', issue, index)

    add_verification_findings(findings, seen, verification, index)

    for reason in (verification.get('patch_gate', {}) or {}).get('reasons', []):
        if reason in {'quality', 'tool_health', 'compileall', 'architecture'}:
            continue
        add_item(findings, seen, f'patch-gate:{reason}', 'verification', reason, index)

    if release.get('release_train', {}).get('status') == 'blocked':
        issue = 'release-train-blocked'
        add_item(findings, seen, f'release:{issue}', 'release_operations', issue, index)

    if not BACKLOG.exists() or not PLAN.exists() or not STATUS.exists() or not HANDOFF.exists():
        issue = 'self-improvement-bootstrap-gap'
        add_item(findings, seen, f'self-improvement:{issue}', 'self_improvement', issue, index)

    for item in failures[:3]:
        kind = str(item.get('pattern') or item.get('error') or 'failure-pattern').strip() or 'failure-pattern'
        template = issue_template('tool_health')
        add_item(findings, seen, f'failure:{kind}', 'failure_patterns', kind, index, template={
            'title': f'Address failure pattern: {kind}',
            'summary': item.get('solution') or item.get('mitigation') or template['summary'],
            'target_files': template['target_files'],
            'priority': 'medium',
            'validation': template['validation'],
        })

    ai_status = str(ai_test.get('status') or '').strip().lower()
    if ai_status in {'attention', 'degraded', 'missing'} or ai_test.get('error_count', 0) > 0 or ai_test.get('failing_case_ids'):
        issue = 'ai-test-suite-regression'
        template = issue_template(issue)
        failing_cases = ai_test.get('failing_case_ids', [])[:5]
        add_item(findings, seen, f'ai-test:{issue}', 'ai_test_status', issue, index, template={
            **template,
            'summary': f"{template['summary']} failing_cases={','.join(failing_cases) or 'none'} error_count={ai_test.get('error_count', 0)}",
        })

    attempted = ai_test.get('attempted_providers', []) or []
    failed_providers = [item for item in attempted if item.get('all_errors')]
    if failed_providers:
        issue = 'ai-test-provider-fallback'
        template = issue_template(issue)
        provider_names = ','.join(str(item.get('provider') or 'unknown') for item in failed_providers[:5])
        error_types = sorted({str(err) for item in failed_providers for err in (item.get('error_types') or []) if err})
        add_item(findings, seen, f'ai-test:{issue}:{provider_names}', 'ai_test_status', issue, index, template={
            **template,
            'summary': f"{template['summary']} failed_providers={provider_names or 'unknown'} error_types={','.join(error_types) or 'unknown'}",
        })

    total = int(telemetry.get('task_total', 0) or 0)
    failed = int(telemetry.get('task_failed', 0) or 0)
    success_rate = float(telemetry.get('task_success_rate', 0.0) or 0.0)
    if total >= 5 and (failed > 0 or success_rate < 0.5):
        issue = 'telemetry-low-success-rate'
        template = issue_template(issue)
        add_item(findings, seen, f'telemetry:{issue}', 'telemetry_events', issue, index, template={
            **template,
            'summary': f"{template['summary']} task_total={total} task_failed={failed} success_rate={success_rate}",
        })

    quality_status = str(quality.get('status') or '').strip().lower()
    task_score = float(quality.get('task_score', 1.0) or 0.0)
    overall_score = float(quality.get('overall_score', 1.0) or 0.0)
    if quality_status in {'candidate', 'attention'} and task_score < 0.5:
        issue = 'quality-low-task-throughput'
        template = issue_template(issue)
        add_item(findings, seen, f'quality:{issue}', 'quality_status', issue, index, template={
            **template,
            'summary': f"{template['summary']} task_score={task_score} overall_score={overall_score} status={quality_status}",
        })

    if isinstance(tool_health_history, list) and tool_health_history:
        recent_history = tool_health_history[-8:]
        daemon_failures = [
            item for item in recent_history
            if 'daemon-not-running' in (item.get('issues') or [])
        ]
        latest_daemon = ((recent_history[-1].get('daemon') or {}).get('status') if recent_history else None)
        if len(daemon_failures) >= 3:
            issue = 'daemon-health-flapping'
            template = issue_template(issue)
            add_item(findings, seen, f'tool-health:{issue}', 'tool_health_history', issue, index, template={
                **template,
                'summary': f"{template['summary']} recent_failures={len(daemon_failures)} latest_daemon_status={latest_daemon or 'unknown'}",
            })

    for node_id, submission in submission_by_node.items():
        if not str(node_id).startswith('self_improvement::'):
            continue
        if submission.get('status') == 'merged':
            continue
        candidate_id = str(node_id).split('self_improvement::', 1)[1]
        target_files = []
        for module in submission.get('module_focus') or []:
            item = index.get(module) or {}
            path = item.get('path')
            if path:
                try:
                    target_files.append(str(Path(path).resolve().relative_to(ROOT)).replace('\\', '/'))
                except Exception:
                    pass
        template = {
            'title': str(submission.get('title') or f'Self-improvement patch {candidate_id}').replace('Self-improvement patch for ', ''),
            'summary': submission.get('reason') or 'Pending self-improvement patch awaiting completion.',
            'target_files': target_files,
            'priority': 'high' if submission.get('merge_policy', {}).get('requires_architecture_validation') else 'medium',
            'validation': ['python -m compileall app runtime tools state', 'refresh verification status'] if target_files else ['static review'],
        }
        add_item(findings, seen, f'pending-patch:{candidate_id}', 'patch_submission', candidate_id, index, template=template, existing_submission=submission)

    return findings


def build_plan(backlog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan = []
    seen_candidate_ids: set[str] = set()
    for item in backlog:
        candidate_id = item['finding_id']
        if candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate_id)
        merge_decision = decide('approved_patch') if item.get('approved_patch_required') else decide('filesystem.write_workspace', target_path=str(ROOT / 'workspace'))
        plan.append({
            'candidate_id': candidate_id,
            'branch': f"codex/self-improve-{candidate_id[:8]}",
            'title': item['title'],
            'summary': item['summary'],
            'target_files': item['target_files'],
            'module_focus': item['module_focus'],
            'owner_teams': item['owner_teams'],
            'priority': item['priority'],
            'validation': item['validation'],
            'approved_patch_required': item['approved_patch_required'],
            'approval_mode': merge_decision.mode,
            'approval_reason': merge_decision.reason,
            'auto_patch_kind': 'proposal-only' if item['approved_patch_required'] else 'bounded-auto-patch',
            'status': 'planned',
            'existing_patch_id': item.get('existing_patch_id'),
            'existing_patch_status': item.get('existing_patch_status'),
        })
    return plan


def file_artifact(rel_path: str) -> dict[str, Any]:
    path = ROOT / rel_path
    payload: dict[str, Any] = {'path': rel_path, 'exists': path.exists()}
    if not path.exists():
        return payload
    stat = path.stat()
    payload.update({
        'size': stat.st_size,
        'mtime': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat().replace('+00:00', 'Z'),
    })
    raw: bytes | None = None
    try:
        raw = path.read_bytes()
        payload['sha1'] = hashlib.sha1(raw).hexdigest()
    except Exception as exc:
        payload['hash_error'] = f"{type(exc).__name__}: {exc}"
        raw = None
    if raw is not None and stat.st_size <= 65536:
        try:
            text_preview = raw.decode('utf-8')
            lines = text_preview.splitlines()
            payload['text_preview'] = lines[:120]
            payload['line_count'] = len(lines)
            payload['preview_truncated'] = len(lines) > 120
        except Exception:
            payload['text_preview'] = None
    return payload


def build_diff_summary(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any] | None:
    if previous is None:
        return {
            'path': current.get('path'),
            'status': 'new-target',
            'summary': 'No previous artifact snapshot was available for this target.',
        }
    if previous.get('sha1') == current.get('sha1') and previous.get('size') == current.get('size'):
        return None
    previous_lines = previous.get('text_preview')
    current_lines = current.get('text_preview')
    if isinstance(previous_lines, list) and isinstance(current_lines, list):
        diff_lines = list(difflib.unified_diff(previous_lines, current_lines, fromfile='before', tofile='after', n=2))
        if diff_lines:
            return {
                'path': current.get('path'),
                'status': 'modified',
                'summary': f"sha1 {previous.get('sha1', 'unknown')[:12]} -> {current.get('sha1', 'unknown')[:12]}",
                'diff_excerpt': diff_lines[:40],
                'excerpt_truncated': len(diff_lines) > 40,
            }
    return {
        'path': current.get('path'),
        'status': 'modified',
        'summary': (
            f"size {previous.get('size', 'unknown')} -> {current.get('size', 'unknown')}; "
            f"sha1 {str(previous.get('sha1') or 'unknown')[:12]} -> {str(current.get('sha1') or 'unknown')[:12]}"
        ),
    }


def build_artifact_evidence(plan_item: dict[str, Any]) -> dict[str, Any]:
    artifact_store = load_json(ARTIFACTS, {'baseline': {}, 'history': []})
    baseline_map = artifact_store.get('baseline', {}) or {}
    current_files = [file_artifact(path) for path in plan_item.get('target_files', [])]
    previous_files = baseline_map.get(plan_item['candidate_id'], []) or []
    previous_index = {item.get('path'): item for item in previous_files if item.get('path')}
    changed_files: list[str] = []
    unchanged_files: list[str] = []
    diff_summary: list[dict[str, Any]] = []
    for item in current_files:
        previous = previous_index.get(item.get('path'))
        if previous is None:
            changed_files.append(str(item.get('path')))
            summary = build_diff_summary(previous, item)
            if summary:
                diff_summary.append(summary)
            continue
        if previous.get('sha1') != item.get('sha1') or previous.get('size') != item.get('size'):
            changed_files.append(str(item.get('path')))
            summary = build_diff_summary(previous, item)
            if summary:
                diff_summary.append(summary)
        else:
            unchanged_files.append(str(item.get('path')))
    evidence = {
        'captured_at': utc_iso(),
        'candidate_id': plan_item['candidate_id'],
        'branch': plan_item.get('branch'),
        'target_files': current_files,
        'previous_target_files': previous_files,
        'changed_files': changed_files,
        'unchanged_files': unchanged_files,
        'change_count': len(changed_files),
        'material_change': len(changed_files) > 0,
        'evidence_status': 'material-change' if changed_files else 'logical-only',
        'diff_summary': diff_summary,
    }
    baseline_map[plan_item['candidate_id']] = current_files
    artifact_store['baseline'] = baseline_map
    history = list(artifact_store.get('history') or [])
    history.append({
        'captured_at': evidence['captured_at'],
        'candidate_id': plan_item['candidate_id'],
        'change_count': evidence['change_count'],
        'evidence_status': evidence['evidence_status'],
        'material_change': evidence['material_change'],
        'changed_files': list(evidence.get('changed_files') or []),
        'diff_summary': list(evidence.get('diff_summary') or []),
    })
    artifact_store['history'] = history[-200:]
    save_json(ARTIFACTS, artifact_store)
    return evidence


def run_validation(plan_item: dict[str, Any]) -> dict[str, Any]:
    target_files = plan_item.get('target_files', [])
    validation_steps = plan_item.get('validation', [])
    checks = []
    passed = True
    python_targets = [path for path in target_files if path.endswith('.py')]
    if python_targets:
        python_exe = ROOT.parent / 'tools' / 'python311-embed' / 'python.exe'
        if not python_exe.exists():
            python_exe = Path(sys.executable)
        command = [str(python_exe), '-m', 'compileall', str(ROOT / 'tools')]
        completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
        checks.append({'type': 'compileall-tools', 'command': command, 'returncode': completed.returncode, 'passed': completed.returncode == 0, 'stdout_tail': completed.stdout.splitlines()[-10:], 'stderr_tail': completed.stderr.splitlines()[-10:]})
        passed = passed and completed.returncode == 0
    for path in target_files:
        exists = (ROOT / path).exists()
        checks.append({'type': 'file-presence', 'path': path, 'passed': exists})
        passed = passed and exists
    if any(step == 'refresh verification status' for step in validation_steps):
        python_exe = ROOT.parent / 'tools' / 'python311-embed' / 'python.exe'
        if not python_exe.exists():
            python_exe = Path(sys.executable)
        command = [str(python_exe), str(ROOT / 'tools' / 'verification_engine.py')]
        completed = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
        checks.append({'type': 'verification-refresh', 'command': command, 'returncode': completed.returncode, 'passed': completed.returncode == 0, 'stdout_tail': completed.stdout.splitlines()[-10:], 'stderr_tail': completed.stderr.splitlines()[-10:]})
        passed = passed and completed.returncode == 0
    return {'passed': passed, 'checks': checks}


def transition_patch_submission(plan_item: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    node_id = f"self_improvement::{plan_item['candidate_id']}"
    existing = find_patch_submission(node_id=node_id)
    if existing is None and plan_item.get('existing_patch_id'):
        _, by_patch = patch_submission_index()
        existing = by_patch.get(plan_item['existing_patch_id'])
    if existing is None:
        existing = create_patch_submission(task_id=None, node_id=node_id, title=f"Self-improvement patch for {plan_item['title']}", team=(plan_item.get('owner_teams') or ['infrastructure_team'])[0], owner_teams=plan_item.get('owner_teams') or ['infrastructure_team'], module_focus=plan_item.get('module_focus') or [], reason=plan_item['summary'], repo_path=str(ROOT))
    patch_id = existing['patch_id']
    current_status = existing.get('status')
    merge_status = existing.get('merge_status')

    approval_record = approved_patch_record({**plan_item, 'existing_patch_id': patch_id})
    if plan_item.get('approved_patch_required') and approval_record is None:
        return {'patch_id': patch_id, 'status': current_status, 'merge_status': merge_status, 'resolution': 'waiting-approved-patch'}

    if validation.get('passed'):
        if current_status not in {'approved', 'merged'}:
            approval_reason = 'Approved patch record accepted by self-improvement loop.' if approval_record else 'Auto-approved by self-improvement loop after candidate validation passed.'
            existing = resolve_patch_submission(patch_id, status='approved', resolution=approval_reason)
        if existing.get('status') != 'merged':
            merge_reason = 'Merged after approved patch record and validation passed.' if approval_record else 'Auto-merged by self-improvement loop after candidate validation passed.'
            existing = resolve_patch_submission(patch_id, status='merged', resolution=merge_reason)
    return {'patch_id': existing['patch_id'], 'status': existing.get('status'), 'merge_status': existing.get('merge_status'), 'resolution': existing.get('resolution')}


def normalize_artifact_evidence(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(payload or {})
    material_change = bool(payload.get('material_change')) or str(payload.get('evidence_status') or '').strip().lower() == 'material-change' or int(payload.get('change_count', 0) or 0) > 0
    payload['material_change'] = material_change
    payload['evidence_status'] = 'material-change' if material_change else 'logical-only'
    if material_change and not payload.get('changed_files'):
        payload['changed_files'] = [item.get('path') for item in (payload.get('target_files') or []) if item.get('path')]
    diff_summary = list(payload.get('diff_summary') or [])
    if material_change and not diff_summary:
        diff_summary = [
            {
                'path': path,
                'status': 'historical-material-change',
                'summary': 'Historical material change preserved; detailed diff excerpt was not captured in the original evidence snapshot.',
            }
            for path in (payload.get('changed_files') or [])
        ]
    payload['diff_summary'] = diff_summary
    return payload


def strongest_historical_evidence(candidate_id: str) -> dict[str, Any] | None:
    artifact_store = load_json(ARTIFACTS, {'history': []})
    history = list(artifact_store.get('history') or [])
    for item in reversed(history):
        if item.get('candidate_id') != candidate_id:
            continue
        material_change = bool(item.get('material_change')) or str(item.get('evidence_status') or '').strip().lower() == 'material-change' or int(item.get('change_count', 0) or 0) > 0
        if not material_change:
            continue
        normalized = dict(item)
        normalized['material_change'] = True
        normalized['evidence_status'] = 'material-change'
        return normalize_artifact_evidence(normalized)
    return None


def choose_artifact_evidence(current: dict[str, Any], existing: dict[str, Any] | None, historical: dict[str, Any] | None = None) -> dict[str, Any]:
    current = normalize_artifact_evidence(current)
    existing = normalize_artifact_evidence(existing)
    historical = normalize_artifact_evidence(historical)
    if existing.get('material_change') and not current.get('material_change'):
        return normalize_artifact_evidence(existing)
    if existing.get('change_count', 0) > current.get('change_count', 0):
        return normalize_artifact_evidence(existing)
    if historical.get('material_change') and not current.get('material_change'):
        merged = dict(current)
        merged['material_change'] = True
        merged['evidence_status'] = historical.get('evidence_status', 'material-change')
        merged['change_count'] = historical.get('change_count', current.get('change_count', 0))
        merged['changed_files'] = historical.get('changed_files') or [item.get('path') for item in (current.get('target_files') or []) if item.get('path')]
        merged['diff_summary'] = historical.get('diff_summary', current.get('diff_summary', []))
        return normalize_artifact_evidence(merged)
    if historical.get('change_count', 0) > current.get('change_count', 0):
        merged = dict(current)
        merged['material_change'] = True
        merged['change_count'] = historical.get('change_count')
        merged['changed_files'] = historical.get('changed_files') or [item.get('path') for item in (current.get('target_files') or []) if item.get('path')]
        merged['diff_summary'] = historical.get('diff_summary', current.get('diff_summary', []))
        merged['evidence_status'] = historical.get('evidence_status', 'material-change')
        return normalize_artifact_evidence(merged)
    return normalize_artifact_evidence(current)


def build_status(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for entry in plan:
        validation = run_validation(entry)
        patch_state = transition_patch_submission(entry, validation)
        evidence = build_artifact_evidence(entry)
        existing_submission = None
        try:
            _, by_patch = patch_submission_index()
            existing_submission = by_patch.get(patch_state['patch_id'])
        except Exception:
            existing_submission = None
        evidence = choose_artifact_evidence(
            evidence,
            (existing_submission or {}).get('artifacts'),
            strongest_historical_evidence(entry['candidate_id']),
        )
        try:
            record_patch_artifacts(patch_state['patch_id'], artifacts=evidence)
        except Exception:
            pass
        items.append({
            'candidate_id': entry['candidate_id'],
            'title': entry['title'],
            'approved_patch_required': entry['approved_patch_required'],
            'upgrade_lane': entry.get('upgrade_lane'),
            'small_feature_upgrade': entry.get('small_feature_upgrade'),
            'validation_passed': validation['passed'],
            'validation': validation['checks'],
            'artifact_evidence': evidence,
            'patch_submission': patch_state,
            'status': 'merged' if patch_state.get('status') == 'merged' else 'waiting_approval' if entry['approved_patch_required'] and patch_state.get('resolution') == 'waiting-approved-patch' else 'blocked' if not validation['passed'] else 'approved',
        })
    return items


def backfill_patch_artifacts(status_items: list[dict[str, Any]]) -> None:
    for item in status_items:
        patch_state = item.get('patch_submission') or {}
        patch_id = patch_state.get('patch_id')
        evidence = item.get('artifact_evidence')
        if not patch_id or not evidence:
            continue
        try:
            record_patch_artifacts(patch_id, artifacts=evidence)
        except Exception:
            continue


def _bundle_slug(candidate_id: str, title: str) -> str:
    safe = ''.join(ch.lower() if ch.isalnum() else '-' for ch in title).strip('-')
    while '--' in safe:
        safe = safe.replace('--', '-')
    return f"{candidate_id[:8]}-{safe[:48].strip('-')}".strip('-')


def _bundle_markdown(bundle: dict[str, Any]) -> str:
    evidence = bundle.get('artifact_evidence') or {}
    diff_summary = evidence.get('diff_summary') or []
    checks = bundle.get('validation') or []
    lines = [
        f"# {bundle.get('title')}",
        '',
        f"- Candidate: `{bundle.get('candidate_id')}`",
        f"- Patch: `{bundle.get('patch_id') or 'none'}`",
        f"- Branch: `{bundle.get('branch') or 'none'}`",
        f"- Status: `{bundle.get('status')}`",
        f"- Approval Required: `{bundle.get('approved_patch_required')}`",
        '',
        '## Summary',
        bundle.get('summary') or '',
        '',
        '## Targets',
    ]
    for item in bundle.get('target_files') or []:
        lines.append(f"- `{item}`")
    lines.extend(['', '## Validation'])
    for check in checks:
        lines.append(f"- `{check.get('type')}`: `passed={check.get('passed')}`")
    lines.extend(['', '## Artifact Evidence'])
    lines.append(f"- Evidence Status: `{evidence.get('evidence_status')}`")
    lines.append(f"- Material Change: `{evidence.get('material_change')}`")
    lines.append(f"- Changed Files: `{', '.join(evidence.get('changed_files') or []) or 'none'}`")
    lines.extend(['', '## Diff Summary'])
    if diff_summary:
        for item in diff_summary:
            lines.append(f"- `{item.get('path')}`: {item.get('summary')}")
    else:
        lines.append('- none')
    return '\n'.join(lines) + '\n'


def write_patch_bundles(status_items: list[dict[str, Any]], plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    BUNDLES.mkdir(parents=True, exist_ok=True)
    plan_index = {item['candidate_id']: item for item in plan}
    bundles = []
    for item in status_items:
        candidate_id = item.get('candidate_id')
        if not candidate_id or candidate_id not in plan_index:
            continue
        plan_item = plan_index[candidate_id]
        patch_state = item.get('patch_submission') or {}
        slug = _bundle_slug(candidate_id, item.get('title') or candidate_id)
        bundle_json = BUNDLES / f"{slug}.json"
        bundle_md = BUNDLES / f"{slug}.md"
        bundle = {
            'updated_at': utc_iso(),
            'candidate_id': candidate_id,
            'title': item.get('title'),
            'summary': plan_item.get('summary'),
            'branch': plan_item.get('branch'),
            'status': item.get('status'),
            'patch_id': patch_state.get('patch_id'),
            'merge_status': patch_state.get('merge_status'),
            'resolution': patch_state.get('resolution'),
            'approved_patch_required': item.get('approved_patch_required'),
            'target_files': plan_item.get('target_files') or [],
            'validation': item.get('validation') or [],
            'artifact_evidence': item.get('artifact_evidence') or {},
            'bundle_files': {
                'json': str(bundle_json),
                'markdown': str(bundle_md),
            },
        }
        save_json(bundle_json, bundle)
        bundle_md.write_text(_bundle_markdown(bundle), encoding='utf-8')
        item['bundle_files'] = bundle['bundle_files']
        bundles.append({
            'candidate_id': candidate_id,
            'patch_id': patch_state.get('patch_id'),
            'status': item.get('status'),
            'json': str(bundle_json),
            'markdown': str(bundle_md),
        })
    save_json(BUNDLE_INDEX, {'updated_at': utc_iso(), 'bundle_count': len(bundles), 'items': bundles})
    return bundles


def build_handoff(status_items: list[dict[str, Any]], plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan_index = {item['candidate_id']: item for item in plan}
    handoff = []
    for item in status_items:
        if item['status'] == 'merged':
            continue
        plan_item = plan_index[item['candidate_id']]
        handoff.append({
            'candidate_id': item['candidate_id'],
            'title': item['title'],
            'branch': plan_item['branch'],
            'target_files': plan_item['target_files'],
            'upgrade_lane': plan_item.get('upgrade_lane'),
            'tests_run': [check['type'] for check in item['validation']],
            'validation_passed': item['validation_passed'],
            'artifact_evidence': item.get('artifact_evidence'),
            'bundle_files': item.get('bundle_files'),
            'approved_patch_required': item['approved_patch_required'],
            'merge_status': (item.get('patch_submission') or {}).get('merge_status'),
            'patch_id': (item.get('patch_submission') or {}).get('patch_id'),
            'resolution': (item.get('patch_submission') or {}).get('resolution'),
            'approval_record_required_fields': (load_json(APPROVED_PATCH, {}) or {}).get('required_fields', []),
            'rollback_note': 'Revert logical patch record and restore previous approved asset if post-merge verification fails.',
        })
    return handoff


def rewrite_saved_artifact_records() -> None:
    status_payload = load_json(STATUS, {})
    patch_payload = load_json(PATCH_SUBMISSIONS, {'submissions': []})
    changed = False

    for item in status_payload.get('items', []) or []:
        candidate_id = item.get('candidate_id')
        evidence = normalize_artifact_evidence(
            choose_artifact_evidence(
                item.get('artifact_evidence') or {},
                None,
                strongest_historical_evidence(candidate_id) if candidate_id else None,
            )
        )
        if item.get('artifact_evidence') != evidence:
            item['artifact_evidence'] = evidence
            changed = True

    for item in patch_payload.get('submissions', []) or []:
        node_id = str(item.get('node_id') or '')
        candidate_id = node_id.split('self_improvement::', 1)[1] if node_id.startswith('self_improvement::') else None
        evidence = normalize_artifact_evidence(
            choose_artifact_evidence(
                (item.get('artifacts') or {}),
                None,
                strongest_historical_evidence(candidate_id) if candidate_id else None,
            )
        )
        if item.get('artifacts') != evidence:
            item['artifacts'] = evidence
            item['updated_at'] = utc_iso()
            changed = True

    if changed:
        save_json(STATUS, status_payload)
        save_json(PATCH_SUBMISSIONS, patch_payload)


def self_improvement_status() -> dict[str, Any]:
    status_payload = load_json(STATUS, {})
    candidate_payload = load_json(OUT, {})
    handoff_payload = load_json(HANDOFF, {})
    items = list(status_payload.get('items') or [])
    small_feature_items = [item for item in items if item.get('upgrade_lane') == 'small_feature']
    auto_upgrade_ready = [item for item in items if item.get('upgrade_lane') == 'small_feature' and item.get('status') in {'approved', 'merged'}]
    return {
        'updated_at': utc_iso(),
        'status': status_payload.get('status'),
        'candidate_count': int(candidate_payload.get('candidate_count', len(candidate_payload.get('candidates') or [])) or 0),
        'small_feature_candidate_count': int(candidate_payload.get('small_feature_candidate_count', len([item for item in (candidate_payload.get('candidates') or []) if item.get('upgrade_lane') == 'small_feature'])) or 0),
        'auto_upgrade_ready_count': int(candidate_payload.get('auto_upgrade_ready_count', len(auto_upgrade_ready)) or 0),
        'merged_count': int(status_payload.get('merged_count', 0) or 0),
        'waiting_approval_count': int(status_payload.get('waiting_approval_count', 0) or 0),
        'blocked_count': int(status_payload.get('blocked_count', 0) or 0),
        'small_feature_auto_upgrade_count': int(status_payload.get('small_feature_auto_upgrade_count', len([item for item in small_feature_items if item.get('status') == 'merged'])) or 0),
        'recent_items': items[-10:],
        'handoff_status': handoff_payload.get('status'),
        'handoff_count': int(handoff_payload.get('handoff_count', len(handoff_payload.get('items') or [])) or 0),
    }


def reconcile_artifact_records(status_items: list[dict[str, Any]]) -> None:
    status_payload = load_json(STATUS, {})
    patch_payload = load_json(PATCH_SUBMISSIONS, {'submissions': []})
    status_index = {item.get('candidate_id'): item for item in (status_payload.get('items') or []) if item.get('candidate_id')}
    patch_index = {}
    for item in patch_payload.get('submissions', []):
        node_id = str(item.get('node_id') or '')
        if node_id.startswith('self_improvement::'):
            patch_index[node_id.split('self_improvement::', 1)[1]] = item

    changed = False
    for item in status_items:
        candidate_id = item.get('candidate_id')
        if not candidate_id:
            continue
        patch_state = item.get('patch_submission') or {}
        patch_id = patch_state.get('patch_id')
        evidence = choose_artifact_evidence(
            item.get('artifact_evidence') or {},
            ((patch_index.get(candidate_id) or {}).get('artifacts')),
            strongest_historical_evidence(candidate_id),
        )
        evidence = normalize_artifact_evidence(evidence)
        if candidate_id in status_index:
            status_index[candidate_id]['artifact_evidence'] = evidence
            changed = True
        patch_item = patch_index.get(candidate_id)
        if patch_item is not None:
            patch_item['artifacts'] = evidence
            patch_item['updated_at'] = utc_iso()
            changed = True
        elif patch_id:
            try:
                record_patch_artifacts(patch_id, artifacts=evidence)
                changed = True
            except Exception:
                pass

    if changed:
        save_json(STATUS, status_payload)
        save_json(PATCH_SUBMISSIONS, patch_payload)


def main() -> int:
    backlog = build_backlog()
    plan = build_plan(backlog)
    status_items = build_status(plan)
    backfill_patch_artifacts(status_items)
    write_patch_bundles(status_items, plan)
    handoff = build_handoff(status_items, plan)

    candidate_payload = {
        'updated_at': utc_iso(),
        'status': 'attention' if plan else 'stable',
        'candidate_count': len(plan),
        'small_feature_candidate_count': sum(1 for item in plan if item.get('upgrade_lane') == 'small_feature'),
        'auto_upgrade_ready_count': sum(1 for item in plan if item.get('upgrade_lane') == 'small_feature' and not item.get('approved_patch_required')),
        'candidates': [{
            'candidate_id': item['candidate_id'],
            'title': item['title'],
            'target_files': item['target_files'],
            'priority': item['priority'],
            'approved_patch_required': item['approved_patch_required'],
            'upgrade_lane': item.get('upgrade_lane'),
            'small_feature_upgrade': item.get('small_feature_upgrade'),
            'cheap_worker_ok': not item['approved_patch_required'],
            'sandbox_required': bool(item['target_files']),
            'existing_patch_id': item.get('existing_patch_id'),
        } for item in plan],
    }
    status_payload = {
        'updated_at': utc_iso(),
        'status': 'stable' if not status_items else 'pass' if all(item['status'] in {'merged', 'approved', 'waiting_approval'} for item in status_items) else 'attention',
        'items': status_items,
        'merged_count': sum(1 for item in status_items if item['status'] == 'merged'),
        'waiting_approval_count': sum(1 for item in status_items if item['status'] == 'waiting_approval'),
        'blocked_count': sum(1 for item in status_items if item['status'] == 'blocked'),
        'small_feature_auto_upgrade_count': sum(1 for item in status_items if item.get('upgrade_lane') == 'small_feature' and item.get('status') == 'merged'),
    }
    handoff_payload = {'updated_at': utc_iso(), 'status': 'ready' if handoff else 'idle', 'handoff_count': len(handoff), 'items': handoff}

    save_json(OUT, candidate_payload)
    save_json(BACKLOG, {'updated_at': utc_iso(), 'status': 'ready' if backlog else 'stable', 'items': backlog})
    save_json(PLAN, {'updated_at': utc_iso(), 'status': 'ready' if plan else 'idle', 'items': plan})
    save_json(STATUS, status_payload)
    save_json(HANDOFF, handoff_payload)
    reconcile_artifact_records(status_items)
    rewrite_saved_artifact_records()

    append_trace('self-improvement', 'run bug-intake to patch-test-merge loop', 'run self_patch_loop.py', f"candidates={len(plan)} merged={status_payload['merged_count']} waiting_approval={status_payload['waiting_approval_count']}", 'review self improvement handoff', worker='local-runtime')
    print(json.dumps({'candidates': len(plan), 'merged': status_payload['merged_count'], 'waiting_approval': status_payload['waiting_approval_count'], 'blocked': status_payload['blocked_count']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
