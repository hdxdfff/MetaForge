from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.provider_gateway import provider_gateway
from tools.io_utils import atomic_write_json
DATA = ROOT / "data"
KNOWLEDGE_PATH = DATA / "internet_knowledge.json"
STATUS_PATH = DATA / "perplexity_research_status.json"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def load_internet_knowledge() -> dict[str, Any]:
    return _load_json(
        KNOWLEDGE_PATH,
        {
            "updated_at": None,
            "provider": "perplexity",
            "status": "not-run",
            "latest": None,
            "history": [],
        },
    )


def load_perplexity_status() -> dict[str, Any]:
    return _load_json(
        STATUS_PATH,
        {
            "updated_at": None,
            "provider": "perplexity",
            "configured": False,
            "status": "not-configured",
            "model": settings.perplexity_model,
            "base_url": settings.perplexity_base_url,
            "history_count": 0,
        },
    )


def _persist_result(entry: dict[str, Any], *, status: str, configured: bool, error: str | None = None) -> dict[str, Any]:
    knowledge = load_internet_knowledge()
    history = list(knowledge.get("history", []))
    history.append(entry)
    history = history[-30:]
    atomic_write_json(
        KNOWLEDGE_PATH,
        {
            "updated_at": _utc(),
            "provider": "perplexity",
            "status": status,
            "latest": entry,
            "history": history,
        },
    )
    atomic_write_json(
        STATUS_PATH,
        {
            "updated_at": _utc(),
            "provider": "perplexity",
            "configured": configured,
            "status": status,
            "model": settings.perplexity_model,
            "base_url": settings.perplexity_base_url,
            "history_count": len(history),
            "last_query": entry.get("query"),
            "last_focus": entry.get("focus"),
            "last_error": error,
        },
    )
    return entry


def run_perplexity_search(query: str, *, focus: str = "general") -> dict[str, Any]:
    clean_query = str(query or "").strip()
    clean_focus = str(focus or "general").strip().lower() or "general"
    if not clean_query:
        raise ValueError("query is required")

    entry = {
        "queried_at": _utc(),
        "query": clean_query,
        "focus": clean_focus,
        "provider": "perplexity",
        "model": settings.perplexity_model,
        "status": "disabled",
        "summary": "",
        "raw_text": "",
        "findings": [],
        "source_links": [],
        "next_actions": [],
    }
    if not settings.perplexity_api_key:
        entry["summary"] = "Perplexity API key is not configured."
        entry["next_actions"] = [
            "Set PERPLEXITY_API_KEY in the orchestrator environment.",
            "Rerun the research step to refresh internet knowledge.",
        ]
        return _persist_result(entry, status="not-configured", configured=False, error="missing-api-key")

    fallback = json.dumps(
        {
            "summary": "Perplexity returned no structured content.",
            "findings": [],
            "source_links": [],
            "next_actions": ["Retry the query or refine the search scope."],
        },
        ensure_ascii=False,
    )
    response = provider_gateway.chat_completions_create(
        provider_name="perplexity",
        api_key=settings.perplexity_api_key,
        default_base_url=settings.perplexity_base_url,
        base_url_candidates=list(settings.perplexity_base_url_candidates),
        default_proxy=settings.network_proxy_url,
        proxy_candidates=list(settings.perplexity_proxy_candidates),
        timeout_seconds=settings.perplexity_request_timeout_seconds,
        request_kwargs={
            "model": settings.perplexity_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the Internet Knowledge layer for a local AI factory. "
                        "Return strict JSON with keys summary, findings, source_links, next_actions. "
                        "Keep findings concise and implementation-oriented."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Research focus: {clean_focus}\n"
                        f"Query: {clean_query}\n\n"
                        "Return JSON with:\n"
                        "- summary: string\n"
                        "- findings: string[]\n"
                        "- source_links: string[]\n"
                        "- next_actions: string[]"
                    ),
                },
            ],
            "stream": False,
            "temperature": 0.1,
        },
    )
    text = ""
    if response.choices:
        message = response.choices[0].message
        if isinstance(message.content, str):
            text = message.content
        elif isinstance(message.content, list):
            text = "\n".join(item.text for item in message.content if hasattr(item, "text"))
    text = (text or fallback).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {
            "summary": text[:2000],
            "findings": [],
            "source_links": [],
            "next_actions": ["Normalize the upstream response before downstream routing."],
        }
    entry["status"] = "ready"
    entry["summary"] = str(payload.get("summary") or "")
    entry["raw_text"] = text
    entry["findings"] = [str(item) for item in payload.get("findings", []) if item][:8]
    entry["source_links"] = [str(item) for item in payload.get("source_links", []) if item][:12]
    entry["next_actions"] = [str(item) for item in payload.get("next_actions", []) if item][:8]
    return _persist_result(entry, status="ready", configured=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Perplexity-backed research query and persist Internet Knowledge output.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--focus", default="general")
    args = parser.parse_args()
    print(json.dumps(run_perplexity_search(args.query, focus=args.focus), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
