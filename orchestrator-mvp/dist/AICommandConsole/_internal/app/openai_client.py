from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from .config import settings, strategic_llm_api_style
from .model_usage import load_usage_snapshot
from .models import (
    AgentRole,
    ContextEnvelope,
    ExecutionMode,
    PlannerResponse,
    StepSpec,
    TaskDecompositionResponse,
    TaskDecompositionSpec,
    WorkerType,
)
from .provider_gateway import provider_gateway

READ_ONLY_SYNTAX_CHECK = str(
    Path(__file__).resolve().parent.parent / "tools" / "read_only_syntax_check.py"
)
ORCHESTRATOR_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = ORCHESTRATOR_ROOT.parent
BUNDLED_PYTHON = WORKSPACE_ROOT / "tools" / "python311-embed" / "python.exe"


class OpenAIPlanner:
    def __init__(self) -> None:
        self._configured = bool(settings.openai_api_key and settings.openai_base_url)
        self._reasoning_configured = bool(
            settings.reasoning_llm_api_key and settings.reasoning_llm_base_url
        )
        self._cheap_configured = bool(settings.cheap_llm_api_key and settings.cheap_llm_base_url)

    def available(self) -> bool:
        return self._configured or self._reasoning_configured or self._cheap_configured

    def _planner_fast_timeout_seconds(self, configured_timeout: float) -> float:
        # Planning can always fall back locally, so long network waits only reduce throughput.
        return max(5.0, min(float(configured_timeout), 12.0))

    def build_plan(
        self, prompt: str, repo_path: str | None, context: ContextEnvelope | None = None
    ) -> PlannerResponse:
        if self._is_toyos_evidence_refresh_prompt(prompt, repo_path):
            return self._toyos_evidence_refresh_plan(prompt=prompt, repo_path=repo_path)
        if self._requires_build_first_prompt(prompt, repo_path):
            return self._fallback_plan(prompt=prompt, repo_path=repo_path)
        planners = self._planner_candidates(prompt=prompt, context=context)
        for planner in planners:
            try:
                return planner(prompt=prompt, repo_path=repo_path, context=context)
            except Exception:
                continue
        return self._fallback_plan(prompt=prompt, repo_path=repo_path)

    def build_decomposition(
        self,
        prompt: str,
        repo_path: str | None,
        context: ContextEnvelope | None = None,
        *,
        max_children: int = 4,
        depth: int = 0,
        max_depth: int = 2,
    ) -> TaskDecompositionResponse:
        if self._is_toyos_evidence_refresh_prompt(prompt, repo_path):
            return self._toyos_evidence_refresh_decomposition(prompt=prompt, repo_path=repo_path)
        if self._requires_build_first_prompt(prompt, repo_path):
            return self._fallback_decomposition(prompt=prompt, repo_path=repo_path, max_children=max_children)
        usage = load_usage_snapshot()
        cheap_first = self._should_prefer_cheap_plan(prompt=prompt, context=context)
        reasoning_allowed = bool(usage.get("reasoning_allowed", True))
        strong_allowed = bool(usage.get("strong_allowed", True))
        strategic = self._looks_strategic_prompt(prompt)
        if cheap_first or usage.get("demand_pressure") == "strong-throttled":
            if self._cheap_configured:
                try:
                    return self._cheap_decomposition(
                        prompt=prompt,
                        repo_path=repo_path,
                        context=context,
                        max_children=max_children,
                        depth=depth,
                        max_depth=max_depth,
                    )
                except Exception:
                    pass
            if self._reasoning_configured and reasoning_allowed:
                try:
                    return self._reasoning_decomposition(
                        prompt=prompt,
                        repo_path=repo_path,
                        context=context,
                        max_children=max_children,
                        depth=depth,
                        max_depth=max_depth,
                    )
                except Exception:
                    pass
            if self._configured and strong_allowed:
                try:
                    return self._remote_decomposition(
                        prompt=prompt,
                        repo_path=repo_path,
                        context=context,
                        max_children=max_children,
                        depth=depth,
                        max_depth=max_depth,
                    )
                except Exception:
                    pass
            return self._fallback_decomposition(prompt=prompt, repo_path=repo_path, max_children=max_children)

        if strategic and self._configured and strong_allowed:
            try:
                return self._remote_decomposition(
                    prompt=prompt,
                    repo_path=repo_path,
                    context=context,
                    max_children=max_children,
                    depth=depth,
                    max_depth=max_depth,
                )
            except Exception:
                pass
        if reasoning_allowed and self._reasoning_configured:
            try:
                return self._reasoning_decomposition(
                    prompt=prompt,
                    repo_path=repo_path,
                    context=context,
                    max_children=max_children,
                    depth=depth,
                    max_depth=max_depth,
                )
            except Exception:
                pass
        if self._cheap_configured:
            try:
                return self._cheap_decomposition(
                    prompt=prompt,
                    repo_path=repo_path,
                    context=context,
                    max_children=max_children,
                    depth=depth,
                    max_depth=max_depth,
                )
            except Exception:
                pass
        if self._configured and strong_allowed:
            try:
                return self._remote_decomposition(
                    prompt=prompt,
                    repo_path=repo_path,
                    context=context,
                    max_children=max_children,
                    depth=depth,
                    max_depth=max_depth,
                )
            except Exception:
                pass
        return self._fallback_decomposition(prompt=prompt, repo_path=repo_path, max_children=max_children)

    def _planner_candidates(
        self, prompt: str, context: ContextEnvelope | None
    ) -> list[Callable[..., PlannerResponse]]:
        usage = load_usage_snapshot()
        cheap_first = self._should_prefer_cheap_plan(prompt=prompt, context=context)
        reasoning_allowed = bool(usage.get("reasoning_allowed", True))
        strong_allowed = bool(usage.get("strong_allowed", True))
        strategic = self._looks_strategic_prompt(prompt)
        coding_plan_remote_allowed = bool(strategic and self._configured and self._is_coding_plan_provider())
        strong_remote_allowed = strong_allowed or coding_plan_remote_allowed

        planners: list[Callable[..., PlannerResponse]] = []
        if cheap_first or usage.get("demand_pressure") == "strong-throttled":
            if self._cheap_configured:
                planners.append(self._cheap_plan)
            if self._reasoning_configured and reasoning_allowed:
                planners.append(self._reasoning_plan)
            if self._configured and strong_remote_allowed:
                planners.append(self._remote_plan)
            return planners

        if strategic and self._configured and strong_remote_allowed:
            planners.append(self._remote_plan)
        if reasoning_allowed and self._reasoning_configured:
            planners.append(self._reasoning_plan)
        if self._cheap_configured:
            planners.append(self._cheap_plan)
        if self._configured and strong_remote_allowed and self._remote_plan not in planners:
            planners.append(self._remote_plan)
        return planners or [self._fallback_plan]

    def _planner_shape(self) -> str:
        return (
            '{"summary": string, "steps": [{"title": string, "worker": "planner|coder|shell|docker|reviewer|publisher", '
            '"instructions": string, "phase": string|null, "command": string|null, "workdir": string|null, '
            '"assigned_role": "supervisor|product|architect|coder|tester|reviewer|ops"|null, '
            '"inputs": string[], "outputs": string[], "dependencies": string[], "acceptance_criteria": string[]}]}'
        )

    def _decomposition_shape(self) -> str:
        return (
            '{"summary": string, "strategy": string, "subtasks": [{"title": string, "prompt": string, '
            '"goal": string|null, "task_type": string|null, "queue_name": string|null, '
            '"verification_level": string|null, "preferred_worker": string|null, '
            '"execution_mode": "governance|research|production"|null, "execution_lane": string|null, '
            '"path_kind": "shared|branch|repair"|null, "shared_dependency_group": string|null, '
            '"repair_for": string|null, "decompose_children": boolean, "inputs": string[], "outputs": string[], '
            '"dependencies": string[], "acceptance_criteria": string[], "scheduler_hint": object, '
            '"executor_hint": object}], "dag": object}'
        )

    def _format_context_text(self, context: ContextEnvelope | None) -> str:
        if not context:
            return "No extra context."
        header = (
            f"Mode={context.mode.value}; "
            f"Budget={context.used_chars}/{context.budget_chars}; "
            f"Includes={', '.join(context.includes[:4]) or 'none'}"
        )
        blocks = [self._trim_block(block, 320) for block in context.summary_blocks[:2] if block]
        return "\n\n".join([header, *blocks]) if blocks else header

    def _trim_block(self, text: str, limit: int) -> str:
        compact = "\n".join(line.rstrip() for line in text.strip().splitlines() if line.strip())
        if len(compact) <= limit:
            return compact
        return compact[: max(0, limit - 3)].rstrip() + "..."

    def _is_binary_classification_lab_prompt(self, prompt: str, repo_path: str | None) -> bool:
        corpus = " ".join(part for part in [prompt, repo_path or ""] if part).lower()
        markers = (
            "binary classification",
            "classification lab",
            "logistic regression",
            "svm",
            "perceptron",
            "sgd",
            "accuracy",
        )
        hits = sum(1 for marker in markers if marker in corpus)
        return "ml-binary-classification-lab" in corpus or hits >= 3

    def _looks_strategic_prompt(self, prompt: str) -> bool:
        lowered = prompt.lower()
        markers = (
            "architecture",
            "design",
            "migration",
            "policy",
            "security",
            "cross-project",
            "scheduler",
            "strategy",
            "roadmap",
            "rfc",
        )
        return any(marker in lowered for marker in markers)

    def _requires_build_first_prompt(self, prompt: str, repo_path: str | None) -> bool:
        corpus = " ".join(part for part in [prompt, repo_path or ""] if part).lower()
        return any(
            token in corpus
            for token in (
                "build current runnable baseline",
                "build runnable artifact",
                "system_build",
                "release artifact bundle",
                "toyos",
                "toy os",
                "qemu",
                "kernel",
            )
        )

    def _is_toyos_evidence_refresh_prompt(self, prompt: str, repo_path: str | None) -> bool:
        corpus = " ".join(part for part in [prompt, repo_path or ""] if part).lower()
        if "toyos" not in corpus and "toy os" not in corpus and "generated\\toy-os-demo" not in corpus:
            return False
        artifact_hits = sum(
            1
            for marker in (
                "build-report.json",
                "build-report",
                "generic-qemu-smoke-report.json",
                "generic-qemu-smoke-report",
                "score-report.json",
                "score-report",
            )
            if marker in corpus
        )
        return artifact_hits >= 2 and any(
            token in corpus
            for token in (
                "evidence chain",
                "refresh",
                "confirm",
                "verification summary",
                "summary",
                "current",
                "verify",
                "verification",
            )
        )

    def _toyos_evidence_refresh_plan(self, prompt: str, repo_path: str | None) -> PlannerResponse:
        workdir = repo_path or str(WORKSPACE_ROOT / "generated" / "toy-os-demo")
        artifact_root = Path(workdir)
        build_report = artifact_root / "build-report.json"
        qemu_report = artifact_root / "build" / "generic-qemu-smoke-report.json"
        score_report = artifact_root / "score-report.json"
        summary_path = artifact_root / "toyos-evidence-summary.md"
        python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else "python")
        audit_script = ORCHESTRATOR_ROOT / "tools" / "artifact_audit.py"
        return PlannerResponse(
            summary="Local fallback plan for a ToyOS evidence refresh: inspect the current artifacts, confirm freshness, and emit a concise verification summary without rebuilding.",
            steps=[
                StepSpec(
                    title="Review ToyOS evidence scope",
                    worker=WorkerType.planner,
                    phase="understand",
                    instructions=(
                        "Restate the evidence refresh request and identify the exact ToyOS artifacts "
                        "that must be treated as read-only for this task."
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.product,
                    outputs=["evidence scope"],
                    acceptance_criteria=["ToyOS evidence scope is explicit"],
                ),
                StepSpec(
                    title="Inspect current ToyOS artifacts",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions=(
                        "Inspect the existing ToyOS build, QEMU smoke, and score artifacts on disk "
                        "and capture whether they are present and current."
                    ),
                    command=f'"{python_cmd}" "{audit_script}"',
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    inputs=["evidence scope"],
                    outputs=[
                        "build-report.json",
                        "build/generic-qemu-smoke-report.json",
                        "score-report.json",
                    ],
                    acceptance_criteria=[
                        "ToyOS evidence artifacts are inspected without rebuilding.",
                        "Artifact freshness is captured from existing files.",
                    ],
                ),
                StepSpec(
                    title="Emit ToyOS verification summary",
                    worker=WorkerType.reviewer,
                    phase="review",
                    instructions=(
                        "Summarize the current ToyOS evidence chain, note the freshness of the existing "
                        "artifacts, and point to the exact verification result for the restored delivery goal."
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.reviewer,
                    inputs=[
                        build_report.name,
                        "build/generic-qemu-smoke-report.json",
                        score_report.name,
                    ],
                    outputs=[str(summary_path.relative_to(artifact_root))],
                    acceptance_criteria=[
                        "Verification summary is concise.",
                        "No rebuild loop is introduced.",
                    ],
                ),
            ],
        )

    def _generic_bootstrap_plan(self, prompt: str, repo_path: str | None) -> PlannerResponse:
        workdir = repo_path or str(ORCHESTRATOR_ROOT)
        python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else "python")
        build_runner = ORCHESTRATOR_ROOT / "tools" / "bootstrap_build_runner.py"
        validation_runner = ORCHESTRATOR_ROOT / "tools" / "bootstrap_validation_runner.py"
        report_root = Path(workdir) / "reports"
        build_report = report_root / "bootstrap-build-report.json"
        build_log = report_root / "bootstrap-build.log"
        build_manifest = report_root / "bootstrap-build-manifest.json"
        validation_report = report_root / "bootstrap-validation.json"
        validation_log = report_root / "bootstrap-validation.log"
        return PlannerResponse(
            summary="Local fallback plan for a short bootstrap loop: refresh build evidence, run a bounded validation sweep, then emit a patch decision.",
            steps=[
                StepSpec(
                    title="Refresh bootstrap build evidence",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Run the cheapest local build-equivalent check first and write machine-readable bootstrap evidence.",
                    command=(
                        f'"{python_cmd}" "{build_runner}" --repo "{workdir}" --report "{build_report}" '
                        f'--log "{build_log}" --manifest "{build_manifest}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    outputs=[
                        "reports/bootstrap-build-report.json",
                        "reports/bootstrap-build.log",
                        "reports/bootstrap-build-manifest.json",
                    ],
                    acceptance_criteria=[
                        "Bootstrap build report exists.",
                        "Bootstrap build log exists.",
                        "Bootstrap build manifest exists.",
                    ],
                ),
                StepSpec(
                    title="Run bootstrap validation sweep",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Run the bounded validation sweep after bootstrap build evidence is refreshed.",
                    command=(
                        f'"{python_cmd}" "{validation_runner}" --repo "{workdir}" --report "{validation_report}" '
                        f'--log "{validation_log}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    inputs=["reports/bootstrap-build-report.json"],
                    outputs=[
                        "reports/bootstrap-validation.json",
                        "reports/bootstrap-validation.log",
                    ],
                    acceptance_criteria=[
                        "Bootstrap validation report exists.",
                        "Bootstrap validation log exists.",
                    ],
                ),
                StepSpec(
                    title="Audit bootstrap evidence",
                    worker=WorkerType.reviewer,
                    phase="review",
                    instructions="Review the refreshed bootstrap build and validation evidence and emit a concrete patch decision.",
                    workdir=workdir,
                    assigned_role=AgentRole.reviewer,
                    inputs=[
                        "reports/bootstrap-build-report.json",
                        "reports/bootstrap-validation.json",
                    ],
                    outputs=["patch decision"],
                    acceptance_criteria=["Patch decision is grounded in bootstrap artifacts."],
                ),
            ],
        )

    def _toyos_evidence_refresh_decomposition(
        self, prompt: str, repo_path: str | None
    ) -> TaskDecompositionResponse:
        workdir = repo_path or str(WORKSPACE_ROOT / "generated" / "toy-os-demo")
        return TaskDecompositionResponse(
            summary="ToyOS evidence refresh is best handled as a bounded coordination task with one inspection branch and one summary branch.",
            strategy="Split the refresh into direct artifact inspection and evidence synthesis; avoid rebuilding in this layer.",
            subtasks=[
                TaskDecompositionSpec(
                    title="Inspect existing ToyOS evidence",
                    prompt=(
                        f"Inspect the current ToyOS evidence chain in {workdir}, confirm freshness of the build, QEMU, and score artifacts, and capture the exact evidence state."
                    ),
                    goal="Confirm ToyOS evidence freshness",
                    task_type="artifact_audit",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.research,
                    execution_lane="host-control",
                    decompose_children=False,
                    outputs=["current evidence snapshot"],
                    acceptance_criteria=["Evidence freshness is recorded without rebuild."],
                    scheduler_hint={"evidence_refresh": True, "inspection_focus": "toyos"},
                ),
                TaskDecompositionSpec(
                    title="Synthesize ToyOS evidence summary",
                    prompt=(
                        f"Summarize the inspected ToyOS evidence chain for {workdir}, state whether the current artifacts are fresh, and identify the next bounded verification action."
                    ),
                    goal="Produce a concise ToyOS verification summary",
                    task_type="report_refresh",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    inputs=["current evidence snapshot"],
                    outputs=["toyos evidence summary"],
                    acceptance_criteria=["Summary is concise and grounded in current artifacts."],
                    scheduler_hint={"evidence_refresh": True, "synthesis_focus": "toyos"},
                ),
            ],
        )

    def _fallback_decomposition(
        self,
        prompt: str,
        repo_path: str | None,
        *,
        max_children: int = 4,
    ) -> TaskDecompositionResponse:
        lowered = prompt.lower()
        if any(token in lowered for token in ["research", "investigate", "analysis", "compare", "design", "roadmap", "rfc"]):
            subtasks = [
                TaskDecompositionSpec(
                    title="Frame the problem",
                    prompt=f"Restate the goal, constraints, and success criteria for: {prompt}",
                    goal="Frame the decomposition problem",
                    task_type="report_refresh",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    outputs=["problem framing note"],
                    acceptance_criteria=["The problem framing is explicit and bounded."],
                ),
                TaskDecompositionSpec(
                    title="Collect supporting evidence",
                    prompt=f"Gather the concrete facts, references, or repository signals needed to solve: {prompt}",
                    goal="Collect support evidence",
                    task_type="artifact_audit",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="shell",
                    execution_mode=ExecutionMode.research,
                    execution_lane="host-control",
                    decompose_children=True,
                    outputs=["supporting evidence"],
                    acceptance_criteria=["Evidence is concrete and usable by a follow-up task."],
                ),
                TaskDecompositionSpec(
                    title="Synthesize next action",
                    prompt=f"Use the evidence to identify the next bounded implementation or verification step for: {prompt}",
                    goal="Decide the next action",
                    task_type="report_refresh",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    inputs=["problem framing note", "supporting evidence"],
                    outputs=["next action brief"],
                    acceptance_criteria=["The next action is explicit and actionable."],
                ),
            ]
        elif any(token in lowered for token in ["build", "compile", "test", "fix", "patch", "refactor", "implement", "bug", "error"]):
            subtasks = [
                TaskDecompositionSpec(
                    title="Analyze the current state",
                    prompt=f"Inspect the current repository state and isolate the smallest workable slice for: {prompt}",
                    goal="Identify the smallest viable slice",
                    task_type="report_refresh",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    outputs=["analysis note"],
                    acceptance_criteria=["The smallest feasible slice is identified."],
                ),
                TaskDecompositionSpec(
                    title="Implement the bounded change",
                    prompt=f"Make the smallest safe implementation or repair needed for: {prompt}",
                    goal="Implement the bounded change",
                    task_type="build_fix",
                    queue_name="build_test",
                    verification_level="L2",
                    preferred_worker="coder",
                    execution_mode=ExecutionMode.production,
                    execution_lane="vm-first",
                    decompose_children=True,
                    inputs=["analysis note"],
                    outputs=["bounded patch"],
                    acceptance_criteria=["A bounded implementation exists."],
                ),
                TaskDecompositionSpec(
                    title="Validate the result",
                    prompt=f"Run the narrowest useful validation for the bounded change: {prompt}",
                    goal="Validate the change",
                    task_type="unit_test_run",
                    queue_name="build_test",
                    verification_level="L2",
                    preferred_worker="docker",
                    execution_mode=ExecutionMode.production,
                    execution_lane="vm-first",
                    decompose_children=False,
                    inputs=["bounded patch"],
                    outputs=["validation evidence"],
                    acceptance_criteria=["Validation evidence is recorded."],
                ),
            ]
        else:
            subtasks = [
                TaskDecompositionSpec(
                    title="Clarify the target",
                    prompt=f"Restate the objective and the smallest acceptable outcome for: {prompt}",
                    goal="Clarify target outcome",
                    task_type="report_refresh",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="reviewer",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    outputs=["target brief"],
                    acceptance_criteria=["Target outcome is explicit."],
                ),
                TaskDecompositionSpec(
                    title="Execute the next bounded action",
                    prompt=f"Carry out the smallest bounded action that advances: {prompt}",
                    goal="Execute the next action",
                    task_type="doc_patch",
                    queue_name="fastlane",
                    verification_level="L1",
                    preferred_worker="coder",
                    execution_mode=ExecutionMode.governance,
                    execution_lane="host-control",
                    decompose_children=False,
                    inputs=["target brief"],
                    outputs=["action result"],
                    acceptance_criteria=["The action produces a concrete result."],
                ),
            ]

        return TaskDecompositionResponse(
            summary=f"Fallback decomposition for: {prompt[:120]}",
            strategy="bounded multi-layer split with analysis, execution, and verification branches",
            subtasks=subtasks[: max(1, max_children)],
        )

    def _decomposition_response_from_payload(
        self,
        payload: dict[str, object],
        repo_path: str | None,
        *,
        max_children: int = 4,
    ) -> TaskDecompositionResponse:
        subtasks = payload.get("subtasks", []) if isinstance(payload, dict) else []
        summary = payload.get("summary", "") if isinstance(payload, dict) else ""
        strategy = payload.get("strategy", "") if isinstance(payload, dict) else ""
        return TaskDecompositionResponse(
            summary=str(summary or ""),
            strategy=str(strategy or ""),
            subtasks=[
                TaskDecompositionSpec(
                    title=str(item.get("title") or "Untitled subtask"),
                    prompt=str(item.get("prompt") or ""),
                    goal=item.get("goal"),
                    task_type=item.get("task_type"),
                    queue_name=item.get("queue_name"),
                    verification_level=item.get("verification_level"),
                    preferred_worker=item.get("preferred_worker"),
                    execution_mode=(
                        ExecutionMode(str(item.get("execution_mode")))
                        if item.get("execution_mode")
                        and str(item.get("execution_mode")).strip() in {member.value for member in ExecutionMode}
                        else None
                    ),
                    execution_lane=item.get("execution_lane"),
                    decompose_children=bool(item.get("decompose_children", True)),
                    inputs=list(item.get("inputs", [])),
                    outputs=list(item.get("outputs", [])),
                    dependencies=list(item.get("dependencies", [])),
                    acceptance_criteria=list(item.get("acceptance_criteria", [])),
                    scheduler_hint=dict(item.get("scheduler_hint") or {}),
                    executor_hint=dict(item.get("executor_hint") or {}),
                )
                for item in subtasks[: max(1, max_children)]
                if isinstance(item, dict)
            ],
        )

    def _should_prefer_cheap_plan(self, prompt: str, context: ContextEnvelope | None) -> bool:
        if not self._cheap_configured:
            return False
        if not self._reasoning_configured and not self._configured:
            return True
        if self._should_use_cheap_planner():
            return True
        usage = load_usage_snapshot()
        if usage.get("demand_pressure") == "strong-throttled":
            if self._looks_strategic_prompt(prompt) and self._is_coding_plan_provider():
                return False
            return True
        prompt_chars = len(prompt or "")
        context_chars = int((context.used_chars if context else 0) or 0)
        return (
            not self._looks_strategic_prompt(prompt)
            and prompt_chars <= 280
            and context_chars <= 1800
        )

    def _remote_plan(
        self, prompt: str, repo_path: str | None, context: ContextEnvelope | None
    ) -> PlannerResponse:
        if not self._configured:
            raise RuntimeError("Remote planner is not configured.")
        context_text = self._format_context_text(context)

        system_text = (
            "You are the planner for a local coding orchestrator. "
            "Return strict JSON only. Keep the summary short and produce 3-5 concrete steps. "
            "Prefer cheap, local execution for routine work and reserve expensive reasoning for decomposition, blockers, or high-risk changes. For build or system-build work, the first concrete step must be build/run, not architecture. Reviewer steps may only appear after artifact evidence exists and must emit a patch or release decision."
        )
        user_text = (
            f"Task: {prompt}\n"
            f"Repository: {repo_path or 'not provided'}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Return strict JSON with this shape: {self._planner_shape()}"
        )

        if self._use_chat_planner_api():
            response = provider_gateway.chat_completions_create(
                provider_name="openai-planner",
                api_key=settings.openai_api_key,
                default_base_url=settings.openai_base_url,
                base_url_candidates=list(settings.openai_base_url_candidates),
                default_proxy=settings.network_proxy_url,
                proxy_candidates=list(settings.openai_proxy_candidates),
                timeout_seconds=self._planner_fast_timeout_seconds(
                    settings.planner_request_timeout_seconds
                ),
                request_kwargs={
                    "model": settings.planner_model,
                    "messages": [
                        {"role": "system", "content": system_text},
                        {"role": "user", "content": user_text},
                    ],
                    "stream": False,
                },
            )
            message = response.choices[0].message if response.choices else None
            text = ""
            if message is not None:
                if isinstance(message.content, str):
                    text = message.content
                elif isinstance(message.content, list):
                    text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
            payload = json.loads(text)
            return self._planner_response_from_payload(payload, repo_path)

        schema = {
            "name": "orchestrator_plan",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "worker": {
                                    "type": "string",
                                    "enum": [member.value for member in WorkerType],
                                },
                                "instructions": {"type": "string"},
                                "phase": {"type": ["string", "null"]},
                                "command": {"type": ["string", "null"]},
                                "workdir": {"type": ["string", "null"]},
                                "assigned_role": {
                                    "type": ["string", "null"],
                                    "enum": [member.value for member in AgentRole] + [None],
                                },
                                "inputs": {"type": "array", "items": {"type": "string"}},
                                "outputs": {"type": "array", "items": {"type": "string"}},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                                "acceptance_criteria": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "title",
                                "worker",
                                "instructions",
                                "phase",
                                "command",
                                "workdir",
                                "assigned_role",
                                "inputs",
                                "outputs",
                                "dependencies",
                                "acceptance_criteria",
                            ],
                        },
                    },
                },
                "required": ["summary", "steps"],
            },
        }

        response = provider_gateway.responses_create(
            provider_name="openai-planner",
            api_key=settings.openai_api_key,
            default_base_url=settings.openai_base_url,
            base_url_candidates=list(settings.openai_base_url_candidates),
            default_proxy=settings.network_proxy_url,
            proxy_candidates=list(settings.openai_proxy_candidates),
            timeout_seconds=settings.planner_request_timeout_seconds,
            request_kwargs={
                "model": settings.planner_model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_text}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_text}],
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema["name"],
                        "schema": schema["schema"],
                        "strict": True,
                    }
                },
            },
        )
        payload = json.loads(response.output_text)
        return self._planner_response_from_payload(payload, repo_path)

    def _should_use_cheap_planner(self) -> bool:
        if not self._cheap_configured:
            return False
        api_key = (settings.openai_api_key or "").strip().lower()
        base_url = (settings.openai_base_url or "").strip().lower()
        return (
            (not self._configured)
            or api_key == "local-gateway"
            or "localhost:11434" in base_url
            or "127.0.0.1:11434" in base_url
        )

    def _is_coding_plan_provider(self) -> bool:
        return "/api/coding" in (settings.openai_base_url or "").strip().lower()

    def _reasoning_plan(
        self, prompt: str, repo_path: str | None, context: ContextEnvelope | None
    ) -> PlannerResponse:
        if not self._reasoning_configured:
            raise RuntimeError("Reasoning planner is not configured.")
        context_text = self._format_context_text(context)
        system_text = (
            "You are the reasoning planner in a local coding orchestrator. "
            "Use deeper reasoning only for decomposition, dependency ordering, and validation design. "
            "Return strict JSON with a short actionable summary and 3-5 steps. "
            "Each step must include title, worker, instructions, phase, command, workdir, assigned_role, inputs, outputs, dependencies, acceptance_criteria. "
            "Keep steps compact. Push routine implementation and review to cheap workers. For build or system-build work, the first concrete step must be build/run, not architecture. Reviewer steps may only appear after artifact evidence exists and must emit a patch or release decision."
        )
        user_text = (
            f"Task: {prompt}\nRepository: {repo_path or 'not provided'}\n\nContext:\n{context_text}\n\n"
            + f"Return strict JSON with this shape: {self._planner_shape()}"
        )
        response = provider_gateway.chat_completions_create(
            provider_name="reasoning-planner",
            api_key=settings.reasoning_llm_api_key,
            default_base_url=settings.reasoning_llm_base_url,
            base_url_candidates=list(settings.reasoning_llm_base_url_candidates),
            default_proxy=settings.reasoning_llm_proxy_candidates[0]
            if settings.reasoning_llm_proxy_candidates
            else "",
            proxy_candidates=list(settings.reasoning_llm_proxy_candidates),
            timeout_seconds=max(8.0, min(settings.reasoning_request_timeout_seconds, 45.0)),
            request_kwargs={
                "model": settings.reasoning_planner_model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
            },
        )
        message = response.choices[0].message if response.choices else None
        text = ""
        if message is not None:
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        payload = json.loads(text)
        return self._planner_response_from_payload(payload, repo_path)

    def _cheap_plan(
        self, prompt: str, repo_path: str | None, context: ContextEnvelope | None
    ) -> PlannerResponse:
        if not self._cheap_configured:
            raise RuntimeError("Cheap planner is not configured.")
        context_text = self._format_context_text(context)
        system_text = (
            "You are the planner in a local coding orchestrator. "
            "Return strict JSON with a short actionable summary and 3-5 steps. "
            "Each step must include title, worker, instructions, phase, command, workdir, assigned_role, inputs, outputs, dependencies, acceptance_criteria. "
            "Prefer cheap, safe, repository-local execution and minimal context use. For build or system-build work, the first concrete step must be build/run, not architecture. Reviewer steps may only appear after artifact evidence exists and must emit a patch or release decision."
        )
        user_text = (
            f"Task: {prompt}\nRepository: {repo_path or 'not provided'}\n\nContext:\n{context_text}\n\n"
            + f"Return strict JSON with this shape: {self._planner_shape()}"
        )
        response = provider_gateway.chat_completions_create(
            provider_name="cheap-planner",
            api_key=settings.cheap_llm_api_key,
            default_base_url=settings.cheap_llm_base_url,
            base_url_candidates=list(settings.cheap_llm_base_url_candidates),
            default_proxy=settings.cheap_llm_proxy_candidates[0]
            if settings.cheap_llm_proxy_candidates
            else "",
            proxy_candidates=list(settings.cheap_llm_proxy_candidates),
            timeout_seconds=self._planner_fast_timeout_seconds(
                settings.cheap_request_timeout_seconds
            ),
            request_kwargs={
                "model": settings.default_review_model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
            },
        )
        message = response.choices[0].message if response.choices else None
        text = ""
        if message is not None:
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        payload = json.loads(text)
        return self._planner_response_from_payload(payload, repo_path)

    def _remote_decomposition(
        self,
        *,
        prompt: str,
        repo_path: str | None,
        context: ContextEnvelope | None,
        max_children: int,
        depth: int,
        max_depth: int,
    ) -> TaskDecompositionResponse:
        if not self._configured:
            raise RuntimeError("Remote planner is not configured.")
        context_text = self._format_context_text(context)
        system_text = (
            "You are the decomposition planner for a local coding orchestrator. "
            "Return strict JSON only. Split the task into 2-5 immediate subtasks. "
            "Each subtask must be bounded, actionable, and suitable for a child task that may itself be decomposed until the depth limit is reached. "
            "Prefer a clear sequence of analyze, implement, verify, and synthesize when relevant. "
            "Do not invent more than one layer of nested subtasks in the response; the orchestrator will recurse. "
            "For build or system-build work, include a concrete build or run branch among the immediate subtasks."
        )
        user_text = (
            f"Task: {prompt}\n"
            f"Repository: {repo_path or 'not provided'}\n"
            f"Depth: {depth}/{max_depth}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Return strict JSON with this shape: {self._decomposition_shape()}"
        )
        if self._use_chat_planner_api():
            response = provider_gateway.chat_completions_create(
                provider_name="openai-decomposition",
                api_key=settings.openai_api_key,
                default_base_url=settings.openai_base_url,
                base_url_candidates=list(settings.openai_base_url_candidates),
                default_proxy=settings.network_proxy_url,
                proxy_candidates=list(settings.openai_proxy_candidates),
                timeout_seconds=self._planner_fast_timeout_seconds(
                    settings.planner_request_timeout_seconds
                ),
                request_kwargs={
                    "model": settings.planner_model,
                    "messages": [
                        {"role": "system", "content": system_text},
                        {"role": "user", "content": user_text},
                    ],
                    "stream": False,
                },
            )
            message = response.choices[0].message if response.choices else None
            text = ""
            if message is not None:
                if isinstance(message.content, str):
                    text = message.content
                elif isinstance(message.content, list):
                    text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
            payload = json.loads(text)
            return self._decomposition_response_from_payload(payload, repo_path, max_children=max_children)

        schema = {
            "name": "orchestrator_decomposition",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {"type": "string"},
                    "strategy": {"type": "string"},
                    "subtasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "prompt": {"type": "string"},
                                "goal": {"type": ["string", "null"]},
                                "task_type": {"type": ["string", "null"]},
                                "queue_name": {"type": ["string", "null"]},
                                "verification_level": {"type": ["string", "null"]},
                                "preferred_worker": {"type": ["string", "null"]},
                                "execution_mode": {
                                    "type": ["string", "null"],
                                    "enum": ["governance", "research", "production", None],
                                },
                                "execution_lane": {"type": ["string", "null"]},
                                "decompose_children": {"type": "boolean"},
                                "inputs": {"type": "array", "items": {"type": "string"}},
                                "outputs": {"type": "array", "items": {"type": "string"}},
                                "dependencies": {"type": "array", "items": {"type": "string"}},
                                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                                "scheduler_hint": {"type": "object"},
                                "executor_hint": {"type": "object"},
                            },
                            "required": [
                                "title",
                                "prompt",
                                "goal",
                                "task_type",
                                "queue_name",
                                "verification_level",
                                "preferred_worker",
                                "execution_mode",
                                "execution_lane",
                                "decompose_children",
                                "inputs",
                                "outputs",
                                "dependencies",
                                "acceptance_criteria",
                                "scheduler_hint",
                                "executor_hint",
                            ],
                        },
                    },
                },
                "required": ["summary", "strategy", "subtasks"],
            },
        }
        response = provider_gateway.responses_create(
            provider_name="openai-decomposition",
            api_key=settings.openai_api_key,
            default_base_url=settings.openai_base_url,
            base_url_candidates=list(settings.openai_base_url_candidates),
            default_proxy=settings.network_proxy_url,
            proxy_candidates=list(settings.openai_proxy_candidates),
            timeout_seconds=settings.planner_request_timeout_seconds,
            request_kwargs={
                "model": settings.planner_model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_text}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": user_text}],
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema["name"],
                        "schema": schema["schema"],
                        "strict": True,
                    }
                },
            },
        )
        payload = json.loads(response.output_text)
        return self._decomposition_response_from_payload(payload, repo_path, max_children=max_children)

    def _reasoning_decomposition(
        self,
        *,
        prompt: str,
        repo_path: str | None,
        context: ContextEnvelope | None,
        max_children: int,
        depth: int,
        max_depth: int,
    ) -> TaskDecompositionResponse:
        if not self._reasoning_configured:
            raise RuntimeError("Reasoning planner is not configured.")
        context_text = self._format_context_text(context)
        system_text = (
            "You are the decomposition planner in a local coding orchestrator. "
            "Use deeper reasoning only for decomposition, dependency ordering, and validation design. "
            "Return strict JSON with a short summary, a strategy string, and 2-5 immediate subtasks. "
            "Keep each subtask compact and bounded. "
            "The orchestrator will recurse on child tasks until the depth limit is reached."
        )
        user_text = (
            f"Task: {prompt}\nRepository: {repo_path or 'not provided'}\nDepth: {depth}/{max_depth}\n\nContext:\n{context_text}\n\n"
            + f"Return strict JSON with this shape: {self._decomposition_shape()}"
        )
        response = provider_gateway.chat_completions_create(
            provider_name="reasoning-decomposition",
            api_key=settings.reasoning_llm_api_key,
            default_base_url=settings.reasoning_llm_base_url,
            base_url_candidates=list(settings.reasoning_llm_base_url_candidates),
            default_proxy=settings.reasoning_llm_proxy_candidates[0]
            if settings.reasoning_llm_proxy_candidates
            else "",
            proxy_candidates=list(settings.reasoning_llm_proxy_candidates),
            timeout_seconds=max(8.0, min(settings.reasoning_request_timeout_seconds, 45.0)),
            request_kwargs={
                "model": settings.reasoning_planner_model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
            },
        )
        message = response.choices[0].message if response.choices else None
        text = ""
        if message is not None:
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        payload = json.loads(text)
        return self._decomposition_response_from_payload(payload, repo_path, max_children=max_children)

    def _cheap_decomposition(
        self,
        *,
        prompt: str,
        repo_path: str | None,
        context: ContextEnvelope | None,
        max_children: int,
        depth: int,
        max_depth: int,
    ) -> TaskDecompositionResponse:
        if not self._cheap_configured:
            raise RuntimeError("Cheap planner is not configured.")
        context_text = self._format_context_text(context)
        system_text = (
            "You are the decomposition planner in a local coding orchestrator. "
            "Return strict JSON with a short summary, a strategy string, and 2-5 immediate subtasks. "
            "Prefer cheap, safe, repository-local decomposition. "
            "The orchestrator will recurse on child tasks until the depth limit is reached."
        )
        user_text = (
            f"Task: {prompt}\nRepository: {repo_path or 'not provided'}\nDepth: {depth}/{max_depth}\n\nContext:\n{context_text}\n\n"
            + f"Return strict JSON with this shape: {self._decomposition_shape()}"
        )
        response = provider_gateway.chat_completions_create(
            provider_name="cheap-decomposition",
            api_key=settings.cheap_llm_api_key,
            default_base_url=settings.cheap_llm_base_url,
            base_url_candidates=list(settings.cheap_llm_base_url_candidates),
            default_proxy=settings.cheap_llm_proxy_candidates[0]
            if settings.cheap_llm_proxy_candidates
            else "",
            proxy_candidates=list(settings.cheap_llm_proxy_candidates),
            timeout_seconds=self._planner_fast_timeout_seconds(settings.cheap_request_timeout_seconds),
            request_kwargs={
                "model": settings.default_review_model,
                "messages": [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                "stream": False,
            },
        )
        message = response.choices[0].message if response.choices else None
        text = ""
        if message is not None:
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        payload = json.loads(text)
        return self._decomposition_response_from_payload(payload, repo_path, max_children=max_children)

    def _use_chat_planner_api(self) -> bool:
        return strategic_llm_api_style() == "chat.completions"

    def _planner_response_from_payload(
        self, payload: dict[str, object], repo_path: str | None
    ) -> PlannerResponse:
        steps = payload.get("steps", []) if isinstance(payload, dict) else []
        summary = payload.get("summary", "") if isinstance(payload, dict) else ""
        return PlannerResponse(
            summary=str(summary or ""),
            steps=[
                StepSpec(
                    title=str(step.get("title") or "Untitled step"),
                    worker=WorkerType(str(step.get("worker") or WorkerType.planner.value)),
                    instructions=str(step.get("instructions") or ""),
                    phase=step.get("phase"),
                    command=step.get("command"),
                    workdir=step.get("workdir") or repo_path,
                    assigned_role=AgentRole(step["assigned_role"])
                    if step.get("assigned_role")
                    else None,
                    inputs=list(step.get("inputs", [])),
                    outputs=list(step.get("outputs", [])),
                    dependencies=list(step.get("dependencies", [])),
                    acceptance_criteria=list(step.get("acceptance_criteria", [])),
                )
                for step in steps
                if isinstance(step, dict)
            ],
        )

    def _fallback_plan(self, prompt: str, repo_path: str | None) -> PlannerResponse:
        lowered = prompt.lower()
        url_match = re.search(r"https?://[^\s)]+", prompt)
        if self._is_binary_classification_lab_prompt(prompt, repo_path):
            workdir = repo_path or str(WORKSPACE_ROOT / "generated" / "ml-binary-classification-lab")
            return PlannerResponse(
                summary="Local fallback plan for a deterministic binary-classification lab run with an embedded dataset fallback.",
                steps=[
                    StepSpec(
                        title="Run deterministic binary classification lab",
                        worker=WorkerType.docker,
                        phase="execute",
                        instructions="Generate the bounded lab artifact locally with a deterministic dataset fallback and explicit accuracy comparison.",
                        command="internal://lab/binary-classification-run",
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        outputs=[
                            "BINARY_CLASSIFICATION_AUTORUN_RESULT.md",
                            "binary_classification_metrics.json",
                        ],
                        acceptance_criteria=[
                            "The markdown result artifact exists in the target workspace.",
                            "The metrics JSON exists and lists accuracies for logistic regression, linear SVM, perceptron, and SGD classifier.",
                        ],
                    ),
                ],
            )
        if any(
            token in lowered
            for token in [
                "research",
                "investigate",
                "analysis",
                "design",
                "proposal",
                "roadmap",
                "rfc",
                "compare",
                "competition",
                "github issue",
                "github repo",
            ]
        ):
            workdir = repo_path or "D:\\codex\\orchestrator-mvp"
            query_literal = json.dumps(prompt, ensure_ascii=False)
            return PlannerResponse(
                summary="Local fallback plan for Internet Knowledge acquisition through the Perplexity research layer.",
                steps=[
                    StepSpec(
                        title="Frame research question",
                        worker=WorkerType.reviewer,
                        phase="understand",
                        instructions=f"Restate the research goal, constraints, and target output for: {prompt}",
                        workdir=workdir,
                        assigned_role=AgentRole.product,
                        outputs=["research brief"],
                        acceptance_criteria=["Research brief is explicit and bounded"],
                    ),
                    StepSpec(
                        title="Acquire internet knowledge",
                        worker=WorkerType.docker,
                        phase="execute",
                        instructions="Run the Perplexity-backed Internet Knowledge layer and persist findings into the knowledge store.",
                        command=f"python tools/perplexity_search.py --query {query_literal} --focus research",
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        inputs=["research brief"],
                        outputs=[
                            "data/internet_knowledge.json",
                            "data/perplexity_research_status.json",
                        ],
                        acceptance_criteria=["Internet knowledge snapshot persisted"],
                    ),
                    StepSpec(
                        title="Synthesize research output",
                        worker=WorkerType.reviewer,
                        phase="summarize",
                        instructions="Summarize the latest internet knowledge snapshot, extract implementation-relevant findings, and state the next bounded experiment or implementation step.",
                        workdir=workdir,
                        assigned_role=AgentRole.reviewer,
                        inputs=["data/internet_knowledge.json"],
                        outputs=["research synthesis"],
                        acceptance_criteria=["Findings and next step are explicit"],
                    ),
                ],
            )
        if (
            any(
                token in lowered
                for token in [
                    "browser",
                    "webpage",
                    "website",
                    "read webpage",
                    "login page",
                ]
            )
            or url_match
        ):
            target_url = url_match.group(0) if url_match else "https://example.com"
            workdir = repo_path or "D:\\codex"
            return PlannerResponse(
                summary="Local fallback plan for real-browser webpage reading with optional persistent login session.",
                steps=[
                    StepSpec(
                        title="Understand webpage goal",
                        worker=WorkerType.reviewer,
                        phase="understand",
                        instructions=f"Summarize what information is needed from: {prompt}",
                        workdir=workdir,
                        assigned_role=AgentRole.product,
                    ),
                    StepSpec(
                        title="Read webpage through browser bridge",
                        worker=WorkerType.browser,
                        phase="execute",
                        instructions="Use the local browser bridge to open the page and capture rendered content.",
                        command=target_url,
                        workdir=workdir,
                    ),
                    StepSpec(
                        title="Review rendered webpage content",
                        worker=WorkerType.reviewer,
                        phase="verify",
                        instructions="Summarize the rendered page, note whether login is still required, and identify the next safe action.",
                        workdir=workdir,
                    ),
                ],
            )
        if any(
            token in lowered
            for token in [
                "toyos",
                "toy os",
                "bootloader",
                "kernel module",
                "kernel image",
            ]
        ):
            target_path = Path(repo_path) if repo_path else WORKSPACE_ROOT / "generated" / "toy-os-demo"
            workdir = str(target_path)
            python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else "python")
            build_script = ORCHESTRATOR_ROOT / "tools" / "build_toy_os.py"
            qemu_runner = ORCHESTRATOR_ROOT / "tools" / "generic_test_runner.py"
            score_script = ORCHESTRATOR_ROOT / "tools" / "score_toy_os.py"
            qemu_spec = target_path / "tools" / "generic_qemu_smoke.json"
            return PlannerResponse(
                summary="Local fallback plan for a ToyOS short execution loop: build, boot in QEMU, audit runtime evidence, patch, and rerun the artifact path.",
                steps=[
                StepSpec(
                    title="Build Toy OS baseline",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Run the deterministic ToyOS build check first so the task starts from a real build signal.",
                        command=f'"{python_cmd}" "{build_script}" --target "{target_path}"',
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        outputs=["build-report.json", "kernel.bin"],
                        acceptance_criteria=["Build report refreshed"],
                    ),
                StepSpec(
                    title="Boot ToyOS in QEMU",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Run the reusable ToyOS QEMU regression suite and capture the boot/runtime report before any patching.",
                        command=f'"{python_cmd}" "{qemu_runner}" --spec "{qemu_spec}"',
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        inputs=["build-report.json", "kernel.bin"],
                        outputs=["generic-qemu-smoke-report.json"],
                        acceptance_criteria=["QEMU regression report refreshed"],
                    ),
                    StepSpec(
                        title="Audit ToyOS runtime evidence",
                        worker=WorkerType.reviewer,
                        phase="review",
                        instructions="Audit the build and QEMU artifacts, identify the failing boundary, and emit a concrete patch decision.",
                        workdir=workdir,
                        assigned_role=AgentRole.reviewer,
                        inputs=["build-report.json", "generic-qemu-smoke-report.json"],
                        outputs=["patch decision"],
                        acceptance_criteria=["Patch decision grounded in runtime artifacts"],
                    ),
                    StepSpec(
                        title="Patch Toy OS implementation",
                        worker=WorkerType.coder,
                        phase="draft",
                        instructions="Inspect the current ToyOS sources, make the smallest coherent change set, and keep the stable boot path intact.",
                        workdir=workdir,
                        assigned_role=AgentRole.coder,
                        inputs=["patch decision"],
                        outputs=["patched kernel sources"],
                        acceptance_criteria=["Small coherent kernel patch prepared"],
                    ),
                StepSpec(
                    title="Rebuild Toy OS after patch",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Rebuild ToyOS after the patch and refresh the runnable artifact set.",
                        command=f'"{python_cmd}" "{build_script}" --target "{target_path}"',
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        inputs=["patched kernel sources"],
                        outputs=["build-report.json", "kernel.bin"],
                        acceptance_criteria=["Patched build report refreshed"],
                    ),
                StepSpec(
                    title="Re-run ToyOS QEMU and score artifacts",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Boot the patched ToyOS in QEMU again and refresh the score report for the delivered artifact set.",
                        command=f'"{python_cmd}" "{qemu_runner}" --spec "{qemu_spec}"',
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        inputs=["build-report.json", "kernel.bin"],
                        outputs=["generic-qemu-smoke-report.json"],
                        acceptance_criteria=["Patched QEMU regression report refreshed"],
                    ),
                StepSpec(
                    title="Score ToyOS artifact set",
                    worker=WorkerType.docker,
                    phase="verify",
                    instructions="Inspect the refreshed ToyOS artifact set and write a deterministic score report.",
                        command=f'"{python_cmd}" "{score_script}" --target "{target_path}"',
                        workdir=workdir,
                        assigned_role=AgentRole.tester,
                        inputs=["generic-qemu-smoke-report.json"],
                        outputs=["score-report.json"],
                        acceptance_criteria=["Score report refreshed"],
                    ),
                    StepSpec(
                        title="Issue ToyOS release decision",
                        worker=WorkerType.reviewer,
                        phase="revise",
                        instructions="Review the refreshed ToyOS artifacts and emit a release or follow-up patch decision with residual risk.",
                        workdir=workdir,
                        assigned_role=AgentRole.reviewer,
                        inputs=["build-report.json", "generic-qemu-smoke-report.json", "score-report.json"],
                        outputs=["release decision"],
                        acceptance_criteria=["Release decision backed by refreshed artifacts"],
                    ),
                ],
            )
        if any(
            token in lowered
            for token in [
                "generated\\",
                "generated/",
                ".md",
                "markdown",
                "audit",
                "report",
                "summary",
                "note",
            ]
        ) and any(
            token in lowered
            for token in [
                "only write",
                "only create",
                "do not modify runtime code",
                "do not modify code",
                "artifact",
            ]
        ):
            return PlannerResponse(
                summary="Local fallback plan for bounded artifact generation without unnecessary shell validation.",
                steps=[
                    StepSpec(
                        title="Understand artifact task",
                        worker=WorkerType.planner,
                        phase="understand",
                        instructions=f"Summarize the requested artifact, scope limits, and forbidden changes for: {prompt}",
                        workdir=repo_path,
                        assigned_role=AgentRole.product,
                        outputs=["artifact brief"],
                        acceptance_criteria=["Artifact scope is explicit"],
                    ),
                    StepSpec(
                        title="Draft artifact",
                        worker=WorkerType.coder,
                        phase="draft",
                        instructions="Produce only the requested artifact or documentation file, keeping all runtime code untouched.",
                        workdir=repo_path,
                        assigned_role=AgentRole.coder,
                        inputs=["artifact brief"],
                        outputs=["artifact draft"],
                        acceptance_criteria=["Requested artifact drafted"],
                    ),
                    StepSpec(
                        title="Review artifact scope",
                        worker=WorkerType.reviewer,
                        phase="verify",
                        instructions="Confirm the output stays within scope, names the exact validation commands, and emit an artifact decision.",
                        workdir=repo_path,
                        assigned_role=AgentRole.reviewer,
                        inputs=["artifact draft"],
                        outputs=["artifact decision"],
                        acceptance_criteria=["Scope stayed bounded and decision recorded"],
                    ),
                    StepSpec(
                        title="State next action",
                        worker=WorkerType.planner,
                        phase="revise",
                        instructions="State whether any further validation requires a human or runtime restart, and keep the recommendation low-cost.",
                        workdir=repo_path,
                        assigned_role=AgentRole.architect,
                        inputs=["artifact decision"],
                        outputs=["next action"],
                        acceptance_criteria=["Next action stated"],
                    ),
                ],
            )
        if self._requires_build_first_prompt(prompt, repo_path):
            return self._generic_bootstrap_plan(prompt=prompt, repo_path=repo_path)
        return PlannerResponse(
            summary="Fallback plan generated locally because planner remote access is unavailable.",
            steps=[
                StepSpec(
                    title="Understand task",
                    worker=WorkerType.planner,
                    phase="understand",
                    instructions=f"Summarize the engineering objective and constraints for: {prompt}",
                    workdir=repo_path,
                    assigned_role=AgentRole.product,
                    outputs=["structured requirement"],
                    acceptance_criteria=["Objective restated"],
                ),
                StepSpec(
                    title="Draft solution",
                    worker=WorkerType.coder,
                    phase="draft",
                    instructions="Draft the required code or file changes with a cheap model first.",
                    workdir=repo_path,
                    assigned_role=AgentRole.coder,
                    inputs=["structured requirement"],
                    outputs=["proposed patch plan"],
                    acceptance_criteria=["Small coherent change proposed"],
                ),
                StepSpec(
                    title="Execute validation",
                    worker=WorkerType.docker,
                    phase="execute",
                    instructions="Run a read-only local syntax check first so the task produces execution signal without mutating shared build caches.",
                    command=f"python {READ_ONLY_SYNTAX_CHECK} .",
                    workdir=repo_path,
                    assigned_role=AgentRole.tester,
                    inputs=["proposed patch plan"],
                    outputs=["validation artifact"],
                    acceptance_criteria=[
                        "Local validation command completed or returned a bounded failure report"
                    ],
                ),
                StepSpec(
                    title="Issue patch decision",
                    worker=WorkerType.reviewer,
                    phase="verify",
                    instructions="Review the validation artifact, summarize what passed or failed, and emit a concrete patch decision.",
                    workdir=repo_path,
                    assigned_role=AgentRole.reviewer,
                    inputs=["validation artifact"],
                    outputs=["patch decision"],
                    acceptance_criteria=["Patch decision grounded in validation artifact"],
                ),
                StepSpec(
                    title="Revise next action",
                    worker=WorkerType.planner,
                    phase="revise",
                    instructions="Recommend the next low-cost modification or explicitly mark that escalation is required.",
                    workdir=repo_path,
                    assigned_role=AgentRole.architect,
                    inputs=["patch decision"],
                    outputs=["next action"],
                    acceptance_criteria=["Next action stated"],
                ),
            ],
        )





