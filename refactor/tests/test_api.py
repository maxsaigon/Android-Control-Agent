import hashlib


def test_health_and_resource_summary_do_not_expose_secrets(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-value")

    health = client.get("/api/health")
    resources = client.get("/api/resources")

    assert health.status_code == 200
    assert health.json()["product"] == "Android Device Media Control"
    assert resources.json()["public_url"] == "https://m.buonme.com"
    assert resources.json()["secrets"]["openai"] is True
    assert "super-secret-value" not in resources.text


def test_cloud_device_token_is_returned_once_and_stored_as_hash(client):
    response = client.post(
        "/api/devices",
        json={"name": "Cloud phone", "transport": "cloud", "address": ""},
    )

    assert response.status_code == 201
    payload = response.json()
    token = payload["token"]
    assert token
    assert payload["websocket_url"].endswith(f"/ws/device/{token}")

    repository = client.app.state.repository
    with repository.connect() as database:
        row = database.execute("SELECT token_hash FROM devices").fetchone()
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row["token_hash"]

    listed = client.get("/api/devices").json()
    assert listed[0]["name"] == "Cloud phone"
    assert "token" not in listed[0]


def test_offline_cloud_action_fails_explicitly(client):
    device = client.post(
        "/api/devices",
        json={"name": "Offline helper", "transport": "cloud"},
    ).json()["device"]

    response = client.post(
        f"/api/devices/{device['id']}/actions/tap",
        json={"params": {"x": 10, "y": 20}},
    )

    assert response.status_code == 409
    assert "not connected" in response.json()["detail"]


def test_workflow_registry_is_small_and_deterministic(client):
    workflows = client.get("/api/workflows")

    assert workflows.status_code == 200
    assert workflows.json() == [
        {
            "name": "tiktok.browse",
            "title": "Browse TikTok feed",
            "description": "Launch TikTok and browse a bounded number of feed items.",
            "parameters": {"count": 5, "view_seconds": 2},
        }
    ]


def test_media_upload_is_catalogued(client):
    response = client.post(
        "/api/media",
        files={"file": ("sample.mp4", b"small-video-fixture", "video/mp4")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == "sample.mp4"
    assert payload["size_bytes"] == len(b"small-video-fixture")
    assert client.get("/api/media").json()[0]["sha256"] == payload["sha256"]
