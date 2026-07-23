from datetime import datetime, timezone

import jwt

from app.config import settings
from app.services.livekit_tokens import create_stream_session, device_room


def test_device_room_is_scoped_to_user_and_device():
    assert device_room(7, 42) == "android-device-7-42"


def test_publish_token_has_device_room_and_publish_only(monkeypatch):
    monkeypatch.setattr(settings, "livekit_url", "wss://rtc.example.test")
    monkeypatch.setattr(settings, "livekit_api_key", "test-key")
    test_secret = "test-secret-with-at-least-32-bytes"
    monkeypatch.setattr(settings, "livekit_api_secret", test_secret)
    monkeypatch.setattr(settings, "livekit_token_ttl_seconds", 600)

    session = create_stream_session(
        user_id=7,
        device_id=42,
        identity="android-42",
        can_publish=True,
        can_subscribe=False,
    )
    claims = jwt.decode(
        session.token,
        test_secret,
        algorithms=["HS256"],
        audience=None,
        options={"verify_aud": False},
    )

    assert session.url == "wss://rtc.example.test"
    assert session.room == "android-device-7-42"
    assert claims["iss"] == "test-key"
    assert claims["sub"] == "android-42"
    assert claims["video"]["room"] == session.room
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["canPublish"] is True
    assert claims["video"]["canSubscribe"] is False
    assert claims["exp"] - claims["nbf"] == 600
    assert claims["exp"] > int(datetime.now(timezone.utc).timestamp())
