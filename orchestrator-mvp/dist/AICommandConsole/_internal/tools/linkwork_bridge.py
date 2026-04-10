from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_command(text: str | None) -> list[str]:
    if not text:
        return []
    return [part for part in shlex.split(text, posix=os.name != "nt") if part]


def _read_json_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        raw = _env_value("LINKWORK_JOB_JSON") or ""
    if not raw:
        raise SystemExit("linkwork bridge requires job JSON on stdin or LINKWORK_JOB_JSON")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("linkwork bridge expected a JSON object")
    return payload


def _job_path(job_spec: dict[str, Any]) -> Path | None:
    raw = _env_value("LINKWORK_JOB_PATH")
    if raw:
        return Path(raw)
    task_id = str(job_spec.get("task_id") or "linkwork-task").strip() or "linkwork-task"
    logs_dir = ROOT / "data" / "executor-logs"
    return logs_dir / f"{task_id}.linkwork.job.json"


def _target_command() -> list[str]:
    return [
        *_split_command(_env_value("LINKWORK_TARGET_COMMAND")),
        *_split_command(_env_value("LINKWORK_TARGET_ARGS")),
    ]


def _read_expected_outputs(job_spec: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = job_spec.get("expected_outputs")
    if isinstance(raw, list):
        values.extend(str(item).strip() for item in raw if str(item).strip())
    return list(dict.fromkeys(values))


def _normalize_result(result: dict[str, Any], job_spec: dict[str, Any], *, bridge_log: Path, dispatch_status: str) -> dict[str, Any]:
    summary = str(
        result.get("summary")
        or result.get("message")
        or result.get("text")
        or (
            "LinkWork bridge forwarded the job to an upstream command."
            if dispatch_status == "submitted"
            else "LinkWork bridge prepared the job locally."
        )
    ).strip()
    generated_files = result.get("generated_files")
    if generated_files is None and isinstance(result.get("outputs"), dict):
        generated_files = result["outputs"].get("generated_files")
    if generated_files is None:
        generated_files = _read_expected_outputs(job_spec)
    evidence_bundle = result.get("evidence_bundle")
    if evidence_bundle is None and isinstance(result.get("outputs"), dict):
        evidence_bundle = result["outputs"].get("evidence_bundle")
    if evidence_bundle is None:
        evidence_bundle = [str(bridge_log)]
    outputs = dict(result.get("outputs") or {})
    outputs.setdefault("generated_files", list(dict.fromkeys(str(item) for item in generated_files if str(item).strip())))
    outputs.setdefault("evidence_bundle", list(dict.fromkeys(str(item) for item in evidence_bundle if str(item).strip())))
    outputs.setdefault("logs_path", str(bridge_log))
    return {
        "status": "success",
        "dispatch_status": dispatch_status,
        "summary": summary,
        "generated_files": outputs["generated_files"],
        "evidence_bundle": outputs["evidence_bundle"],
        "outputs": outputs,
        "bridge_log_path": str(bridge_log),
    }


def _run_local(job_spec: dict[str, Any], *, job_path: Path | None) -> dict[str, Any]:
    bridge_log = (job_path or (ROOT / "data" / "executor-logs" / "linkwork.bridge.log")).with_suffix(".bridge.log")
    bridge_log.parent.mkdir(parents=True, exist_ok=True)
    generated_files = _read_expected_outputs(job_spec)
    evidence_bundle = [str(job_path)] if job_path else []
    evidence_bundle.append(str(bridge_log))
    bridge_log.write_text(
        json.dumps(
            {
                "mode": "local-fallback",
                "job_path": str(job_path) if job_path else None,
                "task_id": job_spec.get("task_id"),
                "workspace": job_spec.get("workspace"),
                "expected_outputs": generated_files,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "success",
        "dispatch_status": "prepared",
        "summary": "LinkWork bridge prepared the standardized handoff bundle locally.",
        "generated_files": generated_files,
        "evidence_bundle": list(dict.fromkeys(evidence_bundle)),
        "outputs": {
            "generated_files": generated_files,
            "evidence_bundle": list(dict.fromkeys(evidence_bundle)),
            "logs_path": str(bridge_log),
        },
        "bridge_log_path": str(bridge_log),
    }


def _run_target(job_spec: dict[str, Any], *, job_path: Path | None) -> dict[str, Any]:
    command = _target_command()
    if not command:
        return _run_local(job_spec, job_path=job_path)
    bridge_log = (job_path or (ROOT / "data" / "executor-logs" / "linkwork.bridge.log")).with_suffix(".run.log")
    bridge_log.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        command,
        cwd=str(Path(job_spec.get("workspace") or ROOT)),
        input=json.dumps(job_spec, ensure_ascii=False, indent=2),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=int(_env_value("LINKWORK_TARGET_TIMEOUT_SECONDS") or _env_value("ORCH_LINKWORK_TIMEOUT_SECONDS") or "1800"),
        env={
            **os.environ.copy(),
            "LINKWORK_JOB_PATH": str(job_path) if job_path else "",
            "LINKWORK_JOB_JSON": json.dumps(job_spec, ensure_ascii=False),
            "LINKWORK_TASK_ID": str(job_spec.get("task_id") or ""),
            "LINKWORK_WORKSPACE": str(job_spec.get("workspace") or ""),
        },
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    bridge_log.write_text(
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
        encoding="utf-8",
    )
    parsed: dict[str, Any] = {}
    for text in (stdout.strip(), stderr.strip()):
        if not text:
            continue
        try:
            candidate = json.loads(text)
        except Exception:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
            break
    normalized = _normalize_result(
        parsed,
        job_spec,
        bridge_log=bridge_log,
        dispatch_status="submitted" if completed.returncode == 0 else "failed",
    )
    normalized["outputs"]["logs_path"] = str(bridge_log)
    normalized["bridge_log_path"] = str(bridge_log)
    normalized["upstream_returncode"] = completed.returncode
    normalized["upstream_stdout"] = stdout
    normalized["upstream_stderr"] = stderr
    normalized["upstream_command"] = command
    return normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LinkWork execution bridge")
    parser.add_argument("--smoke", action="store_true", help="Emit a smoke response for the current job payload")
    args = parser.parse_args(argv)

    job_spec = _read_json_payload()
    job_path = _job_path(job_spec)
    if args.smoke or _target_command():
        result = _run_target(job_spec, job_path=job_path)
    else:
        result = _run_local(job_spec, job_path=job_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if str(result.get("status") or "").lower() == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
