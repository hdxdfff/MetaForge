from pathlib import Path
import textwrap

root = Path(r'D:\codex\orchestrator-mvp')

# 1) generic_test_runner.py
path = root / 'tools' / 'generic_test_runner.py'
text = path.read_text(encoding='utf-8')
old = """#!/usr/bin/env python3\nimport argparse\nimport json\nimport subprocess\nfrom pathlib import Path\nfrom tools.io_utils import atomic_write_json\nfrom typing import Any\n"""
new = """#!/usr/bin/env python3\nimport argparse\nimport json\nimport subprocess\nimport sys\nfrom pathlib import Path\nfrom typing import Any\n\nROOT = Path(__file__).resolve().parent.parent\nif str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))\n\nfrom tools.io_utils import atomic_write_json\n"""
assert old in text, 'generic_test_runner header not found'
path.write_text(text.replace(old, new), encoding='utf-8')

# 2) add bootstrap_build_runner.py
(root / 'tools' / 'bootstrap_build_runner.py').write_text(textwrap.dedent("""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.read_only_syntax_check import _check_file, _python_files

DEFAULT_SCAN_DIRS = ("app", "runtime", "tools", "agents", "state")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_scan_roots(repo: Path) -> list[Path]:
    roots: list[Path] = []
    for name in DEFAULT_SCAN_DIRS:
        candidate = repo / name
        if candidate.exists():
            roots.append(candidate)
    if not roots:
        roots.append(repo)
    return roots


def run_bootstrap_build(repo: Path) -> dict[str, Any]:
    scan_roots = _resolve_scan_roots(repo)
    files: list[Path] = []
    for root_path in scan_roots:
        files.extend(_python_files(root_path))
    unique_files = sorted({path for path in files})
    syntax_errors = [issue for issue in (_check_file(path) for path in unique_files) if issue]
    scanned = [str(path.relative_to(repo)) for path in unique_files]
    return {
        "status": "pass" if not syntax_errors else "fail",
        "repo": str(repo),
        "scanned_roots": [str(path.relative_to(repo)) if path != repo else "." for path in scan_roots],
        "checked_file_count": len(unique_files),
        "checked_files": scanned[:200],
        "syntax_error_count": len(syntax_errors),
        "syntax_errors": syntax_errors[:50],
        "generated_at": _utc(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-readable bootstrap build evidence.")
    parser.add_argument("--repo", required=True, help="Repository root to inspect.")
    parser.add_argument("--report", required=True, help="JSON report output path.")
    parser.add_argument("--log", required=True, help="Text log output path.")
    parser.add_argument("--manifest", required=True, help="Manifest output path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report_path = Path(args.report).resolve()
    log_path = Path(args.log).resolve()
    manifest_path = Path(args.manifest).resolve()

    result = run_bootstrap_build(repo)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    atomic_write_json(report_path, result)
    log_lines = [
        f"bootstrap_build_status={result['status']}",
        f"checked_file_count={result['checked_file_count']}",
        f"syntax_error_count={result['syntax_error_count']}",
    ]
    if result["syntax_errors"]:
        log_lines.extend(result["syntax_errors"])
    else:
        log_lines.append("syntax_errors=0")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    atomic_write_json(
        manifest_path,
        {
            "generated_at": result["generated_at"],
            "kind": "bootstrap-build-manifest",
            "artifacts": [str(report_path), str(log_path), str(manifest_path)],
            "status": result["status"],
        },
    )

    print(f"bootstrap build report: {report_path}")
    print(f"checked_file_count={result['checked_file_count']}")
    print(f"syntax_error_count={result['syntax_error_count']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""), encoding='utf-8')

# 3) add bootstrap_validation_runner.py
(root / 'tools' / 'bootstrap_validation_runner.py').write_text(textwrap.dedent("""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

BUNDLED_PYTHON = ROOT.parent / "tools" / "python311-embed" / "python.exe"
QA_CHECK = ROOT / "tools" / "qa_check.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-readable bootstrap validation evidence.")
    parser.add_argument("--repo", required=True, help="Repository root to validate.")
    parser.add_argument("--report", required=True, help="JSON report output path.")
    parser.add_argument("--log", required=True, help="Text log output path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report_path = Path(args.report).resolve()
    log_path = Path(args.log).resolve()
    python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else sys.executable)

    completed = subprocess.run(
        [python_cmd, str(QA_CHECK)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )

    report = {
        "status": "pass" if completed.returncode == 0 else "fail",
        "repo": str(repo),
        "command": [python_cmd, str(QA_CHECK)],
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "generated_at": _utc(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, report)
    log_path.write_text(
        "\n".join(
            [
                f"bootstrap_validation_status={report['status']}",
                f"returncode={completed.returncode}",
                (completed.stdout or "").strip(),
                (completed.stderr or "").strip(),
            ]
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    print(f"bootstrap validation report: {report_path}")
    print(f"returncode={completed.returncode}")
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
"""), encoding='utf-8')

# 4) taskgraph_compiler.py
path = root / 'tools' / 'taskgraph_compiler.py'
text = path.read_text(encoding='utf-8')
text = text.replace(
"""def _artifact_required_paths(target: str, node: dict | None = None) -> list[str]:
    node = node or {}
    corpus = " ".join(
        [
            str(target or ""),
            str(node.get("title") or ""),
            str(node.get("prompt") or ""),
        ]
    ).lower()
    node_kind = str(node.get("kind") or "")
    if node_kind in {
        "architecture",
        "planning",
        "artifact-audit",
        "cross-project-coordination",
        "cross-project-work-package",
        "cross-project-coordination-package",
    }:
        return []
    if "generated/toy-os-demo" in corpus or "toyos" in corpus or "toy-os" in corpus:
""",
"""def _artifact_required_paths(target: str, node: dict | None = None) -> list[str]:
    node = node or {}
    corpus = " ".join(
        [
            str(target or ""),
            str(node.get("title") or ""),
            str(node.get("prompt") or ""),
        ]
    ).lower()
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    if node_kind in {
        "architecture",
        "planning",
        "artifact-audit",
        "cross-project-coordination",
        "cross-project-work-package",
        "cross-project-coordination-package",
    }:
        return []
    if "generated/toy-os-demo" in corpus or "toyos" in corpus or "toy-os" in corpus:
""")
text = text.replace(
"""        return [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
            "generated/toy-os-demo/build/artifact.sha256",
            "generated/toy-os-demo/artifact_manifest.json",
        ]
    goal_type = str(node.get("goal_type") or "")
""",
"""        return [
            "generated/toy-os-demo/build-report.json",
            "generated/toy-os-demo/build/build.log",
            "generated/toy-os-demo/build/kernel.bin",
            "generated/toy-os-demo/build/generic-qemu-smoke-report.json",
            "generated/toy-os-demo/build/artifact.sha256",
            "generated/toy-os-demo/artifact_manifest.json",
        ]
    if node_id == "bootstrap_build":
        return [
            "reports/bootstrap-build-report.json",
            "reports/bootstrap-build.log",
            "reports/bootstrap-build-manifest.json",
        ]
    if node_id == "bootstrap_test":
        return [
            "reports/bootstrap-validation.json",
            "reports/bootstrap-validation.log",
        ]
    goal_type = str(node.get("goal_type") or "")
""")
text = text.replace(
"""def _artifact_outputs(goal_type: str, node: dict | None = None) -> list[str]:
    node = node or {}
    node_kind = str(node.get("kind") or "")
    if node_kind == "artifact-build":
""",
"""def _artifact_outputs(goal_type: str, node: dict | None = None) -> list[str]:
    node = node or {}
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    corpus = " ".join(
        [
            str(node.get("title") or ""),
            str(node.get("prompt") or ""),
        ]
    ).lower()
    if node_id == "bootstrap_build" and not any(marker in corpus for marker in ("toyos", "toy-os", "qemu", "kernel")):
        return ["build_report", "build_log", "artifact_manifest"]
    if node_id == "bootstrap_test" and not any(marker in corpus for marker in ("toyos", "toy-os", "qemu", "kernel")):
        return ["test_report", "runtime_log"]
    if node_kind == "artifact-build":
""")
text = text.replace(
"""    required_artifacts = _artifact_required_paths(target, node)
    node_kind = str(node.get("kind") or "")
    build_required = node_kind not in {
""",
"""    required_artifacts = _artifact_required_paths(target, node)
    node_kind = str(node.get("kind") or "")
    node_id = str(node.get("id") or "")
    build_required = node_kind not in {
""")
text = text.replace(
"""    tests_required = (
        node_kind in {"artifact-test", "artifact-evidence", "verification"} or build_required
    )
""",
"""    if node_id == "bootstrap_build":
        build_required = True
    tests_required = (
        node_kind in {"artifact-test", "artifact-evidence", "verification"} or build_required
    )
    if node_id == "bootstrap_build":
        tests_required = False
    elif node_id == "bootstrap_test":
        tests_required = True
""")
path.write_text(text, encoding='utf-8')

# 5) factory_task_engine.py
path = root / 'tools' / 'factory_task_engine.py'
text = path.read_text(encoding='utf-8')
old = """def _graph_needs_contract_upgrade(goal: dict[str, Any], graph: dict[str, Any]) -> bool:
    if not _goal_requires_artifact_first(goal):
        return False
    if not graph:
        return False
    meta = graph.get("meta") or {}
    if str(meta.get("route_strategy") or "") != "artifact-first":
        return True
    bootstrap = next((node for node in (graph.get("nodes") or []) if str(node.get("id") or "") == "bootstrap_build"), None)
    if bootstrap is None:
        return True
    if bool(bootstrap.get("patch_required")):
        return True
    return False
"""
new = """def _graph_needs_contract_upgrade(goal: dict[str, Any], graph: dict[str, Any]) -> bool:
    if not _goal_requires_artifact_first(goal):
        return False
    if not graph:
        return False
    meta = graph.get("meta") or {}
    if str(meta.get("route_strategy") or "") != "artifact-first":
        return True
    bootstrap = next((node for node in (graph.get("nodes") or []) if str(node.get("id") or "") == "bootstrap_build"), None)
    if bootstrap is None:
        return True
    if bool(bootstrap.get("patch_required")):
        return True
    bootstrap_artifacts = set((bootstrap.get("artifact_spec") or {}).get("required_artifacts") or [])
    toyos_bootstrap = any("generated/toy-os-demo" in item for item in bootstrap_artifacts)
    if not toyos_bootstrap and "reports/bootstrap-build-report.json" not in bootstrap_artifacts:
        return True
    bootstrap_test = next((node for node in (graph.get("nodes") or []) if str(node.get("id") or "") == "bootstrap_test"), None)
    if bootstrap_test is None:
        return True
    test_artifacts = set((bootstrap_test.get("artifact_spec") or {}).get("required_artifacts") or [])
    toyos_test = any("generated/toy-os-demo" in item for item in test_artifacts)
    if not toyos_test and "reports/bootstrap-validation.json" not in test_artifacts:
        return True
    return False
"""
assert old in text, 'factory_task_engine block not found'
path.write_text(text.replace(old, new), encoding='utf-8')

# 6) openai_client.py
path = root / 'app' / 'openai_client.py'
text = path.read_text(encoding='utf-8')
old = """    def _looks_strategic_prompt(self, prompt: str) -> bool:
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

    def _should_prefer_cheap_plan(self, prompt: str, context: ContextEnvelope | None) -> bool:
"""
new = """    def _looks_strategic_prompt(self, prompt: str) -> bool:
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
                    worker=WorkerType.shell,
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
                    worker=WorkerType.shell,
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

    def _should_prefer_cheap_plan(self, prompt: str, context: ContextEnvelope | None) -> bool:
"""
assert old in text, 'openai_client insertion block not found'
text = text.replace(old, new)
marker = """        return PlannerResponse(
            summary="Fallback plan generated locally because planner remote access is unavailable.",
"""
insert = """        if self._requires_build_first_prompt(prompt, repo_path):
            return self._generic_bootstrap_plan(prompt=prompt, repo_path=repo_path)
        return PlannerResponse(
            summary="Fallback plan generated locally because planner remote access is unavailable.",
"""
assert marker in text, 'openai_client fallback marker not found'
text = text.replace(marker, insert, 1)
path.write_text(text, encoding='utf-8')

# 7) orchestrator.py
path = root / 'app' / 'orchestrator.py'
text = path.read_text(encoding='utf-8')
old = """from tools.kernel_mode import should_auto_approve_task


def utc_iso() -> str:
"""
new = """from tools.kernel_mode import should_auto_approve_task

APP_ROOT = Path(__file__).resolve().parent.parent
CODEX_ROOT = APP_ROOT.parent
BUNDLED_PYTHON = CODEX_ROOT / "tools" / "python311-embed" / "python.exe"


def utc_iso() -> str:
"""
assert old in text, 'orchestrator constants insertion point not found'
text = text.replace(old, new)
old = """    def _is_build_or_run_step(self, step: StepSpec) -> bool:
        corpus = " ".join(
            str(part or "")
            for part in [step.title, step.instructions, step.command, step.phase]
        ).lower()
        if step.worker not in {WorkerType.shell, WorkerType.docker}:
            return False
        return any(token in corpus for token in ("build", "run", "boot", "qemu", "compile", "test"))

    def _enforce_production_plan_constraints(self, task: TaskRecord, plan: PlannerResponse) -> PlannerResponse:
"""
new = """    def _is_build_or_run_step(self, step: StepSpec) -> bool:
        corpus = " ".join(
            str(part or "")
            for part in [step.title, step.instructions, step.command, step.phase]
        ).lower()
        if step.worker not in {WorkerType.shell, WorkerType.docker}:
            return False
        return any(token in corpus for token in ("build", "run", "boot", "qemu", "compile", "test"))

    def _build_first_recovery_plan(self, task: TaskRecord, reason: str) -> PlannerResponse:
        corpus = " ".join(
            str(part or "")
            for part in [
                task.prompt,
                task.goal,
                task.title,
                (task.scheduler_hint or {}).get("node_title"),
                (task.scheduler_hint or {}).get("goal_target"),
            ]
        ).lower()
        python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else "python")
        workdir = task.repo_path or str(APP_ROOT)
        if any(token in corpus for token in ("toyos", "toy os", "qemu", "kernel")):
            target_path = Path(task.repo_path) if task.repo_path else CODEX_ROOT / "generated" / "toy-os-demo"
            build_script = APP_ROOT / "tools" / "build_toy_os.py"
            qemu_runner = APP_ROOT / "tools" / "generic_test_runner.py"
            qemu_spec = target_path / "tools" / "generic_qemu_smoke.json"
            return PlannerResponse(
                summary=f"Recovered build-first plan after invalid planner output: {reason}",
                steps=[
                    StepSpec(
                        title="Build Toy OS baseline",
                        worker=WorkerType.shell,
                        phase="execute",
                        instructions="Recover to the deterministic ToyOS build path first.",
                        command=f'"{python_cmd}" "{build_script}" --target "{target_path}"',
                        workdir=str(target_path),
                        assigned_role=AgentRole.tester,
                        outputs=["build-report.json", "kernel.bin"],
                        acceptance_criteria=["Build report refreshed."],
                    ),
                    StepSpec(
                        title="Boot ToyOS in QEMU",
                        worker=WorkerType.shell,
                        phase="verify",
                        instructions="Run the reusable QEMU smoke suite after the build succeeds.",
                        command=f'"{python_cmd}" "{qemu_runner}" --spec "{qemu_spec}"',
                        workdir=str(target_path),
                        assigned_role=AgentRole.tester,
                        inputs=["build-report.json", "kernel.bin"],
                        outputs=["generic-qemu-smoke-report.json"],
                        acceptance_criteria=["QEMU smoke report refreshed."],
                    ),
                    StepSpec(
                        title="Audit ToyOS runtime evidence",
                        worker=WorkerType.reviewer,
                        phase="review",
                        instructions="Review the build and QEMU artifacts and emit a concrete patch decision.",
                        workdir=str(target_path),
                        assigned_role=AgentRole.reviewer,
                        inputs=["build-report.json", "generic-qemu-smoke-report.json"],
                        outputs=["patch decision"],
                        acceptance_criteria=["Patch decision grounded in runtime artifacts."],
                    ),
                ],
            )
        report_root = Path(workdir) / "reports"
        build_runner = APP_ROOT / "tools" / "bootstrap_build_runner.py"
        validation_runner = APP_ROOT / "tools" / "bootstrap_validation_runner.py"
        return PlannerResponse(
            summary=f"Recovered build-first plan after invalid planner output: {reason}",
            steps=[
                StepSpec(
                    title="Refresh bootstrap build evidence",
                    worker=WorkerType.shell,
                    phase="execute",
                    instructions="Run the cheapest local build-equivalent check first and refresh machine-readable bootstrap evidence.",
                    command=(
                        f'"{python_cmd}" "{build_runner}" --repo "{workdir}" '
                        f'--report "{report_root / "bootstrap-build-report.json"}" '
                        f'--log "{report_root / "bootstrap-build.log"}" '
                        f'--manifest "{report_root / "bootstrap-build-manifest.json"}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    outputs=[
                        "reports/bootstrap-build-report.json",
                        "reports/bootstrap-build.log",
                        "reports/bootstrap-build-manifest.json",
                    ],
                    acceptance_criteria=["Bootstrap build evidence refreshed."],
                ),
                StepSpec(
                    title="Run bootstrap validation sweep",
                    worker=WorkerType.shell,
                    phase="verify",
                    instructions="Run the bounded validation sweep after bootstrap build evidence exists.",
                    command=(
                        f'"{python_cmd}" "{validation_runner}" --repo "{workdir}" '
                        f'--report "{report_root / "bootstrap-validation.json"}" '
                        f'--log "{report_root / "bootstrap-validation.log"}"'
                    ),
                    workdir=workdir,
                    assigned_role=AgentRole.tester,
                    inputs=["reports/bootstrap-build-report.json"],
                    outputs=["reports/bootstrap-validation.json", "reports/bootstrap-validation.log"],
                    acceptance_criteria=["Bootstrap validation evidence refreshed."],
                ),
                StepSpec(
                    title="Audit bootstrap evidence",
                    worker=WorkerType.reviewer,
                    phase="review",
                    instructions="Review the bootstrap evidence and emit a concrete patch decision.",
                    workdir=workdir,
                    assigned_role=AgentRole.reviewer,
                    inputs=["reports/bootstrap-build-report.json", "reports/bootstrap-validation.json"],
                    outputs=["patch decision"],
                    acceptance_criteria=["Patch decision grounded in bootstrap artifacts."],
                ),
            ],
        )

    def _enforce_production_plan_constraints(self, task: TaskRecord, plan: PlannerResponse) -> PlannerResponse:
"""
assert old in text, 'orchestrator recovery helper insertion block not found'
text = text.replace(old, new)
old = """                    else:
                        raise ValueError(
                            f"Invalid production plan: reviewer step '{step.title}' lacks artifact input."
                        )
"""
new = """                    else:
                        if self._requires_build_first_plan(task):
                            return self._build_first_recovery_plan(
                                task,
                                f"reviewer step '{step.title}' lacks artifact input",
                            )
                        raise ValueError(
                            f"Invalid production plan: reviewer step '{step.title}' lacks artifact input."
                        )
"""
assert old in text, 'orchestrator reviewer artifact block not found'
text = text.replace(old, new)
old = """            if first_concrete is not None and not self._is_build_or_run_step(first_concrete):
                raise ValueError(
                    f"Invalid production plan: first concrete step '{first_concrete.title}' is not build/run."
                )
"""
new = """            if first_concrete is not None and not self._is_build_or_run_step(first_concrete):
                return self._build_first_recovery_plan(
                    task,
                    f"first concrete step '{first_concrete.title}' is not build/run",
                )
"""
assert old in text, 'orchestrator first concrete block not found'
text = text.replace(old, new)
path.write_text(text, encoding='utf-8')

print('patched files')
