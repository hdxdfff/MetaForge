from __future__ import annotations

import importlib.util
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from openai import OpenAI

from .config import settings
from .io_utils import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_PATH = DATA / "provider_gateway_state.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass(frozen=True)
class ProviderCandidate:
    base_url: str
    proxy: str = ""

    @property
    def key(self) -> str:
        return f"{self.base_url}|{self.proxy}"


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"updated_at": None, "providers": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"updated_at": None, "providers": {}}


class ProviderGateway:
    def __init__(self) -> None:
        self._state = _load_state()

    def responses_create(
        self,
        *,
        provider_name: str,
        api_key: str,
        default_base_url: str,
        base_url_candidates: list[str],
        default_proxy: str,
        proxy_candidates: list[str],
        timeout_seconds: float,
        request_kwargs: dict[str, Any],
    ) -> Any:
        return self._invoke(
            provider_name=provider_name,
            api_key=api_key,
            default_base_url=default_base_url,
            base_url_candidates=base_url_candidates,
            default_proxy=default_proxy,
            proxy_candidates=proxy_candidates,
            timeout_seconds=timeout_seconds,
            operation=lambda client: client.responses.create(**request_kwargs),
        )

    def chat_completions_create(
        self,
        *,
        provider_name: str,
        api_key: str,
        default_base_url: str,
        base_url_candidates: list[str],
        default_proxy: str,
        proxy_candidates: list[str],
        timeout_seconds: float,
        request_kwargs: dict[str, Any],
    ) -> Any:
        return self._invoke(
            provider_name=provider_name,
            api_key=api_key,
            default_base_url=default_base_url,
            base_url_candidates=base_url_candidates,
            default_proxy=default_proxy,
            proxy_candidates=proxy_candidates,
            timeout_seconds=timeout_seconds,
            operation=lambda client: client.chat.completions.create(**request_kwargs),
        )

    def get_state(self) -> dict[str, Any]:
        self._state = _load_state()
        state = self._state
        snapshot = {
            "updated_at": state.get("updated_at"),
            "enabled": settings.provider_gateway_enabled,
            "route_max_attempts": settings.provider_route_max_attempts,
            "route_backoff_seconds": settings.provider_route_backoff_seconds,
            "circuit_failure_threshold": settings.provider_circuit_failure_threshold,
            "circuit_cooldown_seconds": settings.provider_circuit_cooldown_seconds,
            "providers": {},
        }
        for provider_name, provider_state in (state.get("providers") or {}).items():
            routes = []
            for candidate_key, route_state in (provider_state.get("candidates") or {}).items():
                circuit_open_until = route_state.get("circuit_open_until")
                routes.append(
                    {
                        "candidate": candidate_key,
                        "consecutive_failures": int(route_state.get("consecutive_failures", 0) or 0),
                        "success_count": int(route_state.get("success_count", 0) or 0),
                        "failure_count": int(route_state.get("failure_count", 0) or 0),
                        "last_latency_ms": route_state.get("last_latency_ms"),
                        "latency_ewma_ms": route_state.get("latency_ewma_ms"),
                        "last_error": route_state.get("last_error"),
                        "last_success_at": route_state.get("last_success_at"),
                        "last_failure_at": route_state.get("last_failure_at"),
                        "circuit_open_until": circuit_open_until,
                        "circuit_state": "open" if self._is_circuit_open(circuit_open_until) else "closed",
                    }
                )
            snapshot["providers"][provider_name] = {
                "last_selected": provider_state.get("last_selected"),
                "last_success_at": provider_state.get("last_success_at"),
                "last_failure_at": provider_state.get("last_failure_at"),
                "route_count": len(routes),
                "routes": sorted(routes, key=lambda item: (item["circuit_state"] != "closed", item["consecutive_failures"], item["latency_ewma_ms"] or 0.0, item["candidate"])),
            }
        return snapshot

    def _invoke(
        self,
        *,
        provider_name: str,
        api_key: str,
        default_base_url: str,
        base_url_candidates: list[str],
        default_proxy: str,
        proxy_candidates: list[str],
        timeout_seconds: float,
        operation: Callable[[OpenAI], Any],
    ) -> Any:
        if not api_key:
            raise RuntimeError(f"Provider {provider_name} is not configured.")
        if not settings.provider_gateway_enabled:
            client = OpenAI(api_key=api_key, base_url=default_base_url, timeout=timeout_seconds)
            return operation(client)

        candidates = self._build_candidates(default_base_url, base_url_candidates, default_proxy, proxy_candidates)
        if not candidates:
            raise RuntimeError(f"No route available for provider {provider_name}.")
        max_attempts = max(1, min(settings.provider_route_max_attempts, len(candidates)))
        ranked_candidates = self._rank_candidates(provider_name, candidates)
        attempts = ranked_candidates[:max_attempts] or candidates[:1]
        last_error: Exception | None = None
        for attempt_index, candidate in enumerate(attempts, start=1):
            http_client = None
            started = time.perf_counter()
            try:
                http_client = self._build_http_client(timeout_seconds, candidate.proxy)
                client = OpenAI(
                    api_key=api_key,
                    base_url=candidate.base_url,
                    timeout=timeout_seconds,
                    http_client=http_client,
                )
                result = operation(client)
                latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                self._record_success(provider_name, candidate, latency_ms)
                return result
            except Exception as exc:
                last_error = exc
                latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
                self._record_failure(provider_name, candidate, latency_ms, exc)
                if attempt_index < len(attempts):
                    delay = min(
                        settings.provider_route_backoff_seconds * (2 ** (attempt_index - 1)),
                        settings.llm_retry_max_seconds,
                    )
                    time.sleep(delay)
            finally:
                if http_client is not None:
                    try:
                        http_client.close()
                    except Exception:
                        pass
        if last_error is None:
            raise RuntimeError(f"No route available for provider {provider_name}.")
        raise last_error

    def _build_http_client(self, timeout_seconds: float, proxy: str) -> httpx.Client:
        timeout = httpx.Timeout(timeout_seconds)
        if not proxy:
            return httpx.Client(timeout=timeout)
        try:
            return httpx.Client(timeout=timeout, proxy=proxy)
        except TypeError:
            return httpx.Client(timeout=timeout, proxies=proxy)

    def _build_candidates(
        self,
        default_base_url: str,
        base_url_candidates: list[str],
        default_proxy: str,
        proxy_candidates: list[str],
    ) -> list[ProviderCandidate]:
        urls = [item.strip() for item in base_url_candidates if item.strip()]
        if default_base_url.strip() and default_base_url.strip() not in urls:
            urls.insert(0, default_base_url.strip())
        if not urls and default_base_url.strip():
            urls.append(default_base_url.strip())
        proxies = [item.strip() for item in proxy_candidates if item.strip()]
        if default_proxy.strip() and default_proxy.strip() not in proxies:
            proxies.insert(0, default_proxy.strip())

        seen: set[str] = set()
        candidates: list[ProviderCandidate] = []
        for url in urls or [default_base_url.strip()]:
            candidate_proxies = self._candidate_proxies_for_url(url, proxies)
            for proxy in candidate_proxies:
                candidate = ProviderCandidate(base_url=url, proxy=proxy)
                if candidate.key in seen:
                    continue
                seen.add(candidate.key)
                candidates.append(candidate)
        return candidates

    def _candidate_proxies_for_url(self, base_url: str, proxies: list[str]) -> list[str]:
        if self._should_bypass_proxy(base_url):
            return [""]
        filtered = [proxy for proxy in proxies if self._proxy_is_usable(proxy)]
        if "" not in filtered:
            filtered.append("")
        return filtered or [""]

    def _should_bypass_proxy(self, base_url: str) -> bool:
        host = (urlparse(base_url).hostname or "").strip().lower()
        if not host:
            return False
        if host in {"localhost", "127.0.0.1", "::1"}:
            return True
        return self._host_matches_no_proxy(host)

    def _host_matches_no_proxy(self, host: str) -> bool:
        for entry in settings.network_no_proxy:
            candidate = entry.strip().lower()
            if not candidate:
                continue
            if candidate == "*":
                return True
            if candidate.startswith("."):
                candidate = candidate[1:]
            if host == candidate or host.endswith("." + candidate):
                return True
        return False

    def _proxy_is_usable(self, proxy: str) -> bool:
        value = proxy.strip().lower()
        if not value.startswith("socks"):
            return True
        return importlib.util.find_spec("socksio") is not None
    def _rank_candidates(self, provider_name: str, candidates: list[ProviderCandidate]) -> list[ProviderCandidate]:
        provider_state = (self._state.get("providers") or {}).get(provider_name, {})
        candidate_state_map = provider_state.get("candidates") or {}
        now = datetime.now(timezone.utc)

        def score(candidate: ProviderCandidate) -> tuple[float, float, str]:
            route_state = candidate_state_map.get(candidate.key, {})
            open_until = _parse_utc(route_state.get("circuit_open_until"))
            if open_until and open_until > now:
                return (1_000_000.0, 1_000_000.0, candidate.key)
            failure_penalty = float(int(route_state.get("consecutive_failures", 0) or 0) * 1000)
            latency = float(route_state.get("latency_ewma_ms") or route_state.get("last_latency_ms") or 0.0)
            last_failure = _parse_utc(route_state.get("last_failure_at"))
            recency_penalty = 250.0 if last_failure and (now - last_failure) <= timedelta(minutes=10) else 0.0
            return (failure_penalty + latency + recency_penalty, latency, candidate.key)

        return sorted(candidates, key=score)

    def _provider_state(self, provider_name: str) -> dict[str, Any]:
        providers = self._state.setdefault("providers", {})
        provider_state = providers.setdefault(provider_name, {"candidates": {}})
        provider_state.setdefault("candidates", {})
        return provider_state

    def _candidate_state(self, provider_name: str, candidate: ProviderCandidate) -> dict[str, Any]:
        provider_state = self._provider_state(provider_name)
        return provider_state["candidates"].setdefault(
            candidate.key,
            {
                "base_url": candidate.base_url,
                "proxy": candidate.proxy or None,
                "consecutive_failures": 0,
                "success_count": 0,
                "failure_count": 0,
                "last_error": None,
                "last_latency_ms": None,
                "latency_ewma_ms": None,
                "last_success_at": None,
                "last_failure_at": None,
                "circuit_open_until": None,
            },
        )

    def _record_success(self, provider_name: str, candidate: ProviderCandidate, latency_ms: float) -> None:
        provider_state = self._provider_state(provider_name)
        route_state = self._candidate_state(provider_name, candidate)
        route_state["consecutive_failures"] = 0
        route_state["success_count"] = int(route_state.get("success_count", 0) or 0) + 1
        route_state["last_error"] = None
        route_state["last_latency_ms"] = latency_ms
        previous_ewma = float(route_state.get("latency_ewma_ms") or latency_ms)
        route_state["latency_ewma_ms"] = round((previous_ewma * 0.7) + (latency_ms * 0.3), 2)
        route_state["last_success_at"] = _utc()
        route_state["circuit_open_until"] = None
        provider_state["last_selected"] = candidate.key
        provider_state["last_success_at"] = route_state["last_success_at"]
        self._persist()

    def _record_failure(self, provider_name: str, candidate: ProviderCandidate, latency_ms: float, exc: Exception) -> None:
        provider_state = self._provider_state(provider_name)
        route_state = self._candidate_state(provider_name, candidate)
        route_state["consecutive_failures"] = int(route_state.get("consecutive_failures", 0) or 0) + 1
        route_state["failure_count"] = int(route_state.get("failure_count", 0) or 0) + 1
        route_state["last_error"] = f"{type(exc).__name__}: {exc}"
        route_state["last_latency_ms"] = latency_ms
        previous_ewma = float(route_state.get("latency_ewma_ms") or latency_ms)
        route_state["latency_ewma_ms"] = round((previous_ewma * 0.7) + (latency_ms * 0.3), 2)
        route_state["last_failure_at"] = _utc()
        provider_state["last_failure_at"] = route_state["last_failure_at"]
        if route_state["consecutive_failures"] >= settings.provider_circuit_failure_threshold:
            route_state["circuit_open_until"] = (
                datetime.now(timezone.utc) + timedelta(seconds=settings.provider_circuit_cooldown_seconds)
            ).isoformat().replace("+00:00", "Z")
        self._persist()

    def _is_circuit_open(self, open_until: str | None) -> bool:
        opened = _parse_utc(open_until)
        return bool(opened and opened > datetime.now(timezone.utc))

    def _persist(self) -> None:
        self._state["updated_at"] = _utc()
        atomic_write_json(STATE_PATH, self._state)


provider_gateway = ProviderGateway()



