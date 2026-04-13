
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json

BUNDLED_PYTHON = ROOT.parent / "tools" / "python311-embed" / "python.exe"
QA_CHECK = ROOT / "tools" / "qa_check.py"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate machine-readable bootstrap validation evidence.")
    parser.add_argument("--repo", required=True, help="Repository root to validate.")
    parser.add_argument("--report", required=True, help="JSON report output path.")
    parser.add_argument("--log", required=True, help="Text log output path.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    report_path = Path(args.report).resolve()
    log_path = Path(args.log).resolve()
    python_cmd = str(BUNDLED_PYTHON if BUNDLED_PYTHON.exists() else sys.executable)

    completed = subprocess.run(
        [python_cmd, str(QA_CHECK)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )

    report = {
        "status": "pass" if completed.returncode == 0 else "fail",
        "repo": str(repo),
        "command": [python_cmd, str(QA_CHECK)],
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
        "generated_at": _utc(),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(report_path, report)
    log_path.write_text(
        "\n".join(
            [
                f"bootstrap_validation_status={report['status']}",
                f"returncode={completed.returncode}",
                (completed.stdout or "").strip(),
                (completed.stderr or "").strip(),
            ]
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    print(f"bootstrap validation report: {report_path}")
    print(f"returncode={completed.returncode}")
    return 0 if completed.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
