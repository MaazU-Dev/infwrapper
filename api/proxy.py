import os
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse


BACKEND_URL = os.getenv("LLM_BACKEND_URL", "http://localhost:11434/v1").rstrip("/")
PROXY_API_KEY = os.getenv("PROXY_API_KEY", "")
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "backend_url": BACKEND_URL}


@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_v1(path: str, request: Request):
    _check_auth(request)

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
