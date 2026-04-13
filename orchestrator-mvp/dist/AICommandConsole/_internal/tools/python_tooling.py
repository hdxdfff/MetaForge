from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parent
BUNDLED_UV = WORKSPACE_ROOT / "tools" / "python311-embed" / "Scripts" / "uv.exe"
DEFAULT_TARGETS = ["app", "tools"]
DEFAULT_TARGETS.extend(path.name for path in sorted(ROOT.glob("*.py")))


def _uv_executable() -> str:
    override = os.environ.get("UV_EXE")
    if override:
        return override
    if BUNDLED_UV.exists():
        return str(BUNDLED_UV)
    uv = shutil.which("uv")
    if uv:
        return uv
    raise SystemExit("uv not found. Install uv or set UV_EXE to a uv executable path.")


def _with_default_targets(args: list[str]) -> list[str]:
    if any(not item.startswith("-") for item in args):
        return args
    return [*args, *DEFAULT_TARGETS]


def _build_command(command: str, args: list[str]) -> list[str]:
    uv = _uv_executable()
    if command == "sync":
        return [uv, "sync", *args]
    if command == "qa":
        return [uv, "run", "python", "tools/qa_check.py", *args]
    if command == "ruff-check":
        return [uv, "run", "ruff", "check", *_with_default_targets(args)]
    if command == "ruff-format":
        return [uv, "run", "ruff", "format", *_with_default_targets(args)]
    if command == "ty-check":
        return [uv, "run", "--group", "typing", "ty", "check", *_with_default_targets(args)]
    raise SystemExit(
        "Usage: python tools/python_tooling.py [sync|qa|ruff-check|ruff-format|ty-check] [args...]"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit(
            "Usage: python tools/python_tooling.py "
            "[sync|qa|ruff-check|ruff-format|ty-check] [args...]"
        )
    command = _build_command(argv[1], argv[2:])
    completed = subprocess.run(command, cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
