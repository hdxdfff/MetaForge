#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = PROJECT_ROOT.parents[1]
ORCHESTRATOR_ROOT = CODEX_ROOT / "orchestrator-mvp"
DEFAULT_IMAGE = "toyos-managed-toolchain"
DEFAULT_DOCKER_WAIT_SECONDS = 45


@dataclass
class HostState:
    nasm: str | None
    gcc: str | None
    ld: str | None
    qemu: str | None
    grub_mkrescue: str | None
    make: str | None
    docker: str | None
    docker_daemon: bool
    docker_error: str | None
    docker_desktop: str | None

    @property
    def can_build(self) -> bool:
        return bool(self.nasm and self.gcc and self.ld)

    @property
    def can_run_qemu(self) -> bool:
        return bool(self.qemu)

    @property
    def can_make_iso(self) -> bool:
        return bool(self.can_build and self.grub_mkrescue)

    @property
    def can_self_heal_docker(self) -> bool:
        return bool(self.docker and self.docker_desktop)


def _which(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def _probe_docker(docker: str | None) -> tuple[bool, str | None]:
    if not docker:
        return False, "docker client not detected"
    try:
        probe = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    daemon_ready = probe.returncode == 0 and bool((probe.stdout or "").strip())
    detail = None if daemon_ready else (probe.stderr or probe.stdout or "docker daemon unavailable").strip()
    return daemon_ready, detail


def _find_docker_desktop() -> str | None:
    candidates = [
        Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
        Path(r"C:\Program Files\Docker\Docker\frontend\Docker Desktop.exe"),
        Path(r"C:\Program Files\Docker\Docker\resources\Docker desktop.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def inspect_host() -> HostState:
    docker = _which("docker")
    docker_daemon, docker_error = _probe_docker(docker)
    return HostState(
        nasm=_which("nasm"),
        gcc=_which("i686-elf-gcc", "gcc"),
        ld=_which("i686-elf-ld", "ld"),
        qemu=_which("qemu-system-i386"),
        grub_mkrescue=_which("grub-mkrescue"),
        make=_which("make"),
        docker=docker,
        docker_daemon=docker_daemon,
        docker_error=docker_error,
        docker_desktop=_find_docker_desktop(),
    )


def refresh_docker_state(state: HostState) -> HostState:
    daemon_ready, docker_error = _probe_docker(state.docker)
    state.docker_daemon = daemon_ready
    state.docker_error = docker_error
    return state


def ensure_docker_daemon(state: HostState, wait_seconds: int = DEFAULT_DOCKER_WAIT_SECONDS) -> HostState:
    state = refresh_docker_state(state)
    if state.docker_daemon:
        return state
    if not state.can_self_heal_docker:
        return state
    subprocess.Popen([state.docker_desktop])
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(2)
        state = refresh_docker_state(state)
        if state.docker_daemon:
            return state
    return state


def run_command(command: list[str], cwd: Path = PROJECT_ROOT) -> int:
    proc = subprocess.run(command, cwd=cwd, check=False)
    return int(proc.returncode)


def host_supports_qemu_runner(state: HostState) -> bool:
    return bool(state.can_build and state.can_run_qemu and os.name != "nt")


def choose_backend(state: HostState, operation: str, requested: str) -> str:
    docker_capable = state.docker_daemon or state.can_self_heal_docker
    if requested == "host":
        return "host"
    if requested == "docker":
        return "docker"
    if operation == "build":
        if state.can_build:
            return "host"
        if docker_capable:
            return "docker"
    elif operation in {"iso", "real-hardware"}:
        if state.can_make_iso:
            return "host"
        if docker_capable:
            return "docker"
    elif operation in {"run", "run-iso", "qemu-smoke"}:
        if operation == "run" and state.can_build and state.can_run_qemu:
            return "host"
        if operation == "run-iso" and state.can_make_iso and state.can_run_qemu:
            return "host"
        if operation == "qemu-smoke" and host_supports_qemu_runner(state):
            return "host"
        if docker_capable:
            return "docker"
    elif operation == "test":
        if host_supports_qemu_runner(state):
            return "host"
        if docker_capable:
            return "docker"
        return "host"
    elif operation == "clean":
        return "host"
    return "unavailable"


def ensure_backend(state: HostState, backend: str, operation: str) -> HostState:
    if backend == "host":
        if operation == "build" and not state.can_build:
            raise SystemExit("host build backend unavailable: nasm/gcc/ld not detected")
        if operation in {"iso", "real-hardware"} and not state.can_make_iso:
            raise SystemExit("host ISO backend unavailable: grub-mkrescue or build toolchain not detected")
        if operation == "run" and not (state.can_build and state.can_run_qemu):
            raise SystemExit("host run backend unavailable: build toolchain or qemu-system-i386 not detected")
        if operation == "run-iso" and not (state.can_make_iso and state.can_run_qemu):
            raise SystemExit("host run-iso backend unavailable: ISO toolchain or qemu-system-i386 not detected")
        if operation == "qemu-smoke" and not host_supports_qemu_runner(state):
            raise SystemExit("host qemu-smoke backend unavailable on this host; use docker-managed execution instead")
        return state
    if backend == "docker":
        if not state.docker:
            raise SystemExit("docker backend unavailable: docker client not detected")
        state = ensure_docker_daemon(state)
        if not state.docker_daemon:
            detail = state.docker_error or "docker daemon unavailable"
            raise SystemExit(f"docker backend unavailable: {detail}")
        return state
    raise SystemExit(f"no backend available for operation: {operation}")


def docker_volume_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def ensure_docker_image(state: HostState, image: str) -> HostState:
    state = ensure_backend(state, "docker", "build")
    rc = run_command([state.docker or "docker", "build", "-t", image, "-f", "Dockerfile.build", "."], cwd=PROJECT_ROOT)
    if rc != 0:
        raise SystemExit(rc)
    return state


def docker_exec(state: HostState, image: str, command: str) -> int:
    state = ensure_docker_image(state, image)
    docker = state.docker or "docker"
    return run_command(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{docker_volume_path(CODEX_ROOT)}:/codex",
            "-w",
            "/codex/generated/toy-os-demo",
            image,
            "bash",
            "-lc",
            command,
        ],
        cwd=PROJECT_ROOT,
    )


def build_report_command(target: str) -> list[str]:
    return [sys.executable, str(ORCHESTRATOR_ROOT / "tools" / "build_toy_os.py"), "--target", target]


def score_command(target: str) -> list[str]:
    return [sys.executable, str(ORCHESTRATOR_ROOT / "tools" / "score_toy_os.py"), "--target", target]


def run_build(state: HostState, backend: str, image: str) -> int:
    if backend == "host":
        return run_command(build_report_command(str(PROJECT_ROOT)))
    return docker_exec(state, image, "python3 /codex/orchestrator-mvp/tools/build_toy_os.py --target /codex/generated/toy-os-demo")


def run_iso(state: HostState, backend: str, image: str) -> int:
    if backend == "host":
        return run_command(["make", "iso-host"])
    return docker_exec(state, image, "make iso-host")


def run_qemu_smoke(state: HostState, backend: str, image: str) -> int:
    if backend == "host":
        build_rc = run_build(state, "host", image)
        if build_rc != 0:
            return build_rc
        return run_command([sys.executable, str(ORCHESTRATOR_ROOT / "tools" / "generic_test_runner.py"), "--spec", "tools/generic_qemu_smoke.json"])
    return docker_exec(
        state,
        image,
        "export PYTHONPATH=/codex/orchestrator-mvp${PYTHONPATH:+:$PYTHONPATH} && "
        "python3 /codex/orchestrator-mvp/tools/build_toy_os.py --target /codex/generated/toy-os-demo && "
        "python3 /codex/orchestrator-mvp/tools/generic_test_runner.py --spec tools/generic_qemu_smoke.json",
    )


def run_test(state: HostState, backend: str, image: str) -> int:
    if backend == "host":
        build_rc = run_build(state, "host", image)
        if build_rc != 0:
            return build_rc
        if host_supports_qemu_runner(state):
            qemu_rc = run_command([sys.executable, str(ORCHESTRATOR_ROOT / "tools" / "generic_test_runner.py"), "--spec", "tools/generic_qemu_smoke.json"])
            if qemu_rc != 0:
                return qemu_rc
        else:
            print("qemu smoke skipped on host; docker-managed backend is unavailable")
        return run_command(score_command(str(PROJECT_ROOT)))
    return docker_exec(
        state,
        image,
        "export PYTHONPATH=/codex/orchestrator-mvp${PYTHONPATH:+:$PYTHONPATH} && "
        "python3 /codex/orchestrator-mvp/tools/build_toy_os.py --target /codex/generated/toy-os-demo && "
        "python3 /codex/orchestrator-mvp/tools/generic_test_runner.py --spec tools/generic_qemu_smoke.json && "
        "python3 /codex/orchestrator-mvp/tools/score_toy_os.py --target /codex/generated/toy-os-demo",
    )


def run_qemu(state: HostState, backend: str, image: str, iso: bool) -> int:
    if backend == "host":
        target = "run-iso-host" if iso else "run-host"
        return run_command(["make", target])
    if iso:
        command = "make iso-host && qemu-system-i386 -cdrom build/toyos.iso -display none -serial stdio -monitor none -no-reboot -no-shutdown"
    else:
        command = "python3 /codex/orchestrator-mvp/tools/build_toy_os.py --target /codex/generated/toy-os-demo && qemu-system-i386 -kernel build/kernel.bin -display none -serial stdio -monitor none -no-reboot -no-shutdown"
    return docker_exec(state, image, command)


def run_real_hardware(state: HostState, backend: str, image: str) -> int:
    rc = run_iso(state, backend, image)
    if rc == 0:
        print(f"ISO ready: {PROJECT_ROOT / 'build' / 'toyos.iso'}")
        print("Write it to a USB drive with a tool such as Rufus or balenaEtcher, then boot the machine from that USB device.")
    return rc


def run_clean() -> int:
    build_dir = PROJECT_ROOT / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    report = PROJECT_ROOT / "build-report.json"
    if report.exists():
        report.unlink()
    return 0


def print_status(state: HostState) -> int:
    recommended = {
        "build": choose_backend(state, "build", "auto"),
        "iso": choose_backend(state, "iso", "auto"),
        "qemu-smoke": choose_backend(state, "qemu-smoke", "auto"),
    }
    self_heal = "yes" if state.can_self_heal_docker else "no"
    print(f"project: {PROJECT_ROOT}")
    print(f"nasm: {state.nasm or 'missing'}")
    print(f"gcc: {state.gcc or 'missing'}")
    print(f"ld: {state.ld or 'missing'}")
    print(f"qemu-system-i386: {state.qemu or 'missing'}")
    print(f"grub-mkrescue: {state.grub_mkrescue or 'missing'}")
    print(f"docker: {state.docker or 'missing'}")
    print(f"docker-desktop: {state.docker_desktop or 'missing'}")
    print(f"docker-daemon: {'ready' if state.docker_daemon else 'down'}")
    print(f"docker-self-heal: {self_heal}")
    if state.docker_error:
        print(f"docker-detail: {state.docker_error}")
    for name, backend in recommended.items():
        print(f"recommended-{name}: {backend}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="System-managed ToyOS toolchain wrapper")
    parser.add_argument("operation", choices=["status", "build", "iso", "run", "run-iso", "qemu-smoke", "test", "real-hardware", "clean"])
    parser.add_argument("--backend", choices=["auto", "host", "docker"], default="auto")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    args = parser.parse_args()

    state = inspect_host()
    if args.operation == "status":
        return print_status(state)
    if args.operation == "clean":
        return run_clean()

    backend = choose_backend(state, args.operation, args.backend)
    state = ensure_backend(state, backend, "iso" if args.operation == "real-hardware" else args.operation)

    if args.operation == "build":
        return run_build(state, backend, args.image)
    if args.operation == "iso":
        return run_iso(state, backend, args.image)
    if args.operation == "run":
        return run_qemu(state, backend, args.image, iso=False)
    if args.operation == "run-iso":
        return run_qemu(state, backend, args.image, iso=True)
    if args.operation == "qemu-smoke":
        return run_qemu_smoke(state, backend, args.image)
    if args.operation == "test":
        return run_test(state, backend, args.image)
    if args.operation == "real-hardware":
        return run_real_hardware(state, backend, args.image)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
