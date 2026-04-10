from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OPENCODE_ROOT = ROOT / "tools" / "opencode-home"
OPENCODE_CMD = OPENCODE_ROOT / "opencode.cmd"
NODE_ROOT = ROOT / "tools" / "node-v22.22.1-win-x64"
WORKSPACE = ROOT / "opencode-workspace"
STATE_ROOT = ROOT / "oi-state-opencode"


def main() -> int:
    env = os.environ.copy()
    env["OPENCODE_ROOT"] = str(OPENCODE_ROOT)
    env["NODE_ROOT"] = str(NODE_ROOT)
    env["OPENCODE_WORKSPACE"] = str(WORKSPACE)
    env["USERPROFILE"] = str(STATE_ROOT / "userprofile")
    env["HOME"] = str(STATE_ROOT / "userprofile")
    env["XDG_DATA_HOME"] = str(STATE_ROOT / "xdg")
    env["HTTP_PROXY"] = "http://127.0.0.1:7890"
    env["HTTPS_PROXY"] = "http://127.0.0.1:7890"
    env["ALL_PROXY"] = "http://127.0.0.1:7890"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["PATH"] = f"{NODE_ROOT};{env.get('PATH', '')}"
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:] or [str(WORKSPACE)]
    completed = subprocess.run(["cmd", "/c", str(OPENCODE_CMD), *args], env=env, cwd=str(WORKSPACE))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
