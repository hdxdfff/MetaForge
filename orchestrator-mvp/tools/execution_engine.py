from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
if os.name == "nt":
    LOG_DIR = Path(r"D:\codex\logs")
else:
    LOG_DIR = DATA / "logs"
EXECUTION_LOG = LOG_DIR / "execution.log"
WORKER_LOG = LOG_DIR / "worker.log"
DAEMON_LOG = LOG_DIR / "daemon.log"


def _windowless_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _detached_flags(*, breakaway: bool = True) -> int:
    if os.name != "nt":
        return 0
    flags = _windowless_flags()
    if breakaway:
        flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return flags


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(message: str, *, channel: str = "execution") -> None:
    _ensure_log_dir()
    path = {
        "execution": EXECUTION_LOG,
        "worker": WORKER_LOG,
        "daemon": DAEMON_LOG,
    }.get(channel, EXECUTION_LOG)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_hidden(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    capture_output: bool = True,
    log_channel: str = "execution",
) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        capture_output=capture_output,
        text=True,
        check=False,
        creationflags=_windowless_flags(),
        stdin=subprocess.DEVNULL,
    )
    stdout = completed.stdout if capture_output and completed.stdout is not None else ""
    stderr = completed.stderr if capture_output and completed.stderr is not None else ""
    if stdout:
        log(stdout, channel=log_channel)
    if stderr:
        log(stderr, channel=log_channel)
    return CommandResult(completed.returncode, stdout or "", stderr or "")


def spawn_hidden(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    log_channel: str = "execution",
) -> subprocess.Popen[str]:
    _ensure_log_dir()
    stdout = subprocess.DEVNULL
    stderr = subprocess.DEVNULL
    if log_channel == "daemon":
        stderr = subprocess.DEVNULL
    base_kwargs = dict(
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        close_fds=True,
        text=True,
    )
    try:
        return subprocess.Popen(
            list(command),
            creationflags=_detached_flags(breakaway=True),
            **base_kwargs,
        )
    except PermissionError:
        return subprocess.Popen(
            list(command),
            creationflags=_detached_flags(breakaway=False),
            **base_kwargs,
        )


def python_command(script: Path, *args: str, interpreter: Path | None = None) -> list[str]:
    python_exe = interpreter or (ROOT.parent / "tools" / "python311-embed" / "python.exe")
    return [str(python_exe), str(script), *args]


def powershell_command(script: Path, *args: str, executable: str | None = None) -> list[str]:
    shell = executable or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
