from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

FILE_WEIGHTS = {
    "boot.asm": 10,
    "kernel.c": 14,
    "linker.ld": 8,
    "Makefile": 8,
    "README.md": 8,
    ".gitignore": 4,
}
OUT_NAME = "score-report.json"


def load_build_report(target: Path) -> dict:
    path = target / "build-report.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_qemu_report(target: Path) -> dict:
    path = target / "build" / "generic-qemu-smoke-report.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def grade_for(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 65:
        return "C"
    if score >= 50:
        return "D"
    return "E"


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a toy OS scaffold")
    parser.add_argument("--target", required=True, help="Target directory to inspect")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        print("score: 0/100")
        print("grade: E")
        print("status: missing")
        print(f"detail: target not found: {target}")
        return 0

    findings: list[str] = []
    structure_score = 0
    for name, points in FILE_WEIGHTS.items():
        path = target / name
        if path.exists() and path.stat().st_size > 0:
            structure_score += points
            findings.append(f"ok: {name}")
        else:
            findings.append(f"missing: {name}")

    quality_score = 0
    readme = target / "README.md"
    if readme.exists():
        readme_text = readme.read_text(encoding="utf-8", errors="ignore").lower()
        if "teaching" in readme_text or "teaching-oriented" in readme_text:
            quality_score += 8
            findings.append("ok: readme documents teaching intent")
        if "interrupt" in readme_text and "paging" in readme_text:
            quality_score += 4
            findings.append("ok: readme includes next-step roadmap")

    kernel = target / "kernel.c"
    if kernel.exists():
        kernel_text = kernel.read_text(encoding="utf-8", errors="ignore")
        if "kernel_main" in kernel_text:
            quality_score += 8
            findings.append("ok: kernel entry exists")
        if "VGA" in kernel_text and "write_text" in kernel_text:
            quality_score += 6
            findings.append("ok: basic VGA output implementation present")

    boot = target / "boot.asm"
    if boot.exists():
        boot_text = boot.read_text(encoding="utf-8", errors="ignore")
        if "multiboot" in boot_text.lower():
            quality_score += 6
            findings.append("ok: multiboot header present")

    build_report = load_build_report(target)
    qemu_report = load_qemu_report(target)
    build_score = 0
    if build_report:
        findings.append("ok: build report present")
        checks = build_report.get("checks", [])
        successful_checks = sum(1 for item in checks if item.get("ok"))
        build_score += min(successful_checks * 6, 18)
        if build_report.get("build_ready"):
            build_score += 8
            managed = (build_report.get("managed_resolution") or {}).get("recommended_backend")
            if managed == "docker":
                findings.append("ok: managed docker toolchain available")
            else:
                findings.append("ok: cross-toolchain detected")
        else:
            findings.append("warn: no build backend detected")
        if build_report.get("build_success"):
            build_score += 14
            findings.append("ok: kernel binary produced")
        else:
            findings.append("warn: build binary not produced")
        if qemu_report:
            smoke = next((item for item in qemu_report.get("tests", []) if item.get("name") == "qemu_boot_smoke"), None)
            soak = next((item for item in qemu_report.get("tests", []) if item.get("name") == "qemu_boot_soak"), None)
            if smoke and smoke.get("all_passed"):
                build_score += 6
                findings.append("ok: qemu boot smoke passed")
            if soak and soak.get("all_passed"):
                build_score += 6
                findings.append("ok: qemu boot soak passed")
    else:
        toolchain = ["nasm", "i686-elf-gcc", "i686-elf-ld", "qemu-system-i386"]
        installed = [name for name in toolchain if shutil.which(name)]
        build_score += min(len(installed) * 2, 8)
        findings.append("toolchain: " + (", ".join(installed) if installed else "not detected"))

    experiment_score = 0
    makefile = target / "Makefile"
    if makefile.exists():
        makefile_text = makefile.read_text(encoding="utf-8", errors="ignore")
        if "run:" in makefile_text:
            experiment_score += 6
            findings.append("ok: run target present")
        if "clean:" in makefile_text:
            experiment_score += 4
            findings.append("ok: clean target present")
        if "-ffreestanding" in makefile_text:
            experiment_score += 4
            findings.append("ok: freestanding flags configured")

    build_score = min(build_score, 40)
    score = min(structure_score + quality_score + build_score + experiment_score, 100)
    report = {
        "target": str(target),
        "score": score,
        "grade": grade_for(score),
        "status": "ok",
        "structure_score": structure_score,
        "quality_score": quality_score,
        "build_score": build_score,
        "experiment_score": experiment_score,
        "findings": findings,
    }
    (target / OUT_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"score: {score}/100")
    print(f"grade: {grade_for(score)}")
    print(f"target: {target}")
    print(f"structure_score: {structure_score}/52")
    print(f"quality_score: {quality_score}/32")
    print(f"build_score: {build_score}/40")
    print(f"experiment_score: {experiment_score}/14")
    for item in findings:
        print(f"- {item}")
    print(f"score report: {target / OUT_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
