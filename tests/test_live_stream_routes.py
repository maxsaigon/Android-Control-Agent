from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from starlette.middleware.sessions import SessionMiddleware

from app.database import get_session
from app.models import Device, DeviceToken, User
from app.routers import live_streams


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'live.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(id=1, username='owner', password='test'),
            User(id=2, username='other', password='test'),
            Device(id=1, name='Phone', ip_address='cloud', adb_port=0),
            DeviceToken(device_id=1, user_id=1, token='token'),
        ])
        db.commit()

    def session():
        with Session(engine) as db:
            yield db

    @asynccontextmanager
    async def manual_control(device_id):
        yield

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key='test')
    app.include_router(live_streams.router)
    app.dependency_overrides[get_session] = session

    @app.get('/login/{user_id}')
    def login(request: Request, user_id: int):
        request.session['user_id'] = user_id

    monkeypatch.setattr(live_streams, 'is_livekit_configured', lambda: True)
    monkeypatch.setattr(live_streams.device_hub, 'is_connected', lambda _: True)
    monkeypatch.setattr(live_streams.task_queue, 'manual_control', manual_control)
    monkeypatch.setattr(live_streams, 'create_stream_session', lambda **kwargs: SimpleNamespace(
        url='wss://rtc.test', token='scoped-token', room='android-device-1-1', expires_in=600,
    ))
    monkeypatch.setattr(live_streams.device_hub, 'send_command', AsyncMock(return_value={'status': 'ok'}))
    with TestClient(app) as http:
        yield http


def test_start_requires_login_and_ownership(client):
    assert client.post('/api/devices/1/stream/start').status_code == 401
    client.get('/login/2')
    for suffix in ('start', 'stop', 'viewer-token'):
        assert client.post(f'/api/devices/1/stream/{suffix}').status_code == 403
    assert client.get('/api/devices/1/stream/status').status_code == 403
    live_streams.device_hub.send_command.assert_not_awaited()


def test_disabled_and_offline(client, monkeypatch):
    client.get('/login/1')
    monkeypatch.setattr(live_streams, 'is_livekit_configured', lambda: False)
    assert client.post('/api/devices/1/stream/start').status_code == 503
    monkeypatch.setattr(live_streams, 'is_livekit_configured', lambda: True)
    monkeypatch.setattr(live_streams.device_hub, 'is_connected', lambda _: False)
    assert client.post('/api/devices/1/stream/start').status_code == 409
    assert client.get('/api/devices/1/stream/status').status_code == 409


def test_start_and_device_permission_status(client):
    client.get('/login/1')
    assert client.post('/api/devices/1/stream/start').status_code == 200
    live_streams.device_hub.send_command.assert_awaited_with(1, 'start_stream', {
        'url': 'wss://rtc.test', 'token': 'scoped-token', 'room': 'android-device-1-1',
    })
    live_streams.device_hub.send_command.return_value = {
        'status': 'ok', 'result': {'state': 'permission_denied', 'error': 'User declined capture'},
    }
    response = client.get('/api/devices/1/stream/status')
    assert response.json()['result']['state'] == 'permission_denied'
    live_streams.device_hub.send_command.assert_awaited_with(1, 'get_stream_status')


def test_rejected_start_is_not_reported_as_success(client):
    client.get('/login/1')
    live_streams.device_hub.send_command.return_value = {'status': 'error', 'error': 'Capture unavailable'}
    response = client.post('/api/devices/1/stream/start')
    assert response.status_code == 409
    assert response.json()['detail'] == 'Capture unavailable'


def test_status_timeout_is_reported(client):
    client.get('/login/1')
    live_streams.device_hub.send_command.side_effect = TimeoutError('Device timed out')
    assert client.get('/api/devices/1/stream/status').status_code == 409
