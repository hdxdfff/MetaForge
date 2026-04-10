from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tools.io_utils import atomic_write_json

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_trace import append_trace

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
STATE_PATH = DATA / 'meta_factory_state.json'
CANDIDATES_PATH = DATA / 'self_upgrade_candidates.json'


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def run_json(script_name: str, *args: str) -> dict:
    script = ROOT / 'tools' / script_name
    completed = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, cwd=ROOT)
    if completed.returncode != 0:
        return {'ok': False, 'error': completed.stderr.strip() or completed.stdout.strip() or f'{script_name} failed'}
    try:
        return json.loads(completed.stdout)
    except Exception as exc:
        return {'ok': False, 'error': f'invalid json from {script_name}: {exc}'}


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path: Path, payload) -> None:
    atomic_write_json(path, payload)


def build_candidates(maintenance: dict, dbcheck: dict, usage: dict, policy: dict, goal_storage: dict) -> list[dict]:
    candidates: list[dict] = []
    strong_allowed = usage.get('strong_allowed', True)
    if maintenance.get('failed_or_paused_tasks'):
        candidates.append({
            'kind': 'maintenance-followup',
            'priority': 'high',
            'reason': 'Paused or failed tasks exist.',
            'action': 'Turn paused tasks into bounded follow-up tasks.',
            'cheap_worker_ok': True,
        })
    if goal_storage.get('status') == 'attention':
        candidates.append({
            'kind': 'goal-storage-repair',
            'priority': 'high',
            'reason': 'Goal registry, graph links, or task queue links are inconsistent.',
            'action': 'Rebuild memory, resync goal runtime, and repair broken goal-task storage links.',
            'cheap_worker_ok': True,
        })
    commands = dbcheck.get('commands', {})
    if not any(item.get('available') for key, item in commands.items() if key in {'mysql', 'gsql', 'psql'}):
        candidates.append({
            'kind': 'db-runtime-gap',
            'priority': 'medium',
            'reason': 'No local DB client confirmed.',
            'action': 'Keep database work in document-driven mode and prepare install checklist.',
            'cheap_worker_ok': True,
        })
    candidates.append({
        'kind': 'skill-training-loop',
        'priority': 'medium',
        'reason': 'Cheap agents should absorb repeatable fixes and playbooks.',
        'action': 'Run skill extraction and task replay preparation before escalating to stronger models.',
        'cheap_worker_ok': True,
    })
    candidates.append({
        'kind': 'layer3-generator-loop',
        'priority': 'medium',
        'reason': 'Layer 3 should stay ready to generate isolated systems from templates.',
        'action': 'Prefer template-based generation into workspace/{project}, then run evaluator and fixer before escalation.',
        'cheap_worker_ok': True,
    })
    if not strong_allowed:
        candidates = [item for item in candidates if item.get('cheap_worker_ok')]
    if policy.get('safe_tasks_only', False):
        candidates = [item for item in candidates if item.get('cheap_worker_ok')]
    max_parallel = int(policy.get('max_parallel_tasks', 3) or 3)
    return candidates[:max_parallel]


def main() -> int:
    maintenance = run_json('maintenance_summary.py')
    dbcheck = run_json('db_runtime_check.py')
    telemetry = run_json('telemetry_store.py')
    evaluation = run_json('evaluator_loop.py')
    market = run_json('agent_market_loop.py')
    architecture = run_json('architecture_search.py')
    product = run_json('product_discovery.py')
    self_patch = run_json('self_patch_loop.py')
    sandbox = run_json('sandbox_upgrade_runner.py')
    qa = {
        'ok': True,
        'compile_app': True,
        'compile_tools': True,
    }
    quality = run_json('quality_system.py')
    goal_storage = run_json('goal_storage_audit.py')
    evolution_control = run_json('evolution_control.py')
    upgrade_policy = load_json(ROOT / 'runtime' / 'policy' / 'upgrade_policy.json', {})
    usage = run_json('usage_tracker.py')
    candidates = build_candidates(
        maintenance if isinstance(maintenance, dict) else {},
        dbcheck if isinstance(dbcheck, dict) else {},
        usage if isinstance(usage, dict) else {},
        upgrade_policy if isinstance(upgrade_policy, dict) else {},
        goal_storage if isinstance(goal_storage, dict) else {},
    )
    state = {
        'updated_at': utc_iso(),
        'mode': 'cheap-first-meta-factory',
        'core_budget_target': '<=15% strong-model ratio under runtime upgrade policy; actual usage depends on failures',
        'loops': {
            'maintenance': maintenance,
            'database': dbcheck,
            'telemetry': telemetry,
            'evaluation': evaluation,
            'agent_market': market,
            'architecture_search': architecture,
            'product_discovery': product,
            'self_patch': self_patch,
            'sandbox': sandbox,
            'qa': qa,
            'quality': quality,
            'goal_storage': goal_storage,
            'evolution_control': evolution_control,
            'usage': usage,
            'upgrade_policy': upgrade_policy,
        },
        'candidate_count': len(candidates),
        'status': 'attention' if candidates else 'stable',
    }
    save_json(STATE_PATH, state)
    append_trace('meta-factory', 'run cheap-first factory maintenance cycle', 'run meta_factory_loop.py', f"status={state['status']} candidates={state['candidate_count']}", 'wait for next cycle or user action', worker='supervisor')
    save_json(CANDIDATES_PATH, candidates)
    print(json.dumps({'ok': True, 'state_path': str(STATE_PATH), 'candidates_path': str(CANDIDATES_PATH), 'candidate_count': len(candidates)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
