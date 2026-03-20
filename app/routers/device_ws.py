"""WebSocket endpoint for remote device connections (SaaS mode).

Devices connect to: wss://server/ws/device/{token}
The hub authenticates the token, registers the connection, and
routes commands bidirectionally.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlmodel import Session, select

from app.database import engine
from app.models import Device, DeviceStatus, DeviceToken

logger = logging.getLogger(__name__)

router = APIRouter(tags=["device-websocket"])


@router.websocket("/ws/device/{token}")
async def device_connect(websocket: WebSocket, token: str):
    """WebSocket endpoint for remote device connections.

    The Android Helper APK connects here with its device token.
    Once connected, the server can send commands to the device
    through this persistent WebSocket connection.

    Protocol (same as current Accessibility backend):
        Server → Device: {"id": "abc", "action": "tap", "params": {"x": 100, "y": 200}}
        Device → Server: {"id": "abc", "status": "ok", "result": "tapped at (100, 200)"}
        Device → Server: {"type": "heartbeat", "battery": 85, "timestamp": "..."}
    """
    from app.services.device_hub import device_hub

    # 1. Validate token
    with Session(engine) as session:
        device_token = session.exec(
            select(DeviceToken).where(
                DeviceToken.token == token,
                DeviceToken.is_active == True,
            )
        ).first()

        if not device_token:
            await websocket.close(code=4001, reason="Invalid or inactive device token")
            logger.warning(f"❌ Rejected device connection: invalid token {token[:8]}...")
            return

        device_id = device_token.device_id
        user_id = device_token.user_id

        # Update device status
        device = session.get(Device, device_id)
        if device:
            device.status = DeviceStatus.ONLINE
            device.last_seen = datetime.now(timezone.utc)
            session.add(device)
            session.commit()

    # 2. Accept WebSocket connection
    await websocket.accept()
    logger.info(f"📱 Device {device_id} connected via cloud (token={token[:8]}...)")

    # 3. Register with hub
    conn = device_hub.register(token, device_id, user_id, websocket)

    # 4. Send welcome message
    await websocket.send_json({
        "type": "welcome",
        "device_id": device_id,
        "server_time": datetime.now(timezone.utc).isoformat(),
    })

    # 5. Listen for messages from device
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from device {device_id}: {raw[:100]}")
                continue

            msg_type = data.get("type", "")

            if msg_type == "heartbeat":
                # Device heartbeat — update last_seen
                conn.last_ping = datetime.now(timezone.utc)
                with Session(engine) as session:
                    device = session.get(Device, device_id)
                    if device:
                        device.last_seen = datetime.now(timezone.utc)
                        if data.get("battery") is not None:
                            device.battery_level = data["battery"]
                        session.add(device)
                        session.commit()
                # Ack the heartbeat
                await websocket.send_json({"type": "heartbeat_ack"})

            elif "id" in data:
                # This is a response to a command we sent
                conn.handle_response(data)

            else:
                # Unknown message type
                logger.debug(f"Device {device_id} sent: {data}")

    except WebSocketDisconnect:
        logger.info(f"📱 Device {device_id} disconnected (WebSocket closed)")
    except Exception as e:
        logger.error(f"📱 Device {device_id} connection error: {e}")
    finally:
        # Clean up
        device_hub.unregister(device_id)
        with Session(engine) as session:
            device = session.get(Device, device_id)
            if device:
                device.status = DeviceStatus.OFFLINE
                session.add(device)
                session.commit()


# --- REST API for device token management ---

from fastapi import APIRouter as _AR
from pydantic import BaseModel

token_router = APIRouter(prefix="/api/device-tokens", tags=["device-tokens"])


class TokenCreateRequest(BaseModel):
    device_id: int
    name: str = ""


class TokenResponse(BaseModel):
    id: int
    device_id: int
    user_id: int
    token: str
    name: str
    is_active: bool
    created_at: datetime


@token_router.post("/", response_model=TokenResponse)
def create_device_token(req: TokenCreateRequest):
    """Generate a new device token for cloud connection."""
    import secrets

    with Session(engine) as session:
        # Verify device exists
        device = session.get(Device, req.device_id)
        if not device:
            from fastapi import HTTPException
            raise HTTPException(404, f"Device {req.device_id} not found")

        token = DeviceToken(
            device_id=req.device_id,
            user_id=1,  # TODO: multi-tenancy — get from auth
            token=secrets.token_urlsafe(32),
            name=req.name or f"Token for {device.name}",
        )
        session.add(token)
        session.commit()
        session.refresh(token)

        return TokenResponse(
            id=token.id,
            device_id=token.device_id,
            user_id=token.user_id,
            token=token.token,
            name=token.name,
            is_active=token.is_active,
            created_at=token.created_at,
        )


@token_router.get("/", response_model=list[TokenResponse])
def list_device_tokens(device_id: int = None):
    """List device tokens, optionally filtered by device_id."""
    with Session(engine) as session:
        query = select(DeviceToken)
        if device_id:
            query = query.where(DeviceToken.device_id == device_id)
        tokens = session.exec(query).all()
        return [
            TokenResponse(
                id=t.id,
                device_id=t.device_id,
                user_id=t.user_id,
                token=t.token,
                name=t.name,
                is_active=t.is_active,
                created_at=t.created_at,
            )
            for t in tokens
        ]


@token_router.delete("/{token_id}")
def revoke_device_token(token_id: int):
    """Revoke (deactivate) a device token."""
    with Session(engine) as session:
        token = session.get(DeviceToken, token_id)
        if not token:
            from fastapi import HTTPException
            raise HTTPException(404, f"Token {token_id} not found")
        token.is_active = False
        session.add(token)
        session.commit()
        return {"status": "revoked", "token_id": token_id}


@token_router.get("/hub-status")
def hub_status():
    """Get Device Hub connection status."""
    from app.services.device_hub import device_hub
    return device_hub.status
