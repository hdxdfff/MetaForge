from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SHADOW_ROOT = Path(r"D:\codex\orchestrator-mvp\shadow_factory").resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_exists(path_str: str | None) -> bool:
    if not path_str:
        return False
    return Path(path_str).exists()


def _load_json(path_str: str | None) -> dict:
    if not path_str or not Path(path_str).exists():
        return {}
    with Path(path_str).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def assert_shadow_path(path_str: str) -> None:
    resolved = Path(path_str).resolve()
    if SHADOW_ROOT not in [resolved, *resolved.parents]:
        raise ValueError(f"path outside shadow root: {resolved}")


def audit_task(task_packet: dict, run_handoff: dict) -> dict:
    payload = run_handoff.get("payload", {})
    build_report = payload.get("build_report_path")
    execution_report = payload.get("execution_report_path")
    artifact_paths = payload.get("artifact_paths", [])

    issues: list[str] = []

    if not task_packet.get("shadow_mode", False):
        issues.append("task is not running in shadow mode")
    if task_packet.get("artifact_scope") != "shadow_only":
        issues.append("artifact scope is not shadow_only")

    if build_report:
        try:
            assert_shadow_path(build_report)
        except ValueError as exc:
            issues.append(str(exc))
    if execution_report:
        try:
            assert_shadow_path(execution_report)
        except ValueError as exc:
            issues.append(str(exc))
    for artifact_path in artifact_paths:
        try:
            assert_shadow_path(artifact_path)
        except ValueError as exc:
            issues.append(str(exc))

    if not file_exists(build_report):
        issues.append("missing build_report")
    else:
        build_report_data = _load_json(build_report)
        if not build_report_data.get("build_success", False):
            issues.append("build report does not indicate success")
    if not file_exists(execution_report):
        issues.append("missing execution_report")
    else:
        execution_report_data = _load_json(execution_report)
        if execution_report_data.get("status") != "pass":
            issues.append("execution report does not indicate pass")

    missing_artifacts = [path for path in artifact_paths if not Path(path).exists()]
    if missing_artifacts:
        issues.append(f"missing artifacts: {missing_artifacts}")

    verdict = "pass" if not issues else "fail"
    score = 100 if verdict == "pass" else max(0, 100 - 20 * len(issues))

    return {
        "audit_id": f"audit-{task_packet['task_id']}",
        "task_id": task_packet["task_id"],
        "verdict": verdict,
        "score": score,
        "issues": issues,
        "evidence": {
            "build_report": build_report,
            "execution_report": execution_report,
            "artifact_paths": artifact_paths,
        },
        "reproducible": False,
        "shadow_mode": task_packet.get("shadow_mode", False),
        "audited_at": utc_now(),
    }
