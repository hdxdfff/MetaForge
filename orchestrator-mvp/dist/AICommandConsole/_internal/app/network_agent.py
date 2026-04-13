from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from .io_utils import atomic_write_json
from typing import Any, Awaitable, Callable
from uuid import uuid4

BrowserReadFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
BrowserLoginFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class NetworkAgent:
    def __init__(
        self,
        data_dir: Path,
        *,
        probe_urls: list[str],
        poll_seconds: int,
        browser_read: BrowserReadFn,
        browser_login_session: BrowserLoginFn,
        proxy_url: str = "",
        proxy_candidates: list[str] | None = None,
        no_proxy: list[str] | None = None,
    ) -> None:
        self._data_dir = data_dir
        self._probe_urls = probe_urls
        self._poll_seconds = poll_seconds
        self._browser_read = browser_read
        self._browser_login_session = browser_login_session
        self._proxy_url = proxy_url.strip()
        self._proxy_candidates = [item.strip() for item in (proxy_candidates or []) if item.strip()]
        if self._proxy_url and self._proxy_url not in self._proxy_candidates:
            self._proxy_candidates.insert(0, self._proxy_url)
        self._proxy_index = 0
        self._no_proxy = [item.strip().lower() for item in (no_proxy or []) if item.strip()]
        self._queue_file = data_dir / 'external_tasks.json'
        self._state_file = data_dir / 'network_state.json'
        self._cache_dir = data_dir.parent / 'cache' / 'external'
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: list[dict[str, Any]] = []
        self._state: dict[str, Any] = {
            'status': 'starting',
            'last_probe_at': None,
            'last_online_at': None,
            'last_error': None,
            'queue_size': 0,
            'cache_dir': str(self._cache_dir),
            'download_broker': 'local-urllib-cache',
            'proxy_url': self._proxy_url or None,
            'proxy_candidates': self._proxy_candidates,
            'proxy_index': self._proxy_index,
            'poll_seconds': poll_seconds,
        }
        self._loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._load()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._state['status'] = 'starting'
        self._persist()
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self._state['status'] = 'stopped'
        self._persist()

    def refresh_config(
        self,
        *,
        probe_urls: list[str] | None = None,
        poll_seconds: int | None = None,
        proxy_url: str | None = None,
        proxy_candidates: list[str] | None = None,
        no_proxy: list[str] | None = None,
    ) -> dict[str, Any]:
        if probe_urls is not None:
            self._probe_urls = probe_urls
        if poll_seconds is not None:
            self._poll_seconds = poll_seconds
            self._state['poll_seconds'] = poll_seconds
        if proxy_url is not None:
            self._proxy_url = proxy_url.strip()
        if proxy_candidates is not None:
            self._proxy_candidates = [item.strip() for item in proxy_candidates if item.strip()]
            if self._proxy_url and self._proxy_url not in self._proxy_candidates:
                self._proxy_candidates.insert(0, self._proxy_url)
            self._proxy_index = 0
        if no_proxy is not None:
            self._no_proxy = [item.strip().lower() for item in no_proxy if item.strip()]
        self._state['proxy_url'] = self.current_proxy()
        self._state['proxy_candidates'] = self._proxy_candidates
        self._state['proxy_index'] = self._proxy_index
        self._persist()
        return self.get_state()

    def current_proxy(self) -> str | None:
        if self._proxy_candidates:
            idx = max(0, min(self._proxy_index, len(self._proxy_candidates) - 1))
            return self._proxy_candidates[idx]
        return self._proxy_url or None

    def rotate_proxy(self) -> str | None:
        if not self._proxy_candidates:
            return self.current_proxy()
        self._proxy_index = (self._proxy_index + 1) % len(self._proxy_candidates)
        self._state['proxy_index'] = self._proxy_index
        self._state['proxy_url'] = self.current_proxy()
        self._persist()
        return self.current_proxy()

    def get_state(self) -> dict[str, Any]:
        state = dict(self._state)
        state['queue_size'] = len(self._tasks)
        state['queued_types'] = [task['task_type'] for task in self._tasks[:10]]
        state['current_proxy'] = self.current_proxy()
        return state

    def list_tasks(self) -> list[dict[str, Any]]:
        return list(reversed(self._tasks))

    async def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        task_type = str(payload.get('task_type') or '').strip()
        if not task_type:
            raise ValueError('Missing task_type')
        task = {
            'id': payload.get('id') or f"ext-{uuid4().hex[:10]}",
            'task_type': task_type,
            'status': 'queued',
            'created_at': utc_iso(),
            'updated_at': utc_iso(),
            'attempts': 0,
            'max_attempts': int(payload.get('max_attempts') or 8),
            'payload': payload.get('payload') or {},
            'last_error': None,
            'result': None,
        }
        self._tasks.append(task)
        self._persist()
        return task

    async def _run_loop(self) -> None:
        while self._running:
            online, error = await asyncio.to_thread(self._probe_connectivity)
            self._state['last_probe_at'] = utc_iso()
            self._state['queue_size'] = len(self._tasks)
            if online:
                self._state['status'] = 'online'
                self._state['last_online_at'] = utc_iso()
                self._state['last_error'] = None
                await self._drain_queue()
            else:
                self._state['status'] = 'offline'
                self._state['last_error'] = error
                self.rotate_proxy()
            self._persist()
            await asyncio.sleep(self._poll_seconds)

    def _probe_connectivity(self) -> tuple[bool, str | None]:
        errors: list[str] = []
        for url in self._probe_urls:
            try:
                request = urllib.request.Request(url, method='HEAD')
                opener = self._build_opener(url)
                with opener.open(request, timeout=6) as response:
                    if 200 <= response.status < 500:
                        return True, None
            except Exception as exc:
                errors.append(f'{url}: {exc}')
        return False, ' | '.join(errors[:3]) if errors else 'No probe URL configured.'

    async def _drain_queue(self) -> None:
        for task in self._tasks:
            if task['status'] == 'completed':
                continue
            if task['attempts'] >= task['max_attempts']:
                task['status'] = 'failed'
                task['updated_at'] = utc_iso()
                continue
            try:
                task['status'] = 'running'
                task['attempts'] += 1
                task['updated_at'] = utc_iso()
                task['result'] = await self._execute_task(task)
                task['status'] = 'completed'
                task['last_error'] = None
                task['updated_at'] = utc_iso()
            except Exception as exc:
                task['status'] = 'queued'
                task['last_error'] = str(exc)
                task['updated_at'] = utc_iso()
            self._persist()

    async def _execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task['payload'])
        if self.current_proxy() and "proxy" not in payload:
            payload["proxy"] = self.current_proxy()
        task_type = task['task_type']
        if task_type == 'http_get':
            return await asyncio.to_thread(self._download_http, payload)
        if task_type == 'browser_read':
            force_refresh = bool(payload.get('force_refresh'))
            cache_path = self._cache_json_path('browser-read', payload)
            if cache_path.exists() and not force_refresh:
                return json.loads(cache_path.read_text(encoding='utf-8'))
            result = await self._browser_read(payload)
            atomic_write_json(cache_path, result)
            return result
        if task_type == 'browser_login_session':
            return await self._browser_login_session(payload)
        raise ValueError(f'Unsupported external task type: {task_type}')

    def _download_http(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get('url') or '').strip()
        if not url:
            raise ValueError('Missing url')
        target_name = str(payload.get('target_name') or Path(url).name or f"download-{uuid4().hex[:8]}.bin")
        target_path = self._cache_dir / target_name
        force_refresh = bool(payload.get('force_refresh'))
        if target_path.exists() and not force_refresh:
            return {
                'ok': True,
                'url': url,
                'target_path': str(target_path),
                'size_bytes': target_path.stat().st_size,
                'timestamp': utc_iso(),
                'cache_hit': True,
            }
        opener = self._build_opener(url)
        with opener.open(url, timeout=30) as response, target_path.open('wb') as handle:
            shutil.copyfileobj(response, handle)
        return {
            'ok': True,
            'url': url,
            'target_path': str(target_path),
            'size_bytes': target_path.stat().st_size,
            'timestamp': utc_iso(),
            'cache_hit': False,
        }




    def _cache_key(self, prefix: str, payload: dict[str, Any]) -> str:
        material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(f"{prefix}:{material}".encode('utf-8')).hexdigest()
        return digest

    def _cache_json_path(self, prefix: str, payload: dict[str, Any]) -> Path:
        return self._cache_dir / f"{prefix}-{self._cache_key(prefix, payload)[:16]}.json"

    def _build_opener(self, url: str) -> urllib.request.OpenerDirector:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or '').lower()
        proxy = self.current_proxy()
        if self._should_bypass_proxy(host) or not proxy:
            return urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))

    def _should_bypass_proxy(self, host: str) -> bool:
        if not host:
            return True
        return any(host == item or host.endswith(f'.{item}') for item in self._no_proxy)

    def _load(self) -> None:
        if self._queue_file.exists():
            try:
                self._tasks = json.loads(self._queue_file.read_text(encoding='utf-8'))
            except Exception:
                self._tasks = []
        if self._state_file.exists():
            try:
                self._state.update(json.loads(self._state_file.read_text(encoding='utf-8')))
            except Exception:
                pass

    def _persist(self) -> None:
        atomic_write_json(self._queue_file, self._tasks)
        atomic_write_json(self._state_file, self._state)
