from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

POWERSHELL_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script", help="PowerShell script to launch")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments for the script")
    parsed = parser.parse_args()

    script = Path(parsed.script)
    if not script.exists():
        raise SystemExit(f"Missing PowerShell script: {script}")

    command = [
        POWERSHELL_EXE,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *parsed.args,
    ]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    subprocess.Popen(
        command,
        cwd=str(script.parent),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
