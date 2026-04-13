from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = Path(os.environ.get("MODEL_GATEWAY_POLICY_PATH", str(ROOT / "docs" / "openwebui_model_policy.json")))
SYSTEM_PROMPT_PATH = Path(os.environ.get("MODEL_GATEWAY_SYSTEM_PROMPT_PATH", str(ROOT / "docs" / "openwebui_system_prompt.md")))
UPSTREAM_BASE_URL = os.environ.get("MODEL_GATEWAY_UPSTREAM_BASE_URL", "").rstrip("/")
UPSTREAM_API_KEY = os.environ.get("MODEL_GATEWAY_UPSTREAM_API_KEY", "")

app = FastAPI(title="Open WebUI Model Gateway", version="1.0.0")


def _load_policy() -> dict[str, Any]:
    if not POLICY_PATH.exists():
        raise HTTPException(status_code=500, detail=f"policy not found: {POLICY_PATH}")
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        raise HTTPException(status_code=500, detail=f"system prompt not found: {SYSTEM_PROMPT_PATH}")
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _model_map() -> dict[str, dict[str, str]]:
    policy = _load_policy()
    models = policy.get("models", {})
    result: dict[str, dict[str, str]] = {}
    for item in models.values():
        alias = item.get("alias")
        upstream = item.get("upstream")
        if alias and upstream:
            result[alias] = item
    return result


def _visible_models() -> list[dict[str, Any]]:
    models = _model_map()
    visible: list[dict[str, Any]] = []
    for alias, item in models.items():
        visible.append(
            {
                "id": alias,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "metaforge",
                "permission": [],
                "meta": {
                    "alias": alias,
                    "upstream": item["upstream"],
                    "label": item.get("label", alias),
                },
            }
        )
    return sorted(visible, key=lambda entry: entry["id"])


def _upstream_headers(incoming: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    auth = incoming.headers.get("authorization")
    if auth:
        headers["authorization"] = auth
    elif UPSTREAM_API_KEY:
        headers["authorization"] = f"Bearer {UPSTREAM_API_KEY}"
    content_type = incoming.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    accept = incoming.headers.get("accept")
    if accept:
        headers["accept"] = accept
    return headers


async def _proxy_json(path: str, request: Request, payload: dict[str, Any] | None = None) -> Response:
    if not UPSTREAM_BASE_URL:
        raise HTTPException(status_code=500, detail="upstream base url is not configured")
    if payload is None:
        payload = await request.json()
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.request(
            request.method,
            f"{UPSTREAM_BASE_URL}{path}",
            headers=_upstream_headers(request),
            json=payload,
            params=request.query_params,
        )
    return Response(content=response.content, status_code=response.status_code, media_type=response.headers.get("content-type"))


async def _proxy_stream(path: str, request: Request, payload: dict[str, Any]) -> Response:
    if not UPSTREAM_BASE_URL:
        raise HTTPException(status_code=500, detail="upstream base url is not configured")

    async def iterator():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                request.method,
                f"{UPSTREAM_BASE_URL}{path}",
                headers=_upstream_headers(request),
                json=payload,
                params=request.query_params,
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(iterator(), media_type="text/event-stream")


def _rewrite_model(payload: dict[str, Any], model_value: str | None) -> dict[str, Any]:
    if not model_value:
        return payload
    models = _model_map()
    item = models.get(model_value)
    if not item:
        raise HTTPException(status_code=400, detail=f"model not allowed: {model_value}")
    payload = dict(payload)
    payload["model"] = item["upstream"]
    return payload


def _inject_system_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = _load_system_prompt()
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload
    payload = dict(payload)
    payload["messages"] = [{"role": "system", "content": prompt}, *messages]
    return payload


def _last_user_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
    return ""


def _is_identity_question(text: str) -> bool:
    normalized = text.lower()
    keywords = (
        "aifactory",
        "ai工厂",
        "metaforge",
        "你现在在什么系统",
        "你在哪个系统",
        "什么系统",
        "谁控制",
        "谁在控制",
        "你是谁",
        "meta forge",
    )
    return any(keyword in normalized for keyword in keywords)


def _identity_response() -> dict[str, Any]:
    content = (
        "我在 MetaForge 的 Open WebUI 控制入口中。"
        "MetaForge 是运行在 D:\\codex 的本地 AI 软件工厂，"
        "控制真相源是 MetaForge Controller API。"
    )
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "minimax-m2.5",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def _stream_identity_response() -> StreamingResponse:
    content = (
        "data: {\"id\":\"chatcmpl-identity\",\"object\":\"chat.completion.chunk\",\"created\":"
        f"{int(time.time())},\"model\":\"minimax-m2.5\",\"choices\":[{{\"index\":0,\"delta\":{{\"role\":\"assistant\",\"content\":\"我在 MetaForge 的 Open WebUI 控制入口中。MetaForge 是运行在 D:\\\\codex 的本地 AI 软件工厂，控制真相源是 MetaForge Controller API。\"}},\"finish_reason\":null}}]}}\n\n"
        "data: [DONE]\n\n"
    )
    return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/event-stream")


@app.get("/v1/models")
@app.get("/models")
@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    return {"object": "list", "data": _visible_models()}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "policy_path": str(POLICY_PATH), "upstream_configured": bool(UPSTREAM_BASE_URL)}


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(request: Request) -> Response:
    payload = await request.json()
    user_text = _last_user_text(payload)
    user_text_lower = user_text.lower()
    if (
        "MetaForge" in user_text
        or "meta forge" in user_text_lower
        or "AI工厂" in user_text
        or "什么系统" in user_text
        or "你是谁" in user_text
        or "谁控制" in user_text
        or "谁在控制" in user_text
    ):
        if payload.get("stream"):
            return _stream_identity_response()
        return JSONResponse(_identity_response())
    payload = _rewrite_model(payload, payload.get("model"))
    payload = _inject_system_prompt(payload)
    if payload.get("stream"):
        return await _proxy_stream("/chat/completions", request, payload)
    return await _proxy_json("/chat/completions", request, payload)


@app.post("/v1/completions")
@app.post("/completions")
async def completions(request: Request) -> Response:
    payload = await request.json()
    payload = _rewrite_model(payload, payload.get("model"))
    return await _proxy_json("/completions", request, payload)


@app.post("/v1/embeddings")
@app.post("/embeddings")
async def embeddings(request: Request) -> Response:
    payload = await request.json()
    payload = _rewrite_model(payload, payload.get("model"))
    return await _proxy_json("/embeddings", request, payload)
