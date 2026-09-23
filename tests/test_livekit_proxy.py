import asyncio
import threading

import pytest
from aiohttp import web
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.middleware.auth_middleware import AuthMiddleware
from app.routers import livekit_proxy


@pytest.fixture
def proxy(monkeypatch):
    ready = threading.Event()
    loop = asyncio.new_event_loop()
    state = {}

    async def rtc(request):
        state['headers'] = dict(request.headers)
        if (request.query.get('access_token') != 'scoped-test-token'
                and request.headers.get('Authorization') != 'Bearer scoped-test-token'):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if isinstance(msg.data, bytes):
                await ws.send_bytes(msg.data)
            elif isinstance(msg.data, str):
                if msg.data == 'close-upstream':
                    await ws.close()
                    break
                await ws.send_str(msg.data)
        state['closed'] = True
        return ws

    async def validate(request):
        return web.Response(status=200 if request.query.get('access_token') == 'scoped-test-token' else 401)

    async def start():
        app = web.Application()
        app.router.add_get('/rtc', rtc)
        app.router.add_get('/rtc/validate', validate)
        runner = web.AppRunner(app)
        await runner.setup()
        server = await loop.create_server(runner.server, '127.0.0.1', 0)
        state.update(runner=runner, server=server, port=server.sockets[0].getsockname()[1])
        ready.set()

    def run():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start())
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(10)
    monkeypatch.setattr(livekit_proxy.settings, 'livekit_internal_url', f'ws://127.0.0.1:{state["port"]}')
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key='test')
    app.include_router(livekit_proxy.router)
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        state['server'].close()
        asyncio.run_coroutine_threadsafe(state['runner'].cleanup(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(10)
        loop.close()


def test_signaling_relays_binary_text_and_upstream_close(proxy):
    client, state = proxy
    with client.websocket_connect('/livekit/rtc?access_token=scoped-test-token') as ws:
        ws.send_bytes(b'protobuf\x00\xff')
        assert ws.receive_bytes() == b'protobuf\x00\xff'
        ws.send_text('signal')
        assert ws.receive_text() == 'signal'
        ws.send_text('close-upstream')
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    assert state['closed']


def test_signaling_rejects_invalid_token_before_upgrade(proxy):
    client, _ = proxy
    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect('/livekit/rtc?access_token=invalid'):
            pass
    assert denied.value.status_code == 401


def test_v1_preserves_fallback_404(proxy):
    client, _ = proxy
    with pytest.raises(WebSocketDenialResponse) as denied:
        with client.websocket_connect('/livekit/rtc/v1?access_token=scoped-test-token'):
            pass
    assert denied.value.status_code == 404


def test_validate_uses_livekit_auth_without_dashboard_cookie(proxy):
    client, _ = proxy
    assert client.get('/livekit/rtc/validate?access_token=scoped-test-token').status_code == 200
    assert client.get('/livekit/rtc/validate?access_token=invalid').status_code == 401
    assert client.get('/livekit/twirp/livekit.RoomService/ListRooms', headers={'accept': 'application/json'}).status_code == 401


def test_proxy_disabled_by_default(proxy, monkeypatch):
    client, _ = proxy
    monkeypatch.setattr(livekit_proxy.settings, 'livekit_internal_url', '')
    assert client.get('/livekit/rtc/validate').status_code == 503
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/livekit/rtc'):
            pass


def test_access_logs_do_not_receive_jwt_query():
    from starlette.requests import Request
    scope = {'type': 'http', 'headers': [], 'query_string': b'access_token=secret&auto_subscribe=1'}
    query, headers = livekit_proxy._connection_args(Request(scope))
    assert query == 'access_token=secret&auto_subscribe=1'
    assert scope['query_string'] == b''
    assert headers == {}


def test_android_authorization_header_is_forwarded_without_cookie(proxy):
    client, state = proxy
    with client.websocket_connect('/livekit/rtc?sdk=android', headers={
        'Authorization': 'Bearer scoped-test-token', 'Cookie': 'acs_session=private',
    }) as ws:
        ws.send_bytes(b'android-signal')
        assert ws.receive_bytes() == b'android-signal'
    assert state['headers']['Authorization'] == 'Bearer scoped-test-token'
    assert 'Cookie' not in state['headers']
