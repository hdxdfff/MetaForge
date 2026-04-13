from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED = ROOT.parent / 'tools' / 'python311-embed' / 'python.exe'
BOOTSTRAP = ROOT / 'bootstrap_runner.py'
LOG_PATH = ROOT / 'data' / 'network_keepalive.log'
APP_HOST = os.environ.get('ORCH_WEB_HOST', '127.0.0.1')
APP_PORT = int(os.environ.get('ORCH_WEB_PORT', '8787'))
BASE = f'http://{APP_HOST}:{APP_PORT}'
HEALTH_URL = f'{BASE}/api/health'
NETWORK_URL = f'{BASE}/api/network/state'
RELOAD_URL = f'{BASE}/api/network/reload'
ROTATE_URL = f'{BASE}/api/network/rotate-proxy'


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with LOG_PATH.open('a', encoding='utf-8') as handle:
        handle.write(f'[{stamp}] {message}\n')


def read_json(url: str, *, method: str = 'GET') -> dict:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode('utf-8'))


def backend_running() -> bool:
    try:
        data = read_json(HEALTH_URL)
        return data.get('status') == 'ok'
    except Exception:
        return False


def start_backend() -> None:
    if not EMBEDDED.exists() or not BOOTSTRAP.exists():
        raise FileNotFoundError('Missing embedded runtime or bootstrap runner.')
    command = [
        str(EMBEDDED),
        str(BOOTSTRAP),
        '-m',
        'uvicorn',
        'app.main:app',
        '--host',
        APP_HOST,
        '--port',
        str(APP_PORT),
    ]
    subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, 'PYTHONUTF8': '1'})
    log('Backend restart issued.')


def one_pass() -> int:
    if not backend_running():
        log('Backend unreachable. Attempting restart.')
        start_backend()
        time.sleep(4)
    try:
        read_json(HEALTH_URL)
        network = read_json(NETWORK_URL)
        log(f"Health ok. network={network.get('status')} proxy={network.get('current_proxy')}")
        if network.get('status') == 'offline':
            read_json(RELOAD_URL, method='POST')
            time.sleep(1)
            network = read_json(NETWORK_URL)
            if network.get('status') == 'offline':
                read_json(ROTATE_URL, method='POST')
                log('Network offline after reload. Rotated proxy.')
        return 0
    except urllib.error.URLError as exc:
        log(f'Keepalive probe failed: {exc}')
        return 1
    except Exception as exc:
        log(f'Keepalive error: {exc}')
        return 1


def main() -> int:
    loop = '--loop' in sys.argv
    interval = 60
    if '--interval' in sys.argv:
        idx = sys.argv.index('--interval')
        interval = int(sys.argv[idx + 1])
    if not loop:
        return one_pass()
    while True:
        one_pass()
        time.sleep(interval)


if __name__ == '__main__':
    raise SystemExit(main())
