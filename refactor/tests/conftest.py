from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from android_control.config import Settings
from android_control.main import create_app


@pytest.fixture
def raw_client(tmp_path: Path):
    (tmp_path / "admin-password").write_text("correct horse battery staple")
    (tmp_path / "session-secret").write_text("test-session-secret-with-enough-entropy")
    settings = Settings(
        public_url="https://m.buonme.com",
        data_dir=tmp_path,
        database_path=tmp_path / "test.db",
        adb_path="adb",
        admin_password_file=tmp_path / "admin-password",
        session_secret_file=tmp_path / "session-secret",
    )
    app = create_app(settings)
    with TestClient(app, base_url="https://m.buonme.com") as test_client:
        yield test_client


@pytest.fixture
def client(raw_client):
    response = raw_client.post(
        "/auth/login",
        json={"username": "admin", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return raw_client
