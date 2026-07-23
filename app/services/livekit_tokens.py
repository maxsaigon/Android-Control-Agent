"""Short-lived LiveKit access tokens for Android screen streaming."""

from dataclasses import dataclass
from datetime import timedelta

from livekit import api

from app.config import settings


@dataclass(frozen=True)
class LiveKitSession:
    url: str
    room: str
    token: str
    expires_in: int


def is_livekit_configured() -> bool:
    return bool(
        settings.livekit_url
        and settings.livekit_api_key
        and settings.livekit_api_secret
    )


def device_room(user_id: int, device_id: int) -> str:
    return f"android-device-{user_id}-{device_id}"


def create_stream_session(
    *,
    user_id: int,
    device_id: int,
    identity: str,
    can_publish: bool,
    can_subscribe: bool,
) -> LiveKitSession:
    if not is_livekit_configured():
        raise RuntimeError("LiveKit is not configured")

    room = device_room(user_id, device_id)
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(timedelta(seconds=settings.livekit_token_ttl_seconds))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=can_publish,
                can_subscribe=can_subscribe,
                can_publish_data=False,
            )
        )
        .to_jwt()
    )
    return LiveKitSession(
        url=settings.livekit_url,
        room=room,
        token=token,
        expires_in=settings.livekit_token_ttl_seconds,
    )
