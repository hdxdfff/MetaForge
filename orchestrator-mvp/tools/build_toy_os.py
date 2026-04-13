from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json, atomic_write_text


def run_command(command: list[str], cwd: Path) -> dict[str, object]:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": "timeout",
        }
    return {
        "ok": proc.returncode == 0,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def discover_c_sources(target: Path) -> list[Path]:
    sources: list[Path] = []
    kernel = target / "kernel.c"
    if kernel.exists():
        sources.append(kernel)
    src_dir = target / "src"
    if src_dir.exists():
        sources.extend(sorted(src_dir.glob("*.c")))
    return sources


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_build_log(build_dir: Path, checks: list[dict[str, object]]) -> None:
    lines = []
    for check in checks:
        command = " ".join(str(item) for item in check.get("command", []))
        lines.append(f"status={'ok' if check.get('ok') else 'failed'} command={command}")
        stdout = str(check.get("stdout") or "").strip()
        stderr = str(check.get("stderr") or "").strip()
        if stdout:
            lines.append(f"stdout: {stdout}")
        if stderr:
            lines.append(f"stderr: {stderr}")
        lines.append("")
    atomic_write_text(build_dir / "build.log", "\n".join(lines).strip() + "\n")


def _write_sha(target: Path) -> None:
    digest = _sha256(target)
    atomic_write_text(target.parent / "artifact.sha256", f"{digest}  {target.name}\n")


def _discover_docker() -> tuple[str | None, bool, str | None]:
    docker = shutil.which("docker")
    if not docker:
        return None, False, "docker client not detected"
    try:
        probe = subprocess.run(
            [docker, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return docker, False, str(exc)
    daemon_ready = probe.returncode == 0 and bool((probe.stdout or "").strip())
    detail = None if daemon_ready else (probe.stderr or probe.stdout or "docker daemon unavailable").strip()
    return docker, daemon_ready, detail


def _run_docker_command(command: list[str], cwd: Path, *, timeout: int = 600) -> dict[str, object]:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "command": command,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "returncode": None,
            "stdout": exc.stdout or "",
            "stderr": "timeout",
        }
    return {
        "ok": proc.returncode == 0,
        "command": command,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _docker_delegate_build(docker: str, target: Path) -> dict[str, object]:
    image = "toyos-managed-toolchain"
    build_image = _run_docker_command([docker, "build", "-t", image, "-f", "Dockerfile.build", "."], target, timeout=1200)
    if not build_image.get("ok"):
        return {
            "ok": False,
            "stage": "docker-build-image",
            "command": build_image.get("command"),
            "stdout": build_image.get("stdout", ""),
            "stderr": build_image.get("stderr", ""),
            "returncode": build_image.get("returncode"),
        }
    codex_mount = str(ROOT.parent).replace("\\", "/")
    cmd = [
        docker,
        "run",
        "--rm",
        "-e",
        "TOYOS_FORCE_DOCKER_MANAGED=1",
        "-e",
        "TOYOS_BUILD_QUIET=1",
        "-v",
        f"{codex_mount}:/codex",
        "-w",
        "/codex/generated/toy-os-demo",
        image,
        "python3",
        "/codex/orchestrator-mvp/tools/build_toy_os.py",
        "--target",
        "/codex/generated/toy-os-demo",
        "--managed-backend",
        "docker",
    ]
    run = _run_docker_command(cmd, target, timeout=1200)
    return {
        "ok": bool(run.get("ok")),
        "stage": "docker-managed-build",
        "command": run.get("command"),
        "stdout": run.get("stdout", ""),
        "stderr": run.get("stderr", ""),
        "returncode": run.get("returncode"),
    }


def _resolve_managed_backend(requested: str, host_ready: bool, docker_ready: bool) -> str:
    if os.environ.get("TOYOS_FORCE_DOCKER_MANAGED") == "1":
        return "docker"
    if requested == "host":
        if host_ready:
            return "host"
        if docker_ready:
            return "docker"
        return "unavailable"
    if requested == "docker":
        if docker_ready:
            return "docker"
        if host_ready:
            return "host"
        return "unavailable"
    if host_ready:
        return "host"
    if docker_ready:
        return "docker"
    return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or validate a toy OS scaffold")
    parser.add_argument("--target", required=True, help="Target directory to inspect")
    parser.add_argument(
        "--managed-backend",
        choices=["auto", "docker", "host"],
        default="auto",
        help="Preferred managed execution path for report metadata",
    )
    args = parser.parse_args()
    emit_summary = os.environ.get("TOYOS_BUILD_QUIET") != "1"

    target = Path(args.target).resolve()
    build_dir = target / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    cross_gcc = shutil.which("i686-elf-gcc")
    host_gcc = shutil.which("gcc")
    cross_ld = shutil.which("i686-elf-ld")
    host_ld = shutil.which("ld")
    docker, docker_daemon, docker_detail = _discover_docker()

    compiler = cross_gcc or host_gcc
    linker = cross_ld or host_ld
    using_cross = bool(cross_gcc and cross_ld)
    host_build_ready = bool(shutil.which("nasm") and compiler and linker)
    managed_backend = _resolve_managed_backend(args.managed_backend, host_build_ready, docker_daemon)

    if managed_backend == "docker" and not host_build_ready:
        if not docker or not docker_daemon:
            report = {
                "target": str(target),
                "toolchain": {
                    "nasm": shutil.which("nasm"),
                    "gcc": host_gcc,
                    "i686_elf_gcc": cross_gcc,
                    "i686_elf_ld": cross_ld,
                    "ld": host_ld,
                    "qemu_system_i386": shutil.which("qemu-system-i386"),
                    "make": shutil.which("make"),
                    "docker": docker,
                },
                "checks": [],
                "build_ready": False,
                "host_build_ready": host_build_ready,
                "build_success": False,
                "link_mode": "docker-managed",
                "c_source_count": len(discover_c_sources(target)),
                "managed_resolution": {
                    "host_build_tools_present": host_build_ready,
                    "docker_client_present": bool(docker),
                    "docker_daemon_ready": docker_daemon,
                    "docker_detail": docker_detail,
                    "recommended_backend": managed_backend,
                },
                "evidence": {
                    "build_log": str(build_dir / "build.log"),
                    "sha256": str(build_dir / "artifact.sha256"),
                },
                "delegation": {
                    "status": "unavailable",
                    "reason": docker_detail or "docker client or daemon unavailable",
                },
            }
            atomic_write_json(target / "build-report.json", report)
            if emit_summary:
                print(f"build report: {target / 'build-report.json'}")
                print("build ready: False")
                print("build success: False")
                print("link mode: docker-managed")
                print(f"recommended backend: {managed_backend}")
                print(f"c sources: {report['c_source_count']}")
                print(f"delegation: {report['delegation']['reason']}")
            return 0
        delegation = _docker_delegate_build(docker, target)
        report_path = target / "build-report.json"
        if emit_summary:
            print(f"build report: {report_path}")
            print("build ready: True")
            print(f"build success: {delegation.get('ok')}")
            print("link mode: docker-managed")
            print(f"recommended backend: {managed_backend}")
            print(f"c sources: {len(discover_c_sources(target))}")
            if not delegation.get("ok") and delegation.get("stderr"):
                print(delegation["stderr"], file=sys.stderr)
        return 0 if delegation.get("ok") else 1
    report: dict[str, object] = {
        "target": str(target),
        "toolchain": {
            "nasm": shutil.which("nasm"),
            "gcc": host_gcc,
            "i686_elf_gcc": cross_gcc,
            "i686_elf_ld": cross_ld,
            "ld": host_ld,
            "qemu_system_i386": shutil.which("qemu-system-i386"),
            "make": shutil.which("make"),
            "docker": docker,
        },
        "checks": [],
        "build_ready": False,
        "host_build_ready": host_build_ready,
        "build_success": False,
        "link_mode": "cross" if using_cross else ("docker-managed" if managed_backend == "docker" else "host-fallback"),
        "c_source_count": 0,
        "managed_resolution": {
            "host_build_tools_present": host_build_ready,
            "docker_client_present": bool(docker),
            "docker_daemon_ready": docker_daemon,
            "docker_detail": docker_detail,
            "recommended_backend": managed_backend,
        },
        "evidence": {
            "build_log": str(build_dir / "build.log"),
            "sha256": str(build_dir / "artifact.sha256"),
        },
    }

    checks: list[dict[str, object]] = []
    cflags = ["-std=gnu99", "-ffreestanding", "-O2", "-Wall", "-Wextra", "-Iinclude"]
    if not using_cross:
        cflags.append("-m32")

    boot_asm = target / "boot.asm"
    isr_stub = target / "src" / "isr_stub.asm"
    linker_ld_file = target / "linker.ld"

    if shutil.which("nasm") and boot_asm.exists():
        checks.append(run_command(["nasm", "-f", "elf32", "boot.asm", "-o", str(build_dir / "boot.o")], target))
    else:
        checks.append({"ok": False, "command": ["nasm", "boot.asm"], "returncode": None, "stdout": "", "stderr": "nasm unavailable or boot.asm missing"})

    if shutil.which("nasm") and isr_stub.exists():
        checks.append(run_command(["nasm", "-f", "elf32", "src/isr_stub.asm", "-o", str(build_dir / "isr_stub.o")], target))
    else:
        checks.append({"ok": False, "command": ["nasm", "src/isr_stub.asm"], "returncode": None, "stdout": "", "stderr": "nasm unavailable or src/isr_stub.asm missing"})

    c_sources = discover_c_sources(target)
    report["c_source_count"] = len(c_sources)
    c_objects: list[Path] = []
    if compiler:
        compiler_name = Path(compiler).name
        for source in c_sources:
            output = build_dir / f"{source.stem}.o"
            result = run_command([compiler_name, *cflags, "-c", str(source.relative_to(target)), "-o", str(output)], target)
            checks.append(result)
            if result["ok"]:
                c_objects.append(output)
    else:
        checks.append({"ok": False, "command": ["gcc"], "returncode": None, "stdout": "", "stderr": "no compiler available"})

    if linker and linker_ld_file.exists() and (build_dir / "boot.o").exists() and (build_dir / "isr_stub.o").exists() and len(c_objects) == len(c_sources) and c_sources:
        link_command = [Path(linker).name, "-T", "linker.ld", "-nostdlib", "-o", str(build_dir / "kernel.bin")]
        if not using_cross:
            link_command.extend(["-m", "elf_i386"])
        link_command.extend([str(build_dir / "boot.o"), str(build_dir / "isr_stub.o"), *[str(obj) for obj in c_objects]])
        checks.append(run_command(link_command, target))
    else:
        checks.append({"ok": False, "command": [Path(linker).name if linker else "ld"], "returncode": None, "stdout": "", "stderr": "linker unavailable or prerequisites missing"})

    _write_build_log(build_dir, checks)
    report["checks"] = checks
    report["build_ready"] = bool(host_build_ready or docker_daemon)
    report["prebuilt_artifact_present"] = bool((build_dir / "kernel.bin").exists())
    report["build_success"] = bool(checks and checks[-1].get("ok"))

    if report["prebuilt_artifact_present"]:
        _write_sha(build_dir / "kernel.bin")

    report_path = target / "build-report.json"
    atomic_write_json(report_path, report)

    if emit_summary:
        print(f"build report: {report_path}")
        print(f"build ready: {report['build_ready']}")
        print(f"build success: {report['build_success']}")
        print(f"link mode: {report['link_mode']}")
        print(f"recommended backend: {(report['managed_resolution'] or {}).get('recommended_backend')}")
        print(f"c sources: {report['c_source_count']}")
        for check in checks:
            command = " ".join(str(item) for item in check["command"])
            status = "ok" if check["ok"] else "failed"
            print(f"- {status}: {command}")
            stderr = str(check.get("stderr") or "").strip()
            if stderr:
                print(f"  stderr: {stderr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
