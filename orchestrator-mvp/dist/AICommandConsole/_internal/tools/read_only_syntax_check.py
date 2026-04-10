from __future__ import annotations

import argparse
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _check_file(path: Path) -> str | None:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        return f"{path}:{exc.lineno}:{exc.offset}: {exc.msg}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Python syntax sweep.")
    parser.add_argument("paths", nargs="*", default=["."], help="Files or directories to check.")
    args = parser.parse_args()

    roots = [Path(item).resolve() for item in args.paths]
    files: list[Path] = []
    for root in roots:
        files.extend(_python_files(root))

    unique_files = sorted({path for path in files})
    errors = [issue for issue in (_check_file(path) for path in unique_files) if issue]

    print(f"checked_files={len(unique_files)}")
    if errors:
        print("syntax_errors=" + str(len(errors)))
        for issue in errors[:20]:
            print(issue)
        if len(errors) > 20:
            print(f"... truncated {len(errors) - 20} additional errors")
        return 1

    print("syntax_errors=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
