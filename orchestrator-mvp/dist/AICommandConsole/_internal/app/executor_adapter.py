from __future__ import annotations

import json
import os
import shlex
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .executor_routing import list_executors
from .io_utils import atomic_write_json, atomic_write_text
from tools.tool_stack import launch_task

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
EXECUTOR_STATE_PATH = DATA / "executors.json"
OPENCODE_ROOT = ROOT.parent / "tools" / "opencode-home"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", ",").split(",")]
        return [part for part in parts if part]
    return [str(value).strip()] if str(value).strip() else []


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_command(value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=False)
    except Exception:
        return [text]


def _find_opencode_executable() -> Path | None:
    candidates = [
        OPENCODE_ROOT / "node_modules" / "opencode-ai" / "node_modules" / "opencode-windows-x64" / "bin" / "opencode.exe",
        OPENCODE_ROOT / "node_modules" / "opencode-ai" / "node_modules" / "opencode-windows-x64-baseline" / "bin" / "opencode.exe",
        OPENCODE_ROOT / "node_modules" / "opencode-ai" / "node_modules" / "opencode-windows-x64-baseline" / "bin" / "opencode.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for path in (OPENCODE_ROOT / "node_modules").glob("**/bin/opencode.exe"):
        return path
    return None


class ExecutorTaskEnvelope(BaseModel):
    task_id: str
    task_type: str
    goal: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    verification_level: str = "L2"
    max_runtime_seconds: int | None = None
    executor_hint: dict[str, Any] = Field(default_factory=dict)
    artifact_spec: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc)


class ExecutorStatusEnvelope(BaseModel):
    task_id: str
    executor_id: str
    phase: str = "queued"
    progress: float = 0.0
    heartbeat_at: str = Field(default_factory=_utc)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutorResultEnvelope(BaseModel):
    task_id: str
    executor_id: str
    status: str = "success"
    outputs: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    needs_verification: bool = True
    logs_path: str | None = None
    generated_at: str = Field(default_factory=_utc)


class ExecutorRunRequest(BaseModel):
    task: ExecutorTaskEnvelope
    workspace: str | None = None
    prompt_override: str | None = None


class ExecutorAdapter(ABC):
    executor_id: str

    @abstractmethod
    def submit_task(self, task: ExecutorTaskEnvelope) -> ExecutorStatusEnvelope:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, task_id: str) -> ExecutorStatusEnvelope:
        raise NotImplementedError

    @abstractmethod
    def fetch_result(self, task_id: str) -> ExecutorResultEnvelope:
        raise NotImplementedError

    @abstractmethod
    def cancel_task(self, task_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def report_status(
        self,
        task_id: str,
        *,
        phase: str,
        progress: float,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutorStatusEnvelope:
        raise NotImplementedError

    @abstractmethod
    def complete_task(
        self,
        task_id: str,
        *,
        status: str,
        outputs: dict[str, Any] | None = None,
        summary: str = "",
        logs_path: str | None = None,
        needs_verification: bool = True,
    ) -> ExecutorResultEnvelope:
        raise NotImplementedError


@dataclass
class _LocalExecutorState:
    submitted: dict[str, ExecutorTaskEnvelope] = field(default_factory=dict)
    status: dict[str, ExecutorStatusEnvelope] = field(default_factory=dict)
    result: dict[str, ExecutorResultEnvelope] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "submitted": [item.model_dump(mode="json") for item in self.submitted.values()],
            "status": [item.model_dump(mode="json") for item in self.status.values()],
            "result": [item.model_dump(mode="json") for item in self.result.values()],
        }

    def restore(self, payload: dict[str, Any]) -> None:
        self.submitted = {}
        self.status = {}
        self.result = {}
        for item in payload.get("submitted", []) or []:
            try:
                task = ExecutorTaskEnvelope.model_validate(item)
            except Exception:
                continue
            self.submitted[task.task_id] = task
        for item in payload.get("status", []) or []:
            try:
                status = ExecutorStatusEnvelope.model_validate(item)
            except Exception:
                continue
            self.status[status.task_id] = status
        for item in payload.get("result", []) or []:
            try:
                result = ExecutorResultEnvelope.model_validate(item)
            except Exception:
                continue
            self.result[result.task_id] = result


class StaticExecutorAdapter(ExecutorAdapter):
    def __init__(
        self,
        *,
        executor_id: str,
        adapter_name: str,
        task_types: list[str],
        supports_parallel: bool,
        supports_long_horizon: bool,
    ) -> None:
        self.executor_id = executor_id
        self.adapter_name = adapter_name
        self.task_types = list(task_types)
        self.supports_parallel = supports_parallel
        self.supports_long_horizon = supports_long_horizon
        self._state = _LocalExecutorState()

    def snapshot_state(self) -> dict[str, Any]:
        return self._state.snapshot()

    def restore_state(self, payload: dict[str, Any] | None) -> None:
        if isinstance(payload, dict):
            self._state.restore(payload)

    def submit_task(self, task: ExecutorTaskEnvelope) -> ExecutorStatusEnvelope:
        status = ExecutorStatusEnvelope(
            task_id=task.task_id,
            executor_id=self.executor_id,
            phase="accepted",
            progress=0.1,
            metadata={
                "adapter": self.adapter_name,
                "task_type": task.task_type,
                "verification_level": task.verification_level,
            },
        )
        self._state.submitted[task.task_id] = task
        self._state.status[task.task_id] = status
        return status

    def get_status(self, task_id: str) -> ExecutorStatusEnvelope:
        return self._state.status.get(
            task_id,
            ExecutorStatusEnvelope(
                task_id=task_id,
                executor_id=self.executor_id,
                phase="unknown",
                progress=0.0,
                metadata={"adapter": self.adapter_name},
            ),
        )

    def fetch_result(self, task_id: str) -> ExecutorResultEnvelope:
        return self._state.result.get(
            task_id,
            ExecutorResultEnvelope(
                task_id=task_id,
                executor_id=self.executor_id,
                status="pending",
                summary="No result has been produced by this adapter yet.",
                outputs={"submitted": task_id in self._state.submitted},
            ),
        )

    def report_status(
        self,
        task_id: str,
        *,
        phase: str,
        progress: float,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutorStatusEnvelope:
        if task_id not in self._state.submitted:
            self._state.submitted[task_id] = ExecutorTaskEnvelope(task_id=task_id, task_type="unknown")
        status = ExecutorStatusEnvelope(
            task_id=task_id,
            executor_id=self.executor_id,
            phase=phase,
            progress=max(0.0, min(1.0, progress)),
            metadata={
                "adapter": self.adapter_name,
                **(metadata or {}),
            },
        )
        self._state.status[task_id] = status
        return status

    def complete_task(
        self,
        task_id: str,
        *,
        status: str,
        outputs: dict[str, Any] | None = None,
        summary: str = "",
        logs_path: str | None = None,
        needs_verification: bool = True,
    ) -> ExecutorResultEnvelope:
        result = ExecutorResultEnvelope(
            task_id=task_id,
            executor_id=self.executor_id,
            status=status,
            outputs=outputs or {},
            summary=summary,
            needs_verification=needs_verification,
            logs_path=logs_path,
        )
        self._state.result[task_id] = result
        self._state.status[task_id] = ExecutorStatusEnvelope(
            task_id=task_id,
            executor_id=self.executor_id,
            phase="completed" if status == "success" else "failed",
            progress=1.0,
            metadata={"adapter": self.adapter_name},
        )
        return result

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        self._state.status[task_id] = ExecutorStatusEnvelope(
            task_id=task_id,
            executor_id=self.executor_id,
            phase="cancelled",
            progress=1.0,
            metadata={"adapter": self.adapter_name},
        )
        return {"task_id": task_id, "executor_id": self.executor_id, "cancelled": True}

    def healthcheck(self) -> dict[str, Any]:
        return {
            "executor_id": self.executor_id,
            "adapter": self.adapter_name,
            "supports_parallel": self.supports_parallel,
            "supports_long_horizon": self.supports_long_horizon,
            "submitted_tasks": len(self._state.submitted),
            "healthy": True,
        }


class OpencodeExecutorAdapter(StaticExecutorAdapter):
    def __init__(
        self,
        *,
        executor_id: str = "opencode_executor",
        adapter_name: str = "OpencodeExecutorAdapter",
    ) -> None:
        super().__init__(
            executor_id=executor_id,
            adapter_name=adapter_name,
            task_types=[
                "build_fix",
                "demo_rebuild",
                "subsystem_refactor",
                "architecture_migration",
                "path_repair",
                "unit_test_run",
            ],
            supports_parallel=True,
            supports_long_horizon=True,
        )
        self._opencode_executable = _find_opencode_executable()

    def _resolve_run_profile(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace: Path,
    ) -> dict[str, Any]:
        opencode_spec = task.inputs.get("opencode")
        if not isinstance(opencode_spec, dict):
            opencode_spec = {}
        env_overrides = {
            "OPENAI_API_KEY": _env_value("ORCH_OPENCODE_API_KEY"),
            "OPENAI_BASE_URL": _env_value("ORCH_OPENCODE_BASE_URL"),
            "OPENAI_MODEL": _env_value("ORCH_OPENCODE_MODEL"),
            "OPENAI_ORG_ID": _env_value("ORCH_OPENCODE_ORG_ID"),
        }
        env_overrides.update(
            {
                str(key): str(value)
                for key, value in (opencode_spec.get("env") or {}).items()
                if str(key).strip() and value not in (None, "")
            }
        )
        env_overrides = {key: value for key, value in env_overrides.items() if value}
        model = (
            str(opencode_spec.get("model") or "").strip()
            or _env_value("ORCH_OPENCODE_MODEL")
            or _env_value("OPENAI_MODEL")
            or None
        )
        agent = (
            str(opencode_spec.get("agent") or "").strip()
            or _env_value("ORCH_OPENCODE_AGENT")
            or None
        )
        title = (
            str(opencode_spec.get("title") or "").strip()
            or f"{task.task_type}:{task.task_id[:8]}"
        )
        attachments: list[str] = []
        for item in _normalize_list(opencode_spec.get("files")):
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            attachments.append(str(candidate))
        for item in _normalize_list(task.executor_hint.get("files")):
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = workspace / candidate
            attachments.append(str(candidate))
        return {
            "model": model,
            "agent": agent,
            "title": title,
            "attachments": list(dict.fromkeys(attachments)),
            "env": env_overrides,
        }

    def run_prompt(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace: str | Path | None = None,
        prompt_override: str | None = None,
    ) -> ExecutorResultEnvelope:
        self.submit_task(task)
        self.report_status(
            task.task_id,
            phase="starting",
            progress=0.05,
            metadata={"workspace": str(workspace or ROOT), "adapter": self.adapter_name},
        )
        workspace_path = Path(workspace or task.inputs.get("repo_path") or ROOT)
        profile = self._resolve_run_profile(task, workspace=workspace_path)
        prompt = prompt_override or self._build_prompt(task, workspace_path=workspace_path, profile=profile)
        logs_dir = DATA / "executor-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{task.task_id}.log"

        if self._opencode_executable is None:
            output = "OpenCode executor unavailable: opencode executable not found."
            atomic_write_text(log_path, output)
            return self.complete_task(
                task.task_id,
                status="failed",
                outputs={
                    "command": None,
                    "stdout": "",
                    "stderr": output,
                    "returncode": 1,
                },
                summary=output,
                logs_path=str(log_path),
                needs_verification=False,
            )

        command = [
            str(self._opencode_executable),
            "run",
            "--format",
            "json",
            "--dir",
            str(workspace_path),
            "--title",
            profile["title"],
        ]
        if profile["model"]:
            command.extend(["--model", profile["model"]])
        if profile["agent"]:
            command.extend(["--agent", profile["agent"]])
        for attachment in profile["attachments"]:
            command.extend(["--file", attachment])
        command.append(prompt)
        self.report_status(
            task.task_id,
            phase="running",
            progress=0.15,
            metadata={
                "command": command[:4] + ["..."],
                "workspace": str(workspace_path),
                "model": profile["model"],
                "agent": profile["agent"],
                "attachments_count": len(profile["attachments"]),
            },
        )
        completed = subprocess.run(
            command,
            cwd=str(OPENCODE_ROOT),
            env={**os.environ.copy(), **profile["env"]},
            capture_output=True,
            text=True,
            check=False,
            timeout=_safe_int(task.max_runtime_seconds, 1800),
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        atomic_write_text(
            log_path,
            "\n".join(
                [
                    f"command: {command}",
                    f"returncode: {completed.returncode}",
                    "",
                    "stdout:",
                    stdout,
                    "",
                    "stderr:",
                    stderr,
                ]
            ),
        )
        parsed_events = _parse_json_events(stdout)
        summary = _build_summary(stdout, stderr, parsed_events)
        error_detected = completed.returncode != 0 or _contains_error_event(parsed_events) or _looks_like_error_output(stdout, stderr)
        status = "failed" if error_detected else "success"
        result = self.complete_task(
            task.task_id,
            status=status,
            outputs={
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "parsed_events": parsed_events,
                "returncode": completed.returncode,
                "workspace": str(workspace_path),
                "error_detected": error_detected,
            },
            summary=summary,
            logs_path=str(log_path),
            needs_verification=not error_detected,
        )
        return result


class CodexExecutorAdapter(OpencodeExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(executor_id="codex_executor", adapter_name="CodexExecutorAdapter")


class SurfaceLaunchExecutorAdapter(StaticExecutorAdapter):
    def __init__(
        self,
        *,
        executor_id: str,
        adapter_name: str,
        surface_name: str,
        task_types: list[str],
        supports_parallel: bool,
        supports_long_horizon: bool,
    ) -> None:
        super().__init__(
            executor_id=executor_id,
            adapter_name=adapter_name,
            task_types=task_types,
            supports_parallel=supports_parallel,
            supports_long_horizon=supports_long_horizon,
        )
        self.surface_name = surface_name

    def run_prompt(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace: str | Path | None = None,
        prompt_override: str | None = None,
    ) -> ExecutorResultEnvelope:
        self.submit_task(task)
        workspace_path = Path(workspace or task.inputs.get("repo_path") or ROOT)
        self.report_status(
            task.task_id,
            phase="starting",
            progress=0.05,
            metadata={
                "workspace": str(workspace_path),
                "adapter": self.adapter_name,
                "surface": self.surface_name,
            },
        )
        request = (
            prompt_override
            or task.goal
            or str(task.inputs.get("prompt") or "")
            or task.task_type
        )
        logs_dir = DATA / "executor-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{task.task_id}.{self.surface_name.lower()}.json"
        result = launch_task(
            request,
            workspace=str(workspace_path),
            prefer=self.surface_name,
        )
        atomic_write_json(
            log_path,
            {
                "surface": self.surface_name,
                "task_id": task.task_id,
                "workspace": str(workspace_path),
                "request": request,
                "result": result,
            },
        )
        ok = bool(result.get("ok"))
        status = "success" if ok else "failed"
        summary = str(result.get("summary") or result.get("reason") or f"{self.surface_name} launch completed.")
        outputs = {
            "surface": self.surface_name,
            "launch": result,
            "workspace": str(workspace_path),
            "command": result.get("command"),
            "pid": result.get("pid"),
            "mode": result.get("mode"),
        }
        return self.complete_task(
            task.task_id,
            status=status,
            outputs=outputs,
            summary=summary,
            logs_path=str(log_path),
            needs_verification=not ok or bool(result.get("dispatchable", True)),
        )


class AiderExecutorAdapter(SurfaceLaunchExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="aider_executor",
            adapter_name="AiderExecutorAdapter",
            surface_name="Aider",
            task_types=[
                "build_fix",
                "subsystem_refactor",
                "path_repair",
                "unit_test_run",
                "doc_patch",
            ],
            supports_parallel=True,
            supports_long_horizon=False,
        )


class OpenHandsExecutorAdapter(SurfaceLaunchExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="openhands_executor",
            adapter_name="OpenHandsExecutorAdapter",
            surface_name="OpenHands",
            task_types=[
                "new_artifact_bootstrap",
                "new_demo_creation",
                "architecture_migration",
                "subsystem_refactor",
            ],
            supports_parallel=True,
            supports_long_horizon=True,
        )


class PlandexExecutorAdapter(SurfaceLaunchExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="plandex_executor",
            adapter_name="PlandexExecutorAdapter",
            surface_name="Plandex",
            task_types=[
                "demo_rebuild",
                "package_validation",
                "harness_regression_run",
                "qemu_smoke_run",
            ],
            supports_parallel=True,
            supports_long_horizon=True,
        )


class GooseExecutorAdapter(SurfaceLaunchExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="goose_executor",
            adapter_name="GooseExecutorAdapter",
            surface_name="Goose",
            task_types=[
                "report_refresh",
                "registry_reconcile",
                "evidence_collect",
                "doc_patch",
                "json_fix",
                "config_fix",
                "manifest_patch",
            ],
            supports_parallel=True,
            supports_long_horizon=False,
        )


class LinkWorkExecutorAdapter(StaticExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="linkwork_executor",
            adapter_name="LinkWorkExecutorAdapter",
            task_types=[
                "handoff_doc_generate",
                "artifact_evidence_packaging",
                "structured_research_bundle",
                "external_info_collect",
                "tool_assisted_doc_generation",
                "delivery_bundle_prepare",
                "report_refresh",
                "reviewer_role",
                "reporter_role",
                "operator_role",
            ],
            supports_parallel=True,
            supports_long_horizon=True,
        )
        self._linkwork_command = _split_command(_env_value("ORCH_LINKWORK_COMMAND"))
        self._linkwork_args = _split_command(_env_value("ORCH_LINKWORK_ARGS"))
        self._linkwork_timeout_seconds = _safe_int(
            _env_value("ORCH_LINKWORK_TIMEOUT_SECONDS"),
            1800,
        )

    def _build_job_spec(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace_path: Path,
        prompt_override: str | None = None,
    ) -> dict[str, Any]:
        raw_role = task.executor_hint.get("role") or task.inputs.get("role") or task.task_type
        raw_skill = task.executor_hint.get("skill") or task.inputs.get("skill") or task.task_type
        tool_policy = task.executor_hint.get("tool_policy")
        if not isinstance(tool_policy, dict):
            tool_policy = {}
        normalized_tool_policy = {
            "allow_read": True,
            "allow_write": True,
            "allow_external_tools": True,
            "allow_runtime_mutations": False,
            "allow_registry_writes": False,
            "allow_verification_mutations": False,
            "isolation": "container",
            **tool_policy,
        }
        expected_outputs: list[str] = []
        expected_outputs.extend(_normalize_list(task.expected_outputs))
        expected_output_hint = task.inputs.get("expected_outputs")
        if isinstance(expected_output_hint, dict):
            expected_outputs.extend(_normalize_list(expected_output_hint.get("required_files")))
        expected_outputs = list(dict.fromkeys(expected_outputs))
        artifact_spec = task.artifact_spec.model_dump(mode="json") if task.artifact_spec else {}
        prompt = (
            prompt_override
            or task.goal
            or str(task.inputs.get("prompt") or "")
            or task.task_type
        )
        return {
            "executor_id": self.executor_id,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "workspace": str(workspace_path),
            "role": str(raw_role or "operator").strip() or "operator",
            "skill": str(raw_skill or "bundle").strip() or "bundle",
            "goal": task.goal,
            "prompt": prompt,
            "verification_level": task.verification_level,
            "constraints": list(task.constraints),
            "expected_outputs": expected_outputs,
            "artifact_spec": artifact_spec,
            "tool_policy": normalized_tool_policy,
            "inputs": task.inputs,
            "handoff_contract": {
                "owner": "MetaForge verification/artifact",
                "executor_boundary": "LinkWork execution pool",
                "result_contract": "standardized result package",
                "verification_required": True,
                "permissions": {
                    "read_inputs": True,
                    "write_outputs": True,
                    "mutate_registry": False,
                    "mutate_verification": False,
                    "mutate_runtime": False,
                },
                "output_boundary": [
                    "generated_files",
                    "logs_path",
                    "evidence_bundle",
                    "summary",
                ],
            },
        }

    def _launch_linkwork_command(
        self,
        *,
        job_spec: dict[str, Any],
        log_path: Path,
    ) -> dict[str, Any] | None:
        if not self._linkwork_command:
            return None
        command = [*self._linkwork_command, *self._linkwork_args]
        command_log = log_path.with_suffix(".run.log")
        self.report_status(
            job_spec["task_id"],
            phase="running",
            progress=0.35,
            metadata={
                "command": command[:4] + ["..."] if len(command) > 4 else command,
                "executor_boundary": "LinkWork execution pool",
            },
        )
        completed = subprocess.run(
            command,
            cwd=str(Path(job_spec["workspace"])),
            input=json.dumps(job_spec, ensure_ascii=False, indent=2),
            capture_output=True,
            text=True,
            check=False,
            timeout=self._linkwork_timeout_seconds,
            env={
                **os.environ.copy(),
                "LINKWORK_JOB_PATH": str(log_path),
                "LINKWORK_JOB_JSON": json.dumps(job_spec, ensure_ascii=False),
                "LINKWORK_TASK_ID": job_spec["task_id"],
                "LINKWORK_WORKSPACE": str(job_spec["workspace"]),
            },
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        atomic_write_text(
            command_log,
            "\n".join(
                [
                    f"command: {command}",
                    f"returncode: {completed.returncode}",
                    "",
                    "stdout:",
                    stdout,
                    "",
                    "stderr:",
                    stderr,
                ]
            ),
        )
        parsed_result: dict[str, Any] | None = None
        for text in (stdout.strip(), stderr.strip()):
            if not text:
                continue
            try:
                candidate = json.loads(text)
            except Exception:
                continue
            if isinstance(candidate, dict):
                parsed_result = candidate
                break
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "logs_path": str(command_log),
            "parsed_result": parsed_result,
        }

    def run_prompt(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace: str | Path | None = None,
        prompt_override: str | None = None,
    ) -> ExecutorResultEnvelope:
        self.submit_task(task)
        workspace_path = Path(workspace or task.inputs.get("repo_path") or ROOT)
        self.report_status(
            task.task_id,
            phase="starting",
            progress=0.05,
            metadata={
                "workspace": str(workspace_path),
                "adapter": self.adapter_name,
                "executor_boundary": "LinkWork execution pool",
            },
        )
        job_spec = self._build_job_spec(
            task,
            workspace_path=workspace_path,
            prompt_override=prompt_override,
        )
        logs_dir = DATA / "executor-logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{task.task_id}.linkwork.job.json"
        atomic_write_json(
            log_path,
            {
                "job_spec": job_spec,
                "dispatch_status": "prepared",
                "evidence_bundle": [str(log_path)],
            },
        )
        dispatch_result = self._launch_linkwork_command(job_spec=job_spec, log_path=log_path)
        if dispatch_result is None:
            summary = (
                f"Prepared LinkWork handoff for {task.task_type} "
                f"with role={job_spec['role']} and skill={job_spec['skill']}."
            )
            return self.complete_task(
                task.task_id,
                status="success",
                outputs={
                    "dispatch_status": "prepared",
                    "job_spec": job_spec,
                    "generated_files": list(job_spec.get("expected_outputs") or []),
                    "logs_path": str(log_path),
                    "evidence_bundle": [str(log_path)],
                },
                summary=summary,
                logs_path=str(log_path),
                needs_verification=True,
            )

        parsed_result = dispatch_result.get("parsed_result") or {}
        ok = dispatch_result["returncode"] == 0 and str(
            parsed_result.get("status") or "success"
        ).strip().lower() not in {"failed", "error"}
        generated_files = (
            parsed_result.get("generated_files")
            or parsed_result.get("outputs", {}).get("generated_files")
            or job_spec.get("expected_outputs")
            or []
        )
        evidence_bundle = (
            parsed_result.get("evidence_bundle")
            or parsed_result.get("outputs", {}).get("evidence_bundle")
            or [str(log_path), dispatch_result["logs_path"]]
        )
        summary = str(
            parsed_result.get("summary")
            or parsed_result.get("message")
            or parsed_result.get("text")
            or f"LinkWork dispatch completed with return code {dispatch_result['returncode']}."
        )
        outputs = {
            "dispatch_status": "submitted" if ok else "failed",
            "job_spec": job_spec,
            "generated_files": list(dict.fromkeys(_normalize_list(generated_files))),
            "logs_path": dispatch_result["logs_path"],
            "evidence_bundle": list(dict.fromkeys(_normalize_list(evidence_bundle))),
            "external_result": parsed_result or {
                "command": dispatch_result["command"],
                "returncode": dispatch_result["returncode"],
                "stdout": dispatch_result["stdout"],
                "stderr": dispatch_result["stderr"],
            },
        }
        return self.complete_task(
            task.task_id,
            status="success" if ok else "failed",
            outputs=outputs,
            summary=summary,
            logs_path=dispatch_result["logs_path"],
            needs_verification=True,
        )


class ContinueExecutorAdapter(SurfaceLaunchExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="continue_executor",
            adapter_name="ContinueExecutorAdapter",
            surface_name="Continue",
            task_types=[
                "artifact_audit",
                "independent_evidence_check",
                "release_decision_review",
            ],
            supports_parallel=False,
            supports_long_horizon=False,
        )

    def _build_prompt(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace_path: Path,
        profile: dict[str, Any],
    ) -> str:
        constraints = "\n".join(f"- {item}" for item in task.constraints) or "- none"
        outputs = "\n".join(f"- {item}" for item in task.expected_outputs) or "- none"
        artifact_spec = json.dumps(task.artifact_spec, ensure_ascii=False, indent=2) if task.artifact_spec else "{}"
        inputs = json.dumps(task.inputs, ensure_ascii=False, indent=2)
        task_type = str(task.task_type or "").strip().lower()
        if task_type == "build_fix":
            return self._build_build_fix_prompt(
                task,
                workspace_path=workspace_path,
                profile=profile,
                constraints=constraints,
                outputs=outputs,
                artifact_spec=artifact_spec,
                inputs=inputs,
            )
        return (
            "You are the Codex executor for MetaForge OS.\n"
            "Treat the task as a bounded execution contract, not a free-form chat.\n"
            "Operate only inside the provided workspace unless the task explicitly says otherwise.\n"
            "Make the smallest useful change, keep the diff reviewable, and report evidence.\n\n"
            f"Task ID: {task.task_id}\n"
            f"Task type: {task.task_type}\n"
            f"Goal: {task.goal or ''}\n"
            f"Verification level: {task.verification_level}\n\n"
            f"Workspace: {workspace_path}\n"
            f"Model: {profile.get('model') or 'default'}\n"
            f"Agent: {profile.get('agent') or 'default'}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Expected outputs:\n{outputs}\n\n"
            f"Inputs:\n{inputs}\n\n"
            f"Artifact spec:\n{artifact_spec}\n"
            "\nOutput contract:\n"
            "- summarize the root cause or implementation result\n"
            "- list files changed or inspected\n"
            "- list the verification commands you ran\n"
            "- call out any remaining risk or follow-up\n"
        )

    def _build_build_fix_prompt(
        self,
        task: ExecutorTaskEnvelope,
        *,
        workspace_path: Path,
        profile: dict[str, Any],
        constraints: str,
        outputs: str,
        artifact_spec: str,
        inputs: str,
    ) -> str:
        failure_context = task.inputs.get("failure_context") or task.inputs.get("failing_output") or ""
        failing_command = task.inputs.get("failing_command") or ""
        repo_path = task.inputs.get("repo_path") or workspace_path
        return (
            "You are executing a build-fix task for MetaForge OS.\n"
            "Your job is to restore a failing build or test path with the smallest correct change.\n"
            "Do not change verification policy, routing policy, or unrelated runtime behavior.\n"
            "Prefer diagnosis first: inspect the error, identify the root cause, patch it, then verify.\n\n"
            f"Task ID: {task.task_id}\n"
            f"Workspace: {workspace_path}\n"
            f"Repository path: {repo_path}\n"
            f"Requested model: {profile.get('model') or 'default'}\n"
            f"Requested agent: {profile.get('agent') or 'default'}\n"
            f"Verification level: {task.verification_level}\n\n"
            f"Failure context:\n{failure_context or 'none provided'}\n\n"
            f"Failing command:\n{failing_command or 'none provided'}\n\n"
            f"Constraints:\n{constraints}\n\n"
            f"Expected outputs:\n{outputs}\n\n"
            f"Inputs:\n{inputs}\n\n"
            f"Artifact spec:\n{artifact_spec}\n\n"
            "Required output format:\n"
            "1. Root cause summary.\n"
            "2. Files changed.\n"
            "3. Verification commands run.\n"
            "4. Verification outcome.\n"
            "5. Residual risk.\n"
        )


class LocalScriptExecutorAdapter(StaticExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="script_executor",
            adapter_name="LocalScriptExecutorAdapter",
            task_types=[
                "report_refresh",
                "artifact_audit",
                "registry_reconcile",
                "evidence_collect",
                "doc_patch",
                "json_fix",
                "config_fix",
                "manifest_patch",
            ],
            supports_parallel=True,
            supports_long_horizon=False,
        )


class CheapModelExecutorAdapter(StaticExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="cheap_model_executor",
            adapter_name="CheapModelExecutorAdapter",
            task_types=[
                "doc_patch",
                "json_fix",
                "config_fix",
                "manifest_patch",
                "small_json_patch",
            ],
            supports_parallel=True,
            supports_long_horizon=False,
        )


class HumanReviewExecutorAdapter(StaticExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="human_review_executor",
            adapter_name="HumanReviewExecutorAdapter",
            task_types=["release_decision_review", "risk_approval", "architecture_review"],
            supports_parallel=False,
            supports_long_horizon=False,
        )


class CIExecutorAdapter(StaticExecutorAdapter):
    def __init__(self) -> None:
        super().__init__(
            executor_id="ci_executor",
            adapter_name="CIExecutorAdapter",
            task_types=[
                "artifact_audit",
                "qemu_smoke_run",
                "harness_regression_run",
                "package_validation",
                "independent_evidence_check",
            ],
            supports_parallel=True,
            supports_long_horizon=False,
        )


class ExecutorManager:
    def __init__(self) -> None:
        self._state_path = EXECUTOR_STATE_PATH
        self._adapters: dict[str, StaticExecutorAdapter] = {}
        self._registry: dict[str, dict[str, Any]] = {}
        self._build_registry()
        self._restore_state()

    def _build_registry(self) -> None:
        registry = {item.get("executor_id"): item for item in list_executors() if item.get("executor_id")}
        self._registry = registry
        factory_map = {
            "opencode_executor": OpencodeExecutorAdapter,
            "codex_executor": CodexExecutorAdapter,
            "aider_executor": AiderExecutorAdapter,
            "openhands_executor": OpenHandsExecutorAdapter,
            "plandex_executor": PlandexExecutorAdapter,
            "goose_executor": GooseExecutorAdapter,
            "linkwork_executor": LinkWorkExecutorAdapter,
            "continue_executor": ContinueExecutorAdapter,
            "script_executor": LocalScriptExecutorAdapter,
            "cheap_model_executor": CheapModelExecutorAdapter,
            "human_review_executor": HumanReviewExecutorAdapter,
            "ci_executor": CIExecutorAdapter,
        }
        for executor_id in registry:
            executor = registry.get(executor_id) or {}
            if not bool(executor.get("enabled", True)):
                continue
            factory = factory_map.get(executor_id)
            if factory is None:
                continue
            self._adapters[executor_id] = factory()

    def _load_state_file(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _restore_state(self) -> None:
        payload = self._load_state_file()
        executors = payload.get("executors") or {}
        if not isinstance(executors, dict):
            return
        for executor_id, adapter in self._adapters.items():
            adapter.restore_state(executors.get(executor_id) if isinstance(executors.get(executor_id), dict) else {})

    def _persist_state(self) -> None:
        payload = {
            "version": "v1",
            "updated_at": _utc(),
            "executors": {
                executor_id: adapter.snapshot_state()
                for executor_id, adapter in self._adapters.items()
            },
        }
        atomic_write_json(self._state_path, payload)

    def list_adapters(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        persisted = self._load_state_file().get("executors") or {}
        for executor in list_executors():
            executor_id = str(executor.get("executor_id") or "").strip()
            adapter = self._adapters.get(executor_id)
            enabled = bool(executor.get("enabled", True))
            health = (
                adapter.healthcheck()
                if adapter
                else {
                    "healthy": False,
                    "enabled": enabled,
                    "reason": "adapter unavailable" if enabled else "interaction-only mode",
                }
            )
            state = persisted.get(executor_id, {}) if isinstance(persisted, dict) else {}
            entries.append(
                {
                    **executor,
                    "health": health,
                    "state_file": str(self._state_path),
                    "persisted_task_count": len((state.get("submitted") or [])) if isinstance(state, dict) else 0,
                    "active_tasks": len(getattr(adapter, "_state", _LocalExecutorState()).submitted) if adapter else 0,
                }
            )
        return entries

    def get_adapter(self, executor_id: str) -> StaticExecutorAdapter | None:
        executor_id = str(executor_id or "").strip()
        if not executor_id:
            return None
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            return None
        return self._adapters.get(executor_id)

    def submit_task(self, executor_id: str, task: ExecutorTaskEnvelope) -> ExecutorStatusEnvelope:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        status = adapter.submit_task(task)
        self._persist_state()
        return status

    def report_status(
        self,
        executor_id: str,
        task_id: str,
        *,
        phase: str,
        progress: float,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutorStatusEnvelope:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        status = adapter.report_status(task_id, phase=phase, progress=progress, metadata=metadata)
        self._persist_state()
        return status

    def complete_task(
        self,
        executor_id: str,
        task_id: str,
        *,
        status: str,
        outputs: dict[str, Any] | None = None,
        summary: str = "",
        logs_path: str | None = None,
        needs_verification: bool = True,
    ) -> ExecutorResultEnvelope:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        result = adapter.complete_task(
            task_id,
            status=status,
            outputs=outputs,
            summary=summary,
            logs_path=logs_path,
            needs_verification=needs_verification,
        )
        self._persist_state()
        return result

    def cancel_task(self, executor_id: str, task_id: str) -> dict[str, Any]:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        response = adapter.cancel_task(task_id)
        self._persist_state()
        return response

    def get_status(self, executor_id: str, task_id: str) -> ExecutorStatusEnvelope:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        return adapter.get_status(task_id)

    def fetch_result(self, executor_id: str, task_id: str) -> ExecutorResultEnvelope:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        return adapter.fetch_result(task_id)

    def run_task(self, executor_id: str, request: ExecutorRunRequest) -> dict[str, Any]:
        executor_id = str(executor_id or "").strip()
        if not bool((self._registry.get(executor_id) or {}).get("enabled", True)):
            raise NotImplementedError(f"Executor '{executor_id}' is interaction-only and cannot run tasks.")
        adapter = self.get_adapter(executor_id)
        if adapter is None:
            raise KeyError(f"Unknown executor: {executor_id}")
        if not hasattr(adapter, "run_prompt"):
            raise NotImplementedError(f"Executor '{executor_id}' does not support direct runs.")
        result = adapter.run_prompt(
            request.task,
            workspace=request.workspace,
            prompt_override=request.prompt_override,
        )
        self._persist_state()
        return {
            "executor_id": executor_id,
            "task_id": request.task.task_id,
            "status": result.model_dump(mode="json"),
        }


def _parse_json_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        text = line.strip()
        if not text.startswith("{") or not text.endswith("}"):
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _contains_error_event(events: list[dict[str, Any]]) -> bool:
    for event in events:
        event_type = str(event.get("type") or "").strip().lower()
        if event_type in {"error", "fatal"}:
            return True
        if "error" in event:
            return True
    return False


def _looks_like_error_output(stdout: str, stderr: str) -> bool:
    text = "\n".join(part for part in [stdout, stderr] if part).lower()
    if not text.strip():
        return False
    return any(
        marker in text
        for marker in (
            "authentication fails",
            "invalid api key",
            "authentication_error",
            '"type":"error"',
            '"type": "error"',
        )
    )


def _build_summary(stdout: str, stderr: str, events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        for key in ("summary", "message", "text", "output"):
            value = str(event.get(key) or "").strip()
            if value:
                return value[:1200]
    tail = "\n".join(
        part
        for part in [stdout.strip(), stderr.strip()]
        if part
    )
    if not tail:
        return "Executor run completed with no textual output."
    lines = [line.strip() for line in tail.splitlines() if line.strip()]
    return "\n".join(lines[-20:])[:1200]
