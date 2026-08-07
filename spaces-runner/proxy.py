"""Reverse proxy from /{owner}/{repo}/{path} to the running Space container."""
from __future__ import annotations

import asyncio

import httpx
import websockets
from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.datastructures import MutableHeaders

import config
import gpu_control
import spaces

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None))
    return _client


def _not_running_response(owner: str, repo: str) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "space is not running",
            "hint": f"POST /api/spaces/{owner}/{repo}/start to launch it first",
        },
    )


async def proxy_http(request: Request, owner: str, repo: str, path: str) -> StreamingResponse | JSONResponse:
    if config.GPU_WORKERS_ENABLED:
        route = await asyncio.to_thread(gpu_control.runtime_route, owner, repo)
        if route:
            return await _proxy_remote_http(request, route, path)
    status = spaces.probe_container_status(owner, repo)
    if status != "running":
        return _not_running_response(owner, repo)

    spaces.registry.touch(owner, repo)
    container = spaces.container_name(owner, repo)
    target_url = f"http://{container}:{config.CONTAINER_PORT}/{path}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    # Preserve the external Host so Gradio generates URLs for the gateway,
    # not for the internal container hostname.
    original_host = request.headers.get("host")
    if original_host:
        headers["host"] = original_host
        headers["x-forwarded-host"] = original_host
    headers.setdefault("x-forwarded-proto", request.headers.get("x-forwarded-proto", "http"))
    body = await request.body()

    client = get_http_client()
    try:
        upstream_req = client.build_request(
            request.method,
            target_url,
            headers=headers,
            params=request.query_params,
            content=body,
        )
        upstream_resp = await client.send(upstream_req, stream=True)
    except httpx.RequestError:
        return _not_running_response(owner, repo)

    response_headers = MutableHeaders()
    for k, v in upstream_resp.headers.items():
        if k.lower() not in _HOP_BY_HOP:
            response_headers.append(k, v)

    async def stream_body():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_resp.status_code,
        headers=dict(response_headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


async def _proxy_remote_http(
    request: Request, route: dict, path: str
) -> StreamingResponse | JSONResponse:
    target_url = f"{route['url'].rstrip('/')}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    headers["authorization"] = f"Bearer {route['token']}"
    body = await request.body()
    client = get_http_client()
    try:
        upstream_req = client.build_request(
            request.method,
            target_url,
            headers=headers,
            params=request.query_params,
            content=body,
        )
        upstream_resp = await client.send(upstream_req, stream=True)
    except httpx.RequestError:
        return JSONResponse(
            status_code=503,
            content={"error": "remote GPU runtime is unavailable", "job_id": route["job_id"]},
        )
    response_headers = MutableHeaders()
    for key, value in upstream_resp.headers.items():
        if key.lower() not in _HOP_BY_HOP:
            response_headers.append(key, value)

    async def stream_body():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        stream_body(),
        status_code=upstream_resp.status_code,
        headers=dict(response_headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


async def proxy_websocket(ws: WebSocket, owner: str, repo: str, path: str) -> None:
    if config.GPU_WORKERS_ENABLED:
        route = await asyncio.to_thread(gpu_control.runtime_route, owner, repo)
        if route:
            await _proxy_remote_websocket(ws, route, path)
            return
    status = spaces.probe_container_status(owner, repo)
    if status != "running":
        await ws.close(code=1013)  # try again later
        return

    spaces.registry.touch(owner, repo)
    container = spaces.container_name(owner, repo)
    query = f"?{ws.url.query}" if ws.url.query else ""
    target_url = f"ws://{container}:{config.CONTAINER_PORT}/{path}{query}"

    requested_subprotocols = [
        item.strip()
        for item in ws.headers.get("sec-websocket-protocol", "").split(",")
        if item.strip()
    ]

    forward_headers = [
        (k, v)
        for k, v in ws.headers.items()
        if k.lower() not in _HOP_BY_HOP
        and k.lower()
        not in ("sec-websocket-key", "sec-websocket-version", "sec-websocket-protocol")
    ]

    try:
        async with websockets.connect(
            target_url,
            extra_headers=forward_headers,
            subprotocols=requested_subprotocols or None,
            open_timeout=15,
            max_size=None,
        ) as upstream:
            # Streamlit requires the negotiated `streamlit` protocol to be
            # echoed to the browser. Accept only after the upstream handshake
            # so generic Docker Spaces preserve protocol negotiation end to end.
            await ws.accept(subprotocol=upstream.subprotocol)

            async def client_to_upstream():
                try:
                    while True:
                        msg = await ws.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if "text" in msg and msg["text"] is not None:
                            await upstream.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"] is not None:
                            await upstream.send(msg["bytes"])
                except (WebSocketDisconnect, RuntimeError):
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        spaces.registry.touch(owner, repo)
                        if isinstance(message, bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                except websockets.ConnectionClosed:
                    pass

            done, pending = await asyncio.wait(
                [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (OSError, websockets.InvalidHandshake, asyncio.TimeoutError):
        pass
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass


async def _proxy_remote_websocket(ws: WebSocket, route: dict, path: str) -> None:
    base = route["url"].replace("https://", "wss://").replace("http://", "ws://")
    query = f"?{ws.url.query}" if ws.url.query else ""
    target_url = f"{base.rstrip('/')}/{path}{query}"
    try:
        async with websockets.connect(
            target_url,
            extra_headers={"Authorization": f"Bearer {route['token']}"},
            open_timeout=15,
            max_size=None,
        ) as upstream:
            await ws.accept(subprotocol=upstream.subprotocol)

            async def client_to_upstream():
                try:
                    while True:
                        message = await ws.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        if message.get("text") is not None:
                            await upstream.send(message["text"])
                        elif message.get("bytes") is not None:
                            await upstream.send(message["bytes"])
                except (WebSocketDisconnect, RuntimeError):
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await ws.send_bytes(message)
                        else:
                            await ws.send_text(message)
                except websockets.ConnectionClosed:
                    pass

            _, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_upstream()),
                    asyncio.create_task(upstream_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (OSError, websockets.InvalidHandshake, asyncio.TimeoutError):
        await ws.close(code=1013)
