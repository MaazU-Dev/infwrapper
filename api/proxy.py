import os
import json
import time
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


BACKEND_URL = os.getenv("LLM_BACKEND_URL", "http://localhost:11434/v1").rstrip("/")
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "")
PROXY_MODEL_OVERRIDE = os.getenv("PROXY_MODEL_OVERRIDE", "").strip()
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

app = FastAPI(title="Local LLM OpenAI-Compatible Proxy")


def _check_auth(request: Request) -> None:
    if not PROXY_API_KEY:
        return

    auth_header = request.headers.get("authorization", "")
    expected = f"Bearer {PROXY_API_KEY}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _forward_headers(request: Request) -> dict[str, str]:
    headers = {}
    for key, value in request.headers.items():
        lower_key = key.lower()
        if lower_key in HOP_BY_HOP_HEADERS or lower_key == "host":
            continue
        headers[key] = value
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "content-length"
    }


async def _stream_response(
    response: httpx.Response, client: httpx.AsyncClient
) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()
        await client.aclose()


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _anthropic_to_openai_payload(payload: dict[str, Any]) -> dict[str, Any]:
    openai_messages: list[dict[str, str]] = []
    system = payload.get("system")
    if isinstance(system, str) and system:
        openai_messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        system_text = _extract_text_content(system)
        if system_text:
            openai_messages.append({"role": "system", "content": system_text})

    for msg in payload.get("messages", []):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        openai_messages.append(
            {"role": role, "content": _extract_text_content(msg.get("content"))}
        )

    result: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": openai_messages,
        "stream": bool(payload.get("stream", False)),
    }
    if "max_tokens" in payload:
        result["max_tokens"] = payload["max_tokens"]
    if "temperature" in payload:
        result["temperature"] = payload["temperature"]
    if "top_p" in payload:
        result["top_p"] = payload["top_p"]
    if "stop_sequences" in payload and isinstance(payload["stop_sequences"], list):
        result["stop"] = payload["stop_sequences"]
    return result


def _is_claude_model(model: str | None) -> bool:
    return isinstance(model, str) and model.startswith("claude-")


async def _discover_backend_default_model(client: httpx.AsyncClient) -> str | None:
    try:
        models_url = f"{BACKEND_URL}/models"
        response = await client.get(models_url)
        response.raise_for_status()
        body = response.json()
    except Exception:
        return None

    data = body.get("data")
    if not isinstance(data, list):
        return None
    for model in data:
        if isinstance(model, dict) and isinstance(model.get("id"), str):
            return model["id"]
    return None


async def _resolve_target_model(
    incoming_model: Any, client: httpx.AsyncClient
) -> tuple[str | None, str | None]:
    model = incoming_model if isinstance(incoming_model, str) else None

    if PROXY_MODEL_OVERRIDE:
        return PROXY_MODEL_OVERRIDE, model

    if _is_claude_model(model):
        discovered = await _discover_backend_default_model(client)
        if discovered:
            return discovered, model
    return model, model


def _map_finish_reason(reason: str | None) -> str:
    mapping = {
        "stop": "end_turn",
        "length": "max_tokens",
        "content_filter": "stop_sequence",
        "tool_calls": "tool_use",
    }
    return mapping.get(reason or "", "end_turn")


def _openai_to_anthropic_response(payload: dict[str, Any], model: str) -> dict[str, Any]:
    choices = payload.get("choices", [])
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
    text = message.get("content", "") if isinstance(message, dict) else ""
    finish_reason = first_choice.get("finish_reason") if isinstance(first_choice, dict) else None
    usage = payload.get("usage", {}) if isinstance(payload.get("usage"), dict) else {}

    return {
        "id": f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text if isinstance(text, str) else ""}],
        "stop_reason": _map_finish_reason(finish_reason),
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        },
    }


def _sse_event(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


async def _stream_openai_to_anthropic(
    response: httpx.Response, client: httpx.AsyncClient, model: str
) -> AsyncIterator[bytes]:
    message_id = f"msg_{uuid.uuid4().hex}"
    output_tokens = 0
    stop_reason = "end_turn"
    started_content = False

    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    try:
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices", [])
            if not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                delta = {}
            text_delta = delta.get("content", "")

            if isinstance(text_delta, str) and text_delta:
                if not started_content:
                    started_content = True
                    yield _sse_event(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                yield _sse_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text_delta},
                    },
                )

            finish_reason = choice.get("finish_reason")
            if finish_reason:
                stop_reason = _map_finish_reason(
                    finish_reason if isinstance(finish_reason, str) else None
                )

            usage = chunk.get("usage")
            if isinstance(usage, dict):
                output_tokens = int(usage.get("completion_tokens", output_tokens) or 0)
    finally:
        if started_content:
            yield _sse_event("content_block_stop", {"type": "content_block_stop", "index": 0})
        yield _sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            },
        )
        yield _sse_event("message_stop", {"type": "message_stop"})
        await response.aclose()
        await client.aclose()


async def _proxy_anthropic_messages(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request_error", "message": "Invalid JSON body"}},
        )

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request_error", "message": "Invalid JSON body"}},
        )

    openai_payload = _anthropic_to_openai_payload(payload)
    target_url = f"{BACKEND_URL}/chat/completions"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    client = httpx.AsyncClient(timeout=None)
    resolved_model, original_model = await _resolve_target_model(payload.get("model"), client)
    if resolved_model:
        openai_payload["model"] = resolved_model

    headers = _forward_headers(request)
    headers.pop("content-length", None)
    headers["content-type"] = "application/json"

    upstream_request = client.build_request(
        "POST",
        target_url,
        headers=headers,
        json=openai_payload,
    )

    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"error": "backend_unavailable", "detail": str(exc)},
        )

    if openai_payload.get("stream"):
        return StreamingResponse(
            _stream_openai_to_anthropic(
                upstream_response, client, str(original_model or resolved_model or "unknown")
            ),
            status_code=upstream_response.status_code,
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    try:
        raw = await upstream_response.aread()
        upstream_json = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        await upstream_response.aclose()
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"error": "invalid_backend_response", "detail": "Expected JSON body"},
        )

    status_code = upstream_response.status_code
    await upstream_response.aclose()
    await client.aclose()
    if status_code >= 400:
        return JSONResponse(status_code=status_code, content=upstream_json)

    return JSONResponse(
        status_code=status_code,
        content=_openai_to_anthropic_response(
            upstream_json, str(original_model or resolved_model or "unknown")
        ),
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "backend_url": BACKEND_URL}


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_v1(path: str, request: Request):
    _check_auth(request)
    if request.method == "POST" and path == "messages":
        return await _proxy_anthropic_messages(request)

    target_url = f"{BACKEND_URL}/{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    client = httpx.AsyncClient(timeout=None)
    upstream_request = client.build_request(
        request.method,
        target_url,
        headers=_forward_headers(request),
        content=body,
    )

    try:
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        return JSONResponse(
            status_code=502,
            content={"error": "backend_unavailable", "detail": str(exc)},
        )

    return StreamingResponse(
        _stream_response(upstream_response, client),
        status_code=upstream_response.status_code,
        headers=_response_headers(upstream_response),
        media_type=upstream_response.headers.get("content-type"),
    )
