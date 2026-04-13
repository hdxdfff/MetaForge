#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json


def load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def find_markers_in_order(text: str, markers: list[str]) -> tuple[dict[str, int], list[str]]:
    positions: dict[str, int] = {}
    search_from = 0
    missing: list[str] = []
    for marker in markers:
        index = text.find(marker, search_from)
        positions[marker] = index
        if index < 0:
            missing.append(marker)
        else:
            search_from = index + len(marker)
    return positions, missing


def collect_combined_text(root: Path, test: dict[str, Any], stdout: str, stderr: str) -> tuple[str, list[dict[str, Any]]]:
    combined = [stdout, stderr]
    log_sources: list[dict[str, Any]] = []
    for entry in test.get("log_files", []):
        log_path = root / entry
        log_text = load_text(log_path)
        log_sources.append({"path": str(log_path), "size": len(log_text)})
        combined.append(log_text)
    return "\n".join(combined), log_sources


def run_once(test: dict[str, Any], root: Path, round_index: int) -> dict[str, Any]:
    cwd = root / test.get("cwd", ".")
    timeout_seconds = int(test.get("timeout_seconds", 30))
    command = list(test["command"])
    if command and command[0] in {"python", "python3", "py"}:
        command[0] = sys.executable
    use_shell = bool(test.get("shell", False))
    expected_returncodes = test.get("expected_returncodes", [0])
    allow_timeout = bool(test.get("allow_timeout", False))

    timed_out = False
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            shell=use_shell,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")
        stderr = (exc.stderr or "")
        returncode = None
        timed_out = True

    combined_text, log_sources = collect_combined_text(root, test, stdout, stderr)
    pass_markers = test.get("pass_markers", [])
    fail_markers = test.get("fail_markers", [])
    ordered_markers = bool(test.get("ordered_pass_markers", True))

    if ordered_markers:
        positions, missing_markers = find_markers_in_order(combined_text, pass_markers)
    else:
        positions = {marker: combined_text.find(marker) for marker in pass_markers}
        missing_markers = [marker for marker, index in positions.items() if index < 0]

    seen_fail_markers = [marker for marker in fail_markers if marker in combined_text]
    min_log_size = int(test.get("min_log_size", 0))
    total_log_size = sum(item["size"] for item in log_sources)
    log_size_ok = total_log_size >= min_log_size
    passed = (
        ((timed_out and allow_timeout) or (not timed_out and returncode in expected_returncodes))
        and not missing_markers
        and not seen_fail_markers
        and log_size_ok
    )

    return {
        "round": round_index,
        "name": test.get("name", f"test-{round_index}"),
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "log_sources": log_sources,
        "total_log_size": total_log_size,
        "min_log_size": min_log_size,
        "marker_positions": positions,
        "missing_markers": missing_markers,
        "seen_fail_markers": seen_fail_markers,
        "passed": passed,
    }


def summarize_test(test: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    rounds = int(test.get("rounds", 1))
    required_passes = int(test.get("required_passes", rounds))
    passed_rounds = sum(1 for item in results if item.get("passed"))
    return {
        "name": test.get("name", "unnamed"),
        "rounds": rounds,
        "required_passes": required_passes,
        "passed_rounds": passed_rounds,
        "all_passed": passed_rounds >= required_passes,
        "results": results,
    }


def run_test(test: dict[str, Any], root: Path) -> dict[str, Any]:
    rounds = int(test.get("rounds", 1))
    results = [run_once(test, root, index + 1) for index in range(rounds)]
    return summarize_test(test, results)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reusable local code tests from a JSON spec.")
    parser.add_argument("--spec", required=True, help="Path to JSON test spec")
    parser.add_argument("--report", default="", help="Optional report path override")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    root = spec_path.parent.parent if spec_path.parent.name == "tools" else spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    tests = spec.get("tests", [])
    if not tests:
        raise SystemExit("spec contains no tests")

    report = {
        "suite": spec.get("name", spec_path.stem),
        "root": str(root),
        "tests": [run_test(test, root) for test in tests],
    }
    report["all_passed"] = all(item["all_passed"] for item in report["tests"])

    report_path = Path(args.report) if args.report else root / spec.get("report", "build/generic-test-report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, report)

    print(f"generic test report: {report_path}")
    for item in report["tests"]:
        print(
            f"- {item['name']}: {item['passed_rounds']}/{item['rounds']} passed "
            f"(required {item['required_passes']})"
        )
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
