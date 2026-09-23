"""Expose only LiveKit RTC signaling behind the dashboard's existing TLS endpoint.

The fixed upstream verifies LiveKit JWTs; no dashboard cookie is forwarded and
neither the room-admin API nor arbitrary upstream URLs are exposed.
"""

import asyncio
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from starlette.responses import Response

from app.config import settings

router = APIRouter(prefix="/livekit", tags=["livekit-signaling"])


def _upstream(path: str, query: str, *, http: bool = False) -> str | None:
    base = urlsplit(settings.livekit_internal_url)
    if base.scheme not in {"ws", "wss"} or not base.netloc:
        return None
    scheme = {"ws": "http", "wss": "https"}[base.scheme] if http else base.scheme
    return urlunsplit((scheme, base.netloc, base.path.rstrip("/") + path, query, ""))


def _connection_args(connection: Request | WebSocket) -> tuple[str, dict[str, str]]:
    query = connection.scope.get("query_string", b"").decode("ascii")
    # Uvicorn logs the scope when responding/accepting. Never log JWT queries.
    connection.scope["query_string"] = b""
    authorization = connection.headers.get("authorization")
    return query, {"Authorization": authorization} if authorization else {}


@router.get("/rtc/validate")
async def validate(request: Request):
    query, headers = _connection_args(request)
    url = _upstream("/rtc/validate", query, http=True)
    if not url:
        return Response(status_code=503)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers, allow_redirects=False) as response:
                body = await response.content.read(65536)
                return Response(body, status_code=response.status,
                                headers={"Content-Type": response.headers.get("Content-Type", "text/plain")})
    except (aiohttp.ClientError, TimeoutError):
        return Response(status_code=502)


@router.websocket("/rtc")
@router.websocket("/rtc/v1")
async def signaling(websocket: WebSocket):
    query, headers = _connection_args(websocket)
    path = websocket.url.path.removeprefix("/livekit")
    url = _upstream(path, query)
    if not url:
        await websocket.close(code=1013)
        return
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.ws_connect(url, headers=headers, max_msg_size=2**20,
                                          heartbeat=30) as upstream:
                await websocket.accept()

                async def to_livekit():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        if message.get("bytes") is not None:
                            await upstream.send_bytes(message["bytes"])
                        elif message.get("text") is not None:
                            await upstream.send_str(message["text"])

                async def to_client():
                    async for message in upstream:
                        if message.type == aiohttp.WSMsgType.BINARY:
                            await websocket.send_bytes(message.data)
                        elif message.type == aiohttp.WSMsgType.TEXT:
                            await websocket.send_text(message.data)
                        else:
                            return

                tasks = [asyncio.create_task(to_livekit()), asyncio.create_task(to_client())]
                try:
                    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                with suppress(RuntimeError, WebSocketDisconnect):
                    await websocket.close(code=1000 if upstream.close_code in {None, 1000} else 1011)
    except aiohttp.WSServerHandshakeError as exc:
        # Preserve e.g. v1's 404 so newer SDKs can fall back to legacy signaling.
        await websocket.send_denial_response(Response(status_code=exc.status))
    except (aiohttp.ClientError, TimeoutError):
        with suppress(RuntimeError, WebSocketDisconnect):
            await websocket.close(code=1011)
