from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import webview

ROOT = Path(__file__).resolve().parent
APP_HOST = "127.0.0.1"
APP_TITLE = "AI Command Console"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
VENV_SITE_PACKAGES = ROOT / ".venv" / "Lib" / "site-packages"
EMBEDDED_PYTHON = ROOT.parent / "tools" / "python311-embed" / "python.exe"
BOOTSTRAP_RUNNER = ROOT / "bootstrap_runner.py"


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((APP_HOST, 0))
        return sock.getsockname()[1]


def wait_for_server(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.4)
    raise RuntimeError(f"Backend did not start in time: {last_error}")


def _backend_command(port: int) -> list[str]:
    if EMBEDDED_PYTHON.exists() and BOOTSTRAP_RUNNER.exists():
        return [
            str(EMBEDDED_PYTHON),
            str(BOOTSTRAP_RUNNER),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            APP_HOST,
            "--port",
            str(port),
        ]
    if VENV_PYTHON.exists():
        return [str(VENV_PYTHON), "-m", "uvicorn", "app.main:app", "--host", APP_HOST, "--port", str(port)]
    raise FileNotFoundError("No usable Python runtime found for backend startup.")


def start_backend(port: int) -> subprocess.Popen[str]:
    command = _backend_command(port)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        creationflags=creationflags,
    )


def main() -> int:
    port = find_free_port()
    backend = start_backend(port)
    try:
        wait_for_server(f"http://{APP_HOST}:{port}/api/health")
        webview.create_window(APP_TITLE, f"http://{APP_HOST}:{port}/", width=1540, height=980, min_size=(1200, 760))
        webview.start()
        return 0
    except Exception as exc:
        print(f"Failed to launch desktop app: {exc}", file=sys.stderr)
        return 1
    finally:
        if backend.poll() is None:
            backend.terminate()
            try:
                backend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend.kill()


if __name__ == "__main__":
    raise SystemExit(main())
