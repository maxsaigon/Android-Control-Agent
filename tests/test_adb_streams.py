import asyncio
import importlib
import json
import struct
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlmodel import Session, SQLModel, create_engine
from starlette.middleware.sessions import SessionMiddleware
from starlette.websockets import WebSocketDisconnect

from app.models import Device, DeviceStatus, DeviceToken, User
from app.routers import adb_streams


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'devices.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(adb_streams, 'engine', engine)
    monkeypatch.setattr(adb_streams.settings, 'scrcpy_enabled', False)
    monkeypatch.setattr(adb_streams.settings, 'helper_owner_username', 'operator')
    with Session(engine) as db:
        db.add_all([
            User(id=1, username='operator', password='test'),
            User(id=2, username='other', password='test'),
            Device(id=1, name='ADB', ip_address='192.0.2.1', status=DeviceStatus.ONLINE),
            Device(id=2, name='Cloud', ip_address='cloud', adb_port=0, status=DeviceStatus.ONLINE),
        ])
        db.commit()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key='test')
    app.include_router(adb_streams.router)

    @app.get('/login/{user_id}')
    def login(request: Request, user_id: int):
        request.session['user_id'] = user_id

    with TestClient(app) as http:
        yield http


def test_socket_rejects_missing_session_and_cross_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/adb/1', headers={'origin': 'http://testserver'}):
            pass
    client.get('/login/1')
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/adb/1', headers={'origin': 'https://evil.test'}):
            pass


def test_unassigned_device_is_operator_only(client):
    client.get('/login/2')
    with client.websocket_connect('/ws/adb/1', headers={'origin': 'http://testserver'}) as ws:
        assert 'belong' in ws.receive_json()['error']


def test_disabled_gateway_reports_actionable_error(client):
    client.get('/login/1')
    with client.websocket_connect('/ws/adb/1', headers={'origin': 'http://testserver'}) as ws:
        assert 'SCRCPY_ENABLED' in ws.receive_json()['error']


def test_cloud_device_cannot_enter_adb_gateway(client):
    with pytest.raises(ValueError, match='LiveKit'):
        adb_streams.allowed_serial(2, 1)


def test_token_owner_and_revocation(client):
    with Session(adb_streams.engine) as db:
        token = DeviceToken(device_id=1, user_id=2, token='test-token')
        db.add(token)
        db.commit()
        assert adb_streams.allowed_serial(1, 2) == '192.0.2.1:5555'
        token.is_active = False
        db.add(token)
        db.commit()
    with pytest.raises(PermissionError):
        adb_streams.allowed_serial(1, 2)


@pytest.mark.parametrize('message', [
    {'action': 'shell', 'text': 'reboot'},
    {'action': 'touch', 'phase': 0, 'pointerId': 1, 'x': -1, 'y': 0},
    {'action': 'touch', 'phase': 0, 'pointerId': 1, 'x': float('nan'), 'y': 0},
    {'action': 'key', 'keyCode': 26},
    {'action': 'text', 'text': 'x' * 4097},
])
def test_control_rejects_unsupported_or_unbounded_input(message):
    with pytest.raises(ValidationError):
        adb_streams.control_message.validate_python(message)


def test_relay_preserves_binary_and_unicode_and_cancels_readers():
    async def run():
        stdout = asyncio.StreamReader()
        stderr = asyncio.StreamReader()
        packet = b'\x01' + (123).to_bytes(8, 'big') + b'\x00\x00\x00\x01\x65'
        stdout.feed_data(struct.pack('>I', len(packet))[:2])
        stdout.feed_data(struct.pack('>I', len(packet))[2:] + packet)
        received = asyncio.Event()
        writes = []
        stdin = SimpleNamespace(write=writes.append, drain=AsyncMock())

        class Socket:
            count = 0

            async def send_bytes(self, value):
                assert value == packet
                received.set()

            async def receive_text(self):
                if self.count == 0:
                    self.count += 1
                    return json.dumps({'action': 'text', 'text': 'Xin chào Việt Nam'})
                await received.wait()
                raise WebSocketDisconnect()

        with pytest.raises(WebSocketDisconnect):
            await adb_streams.relay_worker(Socket(), SimpleNamespace(stdout=stdout, stderr=stderr, stdin=stdin))
        assert json.loads(writes[0])['text'] == 'Xin chào Việt Nam'
        assert not stdout._waiter
        assert not stderr._waiter

    asyncio.run(run())


def test_worker_cleanup_precedes_device_unlock(client, monkeypatch, tmp_path):
    binary = tmp_path / 'server.jar'
    binary.write_bytes(b'test')
    monkeypatch.setattr(adb_streams.settings, 'scrcpy_enabled', True)
    monkeypatch.setattr(adb_streams.settings, 'scrcpy_server_path', str(binary))
    events = []

    @asynccontextmanager
    async def reservation(device_id):
        events.append('lock')
        try:
            yield
        finally:
            events.append('unlock')

    process = SimpleNamespace(returncode=None)
    process.terminate = lambda: events.append('terminate')
    process.wait = AsyncMock(side_effect=lambda: events.append('wait'))

    async def relay(ws, proc):
        raise WebSocketDisconnect()

    monkeypatch.setattr(adb_streams.task_queue, 'manual_control', reservation)
    monkeypatch.setattr(adb_streams.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    monkeypatch.setattr(adb_streams, 'relay_worker', relay)
    client.get('/login/1')
    with client.websocket_connect('/ws/adb/1', headers={'origin': 'http://testserver'}) as ws:
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert events == ['lock', 'terminate', 'wait', 'unlock']


def test_manual_reservation_blocks_second_viewer_and_automation(client, monkeypatch):
    queue_module = importlib.import_module('app.services.task_queue')
    monkeypatch.setattr(queue_module, 'engine', adb_streams.engine)

    async def run():
        queue = queue_module.TaskQueue()
        entered = asyncio.Event()

        async def automation():
            async with queue.device_execution(1):
                entered.set()

        async with queue.manual_control(1):
            with pytest.raises(RuntimeError, match='busy'):
                async with queue.manual_control(1):
                    pass
            task = asyncio.create_task(automation())
            await asyncio.sleep(0)
            assert not entered.is_set()
        await asyncio.wait_for(task, 1)
        assert entered.is_set()

    asyncio.run(run())
