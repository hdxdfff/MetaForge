from __future__ import annotations

from typing import Any, Awaitable, Callable

from .config import settings
from .models import StepSpec, TaskRecord
from tools.security_audit import append_security_audit
from tools.vm_orchestrator import append_vm_log, choose_template_for_task, ensure_task_vm, finalize_task_vm

Runner = Callable[[StepSpec, object], Awaitable[Any]]


def _prefer_local_subprocess(step: StepSpec) -> bool:
    command = step.command or ""
    return ":\\" in command or ":/" in command


def _worker_result(*, message: str, output: str, route: object, metadata: dict[str, Any] | None = None):
    from .worker_adapters import WorkerResult
    return WorkerResult(message=message, output=output, route=route, metadata=metadata or {})


class SandboxExecutor:
    def _resolve_template(self, task: TaskRecord, step: StepSpec) -> dict[str, Any] | None:
        if task.vm_template:
            return task.vm_template
        request = ' '.join(item for item in [task.goal or '', task.prompt or '', step.command or '', step.instructions or ''] if item)
        selected = choose_template_for_task(request, goal=task.goal, prompt=task.prompt)
        if selected:
            task.vm_template = selected
            task.vm_context.update({'selected_template': selected})
        return selected

    async def execute_shell(self, task: TaskRecord, step: StepSpec, route: object, *, require_sandbox: bool, subprocess_runner: Runner, open_interpreter_runner: Runner, qemu_runner: Runner):
        return await self._execute(task, step, route, require_sandbox=require_sandbox, purpose='shell', subprocess_runner=subprocess_runner, open_interpreter_runner=open_interpreter_runner, qemu_runner=qemu_runner)

    async def execute_docker(self, task: TaskRecord, step: StepSpec, route: object, *, require_sandbox: bool, subprocess_runner: Runner, docker_runner: Runner, qemu_runner: Runner):
        return await self._execute(task, step, route, require_sandbox=require_sandbox, purpose='docker', subprocess_runner=subprocess_runner, open_interpreter_runner=None, docker_runner=docker_runner, qemu_runner=qemu_runner)

    async def _execute(self, task: TaskRecord, step: StepSpec, route: object, *, require_sandbox: bool, purpose: str, subprocess_runner: Runner, open_interpreter_runner: Runner | None, qemu_runner: Runner, docker_runner: Runner | None = None):
        if purpose == 'docker' and _prefer_local_subprocess(step):
            append_security_audit(
                action='sandbox_entry',
                actor='sandbox_executor',
                result='host-execution',
                target=purpose,
                details={
                    'task_id': task.id,
                    'step_id': step.id,
                    'backend': 'local-subprocess',
                    'reason': 'docker command targets a host-local Windows path',
                },
            )
            return await subprocess_runner(step, route)
        if purpose == 'docker' and settings.real_execution_enabled:
            if settings.approval_mode == 'manual' and not task.auto_approve:
                raise RuntimeError('Real execution requires task auto-approve when ORCH_APPROVAL_MODE is manual.')
            append_security_audit(action='sandbox_entry', actor='sandbox_executor', result='host-execution', target=purpose, details={'task_id': task.id, 'step_id': step.id, 'backend': 'docker', 'image': settings.docker_image})
            if docker_runner is None:
                raise RuntimeError('Docker runner unavailable.')
            return await docker_runner(step, route)
        template = self._resolve_template(task, step) if require_sandbox else task.vm_template
        if template:
            return await self._execute_in_vm(task, step, route, template=template, purpose=purpose, subprocess_runner=subprocess_runner, open_interpreter_runner=open_interpreter_runner, qemu_runner=qemu_runner)
        if not settings.real_execution_enabled:
            output = f"{purpose.capitalize()} execution simulated.\nAssigned summarizer: {getattr(route, 'model', 'unknown')}\nPlanned command: {step.command or '(none specified)'}\nBackend: {settings.shell_backend}"
            append_security_audit(action='sandbox_entry', actor='sandbox_executor', result='simulated-host', target=purpose, details={'task_id': task.id, 'step_id': step.id, 'backend': settings.shell_backend})
            return _worker_result(message=f"{purpose.capitalize()} step simulated.", output=output, route=route)
        if settings.approval_mode == 'manual' and not task.auto_approve:
            raise RuntimeError('Real execution requires task auto-approve when ORCH_APPROVAL_MODE is manual.')
        append_security_audit(action='sandbox_entry', actor='sandbox_executor', result='host-execution', target=purpose, details={'task_id': task.id, 'step_id': step.id, 'backend': settings.shell_backend})
        if settings.shell_backend == 'open-interpreter' and open_interpreter_runner is not None:
            return await open_interpreter_runner(step, route)
        return await subprocess_runner(step, route)

    async def _execute_in_vm(self, task: TaskRecord, step: StepSpec, route: object, *, template: dict[str, Any], purpose: str, subprocess_runner: Runner, open_interpreter_runner: Runner | None, qemu_runner: Runner):
        vm = ensure_task_vm(task.id, template, purpose=purpose, workdir=step.workdir)
        if not vm:
            raise RuntimeError('Sandbox VM provisioning failed.')
        task.execution_lane = 'worker-vm'
        task.vm_context.update({'mode': 'vm-first', 'vm_id': vm.get('vm_id'), 'vm_status': vm.get('status'), 'vm_backend': vm.get('backend', 'sandbox-vm'), 'selected_template': template})
        append_vm_log(vm['vm_id'], 'sandbox-entry', {'worker': purpose, 'command': step.command or '', 'workdir': step.workdir})
        append_security_audit(action='sandbox_entry', actor='sandbox_executor', result='vm-execution', target=purpose, details={'task_id': task.id, 'step_id': step.id, 'vm_id': vm.get('vm_id'), 'template_id': template.get('template_id')})
        try:
            if not settings.real_execution_enabled:
                output = f"VM {purpose} simulated.\nVM: {vm.get('vm_id')}\nTemplate: {template.get('template_id')}\nWould run: {step.command or '(none specified)'}"
                finalize = finalize_task_vm(vm['vm_id'], success=True, snapshot_prefix=f'{purpose}-sim', details={'simulated': True})
                task.vm_context.update({'last_finalize': finalize, 'vm_status': 'stopped'})
                return _worker_result(message=f'{purpose.capitalize()} step simulated in VM lane.', output=output, route=route, metadata={'vm_execution': True, 'vm_id': vm.get('vm_id'), 'vm_finalize': finalize})
            if settings.approval_mode == 'manual' and not task.auto_approve:
                raise RuntimeError('Real execution requires task auto-approve when ORCH_APPROVAL_MODE is manual.')
            backend = vm.get('backend', 'sandbox-vm')
            if backend == 'qemu-test':
                result = await qemu_runner(step, route)
            elif settings.shell_backend == 'open-interpreter' and open_interpreter_runner is not None:
                result = await open_interpreter_runner(step, route)
            else:
                result = await subprocess_runner(step, route)
            finalize = finalize_task_vm(vm['vm_id'], success=True, snapshot_prefix=purpose, details={'worker': purpose})
            task.vm_context.update({'last_finalize': finalize, 'vm_status': 'stopped'})
            result.metadata.update({'vm_execution': True, 'vm_id': vm.get('vm_id'), 'vm_finalize': finalize})
            result.message = f'{purpose.capitalize()} step executed through sandbox lane.'
            result.output = f"Sandbox execution lane\nVM: {vm.get('vm_id')}\nTemplate: {template.get('template_id')}\nVM backend: {backend}\nExecution backend: {settings.shell_backend}\n\n{result.output}"
            return result
        except Exception as exc:
            finalize = finalize_task_vm(vm['vm_id'], success=False, snapshot_prefix=f'{purpose}-fail', details={'worker': purpose, 'error': str(exc)})
            task.vm_context.update({'last_finalize': finalize, 'vm_status': 'stopped'})
            append_security_audit(action='sandbox_entry', actor='sandbox_executor', result='vm-failed', target=purpose, severity='error', details={'task_id': task.id, 'step_id': step.id, 'vm_id': vm.get('vm_id'), 'error': str(exc)})
            raise
