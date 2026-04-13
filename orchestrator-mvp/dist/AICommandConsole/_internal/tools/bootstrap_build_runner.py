
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from tools.read_only_syntax_check import _check_file, _python_files

DEFAULT_SCAN_DIRS = ("app", "runtime", "tools", "agents", "state")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_scan_roots(repo: Path) -> list[Path]:
    roots: list[Path] = []
    for name in DEFAULT_SCAN_DIRS:
        candidate = repo / name
        if candidate.exists():
            roots.append(candidate)
    if not roots:
        roots.append(repo)
    return roots


def run_bootstrap_build(repo: Path) -> dict[str, Any]:
    scan_roots = _resolve_scan_roots(repo)
    files: list[Path] = []
    for root_path in scan_roots:
        files.extend(_python_files(root_path))
    unique_files = sorted({path for path in files})
    syntax_errors = [issue for issue in (_check_file(path) for path in unique_files) if issue]
    scanned = [str(path.relative_to(repo)) for path in unique_files]
    return {
        "status": "pass" if not syntax_errors else "fail",
        "repo": str(repo),
        "scanned_roots": [str(path.relative_to(repo)) if path != repo else "." for path in scan_roots],
        "checked_file_count": len(unique_files),
        "checked_files": scanned[:200],
        "syntax_error_count": len(syntax_errors),
        "syntax_errors": syntax_errors[:50],
        "generated_at": _utc(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-readable bootstrap build evidence.")
    parser.add_argument("--repo", required=True, help="Repository root to inspect.")
    parser.add_argument("--report", required=True, help="JSON report output path.")
    parser.add_argument("--log", required=True, help="Text log output path.")
    parser.add_argument("--manifest", required=True, help="Manifest output path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report_path = Path(args.report).resolve()
    log_path = Path(args.log).resolve()
    manifest_path = Path(args.manifest).resolve()

    result = run_bootstrap_build(repo)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    atomic_write_json(report_path, result)
    log_lines = [
        f"bootstrap_build_status={result['status']}",
        f"checked_file_count={result['checked_file_count']}",
        f"syntax_error_count={result['syntax_error_count']}",
    ]
    if result["syntax_errors"]:
        log_lines.extend(result["syntax_errors"])
    else:
        log_lines.append("syntax_errors=0")
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    atomic_write_json(
        manifest_path,
        {
            "generated_at": result["generated_at"],
            "kind": "bootstrap-build-manifest",
            "artifacts": [str(report_path), str(log_path), str(manifest_path)],
            "status": result["status"],
        },
    )

    print(f"bootstrap build report: {report_path}")
    print(f"checked_file_count={result['checked_file_count']}")
    print(f"syntax_error_count={result['syntax_error_count']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
