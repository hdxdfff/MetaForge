from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.artifact_audit import evaluate_artifact
from tools.io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
GENERATED = ROOT.parent / "generated"
OUT = DATA / "pipeline_status.json"
PRODUCTION_FOCUS = DATA / "production_focus_status.json"
ENGINEERING_OS = DATA / "engineering_os.json"
AI_TESTING = DATA / "ai_testing.json"
VERIFICATION = DATA / "verification_status.json"
RELEASE_OPERATIONS = DATA / "release_operations_status.json"
RND_PIPELINE = DATA / "rnd_delivery_pipeline_status.json"
QUALITY_STATUS = DATA / "quality_status.json"
AUTONOMY_SCORE = DATA / "autonomy_score.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _primary_artifact_dir() -> Path:
    focus = _load_json(PRODUCTION_FOCUS, {})
    artifact_id = str((focus or {}).get("primary_artifact_id") or "toy-os-demo").strip()
    if not artifact_id:
        artifact_id = "toy-os-demo"
    candidate = Path(artifact_id)
    if candidate.is_absolute():
        return candidate
    return GENERATED / artifact_id


def _status_from_checks(*checks: bool) -> str:
    return "pass" if all(checks) else "attention"


def _gate_summary(name: str, status: str, detail: dict[str, Any], *, next_action: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "next_action": next_action,
    }


def build_pipeline_status(*, write_outputs: bool = True) -> dict[str, Any]:
    engineering_os = _load_json(ENGINEERING_OS, {})
    ai_testing = _load_json(AI_TESTING, {})
    verification = _load_json(VERIFICATION, {})
    release_ops = _load_json(RELEASE_OPERATIONS, {})
    rnd_pipeline = _load_json(RND_PIPELINE, {})
    quality_status = _load_json(QUALITY_STATUS, {})
    autonomy_score = _load_json(AUTONOMY_SCORE, {})

    artifact_dir = _primary_artifact_dir()
    artifact = evaluate_artifact(artifact_dir) if artifact_dir.exists() else {
        "artifact_path": str(artifact_dir),
        "real": False,
        "status": "prototype",
        "issues": ["artifact-dir-missing"],
        "checks": {},
        "verified": {},
        "manifest_present": False,
        "value": {},
    }
    artifact_checks = artifact.get("checks") or {}
    verified = artifact.get("verified") or {}

    ci_ok = _status_from_checks(
        str((engineering_os.get("engineering_os") or {}).get("status") or engineering_os.get("status") or "").lower() == "pass",
        str(ai_testing.get("status") or "").lower() == "pass",
        str(verification.get("status") or "").lower() == "pass",
        str((verification.get("patch_gate") or {}).get("status") or verification.get("patch_gate_status") or "").lower() == "pass",
    )
    ci_detail = {
        "engineering_os_status": (engineering_os.get("engineering_os") or {}).get("status") or engineering_os.get("status"),
        "ai_testing_status": ai_testing.get("status"),
        "verification_status": verification.get("status"),
        "patch_gate_status": (verification.get("patch_gate") or {}).get("status") or verification.get("patch_gate_status"),
    }

    cd_ok = _status_from_checks(
        bool(artifact.get("real")),
        bool(artifact.get("manifest_present")),
        bool(artifact_checks.get("build_report_exists")),
        bool(artifact_checks.get("qemu_report_exists")),
        bool(artifact_checks.get("sha256_generated")),
        bool(verified.get("buildable")),
        bool(verified.get("runnable")),
        bool(verified.get("test_passed")),
        bool(verified.get("reproducible")),
    )
    cd_detail = {
        "artifact_id": artifact.get("artifact_id"),
        "artifact_path": artifact.get("artifact_path"),
        "real": artifact.get("real"),
        "status": artifact.get("status"),
        "issues": artifact.get("issues", []),
        "build_report_exists": artifact_checks.get("build_report_exists"),
        "qemu_report_exists": artifact_checks.get("qemu_report_exists"),
        "manifest_present": artifact.get("manifest_present"),
        "sha256_generated": artifact_checks.get("sha256_generated"),
        "verified": verified,
        "latest_evidence_at": artifact_checks.get("latest_evidence_at"),
    }

    release_train = release_ops.get("release_train") or {}
    release_gate = release_ops.get("verification_release_gate") or {}
    release_ok = _status_from_checks(
        ci_ok == "pass",
        cd_ok == "pass",
        str(release_train.get("status") or "").lower() == "ready",
        str(release_gate.get("status") or "").lower() == "pass",
        not bool(release_gate.get("sample_failures")),
    )

    blocked_reasons: list[str] = []
    if ci_ok != "pass":
        blocked_reasons.append("ci")
    if cd_ok != "pass":
        blocked_reasons.append("cd")
    if str(release_train.get("status") or "").lower() != "ready":
        blocked_reasons.append("release_train")
    if str(release_gate.get("status") or "").lower() != "pass":
        blocked_reasons.append("release_gate")
    if bool(release_gate.get("sample_failures")):
        blocked_reasons.append("release_gate_samples")

    payload = {
        "contract": {
            "name": "ci_cd_pipeline_status",
            "version": "1.0",
            "gate_order": ["ci", "cd", "release"],
            "stable_fields": [
                "updated_at",
                "status",
                "contract",
                "primary_artifact",
                "ci",
                "cd",
                "release",
                "blocked_reasons",
                "recommendation",
                "control_snapshot",
                "evidence",
            ],
        },
        "updated_at": _utc(),
        "status": "pass" if release_ok == "pass" else "attention",
        "primary_artifact": {
            "artifact_dir": str(artifact_dir),
            "artifact": artifact,
        },
        "ci": _gate_summary(
            "ci",
            ci_ok,
            ci_detail,
            next_action="restore-validation-chain" if ci_ok != "pass" else "observe-only",
        ),
        "cd": _gate_summary(
            "cd",
            cd_ok,
            cd_detail,
            next_action="repair-primary-artifact" if cd_ok != "pass" else "observe-only",
        ),
        "release": _gate_summary(
            "release",
            release_ok,
            {
                "release_train_status": release_train.get("status"),
                "release_gate_status": release_gate.get("status"),
                "release_gate_sample_failures": release_gate.get("sample_failures", []),
                "rnd_pipeline_stage": rnd_pipeline.get("stage"),
                "quality_status": quality_status.get("status"),
                "autonomy_stage": autonomy_score.get("stage"),
            },
            next_action="observe-release-signal" if release_ok == "pass" else "repair-release-path",
        ),
        "blocked_reasons": blocked_reasons,
        "recommendation": (
            "release-ready"
            if release_ok == "pass"
            else "repair-ci" if "ci" in blocked_reasons
            else "repair-cd" if "cd" in blocked_reasons
            else "observe-release-signal"
        ),
        "control_snapshot": {
            "engineering_os_status": (engineering_os.get("engineering_os") or {}).get("status") or engineering_os.get("status"),
            "ai_testing_status": ai_testing.get("status"),
            "release_train_status": release_train.get("status"),
            "quality_status": quality_status.get("status"),
            "autonomy_stage": autonomy_score.get("stage"),
            "autonomy_score": autonomy_score.get("score"),
        },
        "evidence": {
            "pipeline_stage": rnd_pipeline.get("stage"),
            "pipeline_status": rnd_pipeline.get("status"),
            "passed_phase_count": (rnd_pipeline.get("summary") or {}).get("passed_phase_count"),
            "total_phase_count": (rnd_pipeline.get("summary") or {}).get("total_phase_count"),
            "primary_artifact_real": bool(artifact.get("real")),
            "primary_artifact_issue_count": len(artifact.get("issues") or []),
        },
    }
    if write_outputs:
        atomic_write_json(OUT, payload)
    return payload


if __name__ == "__main__":
    print(json.dumps(build_pipeline_status(), ensure_ascii=False, indent=2))
