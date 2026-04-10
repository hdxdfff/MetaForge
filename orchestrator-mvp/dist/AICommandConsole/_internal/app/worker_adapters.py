from __future__ import annotations

import asyncio
import json
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .budget_manager import CheapLaneGovernor
from .audit_validation import is_audit_task, validate_audit_output
from .config import settings
from .execution_guard import evaluate_execution_guard, normalize_command_prefix
from .sandbox_executor import SandboxExecutor
from .llm_service import LlmService
from .model_router import RoutedModel
from .models import StepSpec, TaskRecord, WorkerType
from tools.vm_orchestrator import append_vm_log, ensure_task_vm, finalize_task_vm
from tools.security_audit import append_security_audit

APP_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = APP_ROOT.parent
BUNDLED_PYTHON = CODEX_ROOT / "tools" / "python311-embed" / "python.exe"
BROWSER_BRIDGE = CODEX_ROOT / "tools" / "browser-automation" / "browser_bridge.py"
LEGACY_SCRIPT_MAP = {
    r"orchestrator-mvp\tools\build_toy_os.py": APP_ROOT / "tools" / "build_toy_os.py",
    r"orchestrator-mvp\tools\generic_test_runner.py": APP_ROOT / "tools" / "generic_test_runner.py",
    r"orchestrator-mvp\tools\score_toy_os.py": APP_ROOT / "tools" / "score_toy_os.py",
    r"orchestrator-mvp\tools\read_only_syntax_check.py": APP_ROOT / "tools" / "read_only_syntax_check.py",
}


@dataclass
class WorkerResult:
    message: str
    output: str
    route: RoutedModel
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkerSafetyError(RuntimeError):
    pass


class WorkerAdapters:
    def __init__(self) -> None:
        self._llm = LlmService()
        self._governor = CheapLaneGovernor()
        self._sandbox = SandboxExecutor()

    def _task_execution_mode(self, task: TaskRecord) -> str:
        execution_mode = getattr(task, "execution_mode", "")
        return str(getattr(execution_mode, "value", execution_mode) or "").strip().lower()

    def _task_type(self, task: TaskRecord) -> str:
        return str(getattr(task, "task_type", "") or "").strip().lower()

    def _is_structured_audit_task(self, task: TaskRecord) -> bool:
        return is_audit_task(self._task_type(task))

    def _format_task_context(self, task: TaskRecord, step: StepSpec) -> str:
        artifact_spec = task.artifact_spec.model_dump(mode="json") if task.artifact_spec else None
        contract = task.contract.model_dump(mode="json") if task.contract else None
        verification_contract = task.verification_contract.model_dump(mode="json") if task.verification_contract else None
        payload = {
            "task_id": task.id,
            "task_type": task.task_type,
            "queue_name": task.queue_name,
            "verification_level": task.verification_level,
            "execution_mode": self._task_execution_mode(task),
            "repo_path": task.repo_path,
            "project_id": task.project_id,
            "goal": task.goal,
            "prompt": task.prompt,
            "title": task.title,
            "required_artifacts": (artifact_spec or {}).get("required_artifacts", []),
            "deliverables": (contract or {}).get("deliverables", []),
            "acceptance_criteria": (contract or {}).get("acceptance_criteria", []),
            "verification_contract": verification_contract,
            "step": {
                "title": step.title,
                "phase": step.phase,
                "worker": step.worker.value if hasattr(step.worker, "value") else str(step.worker),
                "assigned_role": step.assigned_role.value if step.assigned_role and hasattr(step.assigned_role, "value") else None,
                "inputs": step.inputs,
                "outputs": step.outputs,
                "acceptance_criteria": step.acceptance_criteria,
                "instructions": step.instructions,
                "command": step.command,
                "workdir": step.workdir,
            },
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _audit_output_template(self, worker_name: str) -> str:
        if worker_name == "reviewer":
            return (
                "Required output template:\n"
                "# Concrete Review Decision\n"
                "## verdict\n"
                "<pass/fail/reject with one short sentence>\n"
                "## evidence_checked\n"
                "<bullet list of files or artifacts inspected>\n"
                "## validation_status\n"
                "<concise validation status>\n"
                "## regression_risks\n"
                "<bullet list of risks>\n"
                "## follow_up_patch\n"
                "<bounded follow-up patch or null>\n"
                "## next_action\n"
                "<single bounded next action>\n"
            )
        return (
            "Required output template:\n"
            "# artifact_audit Result\n"
            "## target_files\n"
            "<bullet list of exact files>\n"
            "## smallest_gap\n"
            "<single concise gap statement>\n"
            "## patch_plan\n"
            "<numbered or bulleted bounded patch plan>\n"
            "## validation_commands\n"
            "<bullet list of exact commands>\n"
            "## residual_risk\n"
            "<short residual risk statement>\n"
        )

    def _output_satisfies_schema(self, task: TaskRecord, worker_name: str, text: str) -> bool:
        if not self._is_structured_audit_task(task):
            return True
        ok, _ = validate_audit_output(text, worker_name=worker_name)
        return ok

    async def run(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        if step.worker == WorkerType.planner:
            return await self._planner(step, route)
        if step.worker == WorkerType.coder:
            return await self._coder(task, step, route)
        if step.worker == WorkerType.reviewer:
            return await self._reviewer(task, step, route)
        if step.worker == WorkerType.shell:
            return await self._shell(task, step, route)
        if step.worker == WorkerType.docker:
            return await self._docker(task, step, route)
        if step.worker == WorkerType.browser:
            return await self._browser(task, step, route)
        if step.worker == WorkerType.publisher:
            return await self._publisher(step, route)
        raise WorkerSafetyError(f"Unsupported worker: {step.worker}")

    async def _planner(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        await asyncio.sleep(0.2)
        output = f"Planner checkpoint for '{step.title}'\nAssigned model: {route.model}\nReason: {route.reason}\nInstructions: {step.instructions}"
        return WorkerResult(message="Planner step completed.", output=output, route=route)

    async def _coder(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        system_prompt = (
            "You are a coding worker. Produce concrete implementation guidance, exact file targets, and verification commands. "
            "Avoid repetition and avoid generic summaries. "
            "If this is research, governance, artifact_audit, json_fix, report_refresh, doc_patch, or manifest_patch work, the answer must be structured with: "
            "target_files, smallest_gap, patch_plan, validation_commands, residual_risk. "
            "Do not ask for more context unless the task is blocked by a missing target path or missing artifact specification."
        )
        user_prompt = (
            f"Repository: {step.workdir or 'not provided'}\n"
            f"Task context:\n{self._format_task_context(task, step)}\n\n"
            f"Return a concrete change plan for the coder step: {step.instructions}\n\n"
            f"{self._audit_output_template('coder')}"
        )
        fallback = (
            "Cheap coder provider is not configured.\n"
            f"Assigned model: {route.model}\n"
            "Fill CHEAP_LLM_API_KEY and CHEAP_LLM_BASE_URL, then rerun.\n"
            "Expected output sections:\n"
            "- target_files\n"
            "- smallest_gap\n"
            "- patch_plan\n"
            "- validation_commands\n"
            "- residual_risk\n"
            f"Task instructions: {step.instructions}"
        )
        return await self._cheap_or_escalated(
            task, step, route, system_prompt, user_prompt, fallback, "coder"
        )

    async def _reviewer(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        system_prompt = (
            "You are a code review worker. Return a concrete verdict, exact files or artifacts checked, validation status, regression risks, and next action. "
            "Avoid repetition and avoid generic summaries. "
            "If this is research, governance, artifact_audit, json_fix, report_refresh, doc_patch, or manifest_patch work, the answer must be structured with: "
            "verdict, evidence_checked, validation_status, regression_risks, follow_up_patch, next_action. "
            "Do not ask for more context unless the task is blocked by a missing target path or missing artifact specification."
        )
        user_prompt = (
            f"Repository: {step.workdir or 'not provided'}\n"
            f"Task context:\n{self._format_task_context(task, step)}\n\n"
            f"Return a concrete review decision for the reviewer step: {step.instructions}\n\n"
            f"{self._audit_output_template('reviewer')}"
        )
        fallback = (
            "Cheap review provider is not configured.\n"
            f"Assigned model: {route.model}\n"
            "Expected review output:\n"
            "- verdict\n"
            "- evidence_checked\n"
            "- validation_status\n"
            "- regression_risks\n"
            "- follow_up_patch\n"
            "- next_action"
        )
        return await self._cheap_or_escalated(
            task, step, route, system_prompt, user_prompt, fallback, "reviewer"
        )

    async def _cheap_or_escalated(
        self,
        task: TaskRecord,
        step: StepSpec,
        route: RoutedModel,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        worker_name: str,
    ) -> WorkerResult:
        planned_chars = len(system_prompt) + len(user_prompt)
        decision = self._governor.authorize(task, planned_chars)
        if not decision.allowed:
            escalation = await self._maybe_escalate(
                task, step, route, worker_name, decision.reason, fallback
            )
            if escalation:
                return escalation
            output = (
                f"Cheap lane blocked.\nReason: {decision.reason}\nAssigned model: {route.model}"
            )
            return WorkerResult(
                message=f"{worker_name.capitalize()} skipped due to cheap-lane budget guard.",
                output=output,
                route=route,
                metadata={"cheap_blocked": True, "block_reason": decision.reason},
            )

        result = await asyncio.to_thread(
            self._llm.generate, route, system_prompt, user_prompt, fallback
        )
        self._governor.record_usage(task, result.total_chars)
        loop_detected = self._governor.record_output(task, worker_name, result.text)
        if not self._output_satisfies_schema(task, worker_name, result.text):
            audit_reason = (
                "Structured output validation failed for research/governance audit work."
            )
            escalation = await self._maybe_escalate(
                task,
                step,
                route,
                worker_name,
                audit_reason,
                result.text,
            )
            if escalation:
                escalation.metadata.update(
                    {
                        "cheap_calls_used": task.cheap_lane.calls_used,
                        "cheap_chars_used": task.cheap_lane.chars_used,
                        "used_fallback": result.used_fallback,
                        "loop_detected": loop_detected,
                        "cheap_provider": result.provider,
                        "cheap_model": result.model,
                        "structured_output_rejected": True,
                    }
                )
                return escalation
            blocked_output = (
                f"Structured output rejected.\nReason: {audit_reason}\nAssigned model: {route.model}\n"
                "Expected structured audit sections were not present in the worker output."
            )
            return WorkerResult(
                message=f"{worker_name.capitalize()} output rejected by schema guard.",
                output=blocked_output,
                route=route,
                metadata={
                    "cheap_calls_used": task.cheap_lane.calls_used,
                    "cheap_chars_used": task.cheap_lane.chars_used,
                    "used_fallback": result.used_fallback,
                    "loop_detected": loop_detected,
                    "cheap_provider": result.provider,
                    "cheap_model": result.model,
                    "structured_output_rejected": True,
                },
            )
        prefix = "Fallback" if result.used_fallback else f"Cheap {worker_name} response"
        output = f"{prefix}\nAssigned model: {route.model}\nReason: {route.reason}\n\n{result.text}"
        metadata = {
            "cheap_calls_used": task.cheap_lane.calls_used,
            "cheap_chars_used": task.cheap_lane.chars_used,
            "used_fallback": result.used_fallback,
            "loop_detected": loop_detected,
            "cheap_provider": result.provider,
            "cheap_model": result.model,
        }
        if loop_detected or result.used_fallback:
            escalation = await self._maybe_escalate(
                task, step, route, worker_name, "Cheap worker fallback or loop detected.", output
            )
            if escalation:
                escalation.metadata.update(metadata)
                return escalation
        return WorkerResult(
            message=f"{worker_name.capitalize()} step completed.",
            output=output,
            route=route,
            metadata=metadata,
        )

    async def _maybe_escalate(
        self,
        task: TaskRecord,
        step: StepSpec,
        route: RoutedModel,
        worker_name: str,
        reason: str,
        cheap_output: str,
    ) -> WorkerResult | None:
        if not self._governor.can_escalate(task):
            return None
        self._governor.mark_escalation(task)
        escalation_route = RoutedModel(
            provider="openai",
            model=settings.planner_escalation_model,
            reason="Controlled escalation after cheap worker failure or loop guard.",
        )
        fallback = (
            "Core escalation could not run.\n"
            f"Escalation reason: {reason}\n"
            f"Original worker: {worker_name}\n"
            f"Cheap output: {cheap_output[:1200]}"
        )
        result = await asyncio.to_thread(
            self._llm.generate,
            escalation_route,
            "You are the supervising core model. Give a short corrective note, next action, and whether to stop, retry once, or escalate human review. Keep it concise.",
            f"Worker: {worker_name}\nReason: {reason}\nTask: {step.instructions}\nCheap output:\n{cheap_output[:1600]}",
            fallback,
        )
        output = (
            f"Cheap lane escalation triggered.\n"
            f"Original worker: {worker_name}\n"
            f"Escalation model: {escalation_route.model}\n"
            f"Reason: {reason}\n\n"
            f"Cheap worker output:\n{cheap_output}\n\n"
            f"Core supervisor note:\n{result.text}"
        )
        return WorkerResult(
            message=f"{worker_name.capitalize()} escalated to core supervisor.",
            output=output,
            route=escalation_route,
            metadata={
                "escalated": True,
                "escalation_count": task.escalation_count,
                "cheap_calls_used": task.cheap_lane.calls_used,
                "cheap_chars_used": task.cheap_lane.chars_used,
            },
        )

    async def _publisher(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        output = f"Publisher worker delegates actual remote sync to the repo API.\nAssigned model: {route.model}\nReason: {route.reason}\nInstructions: {step.instructions}"
        return WorkerResult(message="Publisher step completed.", output=output, route=route)

    async def _shell(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        command = step.command or ""
        guard = evaluate_execution_guard(
            task, step, action="shell_exec", command=command, workdir=step.workdir
        )
        if not guard.get("allowed"):
            raise WorkerSafetyError(
                str(guard.get("reason") or "Shell execution denied by execution guard.")
            )
        append_security_audit(
            action="shell_step",
            actor="worker_adapter",
            result="approved",
            target=command or "shell",
            details={"task_id": task.id, "step_id": step.id, "guard": guard},
        )
        return await self._sandbox.execute_shell(
            task,
            step,
            route,
            require_sandbox=bool(guard.get("require_sandbox")),
            subprocess_runner=self._subprocess_shell,
            open_interpreter_runner=self._open_interpreter_shell,
            qemu_runner=self._qemu_test_shell,
        )

    async def _subprocess_shell(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        step = self._normalize_shell_step(step)
        tokens = self._split_command_tokens(step.command or "")
        if not tokens:
            raise WorkerSafetyError("Shell command is empty.")
        returncode, stdout, stderr = await self._run_process(tokens, cwd=step.workdir)
        return self._finalize_process(
            "Shell step executed.", route, returncode, stdout, stderr, "Shell command failed"
        )

    def _split_command_tokens(self, command: str) -> list[str]:
        return [token.strip().strip("\"'") for token in shlex.split(command, posix=False)]

    def _normalize_shell_step(self, step: StepSpec) -> StepSpec:
        tokens = self._split_command_tokens(step.command or "")
        if not tokens:
            return step
        normalized = [self._normalize_shell_token(token, index, step.workdir) for index, token in enumerate(tokens)]
        if normalized == tokens:
            return step
        command = " ".join(shlex.quote(token) if " " in token else token for token in normalized)
        return step.model_copy(update={"command": command})

    def _normalize_shell_token(self, token: str, index: int, workdir: str | None) -> str:
        cleaned = token.strip().strip("\"'")
        lowered = cleaned.replace("/", "\\").lower()
        if index == 0 and lowered in {"python", "python3"} and BUNDLED_PYTHON.exists():
            return str(BUNDLED_PYTHON)
        for legacy, resolved in LEGACY_SCRIPT_MAP.items():
            if lowered == legacy.lower():
                return str(resolved)
        if lowered.startswith(r"generated\toy-os-demo"):
            return str(CODEX_ROOT / Path(cleaned.replace("/", "\\")))
        if lowered.startswith("orchestrator-mvp\\"):
            return str(CODEX_ROOT / Path(cleaned.replace("/", "\\")))
        if lowered == r"tools\generic_qemu_smoke.json" and workdir:
            return str(Path(workdir) / "tools" / "generic_qemu_smoke.json")
        return cleaned

    async def _run_process(self, args: list[str], *, cwd: str | None = None) -> tuple[int, bytes, bytes]:
        def _invoke() -> tuple[int, bytes, bytes]:
            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            completed = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                shell=False,
                creationflags=creationflags,
            )
            return completed.returncode, completed.stdout or b"", completed.stderr or b""

        return await asyncio.to_thread(_invoke)

    async def _qemu_test_shell(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        workdir = step.workdir or ""
        root = Path(workdir)
        smoke_script = root / "tools" / "qemu_smoke.py"
        if smoke_script.exists():
            command = f"{shlex.quote(str(BUNDLED_PYTHON))} tools/qemu_smoke.py --kernel build/kernel.bin --report build/qemu-smoke-report.json"
            qemu_step = step.model_copy(update={"command": command})
            return await self._subprocess_shell(qemu_step, route)
        return await self._subprocess_shell(step, route)

    async def _open_interpreter_shell(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        interpreter_cmd = settings.open_interpreter_cmd
        if not Path(interpreter_cmd).exists():
            raise WorkerSafetyError(f"Open Interpreter command not found: {interpreter_cmd}")
        prompt = (
            step.instructions
            if not step.command
            else f"Run this command and report concise output: {step.command}\n\nContext: {step.instructions}"
        )
        returncode, stdout, stderr = await self._run_process(
            ["cmd", "/c", interpreter_cmd, "--yes", "-c", prompt],
            cwd=step.workdir,
        )
        return self._finalize_process(
            "Shell step executed through Open Interpreter.",
            route,
            returncode,
            stdout,
            stderr,
            "Open Interpreter failed",
        )

    async def _docker_shell(self, step: StepSpec, route: RoutedModel) -> WorkerResult:
        docker_exe = settings.docker_executable
        if not shutil.which(docker_exe) and not Path(docker_exe).exists():
            raise WorkerSafetyError(f"Docker executable not found: {docker_exe}")
        workspace = Path(step.workdir or CODEX_ROOT).resolve()
        if not workspace.exists():
            raise WorkerSafetyError(f"Docker workspace does not exist: {workspace}")
        command = self._normalize_docker_command(step.command or "sh -c 'echo docker-ready'", workspace)
        returncode, stdout, stderr = await self._run_process(
            [
                docker_exe,
                "run",
                "--rm",
                "-i",
                "-v",
                f"{workspace}:{settings.docker_workdir}",
                "-w",
                settings.docker_workdir,
                "-e",
                "HOME=/tmp",
                "-e",
                "TMPDIR=/tmp",
                settings.docker_image,
                "sh",
                "-lc",
                command,
            ],
            cwd=str(workspace),
        )
        result = self._finalize_process(
            "Docker step executed in container.",
            route,
            returncode,
            stdout,
            stderr,
            "Docker run failed",
        )
        result.metadata.update(
            {
                "docker_execution": True,
                "docker_image": settings.docker_image,
                "docker_workspace": str(workspace),
                "docker_command": command,
            }
        )
        return result

    async def _docker(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        command = step.command or "sh -c 'echo docker-ready'"
        guard = evaluate_execution_guard(
            task, step, action="docker_exec", command=command, workdir=step.workdir
        )
        if not guard.get("allowed"):
            raise WorkerSafetyError(
                str(guard.get("reason") or "Docker execution denied by execution guard.")
            )
        append_security_audit(
            action="docker_step",
            actor="worker_adapter",
            result="approved",
            target=command,
            details={"task_id": task.id, "step_id": step.id, "guard": guard},
        )
        return await self._sandbox.execute_docker(
            task,
            step.model_copy(update={"command": command}),
            route,
            require_sandbox=bool(guard.get("require_sandbox")),
            subprocess_runner=self._subprocess_shell,
            docker_runner=self._docker_shell,
            qemu_runner=self._qemu_test_shell,
        )

    async def _browser(self, task: TaskRecord, step: StepSpec, route: RoutedModel) -> WorkerResult:
        url = (step.command or "").strip()
        if not url:
            raise WorkerSafetyError("Browser worker requires a URL in step.command.")
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("about:")):
            raise WorkerSafetyError("Browser worker URL must be http(s) or about:blank.")
        append_security_audit(
            action="browser_step",
            actor="worker_adapter",
            result="approved",
            target=url,
            details={"task_id": task.id, "step_id": step.id},
        )
        args = [
            str(BUNDLED_PYTHON),
            str(BROWSER_BRIDGE),
            "--url",
            url,
            "--out",
            str(CODEX_ROOT / "output" / "browser" / "page.json"),
            "--profile",
            "default",
        ]
        returncode, stdout, stderr = await self._run_process(args, cwd=step.workdir)
        payload = self._finalize_process(
            "Browser step executed through the browser bridge.",
            route,
            returncode,
            stdout,
            stderr,
            "Browser bridge failed",
        )
        payload.metadata.update(
            {
                "browser_execution": True,
                "browser_url": url,
                "browser_output": str(CODEX_ROOT / "output" / "browser" / "page.json"),
            }
        )
        return payload

    async def _vm_wrapped_shell(
        self, task: TaskRecord, step: StepSpec, route: RoutedModel
    ) -> WorkerResult:
        vm = ensure_task_vm(task.id, task.vm_template, purpose="shell", workdir=step.workdir)
        if not vm:
            raise WorkerSafetyError("VM template was expected but no VM could be provisioned.")
        task.vm_context.update(
            {
                "mode": "vm-first",
                "vm_id": vm.get("vm_id"),
                "vm_status": vm.get("status"),
                "vm_backend": vm.get("backend", "sandbox-vm"),
                "selected_template": task.vm_template,
            }
        )
        append_vm_log(
            vm["vm_id"],
            "command",
            {"worker": "shell", "command": step.command or "", "workdir": step.workdir},
        )
        try:
            if not settings.real_execution_enabled:
                output = f"VM shell simulated.\nVM: {vm.get('vm_id')}\nTemplate: {task.vm_template.get('template_id')}\nVM backend: {vm.get('backend', 'sandbox-vm')}\nExecution backend: {settings.shell_backend}\nWould run: {step.command or '(none specified)'}"
                finalize = finalize_task_vm(
                    vm["vm_id"],
                    success=True,
                    snapshot_prefix="shell-sim",
                    details={"simulated": True},
                )
                task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
                return WorkerResult(
                    message="Shell step simulated in VM lane.",
                    output=output,
                    route=route,
                    metadata={
                        "vm_execution": True,
                        "vm_id": vm.get("vm_id"),
                        "vm_finalize": finalize,
                    },
                )
            if settings.approval_mode == "manual" and not task.auto_approve:
                raise WorkerSafetyError(
                    "Real execution requires task auto-approve when ORCH_APPROVAL_MODE is manual."
                )
            vm_backend = vm.get("backend", "sandbox-vm")
            if vm_backend == "qemu-test":
                result = await self._qemu_test_shell(step, route)
            elif settings.shell_backend == "open-interpreter":
                result = await self._open_interpreter_shell(step, route)
            else:
                result = await self._subprocess_shell(step, route)
            finalize = finalize_task_vm(
                vm["vm_id"], success=True, snapshot_prefix="shell", details={"worker": "shell"}
            )
            task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
            result.metadata.update(
                {"vm_execution": True, "vm_id": vm.get("vm_id"), "vm_finalize": finalize}
            )
            result.message = "Shell step executed through VM lane."
            result.output = f"VM execution lane\nVM: {vm.get('vm_id')}\nTemplate: {task.vm_template.get('template_id')}\nVM backend: {vm.get('backend', 'sandbox-vm')}\nExecution backend: {settings.shell_backend}\n\n{result.output}"
            return result
        except Exception as exc:
            finalize = finalize_task_vm(
                vm["vm_id"],
                success=False,
                snapshot_prefix="shell-fail",
                details={"worker": "shell", "error": str(exc)},
            )
            task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
            raise

    async def _vm_wrapped_docker(
        self, task: TaskRecord, step: StepSpec, route: RoutedModel
    ) -> WorkerResult:
        vm = ensure_task_vm(task.id, task.vm_template, purpose="docker", workdir=step.workdir)
        if not vm:
            raise WorkerSafetyError("VM template was expected but no VM could be provisioned.")
        task.vm_context.update(
            {
                "mode": "vm-first",
                "vm_id": vm.get("vm_id"),
                "vm_status": vm.get("status"),
                "vm_backend": vm.get("backend", "sandbox-vm"),
                "selected_template": task.vm_template,
            }
        )
        append_vm_log(
            vm["vm_id"],
            "command",
            {
                "worker": "docker",
                "command": step.command or "docker compose up",
                "workdir": step.workdir,
            },
        )
        try:
            if not settings.real_execution_enabled:
                output = f"VM docker simulated.\nVM: {vm.get('vm_id')}\nTemplate: {task.vm_template.get('template_id')}\nVM backend: {vm.get('backend', 'sandbox-vm')}\nExecution backend: {settings.shell_backend}\nWould run: {step.command or 'docker compose up'}"
                finalize = finalize_task_vm(
                    vm["vm_id"],
                    success=True,
                    snapshot_prefix="docker-sim",
                    details={"simulated": True},
                )
                task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
                return WorkerResult(
                    message="Docker step simulated in VM lane.",
                    output=output,
                    route=route,
                    metadata={
                        "vm_execution": True,
                        "vm_id": vm.get("vm_id"),
                        "vm_finalize": finalize,
                    },
                )
            if settings.approval_mode == "manual" and not task.auto_approve:
                raise WorkerSafetyError(
                    "Real execution requires task auto-approve when ORCH_APPROVAL_MODE is manual."
                )
            command = step.command or "docker compose up"
            vm_backend = vm.get("backend", "sandbox-vm")
            if vm_backend == "qemu-test":
                result = await self._qemu_test_shell(
                    step.model_copy(update={"command": command}), route
                )
            else:
                result = await self._subprocess_shell(
                    step.model_copy(update={"command": command}), route
                )
                result.message = "Docker step executed."
            finalize = finalize_task_vm(
                vm["vm_id"], success=True, snapshot_prefix="docker", details={"worker": "docker"}
            )
            task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
            result.metadata.update(
                {"vm_execution": True, "vm_id": vm.get("vm_id"), "vm_finalize": finalize}
            )
            result.message = "Docker step executed through VM lane."
            result.output = f"VM execution lane\nVM: {vm.get('vm_id')}\nTemplate: {task.vm_template.get('template_id')}\nVM backend: {vm.get('backend', 'sandbox-vm')}\nExecution backend: {settings.shell_backend}\n\n{result.output}"
            return result
        except Exception as exc:
            finalize = finalize_task_vm(
                vm["vm_id"],
                success=False,
                snapshot_prefix="docker-fail",
                details={"worker": "docker", "error": str(exc)},
            )
            task.vm_context.update({"last_finalize": finalize, "vm_status": "stopped"})
            raise

    def _finalize_process(
        self,
        success_message: str,
        route: RoutedModel,
        returncode: int,
        stdout: bytes,
        stderr: bytes,
        failure_prefix: str,
    ) -> WorkerResult:
        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")
        if returncode != 0:
            raise WorkerSafetyError(
                f"{failure_prefix} with code {returncode}: {error_output.strip()}"
            )
        combined = output if not error_output else f"{output}\nSTDERR:\n{error_output}"
        return WorkerResult(message=success_message, output=combined.strip(), route=route)

    def _normalize_docker_command(self, command: str, workspace: Path) -> str:
        normalized = command.strip() or "sh -c 'echo docker-ready'"
        workspace_windows = str(workspace)
        workspace_posix = workspace_windows.replace("\\", "/")
        normalized = normalized.replace(workspace_windows, settings.docker_workdir)
        normalized = normalized.replace(workspace_posix, settings.docker_workdir)
        return normalized

    def _validate_shell(self, command: str, workdir: str | None) -> None:
        if not command:
            return
        lowered = command.lower()
        for pattern in settings.denied_command_patterns:
            if pattern and pattern.lower() in lowered:
                raise WorkerSafetyError(f"Command contains denied pattern: {pattern}")
        for operator in ["|", ";", "&&", "||", ">", "<"]:
            if operator in command:
                raise WorkerSafetyError(f"Command contains blocked control operator: {operator}")
        tokens = shlex.split(command, posix=False)
        if not tokens:
            return
        prefix = normalize_command_prefix(tokens[0])
        allowed = {item.lower() for item in settings.allowed_command_prefixes}
        if prefix not in allowed:
            raise WorkerSafetyError(
                f"Command prefix '{prefix}' is not in ORCH_ALLOWED_COMMAND_PREFIXES."
            )
        if workdir:
            resolved = Path(workdir).resolve()
            roots = [Path(root).resolve() for root in settings.allowed_workdirs]
            if not any(str(resolved).lower().startswith(str(root).lower()) for root in roots):
                raise WorkerSafetyError(
                    f"Working directory '{workdir}' is outside ORCH_ALLOWED_WORKDIRS."
                )

