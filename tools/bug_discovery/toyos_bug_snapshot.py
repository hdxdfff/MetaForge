from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOYOS = ROOT / "generated" / "toy-os-demo"
KNOWLEDGE = ROOT / "knowledge"
OUT = KNOWLEDGE / "discovered_issues.json"
BUILD_REPORT = TOYOS / "build-report.json"
KERNEL = TOYOS / "kernel.c"
SYSCALL = TOYOS / "src" / "syscall.c"
SMOKE_SPEC = TOYOS / "tools" / "generic_qemu_smoke.json"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def collect_findings() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    build_report = load_json(BUILD_REPORT, {})
    checks = build_report.get("checks", [])
    failed_checks = [item for item in checks if not item.get("ok", False)]
    findings.append({
        "finding_id": "toyos-build-status",
        "category": "build",
        "severity": "info" if checks and not failed_checks else "medium",
        "status": "open" if failed_checks else "observed",
        "title": "Track ToyOS build pipeline health",
        "summary": "Keep build report health visible so future regressions immediately enter the issue stream.",
        "evidence": {
            "build_report": str(BUILD_REPORT),
            "total_checks": len(checks),
            "failed_checks": len(failed_checks),
        },
        "next_action": "Refresh build report after every kernel-facing patch.",
    })

    kernel_text = KERNEL.read_text(encoding="utf-8-sig") if KERNEL.exists() else ""
    stable_gate_present = "ToyOS: paging stage1 skipped (stable path)" in kernel_text
    stage1_markers_present = "ToyOS: paging stage1 post-enable" in kernel_text
    findings.append({
        "finding_id": "toyos-paging-stage1-gate",
        "category": "paging",
        "severity": "high",
        "status": "open",
        "title": "Paging is still experimental and not part of the stable default path",
        "summary": "ToyOS now needs a guarded Stage 1 validation path while keeping the stable boot contract unchanged until ring3 restore is stronger.",
        "evidence": {
            "file": str(KERNEL),
            "paging_helper_visible": "paging_stage1_smoke_enable()" in kernel_text,
            "stable_gate_present": stable_gate_present,
            "stage1_markers_present": stage1_markers_present,
        },
        "next_action": "Validate the guarded paging path under QEMU and keep it out of the stable default boot path.",
    })

    syscall_text = SYSCALL.read_text(encoding="utf-8-sig") if SYSCALL.exists() else ""
    paging_text = (TOYOS / "src" / "paging.c").read_text(encoding="utf-8-sig") if (TOYOS / "src" / "paging.c").exists() else ""
    validation_stub_present = "syscall_validate_user_buffer" in syscall_text
    paging_aware_validation = "paging_user_accessible_range" in syscall_text or "paging_user_accessible_range" in paging_text
    findings.append({
        "finding_id": "toyos-syscall-pointer-validation",
        "category": "syscall",
        "severity": "high",
        "status": "open",
        "title": "Syscall pointer validation is still only minimally paging-aware",
        "summary": "ToyOS now enforces mapped-range checks when paging is enabled, but it still lacks true per-process and page-permission-aware user-memory validation.",
        "evidence": {
            "file": str(SYSCALL),
            "validation_stub_present": validation_stub_present,
            "paging_aware_validation": paging_aware_validation,
        },
        "next_action": "Upgrade mapped-range checks into true per-process and page-permission-aware user-buffer enforcement before promoting stronger ring3 isolation.",
    })

    smoke = load_json(SMOKE_SPEC, {})
    tests = smoke.get("tests", [])
    findings.append({
        "finding_id": "toyos-regression-surface",
        "category": "verification",
        "severity": "medium",
        "status": "open",
        "title": "Regression surface is still boot-heavy",
        "summary": "The current automated suite now includes guarded paging, explicit user-probe assertions, scripted shell-command coverage, bounded filesystem stress, alternating multi-writer verification, user/kernel mixed filesystem reads, repeated known-file reads, missing-path handling, and empty-path negative cases, but it is still light on raw keyboard automation and broader filesystem regressions.",
        "evidence": {
            "file": str(SMOKE_SPEC),
            "test_count": len(tests),
            "test_names": [item.get("name") for item in tests],
        },
        "next_action": "Expand the suite beyond bounded user/kernel mixed reads into raw keyboard behavior and heavier user/kernel mixed filesystem pressure.",
    })

    return findings


def main() -> None:
    payload = {
        "updated_at": utc_iso(),
        "project": "ToyOS",
        "workspace": str(TOYOS),
        "sources": {
            "build_report": str(BUILD_REPORT),
            "kernel": str(KERNEL),
            "syscall": str(SYSCALL),
            "smoke_spec": str(SMOKE_SPEC),
        },
        "issues": collect_findings(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
