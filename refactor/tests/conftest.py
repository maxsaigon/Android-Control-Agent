from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from android_control.config import Settings
from android_control.main import create_app


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        public_url="https://m.buonme.com",
        data_dir=tmp_path,
        database_path=tmp_path / "test.db",
        adb_path="adb",
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
