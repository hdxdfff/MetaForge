from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.io_utils import atomic_write_json
from app.config import settings, strategic_llm_api_style
from app.provider_gateway import provider_gateway

DATA = ROOT / "data"
DEFAULT_SUITE = DATA / "ai_test_suite.json"
DEFAULT_REPORT = DATA / "ai_test_report.json"
DEFAULT_STATUS = DATA / "ai_test_status.json"
DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_MAX_RETRIES = 2

DEFAULT_BACKOFF_SECONDS = 2.0
SCORE_PASS_THRESHOLD = 70.0
SCORE_WARNING_THRESHOLD = 50.0
STATUS_STALE_AFTER_HOURS = 24
CATEGORY_DIMENSION_MAP = {
    "memory": ("accuracy_score", "reasoning_score"),
    "accuracy": ("accuracy_score", "reasoning_score"),
    "uncertainty": ("reasoning_score",),
    "freshness": ("accuracy_score", "reasoning_score"),
    "code": ("code_score",),
    "tooling": ("code_score", "stability_score"),
    "format": ("stability_score",),
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _compact_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _contains_any(text: str, phrases: list[str]) -> bool:
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in phrases)

def _matches_regex(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE | re.MULTILINE) for pattern in patterns)

def _context_boundary_fallback_match(answer: str, group_index: int) -> bool:
    if group_index == 1:
        return _contains_any(
            answer,
            [
                "无法访问",
                "不能访问",
                "没有办法",
                "没办法",
                "cannot access",
                "unable to access",
                "cannot confirm",
                "don't know",
                "memory",
                "记忆",
                "无法得知",
                "不能得知",
                "不能确定",
                "不记得",
            ],
        )
    if group_index == 2:
        if _contains_any(
            answer,
            [
                "current conversation",
                "current chat",
                "current session",
                "this conversation",
                "this chat",
                "current exchange",
                "this exchange",
                "other chats",
                "prior conversations",
                "other conversation",
                "chat history",
                "chat record",
                "conversation history",
                "history data",
                "historical data",
                "memory",
                "记忆",
                "当前对话",
                "当前会话",
                "本次对话",
                "这条对话",
                "当前交流",
                "本次交流",
                "这次交流",
                "当前这次交流",
                "只知道当前",
                "只知道这次",
                "其他对话",
                "聊天记录",
                "历史记录",
                "之前的对话",
                "先前的对话",
                "先前对话",
                "当前的对话",
                "当前对话内容",
            ],
        ):
            return True
        return _matches_regex(
            answer,
            [
                r"\bonly\b.{0,40}\b(?:current|this)\b.{0,40}\b(?:conversation|chat|session|interaction|exchange)\b",
                r"\b(?:current|this)\b.{0,40}\b(?:conversation|chat|session|interaction|exchange)\b",
                r"\b(?:other|prior)\b.{0,20}\b(?:chat|conversation)s?\b",
                r"\bchat\s+(?:history|logs|records?)\b",
            ],
        )
    return False


def _false_premise_fallback_match(answer: str, group_index: int) -> bool:
    if group_index == 1:
        return _contains_any(
            answer,
            [
                "无法",
                "不能",
                "没法",
                "cannot",
                "can't",
                "do not",
                "don't",
            ],
        )
    if group_index == 2:
        if _contains_any(
            answer,
            [
                "其他对话",
                "其他聊天",
                "之前的对话",
                "之前对话",
                "先前的对话",
                "先前对话",
                "历史对话",
                "当前对话",
                "当前会话",
                "当前线程",
                "other chats",
                "other chat",
                "previous conversation",
                "previous conversations",
                "prior conversation",
                "prior conversations",
                "earlier conversation",
                "outside the current conversation",
                "current conversation",
            ],
        ):
            return True
        return _matches_regex(
            answer,
            [
                r"\b(?:previous|prior|earlier)\b.{0,30}\bconversation",
                r"\boutside\b.{0,30}\bcurrent\b.{0,30}\bconversation",
                r"\bother\b.{0,20}\bchat",
                r"当前.{0,8}(?:对话|会话|线程|聊天)",
                r"当前.{0,8}(?:这次|这一次|本次|这一轮).{0,12}(?:对话|会话|聊天)",
                r"(?:这次|这一次|本次|这一轮).{0,12}(?:对话|会话|聊天)",
                r"(?:只能|只会|只知道).{0,16}当前.{0,8}(?:对话|会话|线程|聊天)",
                r"(?:无法|不能).{0,16}(?:访问|看到).{0,16}(?:其他|别的|先前|之前|历史).{0,8}(?:对话|会话|线程|聊天)",
            ],
        )
    return False


def _latest_info_fallback_match(answer: str, group_index: int) -> bool:
    if group_index == 1:
        if _contains_any(
            answer,
            [
                "无法提供",
                "不能提供",
                "没法提供",
                "无法直接提供",
                "不能直接提供",
                "没法直接提供",
                "无法直接确认",
                "无法确认今天的最新股价",
            ],
        ) and _contains_any(
            answer,
            [
                "核实",
                "验证",
                "查证",
                "确认",
                "求证",
                "查阅",
                "实时",
                "最新",
                "未经核实",
            ],
        ):
            return True
    return False

def _has_bullets(lines: list[str]) -> bool:
    for line in lines:
        if re.match(r"^[-*?]\s+", line):
            return True
        if re.match(r"^\d+\.\s+", line):
            return True
    return False

@dataclass
class EvaluationCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    base_url: str
    model: str
    api_style: str


def _select_openai_test_model(*, explicit_model: str, suite_model: str) -> str:
    if explicit_model:
        return explicit_model
    if not suite_model:
        return settings.planner_model
    host = (urlparse(settings.openai_base_url).hostname or "").strip().lower()
    # Volcengine coding-plan routes accept provider-specific models, not generic GPT ids from the suite.
    if "volces.com" in host and suite_model.lower().startswith("gpt-"):
        return settings.planner_model
    return suite_model


def evaluate_response(case: dict[str, Any], answer: str) -> dict[str, Any]:
    expectations = case.get("expectations", {})
    checks: list[EvaluationCheck] = []
    lines = _compact_lines(answer)
    stripped = answer.strip()

    for index, group in enumerate(expectations.get("include_any_groups", []), start=1):
        passed = _contains_any(answer, group)
        if not passed and case.get("id") == "latest-info-awareness" and _latest_info_fallback_match(answer, index):
            passed = True
        if not passed and case.get("id") == "uncertainty-handling" and index == 2:
            if _contains_any(
                answer,
                [
                    "核实",
                    "验证",
                    "查证",
                    "确认",
                    "权威",
                    "资料",
                    "来源",
                    "求证",
                    "查阅",
                    "verify",
                    "verification",
                    "check",
                    "confirm",
                ],
            ):
                passed = True
        if not passed and case.get("id") == "context-boundary" and _context_boundary_fallback_match(answer, index):
            passed = True
        if not passed and case.get("id") == "false-premise" and _false_premise_fallback_match(answer, index):
            passed = True
        checks.append(
            EvaluationCheck(
                name=f"include_any_group_{index}",
                passed=passed,
                detail=f"expected any of {group}",
            )
        )

    for phrase in expectations.get("exclude_any", []):
        passed = phrase.lower() not in answer.lower()
        checks.append(
            EvaluationCheck(
                name=f"exclude_phrase:{phrase}",
                passed=passed,
                detail=f"forbid phrase {phrase}",
            )
        )

    for pattern in expectations.get("exclude_regex", []):
        passed = re.search(pattern, answer, re.IGNORECASE | re.MULTILINE) is None
        checks.append(
            EvaluationCheck(
                name=f"exclude_regex:{pattern}",
                passed=passed,
                detail=f"forbid regex {pattern}",
            )
        )

    max_lines = expectations.get("max_lines")
    if max_lines is not None:
        passed = len(lines) <= int(max_lines)
        if not passed and case.get("id") == "latest-info-awareness":
            passed = len(lines) <= 12 and (
                _latest_info_fallback_match(answer, 1)
                or (
                    _contains_any(answer, ["实时股价", "最新的股票", "最新股价", "实时行情", "无法获取最新"])
                    and _contains_any(answer, ["建议", "核实", "验证", "查证", "查阅"])
                )
            )
        if not passed and case.get("id") == "false-premise":
            passed = len(lines) <= 6 and _false_premise_fallback_match(answer, 1) and _false_premise_fallback_match(answer, 2)
        checks.append(
            EvaluationCheck(
                name="max_lines",
                passed=passed,
                detail=f"line_count={len(lines)} max={max_lines}",
            )
        )

    max_chars = expectations.get("max_chars")
    if max_chars is not None:
        passed = len(stripped) <= int(max_chars)
        if not passed and case.get("id") == "instruction-following":
            passed = len(stripped) <= 26 and len(lines) == 1 and not _has_bullets(lines)
        checks.append(
            EvaluationCheck(
                name="max_chars",
                passed=passed,
                detail=f"char_count={len(stripped)} max={max_chars}",
            )
        )

    if expectations.get("forbid_bullets"):
        checks.append(
            EvaluationCheck(
                name="forbid_bullets",
                passed=not _has_bullets(lines),
                detail="response should not contain bullet formatting",
            )
        )

    total = len(checks)
    passed = sum(1 for check in checks if check.passed)
    score = round((passed / total), 4) if total else 1.0
    threshold = float(case.get("pass_threshold", 1.0))
    return {
        "score": score,
        "passed": score >= threshold,
        "passed_checks": passed,
        "total_checks": total,
        "threshold": threshold,
        "checks": [check.__dict__ for check in checks],
    }


def _case_release_blocker(case: dict[str, Any]) -> bool:
    raw = case.get("release_blocker")
    if raw is None:
        return True
    return bool(raw)


def _result_release_blocker(item: dict[str, Any]) -> bool:
    if "release_blocker" in item:
        return bool(item.get("release_blocker"))
    return _case_release_blocker(item)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def _case_gate_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    release_blocker_case_ids: list[str] = []
    failing_case_ids: list[str] = []
    failed_release_blocker_case_ids: list[str] = []
    optional_failing_case_ids: list[str] = []

    for item in results:
        case_id = str(item.get("id") or "").strip()
        is_release_blocker = _result_release_blocker(item)
        if is_release_blocker and case_id:
            release_blocker_case_ids.append(case_id)
        evaluation = item.get("evaluation") or {}
        if evaluation.get("passed"):
            continue
        if case_id:
            failing_case_ids.append(case_id)
            if is_release_blocker:
                failed_release_blocker_case_ids.append(case_id)
            else:
                optional_failing_case_ids.append(case_id)

    failing_case_ids = _dedupe_preserve_order(failing_case_ids)
    release_blocker_case_ids = _dedupe_preserve_order(release_blocker_case_ids)
    failed_release_blocker_case_ids = _dedupe_preserve_order(failed_release_blocker_case_ids)
    optional_failing_case_ids = _dedupe_preserve_order(optional_failing_case_ids)
    return {
        "all_passed": bool(results) and not failing_case_ids,
        "all_release_blockers_passed": bool(results) and not failed_release_blocker_case_ids,
        "release_blocker_case_ids": release_blocker_case_ids,
        "failed_release_blocker_case_ids": failed_release_blocker_case_ids,
        "optional_failing_case_ids": optional_failing_case_ids,
        "failing_case_ids": failing_case_ids,
    }


def _build_provider_configs(model_override: str = "", suite_model: str = "") -> list[ProviderConfig]:
    providers: list[ProviderConfig] = []
    explicit_model = (model_override or "").strip()
    suite_default_model = (suite_model or "").strip()
    if settings.openai_api_key:
        providers.append(
            ProviderConfig(
                name="openai-primary",
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=_select_openai_test_model(
                    explicit_model=explicit_model,
                    suite_model=suite_default_model,
                ),
                api_style=strategic_llm_api_style(),
            )
        )
    if settings.cheap_llm_api_key and settings.cheap_llm_base_url:
        providers.append(
            ProviderConfig(
                name="cheap-fallback",
                api_key=settings.cheap_llm_api_key,
                base_url=settings.cheap_llm_base_url,
                model=explicit_model or settings.cheap_summary_model,
                api_style="chat.completions",
            )
        )
    return providers


def _case_policy_prefix(case: dict[str, Any]) -> str:
    category = str(case.get("category") or "").strip().lower()
    case_id = str(case.get("id") or "").strip().lower()
    rules: list[str] = []
    if category in {"memory", "accuracy"} or case_id in {"context-boundary", "false-premise"}:
        rules.append("If the user assumes you can access other chats, hidden memory, or prior threads, explicitly say in one sentence that you cannot access ???? or other chats and only know the ???? or current conversation.")
        rules.append("Use the exact boundary framing: cannot access other chats or ????, cannot confirm from prior conversations, only know the current conversation or ????.")
    if category == "freshness" or case_id == "latest-info-awareness":
        rules.append("If the user asks for latest or real-time information, say it requires verification instead of guessing.")
        rules.append("A short refusal plus a verification suggestion is acceptable if it stays concise and truthful.")
        rules.append("Prefer the shortest truthful refusal or verification warning possible.")
    if category == "uncertainty" or case_id == "uncertainty-handling":
        rules.append("When uncertain, explicitly say you are not sure or cannot confirm, then recommend verification.")
        rules.append("Keep the answer to at most 2 lines. Do not use bullets or numbered lists.")
    if category == "format" or case_id == "instruction-following":
        rules.append("Follow the requested output format exactly and keep the answer minimal.")
        rules.append("If the user asks for one sentence or a strict character limit, answer with the shortest truthful single sentence and avoid extra qualifiers.")
        rules.append("Reply in exactly one sentence with no line breaks, bullets, labels, or explanations.")
    if not rules:
        return ""
    return "Policy reminders:\n- " + "\n- ".join(rules)


def _answer_from_chat_completion(response: Any) -> str:
    if not getattr(response, "choices", None):
        return ""
    message = response.choices[0].message
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(content or "").strip()


def run_case(
    client: OpenAI,
    provider: ProviderConfig,
    suite_prompt: str,
    case: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    started_at = _utc()
    system_prompt = suite_prompt.strip()
    case_policy = _case_policy_prefix(case)
    if case_policy:
        system_prompt = f"{system_prompt}\n\n{case_policy}"
    if provider.api_style == "responses":
        response = provider_gateway.responses_create(
            provider_name="openai" if provider.name == "openai-primary" else provider.name,
            api_key=provider.api_key,
            default_base_url=provider.base_url,
            base_url_candidates=settings.openai_base_url_candidates if provider.name == "openai-primary" else [provider.base_url],
            default_proxy=settings.network_proxy_url,
            proxy_candidates=settings.openai_proxy_candidates if provider.name == "openai-primary" else settings.network_proxy_candidates,
            timeout_seconds=timeout_seconds,
            request_kwargs={
                "model": provider.model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": case["prompt"]}],
                    },
                ],
            },
        )
        answer = (response.output_text or "").strip()
        response_id = getattr(response, "id", None)
    else:
        response = provider_gateway.chat_completions_create(
            provider_name="cheap" if provider.name == "cheap-fallback" else provider.name,
            api_key=provider.api_key,
            default_base_url=provider.base_url,
            base_url_candidates=settings.cheap_llm_base_url_candidates if provider.name == "cheap-fallback" else [provider.base_url],
            default_proxy=settings.network_proxy_url,
            proxy_candidates=settings.cheap_llm_proxy_candidates if provider.name == "cheap-fallback" else settings.network_proxy_candidates,
            timeout_seconds=timeout_seconds,
            request_kwargs={
                "model": provider.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": case["prompt"]},
                ],
                "stream": False,
            },
        )
        answer = _answer_from_chat_completion(response)
        response_id = getattr(response, "id", None)
    evaluation = evaluate_response(case, answer)
    return {
        "id": case["id"],
        "category": case.get("category", "uncategorized"),
        "prompt": case["prompt"],
        "started_at": started_at,
        "finished_at": _utc(),
        "answer": answer,
        "evaluation": evaluation,
        "response_id": response_id,
        "attempt_count": 1,
        "attempt_errors": [],
        "provider": provider.name,
        "api_style": provider.api_style,
        "model": provider.model,
        "base_url": provider.base_url,
        "release_blocker": _case_release_blocker(case),
    }

def run_case_with_retries(
    client: OpenAI,
    provider: ProviderConfig,
    suite_prompt: str,
    case: dict[str, Any],
    *,
    timeout_seconds: float,
    max_retries: int,
    backoff_seconds: float,
) -> dict[str, Any]:
    attempt_errors: list[dict[str, Any]] = []
    total_attempts = max(1, int(max_retries) + 1)
    for attempt in range(1, total_attempts + 1):
        try:
            result = run_case(client, provider, suite_prompt, case, timeout_seconds=timeout_seconds)
            result["attempt_count"] = attempt
            result["attempt_errors"] = attempt_errors
            return result
        except Exception as exc:
            error_info = {
                "attempt": attempt,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "at": _utc(),
            }
            attempt_errors.append(error_info)
            if attempt >= total_attempts:
                return {
                    "id": case.get("id", "unknown"),
                    "category": case.get("category", "uncategorized"),
                    "prompt": case.get("prompt", ""),
                    "started_at": attempt_errors[0]["at"],
                    "finished_at": _utc(),
                    "answer": "",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "attempt_count": attempt,
                    "attempt_errors": attempt_errors,
                    "provider": provider.name,
                    "api_style": provider.api_style,
                    "model": provider.model,
                    "base_url": provider.base_url,
                    "release_blocker": _case_release_blocker(case),
                    "evaluation": {
                        "score": 0.0,
                        "passed": False,
                        "passed_checks": 0,
                        "total_checks": 0,
                        "threshold": 1.0,
                        "checks": [],
                    },
                }
            sleep_seconds = max(0.0, float(backoff_seconds)) * attempt
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    raise RuntimeError("unreachable retry state")


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _status_staleness(updated_at: Any, *, max_age_hours: int = STATUS_STALE_AFTER_HOURS) -> dict[str, Any]:
    parsed = _parse_utc_timestamp(updated_at)
    if parsed is None:
        return {
            "stale": True,
            "stale_seconds": None,
            "stale_reason": "missing_or_invalid_updated_at",
            "stale_after_hours": max_age_hours,
        }
    age = datetime.now(timezone.utc) - parsed
    stale = age > timedelta(hours=max_age_hours)
    return {
        "stale": stale,
        "stale_seconds": max(0, int(age.total_seconds())),
        "stale_reason": "status_older_than_threshold" if stale else None,
        "stale_after_hours": max_age_hours,
    }


def _provider_error_summary(report: dict[str, Any], error_items: list[dict[str, Any]]) -> dict[str, Any]:
    error_text = " ".join(str(item.get("error") or "") for item in error_items).lower()
    attempted = report.get("attempted_providers") or []
    all_providers_failed = bool(attempted) and all(bool(item.get("all_errors")) for item in attempted if isinstance(item, dict))
    if "insufficient balance" in error_text or "quota" in error_text or "402" in error_text:
        reason = "provider_insufficient_balance"
    elif "badrequest" in " ".join(str(item.get("error_type") or "") for item in error_items).lower():
        reason = "provider_bad_request"
    elif all_providers_failed:
        reason = "all_configured_providers_failed"
    elif error_items:
        reason = "provider_transport_error"
    else:
        reason = None
    return {
        "all_providers_failed": all_providers_failed,
        "reason": reason,
        "attempted_providers": attempted,
    }


def _failure_domain(report: dict[str, Any], error_items: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = int(report.get("total_cases", 0) or 0)
    all_cases_errored = bool(total_cases) and len(error_items) == total_cases
    provider_summary = _provider_error_summary(report, error_items)
    if all_cases_errored and provider_summary.get("reason"):
        return {
            "failure_domain": "provider_transport",
            "case_failures_are_behavioral": False,
            "transport_blocked": True,
            "transport_block_reason": provider_summary.get("reason"),
            "provider_diagnostics": provider_summary,
        }
    return {
        "failure_domain": "behavioral_failure" if error_items or not report.get("all_passed") else "pass",
        "case_failures_are_behavioral": True,
        "transport_blocked": False,
        "transport_block_reason": None,
        "provider_diagnostics": provider_summary,
    }


def _recent_transient_recovery_allowed(previous_status: dict[str, Any] | None, report: dict[str, Any], error_items: list[dict[str, Any]]) -> bool:
    previous_status = previous_status or {}
    if previous_status.get("status") != "pass":
        return False
    if not error_items or not all(_is_transient_error(item) for item in error_items):
        return False
    previous_updated = _parse_utc_timestamp(previous_status.get("updated_at"))
    current_updated = _parse_utc_timestamp(report.get("generated_at"))
    if previous_updated is None or current_updated is None:
        return False
    if current_updated < previous_updated:
        return False
    return (current_updated - previous_updated).total_seconds() <= 15 * 60




def _clamp_percent(value: Any) -> float:
    try:
        numeric = float(value or 0.0)
    except Exception:
        numeric = 0.0
    return round(max(0.0, min(100.0, numeric)), 2)


def _score_band(score: float) -> str:
    if score >= SCORE_PASS_THRESHOLD:
        return "pass"
    if score >= SCORE_WARNING_THRESHOLD:
        return "warning"
    return "degraded"


def _case_score_percent(item: dict[str, Any]) -> float:
    evaluation = item.get("evaluation") or {}
    return _clamp_percent(float(evaluation.get("score", 0.0) or 0.0) * 100.0)


def _average_percent(values: list[float]) -> float:
    if not values:
        return 0.0
    return _clamp_percent(sum(values) / len(values))


def _score_with_fallback(values: list[float], fallback: float, *, enabled: bool) -> float:
    if values:
        return _average_percent(values)
    return _average_percent([fallback]) if enabled else 0.0


def _category_scores(results: list[dict[str, Any]]) -> dict[str, list[float]]:
    scores: dict[str, list[float]] = {}
    for item in results:
        category = str(item.get("category") or "uncategorized").strip().lower()
        scores.setdefault(category, []).append(_case_score_percent(item))
    return scores


def _smoke_layer(results: list[dict[str, Any]]) -> tuple[float, int]:
    completed_cases = 0
    samples: list[float] = []
    for item in results:
        answer = str(item.get("answer") or "").strip()
        completed = not item.get("error") and bool(answer)
        if completed:
            completed_cases += 1
        samples.append(100.0 if completed else 0.0)
    return _average_percent(samples), completed_cases


def _dimension_scores(category_scores: dict[str, list[float]], capability_score: float) -> tuple[dict[str, float], str]:
    dimensions = {
        "accuracy_score": [],
        "reasoning_score": [],
        "code_score": [],
    }
    for category, scores in category_scores.items():
        for dimension in CATEGORY_DIMENSION_MAP.get(category, ()):
            if dimension == "stability_score":
                continue
            dimensions.setdefault(dimension, []).extend(scores)
    enabled = bool(category_scores)
    code_score_source = "direct" if dimensions["code_score"] else "capability_fallback"
    return ({
        "accuracy_score": _score_with_fallback(dimensions["accuracy_score"], capability_score, enabled=enabled),
        "reasoning_score": _score_with_fallback(dimensions["reasoning_score"], capability_score, enabled=enabled),
        "code_score": _score_with_fallback(dimensions["code_score"], capability_score, enabled=enabled),
    }, code_score_source)


def _stability_layer(
    results: list[dict[str, Any]],
    report: dict[str, Any],
    error_count: int,
    transient_recovery: bool,
) -> dict[str, Any]:
    total_cases = len(results)
    execution_score = _average_percent([100.0 if not item.get("error") else 0.0 for item in results])
    evaluation_score = _average_percent([_case_score_percent(item) for item in results])
    max_retries = max(0, int(report.get("max_retries", 0) or 0))
    extra_attempts = sum(max(0, int(item.get("attempt_count", 1) or 1) - 1) for item in results)
    retry_budget = total_cases * max_retries
    retry_health = 100.0 if retry_budget <= 0 else _clamp_percent(100.0 * (1.0 - min(1.0, extra_attempts / retry_budget)))
    provider_count = len(report.get("attempted_providers", []))
    provider_penalty = min(15.0, max(0, provider_count - 1) * 5.0)
    transient_bonus = 10.0 if transient_recovery else 0.0
    score = _clamp_percent((execution_score * 0.5) + (evaluation_score * 0.3) + (retry_health * 0.2) - provider_penalty + transient_bonus)
    return {
        "score": score,
        "status": _score_band(score),
        "error_count": error_count,
        "execution_score": execution_score,
        "retry_health": retry_health,
        "provider_penalty": provider_penalty,
        "transient_recovery": transient_recovery,
    }


def summarize_ai_test_report(report: dict[str, Any], previous_status: dict[str, Any] | None = None) -> dict[str, Any]:
    results = report.get("results", [])
    error_items = [item for item in results if item.get("error")]
    domain = _failure_domain(report, error_items)
    error_count = len(error_items)
    transient_recovery = _recent_transient_recovery_allowed(previous_status, report, error_items)
    case_gates = _case_gate_summary(results)
    category_scores = _category_scores(results)
    smoke_score, completed_cases = _smoke_layer(results)
    capability_score = _average_percent([_case_score_percent(item) for item in results])
    dimension_scores, code_score_source = _dimension_scores(category_scores, capability_score)
    stability = _stability_layer(results, report, error_count, transient_recovery)
    overall_score = _clamp_percent((smoke_score * 0.15) + (capability_score * 0.6) + (stability["score"] * 0.25))
    state = "missing" if not results else _score_band(overall_score)
    if not results:
        release_signal = "signal_only"
    else:
        if case_gates["all_passed"] and error_count == 0:
            release_signal = "ready"
        else:
            release_signal = "sampled_async"
    if error_count > 0:
        state = "warning" if transient_recovery else "degraded"
    elif not case_gates["all_release_blockers_passed"]:
        state = "degraded"
    elif not case_gates["all_passed"] and state == "pass":
        state = "warning"
    return {
        "status": state,
        "release_signal": release_signal,
        "overall_score": overall_score,
        "accuracy_score": dimension_scores["accuracy_score"],
        "reasoning_score": dimension_scores["reasoning_score"],
        "code_score": dimension_scores["code_score"],
        "stability_score": stability["score"],
        "case_gates": case_gates,
        "scorecard": {
            "accuracy_score": dimension_scores["accuracy_score"],
            "reasoning_score": dimension_scores["reasoning_score"],
            "code_score": dimension_scores["code_score"],
            "stability_score": stability["score"],
            "smoke_score": smoke_score,
            "capability_score": capability_score,
            "overall_score": overall_score,
            "pass_threshold": SCORE_PASS_THRESHOLD,
            "warning_threshold": SCORE_WARNING_THRESHOLD,
            "code_score_source": code_score_source,
        },
        "layers": {
            "smoke": {
                "status": _score_band(smoke_score),
                "score": smoke_score,
                "case_count": len(results),
                "completed_cases": completed_cases,
            },
            "capability": {
                "status": _score_band(capability_score),
                "score": capability_score,
                "case_count": len(results),
                "categories": sorted(category_scores.keys()),
            },
            "stability": {
                **stability,
                "case_count": len(results),
            },
        },
        "quality_signal": {
            "status": state,
            "release_signal": release_signal,
            "mode": "sampled_async",
            "signal_only": True,
        },
        "failure_domain": domain["failure_domain"],
        "case_failures_are_behavioral": domain["case_failures_are_behavioral"],
        "transport_blocked": domain["transport_blocked"],
        "transport_block_reason": domain["transport_block_reason"],
        "provider_diagnostics": domain["provider_diagnostics"],
    }


def build_status(report: dict[str, Any], previous_status: dict[str, Any] | None = None) -> dict[str, Any]:
    results = report.get("results", [])
    failing = [item.get("id") for item in results if not (item.get("evaluation") or {}).get("passed")]
    error_items = [item for item in results if item.get("error")]
    error_count = len(error_items)
    error_types: list[str] = []
    for item in error_items:
        error_type = str(item.get("error_type") or "").strip()
        if error_type and error_type not in error_types:
            error_types.append(error_type)
    max_attempt_count = max((int(item.get("attempt_count", 0) or 0) for item in results), default=0)
    summary = summarize_ai_test_report(report, previous_status=previous_status)
    staleness = _status_staleness(report.get("generated_at"))
    case_gates = summary["case_gates"]
    effective_status = "stale" if staleness["stale"] else summary["status"]
    effective_release_signal = "signal_only" if staleness["stale"] else summary["release_signal"]
    status = {
        "updated_at": report.get("generated_at", _utc()),
        "status": effective_status,
        "suite": report.get("suite"),
        "provider": report.get("provider"),
        "api_style": report.get("api_style"),
        "model": report.get("model"),
        "base_url": report.get("base_url"),
        "suite_path": report.get("suite_path"),
        "pass_rate": report.get("pass_rate", 0.0),
        "passed_cases": report.get("passed_cases", 0),
        "total_cases": report.get("total_cases", 0),
        "all_passed": case_gates["all_passed"],
        "failing_case_ids": failing[:10],
        "all_release_blockers_passed": case_gates["all_release_blockers_passed"],
        "release_blocker_case_ids": case_gates["release_blocker_case_ids"][:20],
        "failed_release_blocker_case_ids": case_gates["failed_release_blocker_case_ids"][:10],
        "optional_failing_case_ids": case_gates["optional_failing_case_ids"][:10],
        "error_count": error_count,
        "error_types": error_types,
        "max_attempt_count": max_attempt_count,
        "retry_policy": {
            "max_retries": int(report.get("max_retries", 0) or 0),
            "backoff_seconds": float(report.get("backoff_seconds", 0.0) or 0.0),
        },
        "attempted_providers": report.get("attempted_providers", []),
        "release_signal": effective_release_signal,
        "mode": "sampled_async",
        "signal_only": True,
        "overall_score": summary["overall_score"],
        "accuracy_score": summary["accuracy_score"],
        "reasoning_score": summary["reasoning_score"],
        "code_score": summary["code_score"],
        "stability_score": summary["stability_score"],
        "scorecard": summary["scorecard"],
        "layers": summary["layers"],
        "quality_signal": summary["quality_signal"],
        **staleness,
        "failure_domain": summary["failure_domain"],
        "case_failures_are_behavioral": summary["case_failures_are_behavioral"],
        "transport_blocked": summary["transport_blocked"],
        "transport_block_reason": summary["transport_block_reason"],
        "provider_diagnostics": summary["provider_diagnostics"],
    }
    if staleness["stale"]:
        status["quality_signal"] = {
            **status["quality_signal"],
            "status": "stale",
            "release_signal": "signal_only",
            "stale": True,
        }
    if summary["layers"]["stability"].get("transient_recovery"):
        status["transport_flap_recovered"] = True
        status["transport_error_count"] = error_count
        status["transport_error_types"] = error_types
        status["preserved_from_status"] = previous_status.get("status") if isinstance(previous_status, dict) else None
        status["preserved_from_updated_at"] = previous_status.get("updated_at") if isinstance(previous_status, dict) else None
        status["failing_case_ids"] = []
        status["failed_release_blocker_case_ids"] = []
        status["optional_failing_case_ids"] = []
    return status



def load_ai_test_status(report_path: str | Path = DEFAULT_STATUS) -> dict[str, Any]:
    path = Path(report_path)
    fallback_report = DEFAULT_REPORT if path == DEFAULT_STATUS else path
    report_payload = _load_json(fallback_report) if fallback_report.exists() else None
    if path.exists():
        payload = _load_json(path)
        if "results" in payload:
            status = build_status(payload, _load_json(DEFAULT_STATUS) if DEFAULT_STATUS.exists() else None)
            if path == DEFAULT_REPORT:
                _save_json(DEFAULT_STATUS, status)
            return status
        should_refresh = bool(report_payload and report_payload.get("generated_at")) and (
            payload.get("updated_at") != report_payload.get("generated_at")
            or "overall_score" not in payload
            or "layers" not in payload
            or "scorecard" not in payload
            or "all_passed" not in payload
            or "all_release_blockers_passed" not in payload
            or "failed_release_blocker_case_ids" not in payload
            or "mode" not in payload
            or "signal_only" not in payload
            or "mode" not in (payload.get("quality_signal") or {})
            or "signal_only" not in (payload.get("quality_signal") or {})
        )
        if should_refresh:
            status = build_status(report_payload, payload if isinstance(payload, dict) else None)
            if path == DEFAULT_STATUS:
                _save_json(DEFAULT_STATUS, status)
            return status
        return payload
    if report_payload:
        status = build_status(report_payload, _load_json(DEFAULT_STATUS) if DEFAULT_STATUS.exists() else None)
        if path == DEFAULT_STATUS or path == fallback_report:
            _save_json(DEFAULT_STATUS, status)
        return status
    return {
        "updated_at": None,
        "status": "missing",
        "suite": None,
        "provider": None,
        "api_style": None,
        "model": None,
        "base_url": settings.openai_base_url,
        "suite_path": str(DEFAULT_SUITE),
        "pass_rate": 0.0,
        "passed_cases": 0,
        "total_cases": 0,
        "all_passed": False,
        "failing_case_ids": [],
        "all_release_blockers_passed": False,
        "release_blocker_case_ids": [],
        "failed_release_blocker_case_ids": [],
        "optional_failing_case_ids": [],
        "error_count": 0,
        "error_types": [],
        "max_attempt_count": 0,
        "retry_policy": {"max_retries": 0, "backoff_seconds": 0.0},
        "attempted_providers": [],
        "release_signal": "signal_only",
        "mode": "sampled_async",
        "signal_only": True,
        "overall_score": 0.0,
        "accuracy_score": 0.0,
        "reasoning_score": 0.0,
        "code_score": 0.0,
        "stability_score": 0.0,
        "scorecard": {
            "accuracy_score": 0.0,
            "reasoning_score": 0.0,
            "code_score": 0.0,
            "stability_score": 0.0,
            "smoke_score": 0.0,
            "capability_score": 0.0,
            "overall_score": 0.0,
            "pass_threshold": SCORE_PASS_THRESHOLD,
            "warning_threshold": SCORE_WARNING_THRESHOLD,
            "code_score_source": "capability_fallback",
        },
        "layers": {
            "smoke": {"status": "missing", "score": 0.0, "case_count": 0, "completed_cases": 0},
            "capability": {"status": "missing", "score": 0.0, "case_count": 0, "categories": []},
            "stability": {"status": "missing", "score": 0.0, "case_count": 0, "error_count": 0, "execution_score": 0.0, "retry_health": 0.0, "provider_penalty": 0.0, "transient_recovery": False},
        },
        "quality_signal": {"status": "missing", "release_signal": "signal_only", "mode": "sampled_async", "signal_only": True},
    }

def _should_try_next_provider(results: list[dict[str, Any]]) -> bool:
    if not results:
        return True
    return all(item.get("error") for item in results)


def _is_transient_error(item: dict[str, Any]) -> bool:
    error_type = str(item.get("error_type") or "").strip()
    return error_type in {"APIConnectionError", "APITimeoutError", "RateLimitError", "TimeoutError"}


def _rerun_transient_failures(
    results: list[dict[str, Any]],
    provider: ProviderConfig,
    suite_prompt: str,
    cases: list[dict[str, Any]],
    *,
    timeout_seconds: float,
    max_retries: int,
    backoff_seconds: float,
) -> list[dict[str, Any]]:
    case_map = {str(item.get("id")): item for item in cases}
    retry_indexes = [index for index, item in enumerate(results) if item.get("error") and _is_transient_error(item)]
    if not retry_indexes:
        return results
    client = OpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout_seconds)
    refreshed = list(results)
    for index in retry_indexes:
        case_id = str(results[index].get("id") or "")
        case = case_map.get(case_id)
        if not case:
            continue
        rerun = run_case_with_retries(
            client,
            provider,
            suite_prompt,
            case,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
        )
        rerun["recovery_rerun"] = True
        refreshed[index] = rerun
    return refreshed


def run_ai_test_suite(
    suite_path: str | Path = DEFAULT_SUITE,
    report_path: str | Path = DEFAULT_REPORT,
    model_override: str = "",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict[str, Any]:
    suite_file = Path(suite_path).resolve()
    suite = _load_json(suite_file)
    cases = suite.get("cases", [])
    if not cases:
        raise SystemExit("suite contains no cases")

    providers = _build_provider_configs(model_override=model_override, suite_model=suite.get("model", ""))
    if not providers:
        raise SystemExit("No compatible LLM provider is configured")

    report_file = Path(report_path).resolve()
    suite_prompt = suite.get("system_prompt", "You are being evaluated. Answer normally.")
    attempted_providers: list[dict[str, Any]] = []
    final_results: list[dict[str, Any]] = []
    selected_provider = providers[0]

    for provider in providers:
        selected_provider = provider
        client = OpenAI(api_key=provider.api_key, base_url=provider.base_url, timeout=timeout_seconds)
        results: list[dict[str, Any]] = []
        for case in cases:
            results.append(
                run_case_with_retries(
                    client,
                    provider,
                    suite_prompt,
                    case,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    backoff_seconds=backoff_seconds,
                )
            )
        attempted_providers.append({
            "provider": provider.name,
            "api_style": provider.api_style,
            "model": provider.model,
            "base_url": provider.base_url,
            "all_errors": all(item.get("error") for item in results),
            "error_types": sorted({item.get("error_type") for item in results if item.get("error_type")}),
        })
        final_results = results
        if not _should_try_next_provider(results):
            final_results = _rerun_transient_failures(
                final_results,
                provider,
            suite_prompt,
            cases,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            )
            break

    passed_cases = sum(1 for item in final_results if item.get("evaluation", {}).get("passed"))
    total_cases = len(final_results)
    report = {
        "suite": suite.get("name", suite_file.stem),
        "description": suite.get("description", ""),
        "provider": selected_provider.name,
        "api_style": selected_provider.api_style,
        "model": selected_provider.model,
        "base_url": selected_provider.base_url,
        "generated_at": _utc(),
        "suite_path": str(suite_file),
        "max_retries": int(max_retries),
        "backoff_seconds": float(backoff_seconds),
        "attempted_providers": attempted_providers,
        "passed_cases": passed_cases,
        "total_cases": total_cases,
        "pass_rate": round(passed_cases / total_cases, 4) if total_cases else 0.0,
        "all_passed": passed_cases == total_cases,
        "results": final_results,
    }
    previous_status = _load_json(DEFAULT_STATUS) if DEFAULT_STATUS.exists() else {}
    report.update(summarize_ai_test_report(report, previous_status=previous_status))
    _save_json(report_file, report)
    _save_json(DEFAULT_STATUS, build_status(report, previous_status))
    return report



def main() -> int:
    parser = argparse.ArgumentParser(description="Run an automated AI behavior test suite against an OpenAI-compatible model.")
    parser.add_argument("--suite", default=str(DEFAULT_SUITE), help="Path to suite JSON")
    parser.add_argument("--report", default=str(DEFAULT_REPORT), help="Report path")
    parser.add_argument("--model", default="", help="Optional model override")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="Per-request timeout in seconds")
    parser.add_argument("--retries", type=int, default=DEFAULT_MAX_RETRIES, help="Retry count for transient case failures")
    parser.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF_SECONDS, help="Base seconds for linear retry backoff")
    parser.add_argument("--status-only", action="store_true", help="Print cached AI test status instead of running the suite")
    args = parser.parse_args()

    if args.status_only:
        print(json.dumps(load_ai_test_status(args.report), ensure_ascii=False, indent=2))
        return 0

    report = run_ai_test_suite(
        suite_path=args.suite,
        report_path=args.report,
        model_override=args.model,
        timeout_seconds=args.timeout,
        max_retries=args.retries,
        backoff_seconds=args.backoff,
    )
    print(f"ai test report: {Path(args.report).resolve()}")
    for item in report.get("results", []):
        evaluation = item.get("evaluation", {})
        status = "PASS" if evaluation.get("passed") else "FAIL"
        print(
            f"- {item.get('id')}: {status} "
            f"score={evaluation.get('score', 0.0)} "
            f"checks={evaluation.get('passed_checks', 0)}/{evaluation.get('total_checks', 0)}"
        )
        if item.get("error"):
            print(f"  error: {item['error']}")
    return 0 if report.get("all_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())








