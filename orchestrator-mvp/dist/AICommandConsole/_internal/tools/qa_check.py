from __future__ import annotations

import compileall
import json
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_CANDIDATES = [
    ROOT.parent / "tools" / "node-v22.22.1-win-x64" / "node.exe",
    ROOT / "tools" / "node-v22.22.1-win-x64" / "node.exe",
]


def validate_json_files() -> list[str]:
    errors: list[str] = []
    for path in sorted((ROOT / "data").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"Invalid JSON: {path} -> {exc}")
    return errors


def validate_js_syntax() -> list[str]:
    script = ROOT / "app" / "static" / "app.js"
    node = next((candidate for candidate in NODE_CANDIDATES if candidate.exists()), None)
    if node is None:
        return []
    completed = subprocess.run(
        [str(node), "--check", str(script)], cwd=ROOT, capture_output=True, text=True
    )
    if completed.returncode == 0:
        return []
    message = completed.stderr.strip() or completed.stdout.strip() or "Unknown node syntax error"
    return [f"JavaScript syntax check failed: {message}"]


def validate_toml_files() -> list[str]:
    path = ROOT / "pyproject.toml"
    if not path.exists():
        return []
    try:
        tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"Invalid TOML: {path} -> {exc}"]
    return []


def main() -> int:
    ok = compileall.compile_dir(str(ROOT / "app"), quiet=1)
    ok = compileall.compile_dir(str(ROOT / "tools"), quiet=1) and ok
    errors: list[str] = []
    if not ok:
        errors.append("Python compileall failed for app/tools")
    errors.extend(validate_json_files())
    errors.extend(validate_toml_files())
    errors.extend(validate_js_syntax())
    if errors:
        for item in errors:
            print(item)
        return 1
    print("qa_check: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
