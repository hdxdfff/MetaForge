from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.io_utils import atomic_write_json, atomic_write_text
from tools.strategy_engine import refresh_strategy_memory

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT.parent / "generated"
RUNTIME_TASKS = ROOT / "factory" / "runtime" / "tasks"
ARTIFACT_REGISTRY = DATA / "artifact_registry.json"
REALITY_DASHBOARD = DATA / "reality_dashboard.json"
TASKS = DATA / "tasks.json"
TASK_HISTORY = DATA / "task_history.json"
TASK_CHECKPOINTS = DATA / "task_checkpoints.json"
CONTROL = DATA / "control_layer_status.json"
USAGE = DATA / "usage_tracker.json"
PRODUCTION_FOCUS = DATA / "production_focus_status.json"
RELEASES = DATA / "release_records.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _read_json(path: Path, default: Any) -> tuple[Any, str | None]:
    if not path.exists():
        return default, None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except Exception as exc:
        return default, f"{type(exc).__name__}: {exc}"


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def _task_timestamp(task: dict[str, Any]) -> datetime | None:
    if not isinstance(task, dict):
        return None
    return _parse_ts(task.get("updated_at") or task.get("created_at"))


def _checkpoint_timestamp(checkpoint: dict[str, Any]) -> datetime | None:
    if not isinstance(checkpoint, dict):
        return None
    return _parse_ts(checkpoint.get("updated_at") or checkpoint.get("created_at"))


def _latest_task_view(tasks: list[dict[str, Any]], task_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    min_time = datetime.min.replace(tzinfo=timezone.utc)
    for source in (task_history, tasks):
        for item in source:
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("id") or "").strip()
            if not task_id:
                anonymous.append(item)
                continue
            existing = merged.get(task_id)
            existing_time = _task_timestamp(existing) if existing else None
            item_time = _task_timestamp(item)
            if existing is None or (item_time or min_time) >= (existing_time or min_time):
                merged[task_id] = item
    return list(merged.values()) + anonymous


def _execution_evidence_payload(task_id: str) -> dict[str, Any]:
    if not task_id:
        return {}
    payload, _ = _read_json(RUNTIME_TASKS / task_id / "execution-evidence.json", {})
    return payload if isinstance(payload, dict) else {}


def _task_has_verified_completion(task: dict[str, Any]) -> bool:
    if not isinstance(task, dict) or str(task.get("status") or "").strip().lower() not in {"completed", "delivery_ready", "released"}:
        return False
    result = task.get("result")
    if isinstance(result, dict):
        production_evidence = result.get("production_evidence")
        if isinstance(production_evidence, dict) and str(production_evidence.get("status") or "").strip().lower() == "verified":
            return True
    task_id = str(task.get("id") or "").strip()
    payload = _execution_evidence_payload(task_id)
    return bool(payload.get("completed") and (payload.get("steps") or []))


def summarize_verified_completed_tasks(
    tasks: list[dict[str, Any]],
    task_history: list[dict[str, Any]],
    *,
    hours: int = 24,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    verified: list[dict[str, Any]] = []
    unverified_count = 0
    for item in _latest_task_view(tasks, task_history):
        task_id = str(item.get("id") or "").strip()
        ts = _task_timestamp(item)
        if not task_id or ts is None or ts < cutoff or str(item.get("status") or "").strip().lower() not in {"completed", "delivery_ready", "released"}:
            continue
        if _task_has_verified_completion(item):
            verified.append(item)
        else:
            unverified_count += 1
    return {
        "verified_completed_tasks_last_24h": len(verified),
        "verified_completed_task_ids": [str(item.get("id") or "") for item in verified if item.get("id")],
        "unverified_completed_tasks_last_24h": unverified_count,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_sha256_file(target: Path, digest: str) -> None:
    atomic_write_text(target.parent / "artifact.sha256", f"{digest}  {target.name}\n")


def _manifest_path(artifact_dir: Path) -> Path:
    return artifact_dir / "artifact_manifest.json"


def _report_timestamp(payload: Any, *keys: str) -> datetime | None:
    if not isinstance(payload, dict):
        return None
    values = [_parse_ts(payload.get(key)) for key in keys]
    candidates = [item for item in values if item is not None]
    return max(candidates) if candidates else None


def _latest_timestamp(*values: datetime | None) -> datetime | None:
    candidates = [item for item in values if item is not None]
    return max(candidates) if candidates else None


def _iso_timestamp(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _path_timestamp(path: Path) -> datetime | None:
    if not path.exists():
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except Exception:
        return None


def _default_manifest(artifact_dir: Path) -> dict[str, Any]:
    return {
        "artifact_id": artifact_dir.name,
        "type": "unknown",
        "version": "0.1",
        "buildable": False,
        "runnable": False,
        "test_passed": False,
        "reproducible": False,
        "artifact_path": str(artifact_dir),
        "entrypoint": None,
        "evidence": [],
        "notes": "Backfilled by production audit. Update this manifest before claiming a real artifact.",
    }


def ensure_manifest(
    artifact_dir: Path,
    *,
    defaults: dict[str, Any] | None = None,
    overwrite_missing_only: bool = True,
) -> dict[str, Any]:
    manifest_path = _manifest_path(artifact_dir)
    payload = _default_manifest(artifact_dir)
    if defaults:
        payload.update(defaults)
    if manifest_path.exists():
        current, _ = _read_json(manifest_path, payload)
        if isinstance(current, dict):
            if overwrite_missing_only and defaults:
                for key, value in defaults.items():
                    current.setdefault(key, value)
            else:
                current.update(defaults or {})
            payload = current
    atomic_write_json(manifest_path, payload)
    return payload



def _artifact_value_assessment(
    artifact_dir: Path,
    manifest: dict[str, Any],
    checks: dict[str, Any],
    *,
    real: bool,
) -> dict[str, Any]:
    focus_raw, _ = _read_json(PRODUCTION_FOCUS, {})
    focus = focus_raw if isinstance(focus_raw, dict) else {}
    releases_raw, _ = _read_json(RELEASES, [])
    releases = releases_raw if isinstance(releases_raw, list) else []
    value = manifest.get("value") or {}
    if not isinstance(value, dict):
        value = {}

    artifact_id = str(manifest.get("artifact_id") or artifact_dir.name).strip()
    artifact_type = str(manifest.get("type") or "unknown").strip().lower()
    notes = str(manifest.get("notes") or "").strip()
    focus_artifact_id = str(focus.get("primary_artifact_id") or "").strip().lower()
    target_user = str(value.get("target_user") or manifest.get("target_user") or "").strip()
    job_to_be_done = str(value.get("job_to_be_done") or value.get("job") or manifest.get("job_to_be_done") or "").strip()
    delivery_target = str(value.get("delivery_target") or value.get("delivery_path") or manifest.get("delivery_target") or "").strip()

    focus_match = bool(focus_artifact_id and artifact_id.lower() == focus_artifact_id)
    delivery_contract = bool(target_user and (job_to_be_done or delivery_target))
    durable_type = artifact_type not in {"unknown", "prototype"}
    internal_only = artifact_type in {"internal", "recovery"} or "internal recovery" in notes.lower()
    artifact_markers = {
        artifact_id.lower(),
        artifact_dir.name.lower(),
        str(manifest.get("entrypoint") or "").strip().lower(),
    }
    release_linked = False
    for item in releases:
        if str(item.get("status") or "").strip().lower() == "archived":
            continue
        artifacts = [str(entry).strip().lower() for entry in (item.get("artifacts") or []) if str(entry).strip()]
        if any(marker and any(marker in artifact for artifact in artifacts) for marker in artifact_markers):
            release_linked = True
            break
    value_sources: list[str] = []
    if focus_match:
        value_sources.append("production_focus")
    if release_linked:
        value_sources.append("release_candidate")
    if delivery_contract:
        value_sources.append("manifest_value_contract")

    valuable = bool(
        real
        and durable_type
        and not internal_only
        and value_sources
    )
    return {
        "valuable": valuable,
        "value_sources": value_sources,
        "focus_match": focus_match,
        "delivery_contract": delivery_contract,
        "release_linked": release_linked,
        "target_user": target_user or None,
        "job_to_be_done": job_to_be_done or None,
        "delivery_target": delivery_target or None,
        "internal_only": internal_only,
    }



def _evidence_checks(artifact_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    entrypoint = manifest.get("entrypoint")
    entrypoint_path = artifact_dir / str(entrypoint) if entrypoint else None
    evidence_items = [str(item) for item in (manifest.get("evidence") or []) if str(item).strip()]
    evidence_paths = [artifact_dir / item for item in evidence_items]
    existing_evidence = [path for path in evidence_paths if path.exists()]
    missing_evidence = [_safe_rel(path, artifact_dir) for path in evidence_paths if not path.exists()]

    build_report_path = artifact_dir / "build-report.json"
    build_report, build_report_error = _read_json(build_report_path, {})
    test_report_path = artifact_dir / "test-report.json"
    test_report, test_report_error = _read_json(test_report_path, {})
    execution_report_path = artifact_dir / "execution-report.json"
    execution_report, execution_report_error = _read_json(execution_report_path, {})
    qemu_report_path = artifact_dir / "build" / "generic-qemu-smoke-report.json"
    qemu_report, qemu_report_error = _read_json(qemu_report_path, {})

    qemu_all_passed = bool(qemu_report and qemu_report.get("all_passed"))
    build_success = bool(build_report.get("build_success"))
    build_ready = bool(build_report.get("build_ready"))
    generic_test_passed = bool(
        test_report
        and (
            test_report.get("all_passed")
            or test_report.get("passed")
            or str(test_report.get("status") or "").strip().lower() in {"pass", "passed", "ok", "completed"}
        )
    )
    execution_exit_code = (execution_report or {}).get("exit_code") if isinstance(execution_report, dict) else None
    execution_exit_ok = True
    if execution_exit_code is not None:
        try:
            execution_exit_ok = int(execution_exit_code) == 0
        except Exception:
            execution_exit_ok = False
    generic_execution_passed = bool(
        execution_report
        and execution_exit_ok
        and (
            execution_report.get("executed")
            or execution_report.get("success")
            or str(execution_report.get("status") or "").strip().lower() in {"pass", "passed", "ok", "completed"}
        )
    )

    build_timestamp = _report_timestamp(build_report, "build_timestamp", "built_at", "updated_at", "created_at") or _path_timestamp(build_report_path)
    test_timestamp = _report_timestamp(test_report, "test_timestamp", "tested_at", "updated_at", "created_at") or _path_timestamp(test_report_path)
    execution_timestamp = _report_timestamp(execution_report, "execution_timestamp", "executed_at", "updated_at", "created_at") or _path_timestamp(execution_report_path)
    qemu_timestamp = _report_timestamp(qemu_report, "updated_at", "run_at", "created_at") or _path_timestamp(qemu_report_path)
    latest_evidence_at = _latest_timestamp(build_timestamp, test_timestamp, execution_timestamp, qemu_timestamp)

    dockerfile = artifact_dir / "Dockerfile.build"
    build_script = artifact_dir / "build.sh"
    reproducibility_assets = [path for path in [dockerfile, build_script] if path.exists()]

    sha_target = entrypoint_path if entrypoint_path and entrypoint_path.exists() else None
    if sha_target is not None:
        digest = _sha256(sha_target)
        _write_sha256_file(sha_target, digest)
    else:
        digest = None

    return {
        "entrypoint_exists": bool(entrypoint_path and entrypoint_path.exists()),
        "entrypoint_path": str(entrypoint_path) if entrypoint_path else None,
        "existing_evidence": [_safe_rel(path, artifact_dir) for path in existing_evidence],
        "missing_evidence": missing_evidence,
        "build_report_exists": build_report_path.exists(),
        "build_report_error": build_report_error,
        "build_success": build_success,
        "build_ready": build_ready,
        "test_report_exists": test_report_path.exists(),
        "test_report_error": test_report_error,
        "generic_test_passed": generic_test_passed,
        "execution_report_exists": execution_report_path.exists(),
        "execution_report_error": execution_report_error,
        "generic_execution_passed": generic_execution_passed,
        "qemu_report_exists": qemu_report_path.exists(),
        "qemu_report_error": qemu_report_error,
        "qemu_all_passed": qemu_all_passed,
        "build_timestamp": _iso_timestamp(build_timestamp),
        "test_timestamp": _iso_timestamp(test_timestamp),
        "execution_timestamp": _iso_timestamp(execution_timestamp),
        "qemu_timestamp": _iso_timestamp(qemu_timestamp),
        "latest_evidence_at": _iso_timestamp(latest_evidence_at),
        "reproducibility_assets": [_safe_rel(path, artifact_dir) for path in reproducibility_assets],
        "reproducibility_assets_present": bool(reproducibility_assets),
        "sha256_generated": bool(digest),
        "sha256": digest,
    }


def evaluate_artifact(artifact_dir: Path) -> dict[str, Any]:
    manifest_path = _manifest_path(artifact_dir)
    manifest, manifest_error = _read_json(manifest_path, _default_manifest(artifact_dir))
    manifest_present = manifest_path.exists()
    if not isinstance(manifest, dict):
        manifest = _default_manifest(artifact_dir)
        manifest_error = manifest_error or "manifest-not-a-dict"

    checks = _evidence_checks(artifact_dir, manifest)
    declared_buildable = bool(manifest.get("buildable"))
    declared_runnable = bool(manifest.get("runnable"))
    declared_test_passed = bool(manifest.get("test_passed"))
    declared_reproducible = bool(manifest.get("reproducible"))

    buildable = bool(declared_buildable and checks["build_success"])
    runnable = bool(
        declared_runnable
        and (
            checks["qemu_all_passed"]
            or checks["generic_execution_passed"]
            or any("execution" in item or "boot" in item for item in checks["existing_evidence"])
        )
    )
    test_passed = bool(declared_test_passed and (checks["qemu_all_passed"] or checks["generic_test_passed"]))
    reproducible = bool(declared_reproducible and checks["reproducibility_assets_present"])
    real = bool(buildable and runnable and test_passed and reproducible)
    value = _artifact_value_assessment(artifact_dir, manifest, checks, real=real)

    issues: list[str] = []
    if not manifest_present:
        issues.append("manifest-missing")
    if manifest_error:
        issues.append(f"manifest-error:{manifest_error}")
    if declared_buildable and not buildable:
        issues.append("buildable-claim-without-build-proof")
    if declared_runnable and not runnable:
        issues.append("runnable-claim-without-runtime-proof")
    if declared_test_passed and not test_passed:
        issues.append("test-pass-claim-without-test-proof")
    if declared_reproducible and not reproducible:
        issues.append("reproducible-claim-without-repro-assets")
    if checks["missing_evidence"]:
        issues.append("evidence-missing")

    return {
        "artifact_id": manifest.get("artifact_id") or artifact_dir.name,
        "type": manifest.get("type") or "unknown",
        "version": manifest.get("version") or "0.1",
        "artifact_path": str(artifact_dir),
        "entrypoint": manifest.get("entrypoint"),
        "manifest_present": manifest_present,
        "real": real,
        "status": "real" if real else "prototype",
        "delivery_status": "valuable" if value.get("valuable") else "technical_only" if real else "prototype",
        "declared": {
            "buildable": declared_buildable,
            "runnable": declared_runnable,
            "test_passed": declared_test_passed,
            "reproducible": declared_reproducible,
        },
        "verified": {
            "buildable": buildable,
            "runnable": runnable,
            "test_passed": test_passed,
            "reproducible": reproducible,
        },
        "value": value,
        "checks": checks,
        "issues": issues,
    }


def _artifact_dirs() -> list[Path]:
    if not GENERATED.exists():
        return []
    return sorted(path for path in GENERATED.iterdir() if path.is_dir())


def audit_artifacts(*, write_outputs: bool = True) -> dict[str, Any]:
    artifacts = [evaluate_artifact(path) for path in _artifact_dirs()]
    real_artifacts = [item for item in artifacts if item.get("real")]
    valuable_artifacts = [item for item in artifacts if (item.get("value") or {}).get("valuable")]
    prototype_artifacts = [item for item in artifacts if not item.get("real")]
    base_payload = {
        "updated_at": _utc(),
        "artifact_count": len(artifacts),
        "real_artifact_count": len(real_artifacts),
        "valuable_artifact_count": len(valuable_artifacts),
        "prototype_artifact_count": len(prototype_artifacts),
        "status": "pass" if valuable_artifacts else "attention" if artifacts else "empty",
        "artifacts": artifacts,
        "issues": [
            {"artifact_id": item.get("artifact_id"), "issues": item.get("issues")}
            for item in artifacts
            if item.get("issues")
        ],
    }
    strategy_learning = refresh_strategy_memory(base_payload, write_outputs=write_outputs)
    payload = {
        **base_payload,
        "strategy_learning": strategy_learning.get("status", {}),
    }
    if write_outputs:
        atomic_write_json(ARTIFACT_REGISTRY, payload)
    return payload

def _recent_task_metrics() -> dict[str, Any]:
    history_raw, history_error = _read_json(TASK_HISTORY, [])
    history = history_raw if isinstance(history_raw, list) else []
    checkpoints_raw, checkpoints_error = _read_json(TASK_CHECKPOINTS, {})
    checkpoints = checkpoints_raw if isinstance(checkpoints_raw, dict) else {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    verified_completed_task_ids: list[str] = []
    seen_task_ids: set[str] = set()

    for item in history:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or item.get("id") or "").strip()
        if not task_id or task_id in seen_task_ids:
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in {"completed", "released"}:
            continue
        ts = _task_timestamp(item)
        if ts is None or ts < cutoff:
            continue
        verified_completed_task_ids.append(task_id)
        seen_task_ids.add(task_id)

    for task_id, item in checkpoints.items():
        if not isinstance(item, dict):
            continue
        task_id = str(task_id or item.get("task_id") or item.get("id") or "").strip()
        if not task_id or task_id in seen_task_ids:
            continue
        status = str(item.get("task_status") or item.get("status") or "").strip().lower()
        if status not in {"completed", "released", "verification-passed"}:
            continue
        ts = _checkpoint_timestamp(item)
        if ts is None or ts < cutoff:
            continue
        verified_completed_task_ids.append(task_id)
        seen_task_ids.add(task_id)

    return {
        "completed_tasks_last_24h": len(verified_completed_task_ids),
        "verified_completed_tasks_last_24h": len(verified_completed_task_ids),
        "verified_completed_task_ids": verified_completed_task_ids,
        "unverified_completed_tasks_last_24h": 0,
        "tasks_parse_error": None,
        "task_history_parse_error": history_error,
        "task_checkpoints_parse_error": checkpoints_error,
        "tasks_source": "task_history+task_checkpoints",
    }


def _llm_metrics() -> dict[str, Any]:
    usage_raw, usage_error = _read_json(USAGE, {})
    control_raw, control_error = _read_json(CONTROL, {})
    recent_window = (((control_raw or {}).get("resource_governor") or {}).get("usage") or {}).get("recent_window")
    if not recent_window:
        recent_window = (((control_raw or {}).get("daemon") or {}).get("last_result") or {}).get("guard", {}).get("usage", {}).get("recent_window", {})
    return {
        "usage_parse_error": usage_error,
        "control_parse_error": control_error,
        "cheap_calls": int((recent_window or {}).get("cheap_calls", (usage_raw or {}).get("cheap_calls", 0)) or 0),
        "reasoning_calls": int((recent_window or {}).get("reasoning_calls", (usage_raw or {}).get("reasoning_calls", 0)) or 0),
        "strong_calls": int((recent_window or {}).get("strong_calls", (usage_raw or {}).get("strong_calls", 0)) or 0),
        "source_window_hours": int((recent_window or {}).get("hours", 24) or 24),
    }


def _focus_metrics(registry: dict[str, Any]) -> dict[str, Any]:
    focus_raw, focus_error = _read_json(PRODUCTION_FOCUS, {})
    if not isinstance(focus_raw, dict):
        focus_raw = {}
    focus_enabled = bool(focus_raw.get("single_product_mode"))
    focus_artifact_id = str(focus_raw.get("primary_artifact_id") or "").strip()
    focus_target = str(focus_raw.get("primary_target") or "").strip()
    focus_artifact = next(
        (item for item in (registry.get("artifacts") or []) if str(item.get("artifact_id") or "").strip() == focus_artifact_id),
        None,
    )
    focus_artifact_real = bool(focus_artifact and focus_artifact.get("real"))
    focus_artifact_valuable = bool(focus_artifact and ((focus_artifact.get("value") or {}).get("valuable")))
    return {
        "enabled": focus_enabled,
        "reason": str(focus_raw.get("reason") or "").strip(),
        "focus_error": focus_error,
        "artifact_id": focus_artifact_id,
        "target": focus_target,
        "artifact_real": focus_artifact_real,
        "artifact_valuable": focus_artifact_valuable,
    }


def build_reality_dashboard(*, write_outputs: bool = True) -> dict[str, Any]:
    registry = audit_artifacts(write_outputs=write_outputs)
    task_metrics = _recent_task_metrics()
    llm_metrics = _llm_metrics()
    focus_metrics = _focus_metrics(registry)
    strategy_metrics = (registry.get("strategy_learning") or {}) if isinstance(registry, dict) else {}
    completed_tasks = int(task_metrics["completed_tasks_last_24h"] or 0)
    technical_real_artifacts = int(registry["real_artifact_count"] or 0)
    valuable_artifacts = int(registry.get("valuable_artifact_count", 0) or 0)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_technical_real_artifacts = [
        item
        for item in registry.get("artifacts", [])
        if item.get("real")
        and ((_parse_ts(((item.get("checks") or {}).get("latest_evidence_at"))) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff)
    ]
    recent_real_artifacts = [
        item
        for item in recent_technical_real_artifacts
        if (item.get("value") or {}).get("valuable")
    ]
    recent_real_count = len(recent_real_artifacts)
    technical_conversion_rate = round((len(recent_technical_real_artifacts) / completed_tasks) * 100.0, 2) if completed_tasks else 0.0
    value_conversion_rate = round((recent_real_count / completed_tasks) * 100.0, 2) if completed_tasks else 0.0
    bootstrap_success = bool(focus_metrics["artifact_id"] and focus_metrics["artifact_valuable"])

    payload = {
        "updated_at": _utc(),
        "status": "pass" if (technical_conversion_rate >= 5.0 and technical_real_artifacts > 0) or bootstrap_success else "attention",
        "products_real": valuable_artifacts,
        "technical_real_artifacts": technical_real_artifacts,
        "artifacts_total": int(registry["artifact_count"] or 0),
        "artifacts_prototype": int(registry["prototype_artifact_count"] or 0),
        "reproducible_real": sum(
            1 for item in registry.get("artifacts", [])
            if (item.get("verified") or {}).get("reproducible") and (item.get("value") or {}).get("valuable")
        ),
        "tasks_completed_last_24h": completed_tasks,
        "artifacts_produced_last_24h": max(recent_real_count, len(recent_technical_real_artifacts)),
        "technical_artifacts_produced_last_24h": len(recent_technical_real_artifacts),
        "conversion_rate": technical_conversion_rate,
        "technical_conversion_rate": technical_conversion_rate,
        "value_conversion_rate": value_conversion_rate,
        "single_product_mode": focus_metrics["enabled"],
        "focus_artifact_id": focus_metrics["artifact_id"],
        "focus_reason": focus_metrics["reason"],
        "focus_target": focus_metrics["target"],
        "focus_artifact_real": focus_metrics["artifact_real"],
        "focus_artifact_valuable": focus_metrics["artifact_valuable"],
        "bootstrap_success": bootstrap_success,
        "llm_throughput": llm_metrics,
        "strategy": {
            "revision": strategy_metrics.get("revision", 0),
            "pattern_count": strategy_metrics.get("pattern_count", 0),
            "active_pattern_count": strategy_metrics.get("active_pattern_count", 0),
            "reuse_success_rate": strategy_metrics.get("reuse_success_rate", 0.0),
            "valuable_artifact_ratio": strategy_metrics.get("valuable_artifact_ratio", 0.0),
            "pattern_score_variance": strategy_metrics.get("pattern_score_variance", 0.0),
            "top_patterns": strategy_metrics.get("top_patterns", []),
        },
        "data_quality": {
            "tasks_parse_error": task_metrics.get("tasks_parse_error"),
            "task_history_parse_error": task_metrics.get("task_history_parse_error"),
            "usage_parse_error": llm_metrics.get("usage_parse_error"),
            "control_parse_error": llm_metrics.get("control_parse_error"),
            "production_focus_parse_error": focus_metrics.get("focus_error"),
            "unverified_completed_tasks_last_24h": task_metrics.get("unverified_completed_tasks_last_24h", 0),
        },
        "registry": {
            "status": registry.get("status"),
            "issue_count": len(registry.get("issues", [])),
        },
        "verified_completed_task_ids": task_metrics.get("verified_completed_task_ids", []),
        "recent_real_artifact_ids": [item.get("artifact_id") for item in recent_real_artifacts],
        "recent_technical_real_artifact_ids": [item.get("artifact_id") for item in recent_technical_real_artifacts],
        "top_issues": registry.get("issues", [])[:10],
    }
    if write_outputs:
        atomic_write_json(REALITY_DASHBOARD, payload)
    return payload


def _artifact_observed_at(path: Path) -> datetime:
    if path.suffix.lower() == ".json":
        payload, _ = _read_json(path, {})
        observed = _latest_timestamp(
            _report_timestamp(payload, "execution_timestamp", "executed_at"),
            _report_timestamp(payload, "test_timestamp", "tested_at"),
            _report_timestamp(payload, "build_timestamp", "built_at"),
            _report_timestamp(payload, "updated_at", "created_at"),
        )
        if observed is not None:
            return observed
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def validate_release_payload(repo_path: str | None, artifacts: list[str] | None) -> dict[str, Any]:
    repo_root = Path(repo_path) if repo_path else None
    artifact_items = [str(item) for item in (artifacts or []) if str(item).strip()]
    existing: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in artifact_items:
        path = (repo_root / item) if repo_root and not Path(item).is_absolute() else Path(item)
        if path.exists():
            existing.append({"path": str(path), "size": path.stat().st_size})
        else:
            missing.append(item)
    return {
        "artifact_count": len(artifact_items),
        "existing_count": len(existing),
        "missing_count": len(missing),
        "existing": existing,
        "missing": missing,
        "passed": bool(artifact_items and not missing),
    }


def validate_task_artifact_completion(
    *,
    repo_root: Path,
    artifact_spec: dict[str, Any] | None,
    created_at: datetime,
) -> dict[str, Any]:
    if not artifact_spec:
        raise ValueError("Production task rejected: artifact_spec is required.")
    required = [str(item) for item in (artifact_spec.get("required_artifacts") or []) if str(item).strip()]
    if not required:
        raise ValueError("Production task rejected: artifact_spec.required_artifacts is empty.")

    fresh: list[dict[str, Any]] = []
    stale: list[str] = []
    missing: list[str] = []
    for item in required:
        path = repo_root / item
        if not path.exists():
            missing.append(item)
            continue
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        observed_at = _artifact_observed_at(path)
        artifact = {
            "path": str(path),
            "size": stat.st_size,
            "mtime": mtime.isoformat().replace("+00:00", "Z"),
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        }
        if observed_at >= created_at:
            fresh.append(artifact)
        else:
            stale.append(item)

    min_fresh = int(artifact_spec.get("min_fresh_artifacts") or len(required) or 1)
    if len(fresh) < min_fresh:
        raise ValueError(
            "Production evidence incomplete: "
            f"fresh={len(fresh)}/{min_fresh} missing={missing or ['none']} stale={stale or ['none']}"
        )
    return {
        "status": "verified",
        "artifact_spec": artifact_spec,
        "required_count": len(required),
        "min_fresh_artifacts": min_fresh,
        "fresh_artifacts": fresh,
        "stale_artifacts": stale,
        "missing_artifacts": missing,
    }


if __name__ == "__main__":
    print(json.dumps(build_reality_dashboard(write_outputs=True), ensure_ascii=False, indent=2))




