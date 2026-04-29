"""Tests for username-only Android device approval linking."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

from app.models import (
    Device,
    DeviceLinkRequest,
    DeviceLinkStatus,
    DeviceStatus,
    DeviceToken,
    User,
)
from app.routers import device_link, device_ws
from app.services.device_hub import device_hub


@pytest.fixture()
def approval_app(tmp_path, monkeypatch):
    db_path = tmp_path / "approval_link.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(User(username="admin", password="admin"))
        session.add(User(username="operator", password="operator"))
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(device_ws, "engine", engine)
    device_hub._connections.clear()
    device_hub._token_map.clear()

    app = FastAPI()

    @app.middleware("http")
    async def test_session_middleware(request: Request, call_next):
        username = request.headers.get("x-test-user")
        request.scope["session"] = {}
        if username:
            with Session(engine) as session:
                user = session.exec(select(User).where(User.username == username)).first()
                if user:
                    request.scope["session"] = {
                        "user_id": user.id,
                        "username": user.username,
                    }
        return await call_next(request)

    app.dependency_overrides[device_link.get_session] = override_session
    app.include_router(device_link.router)
    app.include_router(device_ws.router)

    yield app, engine

    device_hub._connections.clear()
    device_hub._token_map.clear()


def _request_link(client: TestClient, username: str = "admin") -> dict:
    response = client.post(
        "/api/device/link/request",
        json={
            "username": username,
            "device_name": "Pixel Approval Test",
            "device_model": "Pixel 7",
            "android_version": "14",
            "sdk_int": 34,
            "manufacturer": "Google",
            "helper": {
                "version_name": "1.1.1",
                "version_code": 3,
                "build_sha": "test-sha",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_device_link_request_accept_status_and_cloud_connect(approval_app):
    app, engine = approval_app

    with TestClient(app) as client:
        pending = _request_link(client)
        request_id = pending["request_id"]

        assert client.get(f"/api/device/link/status/{request_id}").json() == {
            "status": "pending",
            "device_id": None,
            "device_name": None,
            "device_token": None,
            "ws_url": None,
            "message": None,
        }

        admin_headers = {"x-test-user": "admin"}
        pending_list = client.get("/api/device/link/requests", headers=admin_headers)
        assert pending_list.status_code == 200
        assert [item["request_id"] for item in pending_list.json()] == [request_id]

        accept = client.post(
            f"/api/device/link/requests/{request_id}/accept",
            headers=admin_headers,
        )
        assert accept.status_code == 200, accept.text
        device_id = accept.json()["device_id"]

        status = client.get(f"/api/device/link/status/{request_id}").json()
        assert status["status"] == "approved"
        assert status["device_id"] == device_id
        assert status["device_token"]
        assert status["ws_url"].endswith(status["device_token"])

        with client.websocket_connect(f"/ws/device/{status['device_token']}") as ws:
            welcome = ws.receive_json()
            assert welcome["type"] == "welcome"
            assert welcome["device_id"] == device_id

        with Session(engine) as session:
            device = session.get(Device, device_id)
            assert device is not None
            assert device.ip_address == "cloud"
            assert device.adb_port == 0
            assert device.status == DeviceStatus.OFFLINE
            token = session.exec(
                select(DeviceToken).where(
                    DeviceToken.device_id == device_id,
                    DeviceToken.is_active == True,
                )
            ).first()
            assert token is not None
            assert token.token == status["device_token"]


def test_device_link_request_is_visible_only_to_target_username(approval_app):
    app, _engine = approval_app

    with TestClient(app) as client:
        pending = _request_link(client, username="admin")

        operator_headers = {"x-test-user": "operator"}
        admin_headers = {"x-test-user": "admin"}

        assert client.get(
            "/api/device/link/requests",
            headers=operator_headers,
        ).json() == []
        reject = client.post(
            f"/api/device/link/requests/{pending['request_id']}/reject",
            headers=operator_headers,
        )
        assert reject.status_code == 403

        visible = client.get(
            "/api/device/link/requests",
            headers=admin_headers,
        ).json()
        assert [item["request_id"] for item in visible] == [pending["request_id"]]


def test_device_link_reject_does_not_issue_token(approval_app):
    app, engine = approval_app

    with TestClient(app) as client:
        pending = _request_link(client)
        admin_headers = {"x-test-user": "admin"}

        reject = client.post(
            f"/api/device/link/requests/{pending['request_id']}/reject",
            headers=admin_headers,
        )
        assert reject.status_code == 200

        status = client.get(f"/api/device/link/status/{pending['request_id']}").json()
        assert status["status"] == "rejected"
        assert status["device_token"] is None

        with Session(engine) as session:
            tokens = session.exec(select(DeviceToken)).all()
            assert tokens == []


def test_device_link_unknown_username_is_rejected(approval_app):
    app, _engine = approval_app

    with TestClient(app) as client:
        response = client.post(
            "/api/device/link/request",
            json={
                "username": "missing-user",
                "device_name": "Unknown User Phone",
            },
        )
        assert response.status_code == 404


def test_device_link_expired_request_cannot_be_accepted(approval_app):
    app, engine = approval_app

    with TestClient(app) as client:
        pending = _request_link(client)
        with Session(engine) as session:
            req = session.exec(
                select(DeviceLinkRequest).where(
                    DeviceLinkRequest.request_id == pending["request_id"],
                )
            ).one()
            req.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.add(req)
            session.commit()

        accept = client.post(
            f"/api/device/link/requests/{pending['request_id']}/accept",
            headers={"x-test-user": "admin"},
        )
        assert accept.status_code == 400
        assert "expired" in accept.json()["detail"].lower()

        status = client.get(f"/api/device/link/status/{pending['request_id']}").json()
        assert status["status"] == "expired"
