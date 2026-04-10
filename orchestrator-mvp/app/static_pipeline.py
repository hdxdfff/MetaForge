from __future__ import annotations

import argparse
import json
import os
import shutil
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .audit_engine import assert_shadow_path, audit_task
    from .contract_validator import ContractValidator
    from .role_registry import RoleRegistry
except ImportError:
    APP_DIR = Path(__file__).resolve().parent
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    from audit_engine import assert_shadow_path, audit_task
    from contract_validator import ContractValidator
    from role_registry import RoleRegistry

BASE = Path(r"D:\codex\orchestrator-mvp")
SCHEMA_DIR = BASE / "contracts" / "schemas"
POLICY_PATH = BASE / "contracts" / "policy" / "role_permission_matrix.json"
SHADOW = BASE / "shadow_factory"
STATE_DIR = BASE / "state"
PIPELINE_STATE_PATH = STATE_DIR / "static_pipeline_state.json"
ROLE_RUNTIME_STATE_PATH = STATE_DIR / "role_runtime_state.json"
BUILD_TOY_OS_SCRIPT = BASE / "tools" / "build_toy_os.py"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _record_pipeline_state(task_packet: dict[str, Any], stage: str, *, extra: dict[str, Any] | None = None) -> None:
    payload = _load_json(PIPELINE_STATE_PATH, {"updated_at": None, "runs": []})
    runs = payload.setdefault("runs", [])
    runs.append(
        {
            "task_id": task_packet["task_id"],
            "stage": stage,
            "shadow_mode": task_packet.get("shadow_mode", False),
            "artifact_scope": task_packet.get("artifact_scope"),
            "at": utc_now(),
            **(extra or {}),
        }
    )
    payload["updated_at"] = utc_now()
    write_json(PIPELINE_STATE_PATH, payload)


def _record_role_state(role: str, action: str, task_id: str, *, status: str, outputs: list[str] | None = None) -> None:
    payload = _load_json(ROLE_RUNTIME_STATE_PATH, {"updated_at": None, "events": []})
    events = payload.setdefault("events", [])
    events.append(
        {
            "role": role,
            "action": action,
            "task_id": task_id,
            "status": status,
            "outputs": outputs or [],
            "at": utc_now(),
        }
    )
    payload["updated_at"] = utc_now()
    write_json(ROLE_RUNTIME_STATE_PATH, payload)


def _copy_shadow_project(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination, onerror=_handle_remove_readonly)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "build",
            ".git",
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            "build-report.json",
            "score-report.json",
        ),
    )


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _handle_remove_readonly(function: Any, path: str, exc_info: Any) -> None:
    del exc_info
    os.chmod(path, 0o700)
    function(path)


def _toy_os_build_attempt(target_dir: Path) -> dict[str, Any]:
    command = [sys.executable, str(BUILD_TOY_OS_SCRIPT), "--target", str(target_dir)]
    return _run_command(command, BASE)


def _load_build_report(build_report_path: Path) -> dict[str, Any]:
    if not build_report_path.exists():
        return {}
    return _load_json(build_report_path, {})


def _write_toyos_shadow_manifest(task_packet: dict[str, Any], artifact_dir: Path, artifact_paths: list[Path]) -> Path:
    manifest_path = artifact_dir / "artifact_manifest.json"
    write_json(
        manifest_path,
        {
            "artifact_id": task_packet["task_id"],
            "type": "shadow_build",
            "version": "1.0",
            "buildable": True,
            "runnable": False,
            "test_passed": False,
            "reproducible": False,
            "artifact_path": str(artifact_dir),
            "entrypoint": "build/kernel.bin",
            "evidence": [str(path.relative_to(artifact_dir)).replace("\\", "/") for path in artifact_paths],
            "shadow_mode": True,
            "source_project": task_packet["input_spec"]["project_path"],
            "created_at": utc_now(),
        },
    )
    return manifest_path


def _build_toyos_shadow_task(task_packet: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    source_project = Path(task_packet["input_spec"]["project_path"]).resolve()
    workspace_dir = artifact_dir / "workspace"
    assert_shadow_path(str(workspace_dir))
    _copy_shadow_project(source_project, workspace_dir)

    workspace_build_report = workspace_dir / "build-report.json"
    build_attempts: list[dict[str, Any]] = []
    build_attempts.append(_toy_os_build_attempt(workspace_dir))
    build_report_data = _load_build_report(workspace_build_report)

    build_execution_path = artifact_dir / "builder-execution.json"
    write_json(
        build_execution_path,
        {
            "task_id": task_packet["task_id"],
            "attempts": build_attempts,
            "selected_backend": "local",
            "completed_at": utc_now(),
        },
    )

    workspace_kernel = workspace_dir / "build" / "kernel.bin"
    workspace_build_log = workspace_dir / "build" / "build.log"
    workspace_sha = workspace_dir / "build" / "artifact.sha256"

    build_dir = artifact_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    build_report = artifact_dir / "build-report.json"
    kernel_path = build_dir / "kernel.bin"
    build_log = build_dir / "build.log"
    sha_path = build_dir / "artifact.sha256"

    copied_artifacts: list[Path] = [build_execution_path]
    if workspace_build_report.exists():
        shutil.copy2(workspace_build_report, build_report)
        copied_artifacts.append(build_report)
    if workspace_kernel.exists():
        shutil.copy2(workspace_kernel, kernel_path)
        copied_artifacts.append(kernel_path)
    if workspace_build_log.exists():
        shutil.copy2(workspace_build_log, build_log)
        copied_artifacts.append(build_log)
    if workspace_sha.exists():
        shutil.copy2(workspace_sha, sha_path)
        copied_artifacts.append(sha_path)

    manifest_path = None
    if build_report_data.get("build_success") and kernel_path.exists():
        manifest_path = _write_toyos_shadow_manifest(task_packet, artifact_dir, copied_artifacts)
        copied_artifacts.append(manifest_path)

    handoff = {
        "handoff_id": f"handoff-{task_packet['task_id']}-build",
        "task_id": task_packet["task_id"],
        "from_role": "builder",
        "to_role": "runner",
        "status": "success" if build_report_data.get("build_success") else "failed",
        "payload": {
            "artifact_path": str(kernel_path),
            "artifact_paths": [str(path) for path in copied_artifacts],
            "build_report_path": str(build_report if build_report.exists() else workspace_build_report),
            "shadow_workspace_path": str(workspace_dir),
            "build_command": "build_toy_os.py --target <shadow workspace>",
            "run_mode": "build_acceptance_only",
        },
        "notes": [
            "ToyOS shadow build completed",
            f"source_project={source_project}",
            f"build_success={bool(build_report_data.get('build_success'))}",
        ],
        "created_at": utc_now(),
    }
    _record_role_state(
        "builder",
        "build_execute",
        task_packet["task_id"],
        status="success" if build_report_data.get("build_success") else "failed",
        outputs=[str(path) for path in copied_artifacts],
    )
    return handoff


def builder_step(task_packet: dict[str, Any], roles: RoleRegistry) -> dict[str, Any]:
    roles.assert_allowed("builder", "build_execute")

    artifact_dir = Path(task_packet["input_spec"]["artifact_out_dir"])
    assert_shadow_path(str(artifact_dir))
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if task_packet["input_spec"].get("build_profile") == "toy_os_build_only":
        return _build_toyos_shadow_task(task_packet, artifact_dir)

    build_report = artifact_dir / "build-report.json"
    artifact_file = artifact_dir / "dummy-artifact.txt"

    artifact_file.write_text("shadow build output\n", encoding="utf-8")
    write_json(
        build_report,
        {
            "task_id": task_packet["task_id"],
            "status": "pass",
            "build_success": True,
            "build_ready": True,
            "built_at": utc_now(),
            "shadow_mode": True,
        },
    )

    handoff = {
        "handoff_id": f"handoff-{task_packet['task_id']}-build",
        "task_id": task_packet["task_id"],
        "from_role": "builder",
        "to_role": "runner",
        "status": "success",
        "payload": {
            "artifact_path": str(artifact_file),
            "build_report_path": str(build_report),
            "suggested_run_command": "type dummy-artifact.txt",
        },
        "notes": [
            "shadow build completed"
        ],
        "created_at": utc_now(),
    }
    _record_role_state(
        "builder",
        "build_execute",
        task_packet["task_id"],
        status="success",
        outputs=[str(artifact_file), str(build_report)],
    )
    return handoff


def runner_step(build_handoff: dict[str, Any], roles: RoleRegistry) -> dict[str, Any]:
    roles.assert_allowed("runner", "shell_execute")

    artifact_path = Path(build_handoff["payload"]["artifact_path"])
    assert_shadow_path(str(artifact_path))
    execution_report = artifact_path.parent / "execution-report.json"

    artifact_paths = build_handoff["payload"].get("artifact_paths", [build_handoff["payload"]["artifact_path"]])
    run_mode = build_handoff["payload"].get("run_mode", "generic")

    report_payload = {
        "task_id": build_handoff["task_id"],
        "executed_at": utc_now(),
        "artifact_checked": str(artifact_path),
        "shadow_mode": True,
        "run_mode": run_mode,
    }
    if run_mode == "build_acceptance_only":
        build_report_path = Path(build_handoff["payload"]["build_report_path"])
        build_report = _load_json(build_report_path, {})
        report_payload["acceptance_checks"] = {
            "build_report_exists": build_report_path.exists(),
            "build_success": bool(build_report.get("build_success")),
            "build_ready": bool(build_report.get("build_ready")),
            "artifact_exists": artifact_path.exists(),
        }
    acceptance_checks = report_payload.get("acceptance_checks", {})
    run_passed = all(bool(value) for value in acceptance_checks.values()) if acceptance_checks else build_handoff["status"] == "success"
    report_payload["status"] = "pass" if run_passed else "failed"

    write_json(execution_report, report_payload)

    handoff = {
        "handoff_id": f"handoff-{build_handoff['task_id']}-run",
        "task_id": build_handoff["task_id"],
        "from_role": "runner",
        "to_role": "auditor",
        "status": "success" if run_passed else "failed",
        "payload": {
            "build_report_path": build_handoff["payload"]["build_report_path"],
            "execution_report_path": str(execution_report),
            "artifact_paths": artifact_paths,
        },
        "notes": [
            "shadow run completed"
        ],
        "created_at": utc_now(),
    }
    _record_role_state(
        "runner",
        "shell_execute",
        build_handoff["task_id"],
        status="success",
        outputs=[str(execution_report)],
    )
    return handoff


def auditor_step(
    task_packet: dict[str, Any],
    run_handoff: dict[str, Any],
    roles: RoleRegistry,
    validator: ContractValidator,
) -> dict[str, Any]:
    roles.assert_allowed("auditor", "audit_score")
    record = audit_task(task_packet, run_handoff)
    validator.validate("audit_record.schema.json", record)
    _record_role_state(
        "auditor",
        "audit_score",
        task_packet["task_id"],
        status=record["verdict"],
        outputs=[],
    )
    return record


def run_pipeline(task_packet: dict[str, Any]) -> dict[str, Any]:
    validator = ContractValidator(SCHEMA_DIR)
    roles = RoleRegistry(POLICY_PATH)

    validator.validate("task.schema.json", task_packet)
    _record_pipeline_state(task_packet, "dispatched")

    build_handoff = builder_step(task_packet, roles)
    validator.validate("handoff.schema.json", build_handoff)
    write_json(SHADOW / "handoffs" / f"{build_handoff['handoff_id']}.json", build_handoff)
    _record_pipeline_state(task_packet, "built", extra={"handoff_id": build_handoff["handoff_id"]})

    run_handoff = runner_step(build_handoff, roles)
    validator.validate("handoff.schema.json", run_handoff)
    write_json(SHADOW / "handoffs" / f"{run_handoff['handoff_id']}.json", run_handoff)
    _record_pipeline_state(task_packet, "ran", extra={"handoff_id": run_handoff["handoff_id"]})

    audit_record = auditor_step(task_packet, run_handoff, roles, validator)
    write_json(SHADOW / "audit" / f"{audit_record['audit_id']}.json", audit_record)
    _record_pipeline_state(
        task_packet,
        "passed" if audit_record["verdict"] == "pass" else "failed",
        extra={"audit_id": audit_record["audit_id"], "verdict": audit_record["verdict"]},
    )

    return audit_record


def _load_task_packet(task_file: Path) -> dict[str, Any]:
    with task_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the static shadow pipeline")
    parser.add_argument("--task-file", type=Path, help="Path to a task packet JSON file")
    args = parser.parse_args()

    if args.task_file:
        task_packet = _load_task_packet(args.task_file)
    else:
        task_packet = {
            "task_id": "task-shadow-demo-0001",
            "goal_id": "goal-shadow-demo",
            "task_type": "build",
            "owner_role": "builder",
            "input_spec": {
                "project_path": r"D:\codex\generated\toy-os-demo",
                "build_command": "make all",
                "artifact_out_dir": r"D:\codex\orchestrator-mvp\shadow_factory\artifacts\task-shadow-demo-0001",
            },
            "expected_outputs": [
                "dummy-artifact.txt",
                "build-report.json"
            ],
            "acceptance_checks": [
                "build report exists",
                "artifact exists"
            ],
            "upstream_task_id": None,
            "artifact_scope": "shadow_only",
            "shadow_mode": True,
            "created_at": utc_now(),
        }

    result = run_pipeline(task_packet)
    print(json.dumps(result, ensure_ascii=False, indent=2))
