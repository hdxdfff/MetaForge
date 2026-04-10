from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "opencode-workspace"
FAST_WORKSPACE = ROOT / "opencode-workspace-fast"
OPENCODE_CMD = ROOT / "opencode.cmd"
OPENCODE_FAST_CMD = ROOT / "opencode-fast.cmd"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestrator-mvp"))
sys.path.insert(0, str(ROOT / "orchestrator-mvp" / ".venv" / "Lib" / "site-packages"))

from tools.execution_engine import spawn_hidden


def main() -> int:
    raw_args = sys.argv[1:]
    show_status = "--status" in raw_args or "--with-status" in raw_args
    fast_mode = "--fast" in raw_args or "--lite" in raw_args
    args = [
        arg
        for arg in raw_args
        if arg not in {"--no-status", "--with-status", "--status", "--fast", "--lite"}
    ]
    if show_status:
        print("== AI Meta Factory Status ==")
        factoryctl = str(ROOT / "factoryctl.cmd")
        subprocess.run(["cmd", "/c", factoryctl, "daemon-status"], check=False)
        subprocess.run(["cmd", "/c", factoryctl, "control-layer-status"], check=False)
        subprocess.run(["cmd", "/c", factoryctl, "engineering-os-status"], check=False)
        subprocess.run(["cmd", "/c", factoryctl, "lab-status"], check=False)
        subprocess.run(["cmd", "/c", factoryctl, "tool-stack-status"], check=False)
        print("")
    target_cmd = OPENCODE_FAST_CMD if fast_mode and OPENCODE_FAST_CMD.exists() else OPENCODE_CMD
    target_workspace = FAST_WORKSPACE if fast_mode and OPENCODE_FAST_CMD.exists() else WORKSPACE
    target_workspace.mkdir(parents=True, exist_ok=True)
    if target_cmd.exists():
        spawn_hidden(["cmd", "/c", str(target_cmd), *args], cwd=target_workspace, log_channel="worker")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
