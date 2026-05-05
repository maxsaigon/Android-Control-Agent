"""Cloud device connection integration tests.

These tests exercise the SaaS helper flow without a real phone:

1. Android Helper registers with username/password and receives a token.
2. Helper connects to /ws/device/{token}.
3. Helper sends hello + heartbeat.
4. Server routes a command through DeviceHub and receives the response.
5. Re-registration invalidates the previous token.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import Device, DeviceStatus, DeviceToken, User
from app.routers import device_ws
from app.services.device_hub import device_hub


@pytest.fixture()
def cloud_app(tmp_path, monkeypatch):
    """FastAPI app wired to an isolated SQLite DB for cloud device tests."""
    db_path = tmp_path / "cloud_device_test.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(username="cloud_user", password="secret")
        session.add(user)
        session.commit()

    monkeypatch.setattr(device_ws, "engine", engine)
    device_hub._connections.clear()
    device_hub._token_map.clear()

    app = FastAPI()
    app.include_router(device_ws.router)
    app.include_router(device_ws.register_router)
    app.include_router(device_ws.token_router)

    yield app, engine

    device_hub._connections.clear()
    device_hub._token_map.clear()


def _register_device(client: TestClient, name: str = "Cloud Test Device") -> dict:
    response = client.post(
        "/api/device/register",
        json={
            "username": "cloud_user",
            "password": "secret",
            "device_name": name,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_cloud_device_register_connect_heartbeat_and_disconnect(cloud_app):
    app, engine = cloud_app

    with TestClient(app) as client:
        registration = _register_device(client)
        token = registration["token"]
        device_id = registration["device_id"]

        with client.websocket_connect(f"/ws/device/{token}") as ws:
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert welcome["device_id"] == device_id

            ws.send_json({
                "type": "hello",
                "helper": {
                    "version_name": "1.1.1",
                    "version_code": 3,
                    "build_sha": "test-build",
                },
            })
            ws.send_json({
                "type": "heartbeat",
                "battery": 77,
                "helper": {"version_name": "1.1.1"},
            })
            assert ws.receive_json() == {"type": "heartbeat_ack"}

            hub = client.get("/api/device-tokens/hub-status").json()
            assert hub["connected_devices"] == 1
            assert str(device_id) in hub["devices"]
            assert hub["devices"][str(device_id)]["metadata"]["version_name"] == "1.1.1"

            with Session(engine) as session:
                device = session.get(Device, device_id)
                assert device is not None
                assert device.status == DeviceStatus.ONLINE
                assert device.battery_level == 77
                assert device.last_seen is not None

        with Session(engine) as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.status == DeviceStatus.OFFLINE

        hub = client.get("/api/device-tokens/hub-status").json()
        assert hub["connected_devices"] == 0


def test_cloud_backend_command_round_trip_through_device_hub(cloud_app):
    app, _engine = cloud_app

    with TestClient(app) as client:
        registration = _register_device(client)
        token = registration["token"]
        device_id = registration["device_id"]

        with client.websocket_connect(f"/ws/device/{token}") as ws:
            assert ws.receive_json()["type"] == "welcome"

            command_future = client.portal.start_task_soon(
                device_hub.send_command,
                device_id,
                "tap",
                {"x": 120, "y": 240},
            )

            command = ws.receive_json()
            assert command["action"] == "tap"
            assert command["params"] == {"x": 120, "y": 240}

            ws.send_json({
                "id": command["id"],
                "status": "ok",
                "result": "Tapped at (120, 240)",
            })

            result = command_future.result(timeout=5)

        assert result["status"] == "ok"
        assert result["result"] == "Tapped at (120, 240)"


def test_cloud_device_reregister_invalidates_old_token(cloud_app):
    app, engine = cloud_app

    with TestClient(app) as client:
        first = _register_device(client)
        second = _register_device(client)

        assert second["device_id"] == first["device_id"]
        assert second["token"] != first["token"]

        with Session(engine) as session:
            tokens = session.exec(
                select(DeviceToken).where(
                    DeviceToken.device_id == first["device_id"],
                )
            ).all()
            active_tokens = [token for token in tokens if token.is_active]
            inactive_tokens = [token for token in tokens if not token.is_active]

        assert len(active_tokens) == 1
        assert active_tokens[0].token == second["token"]
        assert any(token.token == first["token"] for token in inactive_tokens)

        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/device/{first['token']}"):
                pass

        with client.websocket_connect(f"/ws/device/{second['token']}") as ws:
            assert ws.receive_json()["type"] == "welcome"
