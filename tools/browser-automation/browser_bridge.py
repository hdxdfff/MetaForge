from __future__ import annotations

import base64
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests
from websocket import create_connection


ROOT = Path(__file__).resolve().parent
PROFILE_ROOT = ROOT / "profiles"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local browser automation bridge.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--screenshot", default="")
    parser.add_argument("--selector", default="body")
    parser.add_argument("--profile", default="")
    parser.add_argument("--browser", default="")
    parser.add_argument("--proxy", default="")
    parser.add_argument("--wait-for", dest="wait_for", default="")
    parser.add_argument("--wait-until", dest="wait_until", default="domcontentloaded")
    parser.add_argument("--timeout", type=int, default=20000)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--login-session", action="store_true")
    return parser.parse_args()


def sanitize_profile(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in (name or "default"))


def resolve_browser(preferred: str) -> str:
    candidates = [preferred] if preferred else []
    candidates.extend(
        [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("No supported browser executable found.")


def free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_json_version(port: int, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=1.0)
            response.raise_for_status()
            payload = response.json()
            if payload.get("webSocketDebuggerUrl"):
                return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(0.2)
    raise RuntimeError(f"Timed out waiting for browser debugging endpoint on port {port}: {last_error}")


class CdpClient:
    def __init__(self, websocket_url: str) -> None:
        self._ws = create_connection(websocket_url, timeout=20)
        self._next_id = 1

    def close(self) -> None:
        self._ws.close()

    def send(self, method: str, params: dict[str, Any] | None = None, *, session_id: str | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {"id": self._next_id, "method": method}
        self._next_id += 1
        if params:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        self._ws.send(json.dumps(message))
        while True:
            raw = self._ws.recv()
            payload = json.loads(raw)
            if payload.get("id") == message["id"]:
                if "error" in payload:
                    raise RuntimeError(payload["error"])
                return payload.get("result", {})


def browser_launch_args(
    browser: str,
    user_data_dir: Path,
    *,
    headed: bool,
    proxy: str,
    remote_port: int,
    url: str,
) -> list[str]:
    args = [
        browser,
        f"--remote-debugging-port={remote_port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-translate",
        "--disable-features=Translate",
    ]
    if not headed:
        args.append("--headless=new")
    if proxy:
        args.append(f"--proxy-server={proxy}")
    args.append(url)
    return args


def launch_browser(browser: str, user_data_dir: Path, *, headed: bool, proxy: str, url: str) -> tuple[subprocess.Popen[str], int]:
    port = free_tcp_port()
    proc = subprocess.Popen(
        browser_launch_args(browser, user_data_dir, headed=headed, proxy=proxy, remote_port=port, url=url),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        text=True,
    )
    return proc, port


def collect_page_state(
    client: CdpClient,
    *,
    url: str,
    selector: str,
    wait_until: str,
    wait_for: str,
    timeout_ms: int,
    screenshot_path: str = "",
) -> dict[str, Any]:
    target = client.send("Target.createTarget", {"url": "about:blank"})
    target_id = target["targetId"]
    attach = client.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    session_id = attach["sessionId"]
    client.send("Page.enable", session_id=session_id)
    client.send("Runtime.enable", session_id=session_id)
    client.send("Page.navigate", {"url": url}, session_id=session_id)
    start = time.time()
    if wait_for:
        deadline = start + max(1.0, timeout_ms / 1000.0)
        while time.time() < deadline:
            result = client.send(
                "Runtime.evaluate",
                {
                    "expression": f"Boolean(document.querySelector({json.dumps(wait_for)}))",
                    "returnByValue": True,
                },
                session_id=session_id,
            )
            if bool(result.get("result", {}).get("value")):
                break
            time.sleep(0.2)
    deadline = start + max(1.0, timeout_ms / 1000.0)
    wait_until_key = (wait_until or "domcontentloaded").strip().lower()
    if wait_until_key in {"load", "networkidle"}:
        ready_states = {"complete"}
    else:
        ready_states = {"interactive", "complete"}
    while time.time() < deadline:
        ready = client.send(
            "Runtime.evaluate",
            {"expression": "document.readyState", "returnByValue": True},
            session_id=session_id,
        )
        ready_value = ready.get("result", {}).get("value")
        if ready_value in ready_states:
            if ready_value == "complete" or wait_until_key == "domcontentloaded":
                break
        time.sleep(0.1)
    state = client.send(
        "Runtime.evaluate",
        {
            "expression": f"""
(() => {{
  const selector = {json.dumps(selector)};
  const node = document.querySelector(selector) || document.body || document.documentElement;
  const links = Array.from(document.querySelectorAll('a')).slice(0, 20).map((a) => ({{
    text: (a.innerText || '').trim().slice(0, 120),
    href: a.href || ''
  }}));
  return {{
    ok: true,
    url: location.href,
    title: document.title || '',
    bodyText: (node && (node.innerText || node.textContent || '')) ? String(node.innerText || node.textContent || '').slice(0, 8000) : '',
    links
  }};
}})()
""".strip(),
            "returnByValue": True,
        },
        session_id=session_id,
    )
    payload = state.get("result", {}).get("value", {})
    if not isinstance(payload, dict):
        payload = {}
    if not payload.get("ok"):
        payload["ok"] = True
    payload["waitUntil"] = wait_until
    if screenshot_path:
        capture_screenshot(client, session_id, screenshot_path)
    return payload


def capture_screenshot(client: CdpClient, session_id: str, path: str) -> None:
    if not path:
        return
    screenshot = client.send(
        "Page.captureScreenshot",
        {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
        },
        session_id=session_id,
    )
    data = screenshot.get("data")
    if not isinstance(data, str) or not data:
        raise RuntimeError("Browser screenshot capture failed.")
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(data))


def write_output(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    browser = resolve_browser(args.browser)
    profile = sanitize_profile(args.profile or "default")
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    user_data_dir = PROFILE_ROOT / profile
    user_data_dir.mkdir(parents=True, exist_ok=True)
    timeout_ms = int(args.timeout)

    if args.login_session:
        proc, _port = launch_browser(
            browser,
            user_data_dir,
            headed=True,
            proxy=args.proxy or os.getenv("ORCH_NETWORK_PROXY_URL", ""),
            url=args.url,
        )
        try:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "message": "Login session opened. Sign in manually, then close the browser window to persist the session.",
                        "browser": browser,
                        "profile": profile,
                        "profileDir": str(user_data_dir),
                        "url": args.url,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return proc.wait()
        finally:
            if proc.poll() is None:
                proc.terminate()
    proc, port = launch_browser(
        browser,
        user_data_dir,
        headed=args.headed,
        proxy=args.proxy or os.getenv("ORCH_NETWORK_PROXY_URL", ""),
        url=args.url,
    )
    try:
        version = wait_for_json_version(port, timeout=max(5.0, timeout_ms / 1000.0))
        client = CdpClient(version["webSocketDebuggerUrl"])
        try:
            payload = collect_page_state(
                client,
                url=args.url,
                selector=args.selector,
                wait_until=args.wait_until,
                wait_for=args.wait_for,
                timeout_ms=timeout_ms,
                screenshot_path=args.screenshot,
            )
        finally:
            client.close()
        payload.update(
            {
                "browser": browser,
                "profile": profile,
                "profileDir": str(user_data_dir),
                "proxyServer": args.proxy or os.getenv("ORCH_NETWORK_PROXY_URL", "") or None,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        write_output(args.out, payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
