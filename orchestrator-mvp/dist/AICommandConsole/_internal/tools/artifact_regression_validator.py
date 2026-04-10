from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT / "generated"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

OUTPUT = DATA / "artifact_regression_validation.json"
ARTIFACT_REGISTRY_PATH = DATA / "artifact_registry.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _artifact_dirs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    if not root.exists():
        return candidates
    for path in root.iterdir():
        if path.is_dir():
            candidates.append(path)
    return sorted(candidates, key=lambda item: item.name.lower())


def _artifact_registry_map() -> dict[str, dict[str, Any]]:
    registry = _load_json(ARTIFACT_REGISTRY_PATH, {})
    items = registry.get("artifacts") or []
    result: dict[str, dict[str, Any]] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            artifact_id = str(item.get("artifact_id") or "")
            if artifact_id:
                result[artifact_id] = item
    return result


def _validate_artifact_dir(path: Path, registry_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    manifest = _load_json(path / "artifact_manifest.json", {})
    entrypoint_name = manifest.get("entrypoint") if isinstance(manifest, dict) else None
    entrypoint = path / str(entrypoint_name) if entrypoint_name else None
    build_report = _load_json(path / "build-report.json", {})
    test_report = _load_json(path / "test-report.json", {})
    execution_report = _load_json(path / "execution-report.json", {})
    qemu_report = _load_json(path / "build" / "generic-qemu-smoke-report.json", {})
    if not qemu_report:
        qemu_report = _load_json(path / "generic-qemu-smoke-report.json", {})
    manifest_present = bool(manifest)
    entrypoint_exists = bool(entrypoint and entrypoint.exists())
    required_evidence = [
        "build-report.json",
        "test-report.json",
        "execution-report.json",
    ]
    if qemu_report:
        required_evidence.append("generic-qemu-smoke-report.json")
    existing_evidence = [name for name in required_evidence if (path / name).exists()]
    artifact_id = manifest.get("artifact_id") if isinstance(manifest, dict) else path.name
    registry_entry = registry_map.get(str(artifact_id) or "")
    registry_status = str((registry_entry or {}).get("status") or "").lower()
    registry_real = bool((registry_entry or {}).get("real"))
    if registry_entry is None and not manifest_present:
        return {
            "artifact_id": artifact_id if artifact_id else path.name,
            "artifact_path": str(path),
            "manifest_present": manifest_present,
            "entrypoint_exists": entrypoint_exists,
            "existing_evidence": existing_evidence,
            "build_success": None,
            "test_success": None,
            "execution_success": None,
            "qemu_success": None,
            "real": False,
            "status": "skipped",
            "issues": [],
            "sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
        }
    manifest_buildable = bool(manifest.get("buildable")) if isinstance(manifest, dict) else False
    manifest_runnable = bool(manifest.get("runnable")) if isinstance(manifest, dict) else False
    manifest_test_passed = bool(manifest.get("test_passed")) if isinstance(manifest, dict) else False
    manifest_reproducible = bool(manifest.get("reproducible")) if isinstance(manifest, dict) else False
    if registry_entry is not None and registry_status != "real" and not registry_real:
        return {
            "artifact_id": artifact_id,
            "artifact_path": str(path),
            "manifest_present": manifest_present,
            "entrypoint_exists": entrypoint_exists,
            "existing_evidence": existing_evidence,
            "build_success": None,
            "test_success": None,
            "execution_success": None,
            "qemu_success": None,
            "real": False,
            "status": "skipped",
            "issues": [],
            "sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
        }
    build_success = bool(
        build_report.get("build_success")
        or build_report.get("build_ready")
        or build_report.get("status") in {"pass", "completed", "success"}
        or build_report.get("ok")
        or manifest_buildable
    )
    test_success = bool(
        test_report.get("generic_test_passed")
        or test_report.get("all_passed")
        or test_report.get("passed")
        or test_report.get("status") in {"pass", "completed", "success"}
        or manifest_test_passed
    )
    execution_success = bool(
        execution_report.get("generic_execution_passed")
        or execution_report.get("success")
        or execution_report.get("executed")
        or execution_report.get("status") in {"pass", "completed", "success"}
        or int(execution_report.get("exit_code") or 1) == 0
        or manifest_runnable
    )
    qemu_success = True
    if qemu_report:
        qemu_success = bool(
            qemu_report.get("status") in {"pass", "completed", "success"}
            or qemu_report.get("all_passed")
            or all(bool(test.get("all_passed")) for test in (qemu_report.get("tests") or []))
        )
    reproducibility_assets = manifest.get("reproducibility_assets") if isinstance(manifest, dict) else []
    reproducible = bool(reproducibility_assets or manifest_reproducible)
    is_real = manifest_present and entrypoint_exists and build_success and test_success and execution_success and reproducible
    issues = []
    if not manifest_present:
        issues.append("manifest-missing")
    if not entrypoint_exists:
        issues.append("entrypoint-missing")
    if not build_success:
        issues.append("build-failed")
    if not test_success:
        issues.append("test-failed")
    if not execution_success:
        issues.append("execution-failed")
    if not reproducible:
        issues.append("reproducibility-assets-missing")
    return {
        "artifact_id": artifact_id if artifact_id else path.name,
        "artifact_path": str(path),
        "manifest_present": manifest_present,
        "entrypoint_exists": entrypoint_exists,
        "existing_evidence": existing_evidence,
        "build_success": build_success,
        "test_success": test_success,
        "execution_success": execution_success,
        "qemu_success": qemu_success if qemu_report else None,
        "real": is_real,
        "status": "pass" if is_real else "attention",
        "issues": issues,
        "sha256": manifest.get("sha256") if isinstance(manifest, dict) else None,
    }


def run_artifact_regression_validation(root: Path | None = None) -> dict[str, Any]:
    root = root or GENERATED
    registry_map = _artifact_registry_map()
    artifacts = [_validate_artifact_dir(path, registry_map) for path in _artifact_dirs(root)]
    validated = [item for item in artifacts if item.get("status") != "skipped"]
    failed = [item for item in validated if item.get("issues")]
    total = len(artifacts)
    validated_total = len(validated)
    fail_rate = round(len(failed) / validated_total, 4) if validated_total else 0.0
    payload = {
        "updated_at": _utc(),
        "status": "pass" if not failed else "attention",
        "artifact_count": total,
        "validated_count": validated_total,
        "real_count": sum(1 for item in validated if item.get("real")),
        "failed_count": len(failed),
        "fail_rate": fail_rate,
        "artifacts": artifacts,
        "failed_artifacts": failed,
        "skipped_count": total - validated_total,
    }
    atomic_write_json(OUTPUT, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated artifacts and refresh the regression report.")
    parser.add_argument("--root", default=str(GENERATED), help="Root directory to scan.")
    args = parser.parse_args()
    payload = run_artifact_regression_validation(Path(args.root))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
