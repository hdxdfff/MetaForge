from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
TEMPLATES = DATA / 'vm_templates.json'
REGISTRY = DATA / 'vm_registry.json'
SNAPSHOTS = ROOT / 'sandbox' / 'vm-snapshots'
VM_LOGS = DATA / 'vm_command_logs.json'


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _save_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def list_templates() -> list[dict[str, Any]]:
    return _load_json(TEMPLATES, {'templates': []}).get('templates', [])


def list_vms() -> list[dict[str, Any]]:
    return _load_json(REGISTRY, {'vms': []}).get('vms', [])


def _save_vms(vms: list[dict[str, Any]]) -> None:
    _save_json(REGISTRY, {'vms': vms})


def _find_template(template_id: str) -> dict[str, Any]:
    match = next((item for item in list_templates() if item.get('template_id') == template_id), None)
    if not match:
        raise RuntimeError(f'VM template not found: {template_id}')
    return match




def infer_worker_vm_policy(*, prompt: str = '', goal: str = '', preferred_worker: str | None = None, tool_route: dict[str, Any] | None = None, vm_template: dict[str, Any] | None = None) -> dict[str, Any]:
    query = ' '.join(item for item in [prompt or '', goal or '', preferred_worker or ''] if item).lower()
    domain = ((tool_route or {}).get('selected') or {}).get('domain') or ''
    heavy_worker = preferred_worker in {'coder', 'tester', 'ops', 'shell', 'docker'}
    build_like = any(token in query for token in ['build', 'compile', 'docker', 'package', 'make', 'cmake', 'cargo', 'npm', 'pytest', 'qemu', 'regression'])
    code_like = any(token in query for token in ['implement', 'code', 'patch', 'module', 'feature', 'kernel', 'syscall', 'scheduler'])
    infra_like = domain in {'infrastructure', 'code', 'system'}
    preferred = bool(vm_template) or (heavy_worker and (build_like or code_like or infra_like))
    required = bool(vm_template and vm_template.get('backend') in {'qemu-test'})
    lane = 'worker-vm' if preferred else 'host-control'
    return {
        'lane': lane,
        'worker_vm_preferred': preferred,
        'worker_vm_required': required,
        'heavy_worker': heavy_worker,
        'reason': 'vm-template-selected' if vm_template else ('heavy-worker-policy' if preferred else 'host-control-default'),
    }
def choose_template_for_task(request: str | None = None, *, goal: str | None = None, prompt: str | None = None) -> dict[str, Any] | None:
    query = ' '.join(item for item in [request or '', goal or '', prompt or ''] if item).lower()
    if not query:
        return None
    if any(token in query for token in ['test', 'pytest', 'qemu', 'regression', '验证', '测试']):
        template_id = 'test_template'
        reason = 'Matched test/regression keywords.'
    elif any(token in query for token in ['experiment', 'benchmark', 'research', '探索', '实验']):
        template_id = 'experiment_template'
        reason = 'Matched experiment/research keywords.'
    elif any(token in query for token in ['build', 'compile', 'docker', 'package', '构建', '编译', '打包']):
        template_id = 'dev_template'
        reason = 'Matched build/package keywords.'
    else:
        return None
    template = _find_template(template_id)
    return {
        'template_id': template_id,
        'name': template.get('name'),
        'role': template.get('role'),
        'cpus': template.get('cpus'),
        'memory_mb': template.get('memory_mb'),
        'preinstalled_tools': template.get('preinstalled_tools', []),
        'backend': template.get('backend', 'sandbox-vm'),
        'reason': reason,
    }


def create_vm(name: str, template_id: str, purpose: str = 'general') -> dict[str, Any]:
    template = _find_template(template_id)
    payload = {
        'vm_id': f'vm_{uuid4().hex[:10]}',
        'name': name,
        'purpose': purpose,
        'template_id': template_id,
        'role': template.get('role'),
        'status': 'provisioned',
        'cpus': template.get('cpus', 1),
        'memory_mb': template.get('memory_mb', 1024),
        'preinstalled_tools': template.get('preinstalled_tools', []),
        'backend': template.get('backend', 'sandbox-vm'),
        'created_at': _utc(),
        'updated_at': _utc(),
        'notes': 'VM orchestrator MVP record only; execution remains bounded until explicit runtime integration.',
        'snapshot_count': 0,
    }
    vms = list_vms()
    vms.append(payload)
    _save_vms(vms)
    return payload


def append_vm_log(vm_id: str, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    logs = _load_json(VM_LOGS, {'entries': []})
    entry = {
        'logged_at': _utc(),
        'vm_id': vm_id,
        'event': event,
        'payload': payload or {},
    }
    logs.setdefault('entries', []).append(entry)
    logs['entries'] = logs['entries'][-500:]
    _save_json(VM_LOGS, logs)
    return entry


def ensure_task_vm(task_id: str, template: dict[str, Any] | None, *, purpose: str = 'task', workdir: str | None = None) -> dict[str, Any] | None:
    if not template:
        return None
    vms = list_vms()
    for item in vms:
        if item.get('task_id') == task_id and item.get('template_id') == template.get('template_id'):
            if item.get('status') != 'running':
                item['status'] = 'running'
                item['updated_at'] = _utc()
                item['last_started_at'] = _utc()
                _save_vms(vms)
            append_vm_log(item['vm_id'], 'reuse', {'task_id': task_id, 'workdir': workdir})
            return item
    vm = create_vm(f'{purpose}-{task_id[:8]}', template['template_id'], purpose=purpose)
    vm['task_id'] = task_id
    vm['workdir'] = workdir
    vm['status'] = 'running'
    vm['last_started_at'] = _utc()
    vm['updated_at'] = _utc()
    vms = list_vms()
    for idx, item in enumerate(vms):
        if item.get('vm_id') == vm.get('vm_id'):
            vms[idx] = vm
            break
    _save_vms(vms)
    append_vm_log(vm['vm_id'], 'provisioned', {'task_id': task_id, 'template_id': template.get('template_id'), 'workdir': workdir})
    return vm


def start_vm(vm_id: str) -> dict[str, Any]:
    vms = list_vms()
    for item in vms:
        if item.get('vm_id') == vm_id:
            item['status'] = 'running'
            item['updated_at'] = _utc()
            item['last_started_at'] = _utc()
            _save_vms(vms)
            append_vm_log(vm_id, 'start', {'status': 'running'})
            return item
    raise RuntimeError(f'VM not found: {vm_id}')


def stop_vm(vm_id: str) -> dict[str, Any]:
    vms = list_vms()
    for item in vms:
        if item.get('vm_id') == vm_id:
            item['status'] = 'stopped'
            item['updated_at'] = _utc()
            item['last_stopped_at'] = _utc()
            _save_vms(vms)
            append_vm_log(vm_id, 'stop', {'status': 'stopped'})
            return item
    raise RuntimeError(f'VM not found: {vm_id}')


def snapshot_vm(vm_id: str, name: str | None = None) -> dict[str, Any]:
    vms = list_vms()
    for item in vms:
        if item.get('vm_id') == vm_id:
            snapshot_id = f'snap_{uuid4().hex[:8]}'
            snapshot_name = name or f'{vm_id}-{snapshot_id}'
            SNAPSHOTS.mkdir(parents=True, exist_ok=True)
            manifest = {
                'snapshot_id': snapshot_id,
                'vm_id': vm_id,
                'name': snapshot_name,
                'created_at': _utc(),
                'vm_status': item.get('status'),
                'template_id': item.get('template_id'),
            }
            _save_json(SNAPSHOTS / f'{snapshot_id}.json', manifest)
            item['snapshot_count'] = int(item.get('snapshot_count', 0) or 0) + 1
            item['last_snapshot_id'] = snapshot_id
            item['updated_at'] = _utc()
            _save_vms(vms)
            append_vm_log(vm_id, 'snapshot', {'snapshot_id': snapshot_id, 'name': snapshot_name})
            return manifest
    raise RuntimeError(f'VM not found: {vm_id}')


def finalize_task_vm(vm_id: str, *, success: bool, snapshot_prefix: str = 'task', stop: bool = True, details: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {'vm_id': vm_id, 'success': success, 'stopped': False, 'snapshot_id': None}
    append_vm_log(vm_id, 'finalize', {'success': success, **(details or {})})
    label = 'ok' if success else 'fail'
    snap = snapshot_vm(vm_id, name=f'{snapshot_prefix}-{label}')
    result['snapshot_id'] = snap.get('snapshot_id')
    if stop:
        stopped = stop_vm(vm_id)
        result['stopped'] = stopped.get('status') == 'stopped'
    return result


def get_vm_logs(vm_id: str | None = None) -> dict[str, Any]:
    logs = _load_json(VM_LOGS, {'entries': []})
    entries = logs.get('entries', [])
    if vm_id:
        entries = [item for item in entries if item.get('vm_id') == vm_id]
    return {'entries': entries[-100:]}


def vm_status() -> dict[str, Any]:
    vms = list_vms()
    running = [item for item in vms if item.get('status') == 'running']
    templates = list_templates()
    return {
        'updated_at': _utc(),
        'vm_count': len(vms),
        'running_count': len(running),
        'template_count': len(templates),
        'running_vm_ids': [item.get('vm_id') for item in running[:8]],
        'templates': [item.get('template_id') for item in templates],
        'backends': sorted({item.get('backend', 'sandbox-vm') for item in templates}),
        'mode': 'registry-backed-orchestrator-mvp',
        'log_entries': len(_load_json(VM_LOGS, {'entries': []}).get('entries', [])),
    }


if __name__ == '__main__':
    print(json.dumps(vm_status(), ensure_ascii=False, indent=2))
