from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOOLS_ROOT = ROOT / "tools"
PYTHON_ROOT = TOOLS_ROOT / "python311-embed"
GIT_ROOT = TOOLS_ROOT / "mingit-2.53.0-64-bit" / "mingw64" / "bin"
NODE_ROOT = TOOLS_ROOT / "node-v22.22.1-win-x64"
DOCKER_ROOT = Path(r"C:\Program Files\Docker\Docker\resources\bin")
SYSTEM32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
DOCKER_CONFIG = ROOT / "tmp" / "docker-config"
MANAGED_IMAGE = "toyos-managed-toolchain"


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


def _convert_codex_container_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if normalized.lower().startswith("d:/codex/"):
        return "/codex" + normalized[len("D:/codex") :]
    if normalized.lower() == "d:/codex":
        return "/codex"
    return value


def _managed_tool_command(tool_name: str, args: list[str]) -> list[str]:
    if tool_name == "python":
        return [str(PYTHON_ROOT / "python.exe"), *args]
    if tool_name == "git":
        return [str(GIT_ROOT / "git.exe"), *args]
    if tool_name == "node":
        return [str(NODE_ROOT / "node.exe"), *args]
    if tool_name == "docker":
        return [str(DOCKER_ROOT / "docker.exe"), *args]
    if tool_name in {"nasm", "gcc", "ld", "qemu-system-i386", "grub-mkrescue", "make"}:
        docker_exe = shutil.which("docker.exe") or str(DOCKER_ROOT / "docker.exe")
        if not Path(docker_exe).exists():
            raise RuntimeError(f"docker.exe not found at {docker_exe}")
        converted_args = [_convert_codex_container_path(arg) for arg in args]
        return [
            docker_exe,
            "run",
            "--rm",
            "-v",
            f"{ROOT}:/codex",
            "-w",
            "/codex",
            MANAGED_IMAGE,
            tool_name,
            *converted_args,
        ]
    resolved = shutil.which(tool_name)
    if resolved:
        return [resolved, *args]
    raise RuntimeError(f"tool not available: {tool_name}")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: codex-run-tool <tool> [args...]")
        return 1
    tool_name = sys.argv[1]
    args = sys.argv[2:]
    env = _build_env()
    DOCKER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    DOCKER_CONFIG.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(_managed_tool_command(tool_name, args), cwd=str(ROOT), env=env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
