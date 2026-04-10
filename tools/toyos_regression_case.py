from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


CODEX_ROOT = Path(__file__).resolve().parent.parent
# This wrapper is invoked from D:\codex\tools, but the ToyOS build/test
# artifacts live under the authoritative delivery workspace.
PROJECT_ROOT = CODEX_ROOT / "generated" / "toy-os-demo"
QEMU_LOG = PROJECT_ROOT / "build" / "qemu-debug.log"
QEMU_WRAPPER_LOG = PROJECT_ROOT / "build" / "qemu-wrapper.log"
BUILD_WRAPPER_LOG = PROJECT_ROOT / "build" / "build-wrapper.log"
DEFAULT_IMAGE = "toyos-managed-toolchain"
QEMU_CONTAINER_LOG = "build/qemu-debug.log"
DOCKER_CONFIG = CODEX_ROOT / "tmp" / "docker-config"


def _run_wrapper(wrapper: Path, *args: str, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    command = ["cmd", "/c", str(wrapper), *args]
    proc = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, proc.returncode, stdout or "", stderr or "")
    except subprocess.TimeoutExpired as exc:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, text=True, check=False)
        stdout, stderr = proc.communicate()
        return subprocess.CompletedProcess(
            command,
            -1,
            (exc.stdout or stdout or ""),
            (exc.stderr or stderr or ""),
        )


def _docker_executable() -> str:
    return shutil.which("docker.exe") or shutil.which("docker") or "docker"


def _qemu_executable() -> str:
    return shutil.which("qemu-system-i386") or "qemu-system-i386"


def _docker_env() -> dict[str, str]:
    env = dict(**os.environ)
    env["DOCKER_CONFIG"] = str(DOCKER_CONFIG)
    return env


def _qemu_command(timeout_seconds: int) -> str:
    return (
        f"mkdir -p /codex/generated/toy-os-demo/build && "
        f"ls -ld /codex/generated/toy-os-demo /codex/generated/toy-os-demo/build && "
        f"rm -f /codex/generated/toy-os-demo/build/qemu-debug.log && "
        f"touch /codex/generated/toy-os-demo/build/qemu-debug.log && "
        f"timeout {timeout_seconds}s qemu-system-i386 -kernel /codex/generated/toy-os-demo/build/kernel.bin -display none "
        f"-debugcon file:/codex/generated/toy-os-demo/build/qemu-debug.log -global isa-debugcon.iobase=0xe9 "
        f"-no-reboot -no-shutdown || true"
    )


def _build_kernel(*build_args: str) -> None:
    if QEMU_LOG.exists():
        QEMU_LOG.unlink()
    if BUILD_WRAPPER_LOG.exists():
        BUILD_WRAPPER_LOG.unlink()
    docker = _docker_executable()
    build_command = "rm -rf build build-report.json && "
    build_command += "make "
    if build_args:
        build_command += " ".join(build_args) + " "
    build_command += "kernel-host"
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{CODEX_ROOT}:/codex",
            "-w",
            "/codex/generated/toy-os-demo",
            DEFAULT_IMAGE,
            "bash",
            "-lc",
            build_command,
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
        env=_docker_env(),
        check=False,
    )
    BUILD_WRAPPER_LOG.parent.mkdir(parents=True, exist_ok=True)
    BUILD_WRAPPER_LOG.write_text(f"{result.stdout or ''}{result.stderr or ''}", encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _run_qemu(timeout_seconds: int) -> int:
    if QEMU_LOG.exists():
        QEMU_LOG.unlink()
    if QEMU_WRAPPER_LOG.exists():
        QEMU_WRAPPER_LOG.unlink()
    docker = _docker_executable()
    qemu = _qemu_executable()
    docker_available = bool(shutil.which("docker.exe") or shutil.which("docker"))
    if docker_available:
        result = subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "-v",
                f"{CODEX_ROOT}:/codex",
                "-w",
                "/codex/generated/toy-os-demo",
                DEFAULT_IMAGE,
                "bash",
                "-lc",
                _qemu_command(timeout_seconds),
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=max(45, timeout_seconds + 15),
            env=_docker_env(),
            check=False,
        )
    else:
        host_command = (
            f"mkdir -p build && "
            f"rm -f build/qemu-debug.log && "
            f"touch build/qemu-debug.log && "
            f"timeout {timeout_seconds}s {qemu} -kernel build/kernel.bin -display none "
            f"-serial stdio -monitor none -no-reboot -no-shutdown "
            f"-debugcon file:build/qemu-debug.log -global isa-debugcon.iobase=0xe9 || true"
        )
        result = subprocess.run(
            ["bash", "-lc", host_command],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=max(45, timeout_seconds + 15),
            check=False,
        )
    QEMU_WRAPPER_LOG.parent.mkdir(parents=True, exist_ok=True)
    QEMU_WRAPPER_LOG.write_text(f"{result.stdout or ''}{result.stderr or ''}", encoding="utf-8", errors="replace")
    if not QEMU_LOG.exists():
        QEMU_LOG.parent.mkdir(parents=True, exist_ok=True)
        QEMU_LOG.write_text("", encoding="utf-8")
    mirror_log = CODEX_ROOT / "build" / "qemu-debug.log"
    mirror_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(QEMU_LOG, mirror_log)
    except FileNotFoundError:
        mirror_log.write_text("", encoding="utf-8")
    if result.returncode not in {0, None} and result.stderr:
        # Keep wrapper failures visible in a sidecar log, but do not overwrite
        # the guest log output the regression suite validates.
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ToyOS regression case.")
    parser.add_argument("--case", required=True)
    args = parser.parse_args()

    case = str(args.case).strip().lower()
    if case == "qemu_boot_paging_stage1":
        _build_kernel("TOYOS_EXPERIMENTAL_PAGING_STAGE1=1")
    elif case in {"qemu_boot_paging_stage2", "qemu_user_probe_stage2_pointer_policy"}:
        _build_kernel("TOYOS_EXPERIMENTAL_PAGING_STAGE2=1")
    elif case == "qemu_user_probe_preempt_unified_return":
        _build_kernel("TOYOS_EXPERIMENTAL_PAGING_STAGE2=1", "TOYOS_EXPERIMENTAL_PREEMPT_UNIFIED_RETURN=1")

    qemu_case_timeouts = {
        "qemu_boot_smoke": 30,
        "qemu_boot_soak": 30,
        "qemu_boot_paging_stage1": 180,
        "qemu_boot_paging_stage2": 180,
        "qemu_user_probe_stage2_pointer_policy": 180,
        "qemu_user_probe_preempt_unified_return": 300,
        "qemu_user_probe_assertions": 180,
        "qemu_filesystem_stress_assertions": 180,
        "qemu_shell_probe_assertions": 180,
        "qemu_filesystem_multiwriter_assertions": 180,
        "qemu_filesystem_mixed_assertions": 180,
    }
    if case in qemu_case_timeouts:
        return _run_qemu(qemu_case_timeouts[case])

    raise SystemExit(f"unknown regression case: {case}")


if __name__ == "__main__":
    raise SystemExit(main())
