"""Live Android screen streaming and interactive control endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.database import get_session
from app.models import Device, DeviceToken
from app.services.device_hub import device_hub
from app.services.livekit_tokens import create_stream_session, is_livekit_configured

router = APIRouter(prefix="/api/devices", tags=["device-live-stream"])


class ControlRequest(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)


def _owned_cloud_device(
    request: Request,
    session: Session,
    device_id: int,
) -> tuple[Device, int]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    token = session.exec(
        select(DeviceToken).where(
            DeviceToken.device_id == device_id,
            DeviceToken.user_id == user_id,
            DeviceToken.is_active == True,
        )
    ).first()
    if not token:
        raise HTTPException(status_code=403, detail="Device does not belong to this user")
    return device, int(user_id)


def _require_stream_ready(device_id: int) -> None:
    if not is_livekit_configured():
        raise HTTPException(status_code=503, detail="LiveKit is not configured")
    if not device_hub.is_connected(device_id):
        raise HTTPException(status_code=409, detail="Device is not connected")


@router.post("/{device_id}/stream/start")
async def start_stream(
    device_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    _device, user_id = _owned_cloud_device(request, session, device_id)
    _require_stream_ready(device_id)
    stream = create_stream_session(
        user_id=user_id,
        device_id=device_id,
        identity=f"android-{device_id}",
        can_publish=True,
        can_subscribe=False,
    )
    result = await device_hub.send_command(
        device_id,
        "start_stream",
        {"url": stream.url, "token": stream.token, "room": stream.room},
    )
    return {
        "status": result.get("status", "ok"),
        "result": result.get("result"),
        "room": stream.room,
        "expires_in": stream.expires_in,
    }


@router.post("/{device_id}/stream/stop")
async def stop_stream(
    device_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    _owned_cloud_device(request, session, device_id)
    if not device_hub.is_connected(device_id):
        raise HTTPException(status_code=409, detail="Device is not connected")
    return await device_hub.send_command(device_id, "stop_stream")


@router.post("/{device_id}/stream/viewer-token")
def viewer_token(
    device_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    _device, user_id = _owned_cloud_device(request, session, device_id)
    _require_stream_ready(device_id)
    stream = create_stream_session(
        user_id=user_id,
        device_id=device_id,
        identity=f"viewer-{user_id}-{device_id}",
        can_publish=False,
        can_subscribe=True,
    )
    return {
        "url": stream.url,
        "token": stream.token,
        "room": stream.room,
        "expires_in": stream.expires_in,
    }


@router.post("/{device_id}/live-control")
async def live_control(
    device_id: int,
    body: ControlRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    _owned_cloud_device(request, session, device_id)
    if not device_hub.is_connected(device_id):
        raise HTTPException(status_code=409, detail="Device is not connected")

    allowed = {
        "tap",
        "swipe",
        "long_press",
        "type_text",
        "global_action",
        "get_screen_size",
    }
    if body.action not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported live-control action")
    return await device_hub.send_command(device_id, body.action, body.params)
