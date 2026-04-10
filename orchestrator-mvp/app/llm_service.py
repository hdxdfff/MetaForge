from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .io_utils import atomic_write_json
from .config import settings, strategic_llm_api_style
from .model_router import RoutedModel
from .provider_gateway import provider_gateway

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TELEMETRY = DATA / "telemetry_events.json"
USAGE = DATA / "usage_tracker.json"
CHECKPOINTS = DATA / "llm_checkpoints.json"
RECENT_WINDOW_HOURS = 1
MIN_RATIO_SAMPLE_CALLS = 5


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, payload)


def _checkpoint_key(provider: str, model: str, system_prompt: str, user_prompt: str) -> str:
    digest = hashlib.sha256(f"{provider}::{model}::{system_prompt}::{user_prompt}".encode("utf-8", errors="replace")).hexdigest()
    return digest[:16]


def _record_checkpoint(provider: str, model: str, system_prompt: str, user_prompt: str, status: str, attempt: int, error: str | None = None) -> None:
    checkpoints = _load_json(CHECKPOINTS, {})
    key = _checkpoint_key(provider, model, system_prompt, user_prompt)
    checkpoints[key] = {
        "provider": provider,
        "model": model,
        "status": status,
        "attempt": attempt,
        "error": error,
        "updated_at": _utc(),
        "prompt_chars": len(system_prompt) + len(user_prompt),
    }
    _save_json(CHECKPOINTS, checkpoints)


def _window_metrics(events: list[dict[str, object]], cutoff: datetime) -> dict[str, float | int]:
    filtered = []
    for event in events:
        try:
            at = datetime.fromisoformat(str(event.get("at", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if at >= cutoff:
            filtered.append(event)
    cheap_calls = sum(1 for event in filtered if event.get("provider") == "cheap")
    reasoning_calls = sum(1 for event in filtered if event.get("provider") == "reasoning")
    strong_calls = sum(1 for event in filtered if event.get("provider") == "openai")
    total_calls = cheap_calls + reasoning_calls + strong_calls
    total = max(1, total_calls)
    has_fallback_signal = any("used_fallback" in event for event in filtered)
    successful_calls = sum(1 for event in filtered if not bool(event.get("used_fallback", False)))
    non_fallback_ratio = round((successful_calls / total), 4) if has_fallback_signal else (1.0 if total_calls else 0.0)
    has_char_signal = any(("input_chars" in event) or ("output_chars" in event) for event in filtered)
    total_input_chars = sum(int(event.get("input_chars", 0) or 0) for event in filtered)
    total_output_chars = sum(int(event.get("output_chars", 0) or 0) for event in filtered)
    if has_char_signal and total_input_chars > 0:
        output_input_ratio = round(total_output_chars / max(1, total_input_chars), 4)
    else:
        output_input_ratio = 0.25 if total_calls else 0.0
    return {
        "cheap_calls": cheap_calls,
        "reasoning_calls": reasoning_calls,
        "strong_calls": strong_calls,
        "total_calls": total_calls,
        "successful_calls": successful_calls if has_fallback_signal else total_calls,
        "non_fallback_ratio": non_fallback_ratio,
        "total_input_chars": total_input_chars,
        "total_output_chars": total_output_chars,
        "output_input_ratio": output_input_ratio,
        "reasoning_ratio": round(reasoning_calls / total, 4),
        "strong_ratio": round(strong_calls / total, 4),
    }


def _record_usage(provider: str, model: str, used_fallback: bool, input_chars: int, output_chars: int) -> None:
    telemetry = _load_json(TELEMETRY, {})
    usage = _load_json(USAGE, {
        "updated_at": _utc(),
        "cheap_calls": 0,
        "reasoning_calls": 0,
        "strong_calls": 0,
        "total_calls": 0,
        "successful_calls": 0,
        "non_fallback_ratio": 0.0,
        "total_input_chars": 0,
        "total_output_chars": 0,
        "output_input_ratio": 0.0,
        "reasoning_ratio": 0.0,
        "strong_ratio": 0.0,
        "max_strong_model_ratio": 0.15,
        "max_reasoning_model_ratio": 0.6,
        "reasoning_allowed": True,
        "strong_allowed": True,
        "window_hours": 24,
        "recent_events": [],
    })
    now = datetime.now(timezone.utc)
    window_hours = int(usage.get("window_hours", 24) or 24)
    cutoff = now - timedelta(hours=window_hours)
    recent_events = []
    for event in usage.get("recent_events", []):
        try:
            at = datetime.fromisoformat(str(event.get("at", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if at >= cutoff:
            recent_events.append(event)
    if not used_fallback and provider in {"cheap", "reasoning", "openai"}:
        recent_events.append({"at": _utc(), "provider": provider, "model": model, "used_fallback": used_fallback, "input_chars": max(0, int(input_chars or 0)), "output_chars": max(0, int(output_chars or 0))})
    if provider == "cheap" and not used_fallback:
        telemetry["cheap_calls_total"] = int(telemetry.get("cheap_calls_total", 0) or 0) + 1
    elif provider == "reasoning" and not used_fallback:
        telemetry["reasoning_calls_total"] = int(telemetry.get("reasoning_calls_total", 0) or 0) + 1
    elif provider == "openai" and not used_fallback:
        telemetry["core_escalations_total"] = int(telemetry.get("core_escalations_total", 0) or 0) + 1
    primary_metrics = _window_metrics(recent_events, cutoff)
    recent_window = {
        "hours": RECENT_WINDOW_HOURS,
        **_window_metrics(recent_events, now - timedelta(hours=RECENT_WINDOW_HOURS)),
    }
    usage["updated_at"] = _utc()
    usage["window_hours"] = window_hours
    usage["recent_events"] = recent_events[-500:]
    usage["cheap_calls"] = int(primary_metrics["cheap_calls"])
    usage["reasoning_calls"] = int(primary_metrics["reasoning_calls"])
    usage["strong_calls"] = int(primary_metrics["strong_calls"])
    usage["total_calls"] = int(primary_metrics["total_calls"])
    usage["successful_calls"] = int(primary_metrics["successful_calls"])
    usage["non_fallback_ratio"] = float(primary_metrics["non_fallback_ratio"])
    usage["total_input_chars"] = int(primary_metrics["total_input_chars"])
    usage["total_output_chars"] = int(primary_metrics["total_output_chars"])
    usage["output_input_ratio"] = float(primary_metrics["output_input_ratio"])
    usage["last_provider"] = provider
    usage["last_model"] = model
    usage["reasoning_ratio"] = float(primary_metrics["reasoning_ratio"])
    usage["strong_ratio"] = float(primary_metrics["strong_ratio"])
    usage["recent_window"] = recent_window
    ratio_sample_min_calls = int(usage.get("ratio_sample_min_calls", MIN_RATIO_SAMPLE_CALLS) or MIN_RATIO_SAMPLE_CALLS)
    recent_total_calls = int(recent_window["total_calls"])
    use_recent_window = recent_total_calls >= ratio_sample_min_calls
    if use_recent_window:
        usage["reasoning_ratio"] = float(recent_window["reasoning_ratio"])
        usage["strong_ratio"] = float(recent_window["strong_ratio"])
        effective_reasoning_ratio = usage["reasoning_ratio"]
        effective_strong_ratio = usage["strong_ratio"]
        total_calls_for_ratio = recent_total_calls
        usage["effective_ratio_source"] = "recent_window"
    else:
        effective_reasoning_ratio = float(usage.get("effective_reasoning_ratio", usage["reasoning_ratio"]) or usage["reasoning_ratio"])
        effective_strong_ratio = float(usage.get("effective_strong_ratio", usage["strong_ratio"]) or usage["strong_ratio"])
        total_calls_for_ratio = int(usage["total_calls"])
        usage["effective_ratio_source"] = "full_window"
    max_reasoning_ratio = float(usage.get("max_reasoning_model_ratio", settings.model_usage_max_reasoning_ratio) or settings.model_usage_max_reasoning_ratio)
    max_strong_ratio = float(usage.get("max_strong_model_ratio", settings.model_usage_max_strong_ratio) or settings.model_usage_max_strong_ratio)
    usage["ratio_sample_min_calls"] = ratio_sample_min_calls
    usage["recent_window_sample_sufficient"] = use_recent_window
    usage["effective_reasoning_ratio"] = effective_reasoning_ratio
    usage["effective_strong_ratio"] = effective_strong_ratio
    usage["max_reasoning_model_ratio"] = max_reasoning_ratio
    usage["max_strong_model_ratio"] = max_strong_ratio
    usage["reasoning_allowed"] = total_calls_for_ratio < ratio_sample_min_calls or effective_reasoning_ratio <= max_reasoning_ratio
    usage["strong_allowed"] = total_calls_for_ratio < ratio_sample_min_calls or effective_strong_ratio <= max_strong_ratio
    usage["reasoning_pressure"] = round(effective_reasoning_ratio / max(0.0001, max_reasoning_ratio), 4)
    usage["strong_pressure"] = round(effective_strong_ratio / max(0.0001, max_strong_ratio), 4)
    usage["demand_pressure"] = "balanced"
    if not usage["strong_allowed"]:
        usage["demand_pressure"] = "strong-throttled"
    elif not usage["reasoning_allowed"]:
        usage["demand_pressure"] = "reasoning-throttled"
    telemetry["updated_at"] = _utc()
    _save_json(TELEMETRY, telemetry)
    _save_json(USAGE, usage)


@dataclass
class LlmResult:
    text: str
    used_fallback: bool = False
    input_chars: int = 0
    output_chars: int = 0
    total_chars: int = 0
    model: str = ""
    provider: str = ""


class LlmService:
    def __init__(self) -> None:
        self._openai_client = bool(settings.openai_api_key and settings.openai_base_url)
        self._reasoning_client = bool(settings.reasoning_llm_api_key and settings.reasoning_llm_base_url)
        self._cheap_client = bool(settings.cheap_llm_api_key and settings.cheap_llm_base_url)

    def _request_timeout_seconds(self, provider: str) -> float:
        if provider == 'cheap':
            return max(5.0, min(settings.cheap_request_timeout_seconds, 12.0))
        if provider == 'reasoning':
            return max(8.0, min(settings.reasoning_request_timeout_seconds, 45.0))
        if provider == 'openai':
            return max(8.0, min(settings.planner_request_timeout_seconds, 15.0))
        return max(5.0, min(settings.cheap_request_timeout_seconds, 12.0))

    def _attempt_budget(self, provider: str) -> int:
        # Worker calls always have a bounded fallback path, so deep retries only destroy throughput.
        if provider in {'cheap', 'reasoning', 'openai'}:
            return 1
        return max(1, settings.llm_max_retries)

    def _is_balance_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        status_code = getattr(exc, "status_code", None)
        return bool(status_code == 402 or "insufficient balance" in message or "payment required" in message)

    def _cheap_balance_fallback_route(self) -> RoutedModel:
        return RoutedModel(
            provider="openai",
            model=settings.planner_escalation_model,
            reason="Cheap provider reported insufficient balance, so the task was escalated to the strategic lane.",
        )

    def generate(self, route: RoutedModel, system_prompt: str, user_prompt: str, fallback: str) -> LlmResult:
        input_chars = len(system_prompt) + len(user_prompt)
        max_retries = self._attempt_budget(route.provider)
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                _record_checkpoint(route.provider, route.model, system_prompt, user_prompt, "running", attempt)
                if route.provider == "openai":
                    result = self._generate_openai(route, system_prompt, user_prompt, fallback, input_chars)
                elif route.provider == "reasoning":
                    result = self._generate_reasoning(route, system_prompt, user_prompt, fallback, input_chars)
                elif route.provider == "cheap":
                    result = self._generate_cheap(route, system_prompt, user_prompt, fallback, input_chars)
                else:
                    result = LlmResult(
                        text=fallback,
                        used_fallback=True,
                        input_chars=input_chars,
                        output_chars=len(fallback),
                        total_chars=input_chars + len(fallback),
                        model=route.model,
                        provider=route.provider,
                    )
                effective_provider = result.provider or route.provider
                effective_model = result.model or route.model
                _record_usage(
                    effective_provider,
                    effective_model,
                    result.used_fallback,
                    result.input_chars,
                    result.output_chars,
                )
                _record_checkpoint(
                    effective_provider,
                    effective_model,
                    system_prompt,
                    user_prompt,
                    "completed",
                    attempt,
                    None if not result.used_fallback else "used-fallback",
                )
                return result
            except Exception as exc:
                last_exc = exc
                if route.provider in {"cheap", "reasoning"} and self._is_balance_error(exc):
                    fallback_route = self._cheap_balance_fallback_route()
                    try:
                        fallback_result = self._generate_openai(
                            fallback_route,
                            system_prompt,
                            user_prompt,
                            fallback,
                            input_chars,
                        )
                        _record_usage(
                            fallback_result.provider or fallback_route.provider,
                            fallback_result.model or fallback_route.model,
                            fallback_result.used_fallback,
                            fallback_result.input_chars,
                            fallback_result.output_chars,
                        )
                        _record_checkpoint(
                            fallback_result.provider or fallback_route.provider,
                            fallback_result.model or fallback_route.model,
                            system_prompt,
                            user_prompt,
                            "completed",
                            attempt,
                            None if not fallback_result.used_fallback else "used-fallback",
                        )
                        return fallback_result
                    except Exception as fallback_exc:
                        last_exc = fallback_exc
                        _record_checkpoint(
                            route.provider,
                            route.model,
                            system_prompt,
                            user_prompt,
                            "failed",
                            attempt,
                            f"{type(exc).__name__}: {exc}",
                        )
                        _record_checkpoint(
                            fallback_route.provider,
                            fallback_route.model,
                            system_prompt,
                            user_prompt,
                            "failed",
                            attempt,
                            f"{type(fallback_exc).__name__}: {fallback_exc}",
                        )
                        if attempt < max_retries:
                            delay = min(settings.llm_retry_max_seconds, settings.llm_retry_base_seconds * (2 ** (attempt - 1)))
                            time.sleep(delay)
                        continue
                _record_checkpoint(route.provider, route.model, system_prompt, user_prompt, "retrying" if attempt < max_retries else "failed", attempt, f"{type(exc).__name__}: {exc}")
                if attempt < max_retries:
                    delay = min(settings.llm_retry_max_seconds, settings.llm_retry_base_seconds * (2 ** (attempt - 1)))
                    time.sleep(delay)
        failure_text = f"{fallback}\n\nProvider error: {type(last_exc).__name__}: {last_exc}" if last_exc else fallback
        output_chars = len(failure_text)
        return LlmResult(
            text=failure_text,
            used_fallback=True,
            input_chars=input_chars,
            output_chars=output_chars,
            total_chars=input_chars + output_chars,
            model=route.model,
            provider=route.provider,
        )

    def _generate_openai(self, route: RoutedModel, system_prompt: str, user_prompt: str, fallback: str, input_chars: int) -> LlmResult:
        if not self._openai_client:
            return LlmResult(text=fallback, used_fallback=True, input_chars=input_chars, output_chars=len(fallback), total_chars=input_chars + len(fallback), model=route.model, provider=route.provider)
        if strategic_llm_api_style() == "chat.completions":
            response = provider_gateway.chat_completions_create(
                provider_name="openai",
                api_key=settings.openai_api_key,
                default_base_url=settings.openai_base_url,
                base_url_candidates=list(settings.openai_base_url_candidates),
                default_proxy=settings.network_proxy_url,
                proxy_candidates=list(settings.openai_proxy_candidates),
                timeout_seconds=self._request_timeout_seconds('openai'),
                request_kwargs={
                    "model": route.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                },
            )
            text = ""
            if response.choices:
                message = response.choices[0].message
                if isinstance(message.content, str):
                    text = message.content
                elif isinstance(message.content, list):
                    text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
            text = self._normalize_text(text.strip(), provider="openai")
        else:
            response = provider_gateway.responses_create(
                provider_name="openai",
                api_key=settings.openai_api_key,
                default_base_url=settings.openai_base_url,
                base_url_candidates=list(settings.openai_base_url_candidates),
                default_proxy=settings.network_proxy_url,
                proxy_candidates=list(settings.openai_proxy_candidates),
                timeout_seconds=self._request_timeout_seconds('openai'),
                request_kwargs={
                    "model": route.model,
                    "input": [
                        {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                        {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                    ],
                },
            )
            text = self._normalize_text((response.output_text or "").strip(), provider="openai")
        used_fallback = not bool(text)
        if used_fallback:
            text = fallback
        output_chars = len(text)
        return LlmResult(text=text, used_fallback=used_fallback, input_chars=input_chars, output_chars=output_chars, total_chars=input_chars + output_chars, model=route.model, provider=route.provider)

    def _generate_cheap(self, route: RoutedModel, system_prompt: str, user_prompt: str, fallback: str, input_chars: int) -> LlmResult:
        if not self._cheap_client:
            return LlmResult(text=fallback, used_fallback=True, input_chars=input_chars, output_chars=len(fallback), total_chars=input_chars + len(fallback), model=route.model, provider=route.provider)
        response = provider_gateway.chat_completions_create(
            provider_name="cheap",
            api_key=settings.cheap_llm_api_key,
            default_base_url=settings.cheap_llm_base_url,
            base_url_candidates=list(settings.cheap_llm_base_url_candidates),
            default_proxy=settings.cheap_llm_proxy_candidates[0] if settings.cheap_llm_proxy_candidates else "",
            proxy_candidates=list(settings.cheap_llm_proxy_candidates),
            timeout_seconds=self._request_timeout_seconds('cheap'),
            request_kwargs={
                "model": route.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
        )
        text = ""
        if response.choices:
            message = response.choices[0].message
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        text = self._normalize_text(text.strip(), provider="cheap")
        used_fallback = not bool(text)
        if used_fallback:
            text = fallback
        output_chars = len(text)
        return LlmResult(text=text, used_fallback=used_fallback, input_chars=input_chars, output_chars=output_chars, total_chars=input_chars + output_chars, model=route.model, provider=route.provider)


    def _generate_reasoning(self, route: RoutedModel, system_prompt: str, user_prompt: str, fallback: str, input_chars: int) -> LlmResult:
        if not self._reasoning_client:
            return LlmResult(text=fallback, used_fallback=True, input_chars=input_chars, output_chars=len(fallback), total_chars=input_chars + len(fallback), model=route.model, provider=route.provider)
        response = provider_gateway.chat_completions_create(
            provider_name="reasoning",
            api_key=settings.reasoning_llm_api_key,
            default_base_url=settings.reasoning_llm_base_url,
            base_url_candidates=list(settings.reasoning_llm_base_url_candidates),
            default_proxy=settings.reasoning_llm_proxy_candidates[0] if settings.reasoning_llm_proxy_candidates else "",
            proxy_candidates=list(settings.reasoning_llm_proxy_candidates),
            timeout_seconds=self._request_timeout_seconds('reasoning'),
            request_kwargs={
                "model": route.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
        )
        text = ""
        if response.choices:
            message = response.choices[0].message
            if isinstance(message.content, str):
                text = message.content
            elif isinstance(message.content, list):
                text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
        text = self._normalize_text(text.strip(), provider="reasoning")
        used_fallback = not bool(text)
        if used_fallback:
            text = fallback
        output_chars = len(text)
        return LlmResult(text=text, used_fallback=used_fallback, input_chars=input_chars, output_chars=output_chars, total_chars=input_chars + output_chars, model=route.model, provider=route.provider)

    def _normalize_text(self, text: str, provider: str) -> str:
        normalized = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n")).strip()
        if provider == "cheap" and len(normalized) > settings.cheap_max_output_chars:
            return normalized[: settings.cheap_max_output_chars].rstrip() + "\n\n[truncated by cheap-lane output guard]"
        return normalized



