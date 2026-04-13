#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

EXPECTED_MARKERS = [
    "ToyOS: kernel_main entered",
    "ToyOS: GDT and TSS ready",
    "ToyOS: core subsystems initialized",
    "ToyOS: memory allocations ready",
    "VFS: format done",
    "ToyOS: filesystems ready",
    "ToyOS: processes created",
    "ToyOS: scheduler rounds completed",
    "ToyOS: kernel services online",
]


def marker_positions(text: str) -> dict[str, int]:
    positions = {}
    search_from = 0
    for marker in EXPECTED_MARKERS:
        index = text.find(marker, search_from)
        positions[marker] = index
        if index >= 0:
            search_from = index + len(marker)
    return positions


def run_round(round_index: int, kernel: Path, log_dir: Path, timeout_seconds: int) -> dict:
    log_path = log_dir / f"round-{round_index:02d}.log"
    if log_path.exists():
        log_path.unlink()

    cmd = [
        "timeout",
        f"{timeout_seconds}s",
        "qemu-system-i386",
        "-kernel",
        str(kernel),
        "-display",
        "none",
        "-debugcon",
        f"file:{log_path}",
        "-global",
        "isa-debugcon.iobase=0xe9",
        "-no-reboot",
        "-no-shutdown",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    positions = marker_positions(log_text)
    missing = [marker for marker, index in positions.items() if index < 0]

    return {
        "round": round_index,
        "returncode": result.returncode,
        "timed_out": result.returncode == 124,
        "log_path": str(log_path),
        "missing_markers": missing,
        "passed": not missing,
        "marker_positions": positions,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeated QEMU smoke tests for ToyOS.")
    parser.add_argument("--kernel", default="build/kernel.bin")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--report", default="build/qemu-smoke-report.json")
    parser.add_argument("--log-dir", default="build/qemu-smoke")
    args = parser.parse_args()

    kernel = Path(args.kernel)
    report_path = Path(args.report)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    if not kernel.exists():
        raise SystemExit(f"kernel not found: {kernel}")

    rounds = [run_round(i + 1, kernel, log_dir, args.timeout_seconds) for i in range(args.rounds)]
    passed = sum(1 for item in rounds if item["passed"])
    report = {
        "kernel": str(kernel),
        "rounds_requested": args.rounds,
        "rounds_passed": passed,
        "all_passed": passed == args.rounds,
        "expected_markers": EXPECTED_MARKERS,
        "results": rounds,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"qemu smoke report: {report_path}")
    print(f"rounds passed: {passed}/{args.rounds}")
    for item in rounds:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"- round {item['round']:02d}: {status} timeout={item['timed_out']} missing={len(item['missing_markers'])}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
