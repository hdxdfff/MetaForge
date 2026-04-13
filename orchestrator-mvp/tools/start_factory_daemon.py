from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.execution_engine import DAEMON_LOG, ROOT, log, spawn_hidden

DATA = ROOT / "data"
DAEMON_SCRIPT = ROOT / "tools" / "factory_daemon.py"
PID_PATH = DATA / "factory_daemon.pid"
STATUS_PATH = DATA / "factory_daemon_state.json"


def _existing_pid() -> int | None:
    if not PID_PATH.exists():
        return None
    try:
        raw = PID_PATH.read_text(encoding="utf-8-sig").strip()
        if not raw:
            return None
        pid = int(raw)
    except Exception:
        return None
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return None
    return pid


def _confirm_started(pid: int, timeout_seconds: int) -> int:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if STATUS_PATH.exists():
            try:
                state = json.loads(STATUS_PATH.read_text(encoding="utf-8-sig"))
            except Exception:
                state = {}
            if int(state.get("pid") or 0) == pid and state.get("started_at"):
                PID_PATH.write_text(str(pid), encoding="utf-8")
                return pid
        time.sleep(0.5)
    return pid


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the factory daemon without showing a window.")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--meta-every", type=int, default=5)
    parser.add_argument("--evolution-every", type=int, default=10)
    parser.add_argument("--startup-timeout-seconds", type=int, default=12)
    args = parser.parse_args()

    existing = _existing_pid()
    if existing is not None:
        print(existing)
        return 0

    command = [
        str(ROOT.parent / "tools" / "python311-embed" / "python.exe"),
        str(DAEMON_SCRIPT),
        "--interval",
        str(args.interval),
        "--meta-every",
        str(args.meta_every),
        "--evolution-every",
        str(args.evolution_every),
    ]
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    proc = spawn_hidden(command, cwd=ROOT, env=env, log_channel="daemon")
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    pid = _confirm_started(proc.pid, args.startup_timeout_seconds)
    log(f"factory daemon launched pid={pid}", channel="daemon")
    print(pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
