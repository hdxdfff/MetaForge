from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = ROOT / "tools"
PYTHON_ROOT = TOOLS_ROOT / "python311-embed"
GIT_ROOT = TOOLS_ROOT / "mingit-2.53.0-64-bit" / "mingw64" / "bin"
NODE_ROOT = TOOLS_ROOT / "node-v22.22.1-win-x64"
DOCKER_ROOT = Path(r"C:\Program Files\Docker\Docker\resources\bin")
SYSTEM32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
DOCKER_CONFIG = ROOT / "tmp" / "docker-config"


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_ROOT"] = str(ROOT)
    env["DOCKER_CONFIG"] = str(DOCKER_CONFIG)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    path_parts = [
        str(PYTHON_ROOT),
        str(GIT_ROOT),
        str(NODE_ROOT),
        str(DOCKER_ROOT),
        str(SYSTEM32),
        env.get("PATH", ""),
    ]
    env["PATH"] = ";".join(part for part in path_parts if part)
    return env


def _print_status(env: dict[str, str]) -> None:
    print("Codex toolchain recovery loaded.")
    print(f"root: {ROOT}")
    print(f"docker_config: {env['DOCKER_CONFIG']}")
    checks = [
        ("python", PYTHON_ROOT / "python.exe"),
        ("git", GIT_ROOT / "git.exe"),
        ("node", NODE_ROOT / "node.exe"),
        ("docker", DOCKER_ROOT / "docker.exe"),
    ]
    for name, candidate in checks:
        resolved = candidate if candidate.exists() else shutil.which(name)
        state = "ok" if resolved else "missing"
        source = str(resolved) if resolved else "unresolved"
        print(f"- {state}: {name} -> {source}")


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--show-status", action="store_true")
    parser.add_argument("--no-shell", action="store_true")
    args = parser.parse_args()

    env = _build_env()
    DOCKER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    DOCKER_CONFIG.mkdir(parents=True, exist_ok=True)

    if args.show_status:
        _print_status(env)

    if args.no_shell:
        return 0

    completed = subprocess.run(["cmd.exe"], cwd=str(ROOT), env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
