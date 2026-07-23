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
from app.models import Device, DeviceStatus, DeviceToken, User
from app.routers.auth import _verify_password
from app.services.device_identity import cloud_display_name

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

    # 5. Server-side keepalive ping task.
    #    Sends a lightweight ping every 25s to prevent Cloudflare Tunnel
    #    and other reverse proxies from closing the idle WebSocket.
    ping_count = 0
    hb_ack_count = 0
    connected_at = datetime.now(timezone.utc)

    async def _server_ping_loop():
        nonlocal ping_count
        try:
            while True:
                await asyncio.sleep(25)
                try:
                    await websocket.send_json({
                        "type": "server_ping",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    ping_count += 1
                    logger.debug(
                        "📡 Device %s server_ping sent (count=%s)",
                        device_id,
                        ping_count,
                    )
                except Exception:
                    break  # WS closed, exit silently
        except asyncio.CancelledError:
            pass

    ping_task = asyncio.create_task(_server_ping_loop())

    # 6. Listen for messages from device
    #    Uses a 90-second receive timeout to detect stale connections
    #    that dropped without a proper close frame (e.g. network loss).
    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"📱 Device {device_id}: no data for 90s — closing stale connection"
                )
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from device {device_id}: {raw[:100]}")
                continue

            msg_type = data.get("type", "")

            if msg_type == "hello":
                helper_meta = data.get("helper") or {}
                conn.update_metadata(helper_meta)
                logger.info(
                    "📱 Device %s helper hello: version=%s code=%s sha=%s",
                    device_id,
                    helper_meta.get("version_name", "?"),
                    helper_meta.get("version_code", "?"),
                    helper_meta.get("build_sha", "?"),
                )

            elif msg_type == "heartbeat":
                # Re-validate token/device on heartbeat so revoked/deleted
                # devices are force-disconnected promptly.
                with Session(engine) as session:
                    latest_token = session.exec(
                        select(DeviceToken).where(DeviceToken.token == token)
                    ).first()
                    latest_device = session.get(Device, device_id)
                    if not latest_token or not latest_token.is_active or not latest_device:
                        logger.warning(
                            "📱 Device %s heartbeat rejected: token/device revoked; closing",
                            device_id,
                        )
                        try:
                            await websocket.close(code=4001, reason="Token revoked")
                        except Exception:
                            pass
                        break

                # Device heartbeat — update last_seen
                conn.last_ping = datetime.now(timezone.utc)
                conn.update_metadata(data.get("helper") or {})
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
                hb_ack_count += 1

            elif msg_type == "server_ping":
                # Ignore echo of our own ping (shouldn't happen, but be safe)
                pass

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
        # Cancel the keepalive ping task
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass

        # Guard unregister with session_id so a reconnect race does not
        # remove the newly registered connection.
        removed_active_connection = device_hub.unregister(
            device_id,
            session_id=conn.session_id,
        )
        if removed_active_connection:
            with Session(engine) as session:
                device = session.get(Device, device_id)
                if device:
                    device.status = DeviceStatus.OFFLINE
                    session.add(device)
                    session.commit()
        uptime_s = (datetime.now(timezone.utc) - connected_at).total_seconds()
        logger.info(
            "📱 Device %s WS session closed: uptime=%.1fs, server_pings=%s, heartbeat_acks=%s",
            device_id,
            uptime_s,
            ping_count,
            hb_ack_count,
        )


# --- REST API for device registration + token management ---

from fastapi import APIRouter as _AR
from pydantic import BaseModel

token_router = APIRouter(prefix="/api/device-tokens", tags=["device-tokens"])
register_router = APIRouter(prefix="/api/device", tags=["device-registration"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    device_name: str
    installation_id: str | None = None


class RegisterResponse(BaseModel):
    token: str
    device_id: int
    device_name: str


@register_router.post("/register", response_model=RegisterResponse)
def register_device(req: RegisterRequest):
    """Register a device using login credentials.

    Auto-creates the device and token. If a device with the same name
    already exists for this user, reuses it (creates a new token).

    This replaces the old manual flow of:
    1. Create device on dashboard
    2. Create token
    3. Copy token to phone
    """
    import secrets
    from fastapi import HTTPException

    with Session(engine) as session:
        # 1. Validate credentials — use bcrypt-aware verifier (same as dashboard login)
        user = session.exec(
            select(User).where(User.username == req.username)
        ).first()
        if not user or not _verify_password(req.password, user.password):
            raise HTTPException(401, "Invalid username or password")
        logger.info(f"🔑 Device registration auth OK for user: {user.username}")

        # 2. Reuse a record only when the helper sends its stable installation
        #    ID. Legacy clients without one still create a dedicated record.
        device = None
        if req.installation_id:
            device = session.exec(
                select(Device).where(
                    Device.installation_id == req.installation_id,
                )
            ).first()

        if device is None:
            device = Device(
                installation_id=req.installation_id,
                name=req.device_name,
                ip_address="cloud",
                adb_port=0,
            )
            session.add(device)
            session.commit()
            session.refresh(device)

        device.name = cloud_display_name(req.device_name, device.id)
        device.ip_address = "cloud"
        device.adb_port = 0
        session.add(device)
        session.commit()
        logger.info(f"📱 Registered cloud device: {device.name} (id={device.id})")

        # 3. Deactivate old tokens for this device
        old_tokens = session.exec(
            select(DeviceToken).where(
                DeviceToken.device_id == device.id,
                DeviceToken.is_active == True,
            )
        ).all()
        for t in old_tokens:
            t.is_active = False
            session.add(t)

        # 4. Create new token
        token = DeviceToken(
            device_id=device.id,
            user_id=user.id,
            token=secrets.token_urlsafe(32),
            name=f"auto_token_{device.id}",
        )
        session.add(token)
        session.commit()
        session.refresh(token)
        logger.info(f"🔑 Auto-created token for device {device.id} (user={user.username})")

        return RegisterResponse(
            token=token.token,
            device_id=device.id,
            device_name=device.name,
        )


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
async def revoke_device_token(token_id: int):
    """Revoke (deactivate) a device token and disconnect active WebSocket.

    After revocation the device's active cloud connection (if any) is
    failed immediately so it cannot receive further commands.
    """
    from app.services.device_hub import device_hub

    with Session(engine) as session:
        token = session.get(DeviceToken, token_id)
        if not token:
            from fastapi import HTTPException
            raise HTTPException(404, f"Token {token_id} not found")
        token.is_active = False
        session.add(token)
        session.commit()

    # Fail pending commands for this device and close connection in the hub.
    # The WebSocket reader loop will detect the disconnect and mark offline.
    device_id = token.device_id
    conn = device_hub.get_connection(device_id)
    if conn and conn.device_token == token.token:
        conn.fail_all_pending("Token revoked")
        try:
            await conn.ws.close(code=4001, reason="Token revoked")
        except Exception:
            logger.debug("WS close failed for revoked token %s", token_id)
        logger.info(f"🔒 Token {token_id} revoked — device {device_id} hub connection closed")
    else:
        logger.info(f"🔒 Token {token_id} revoked (device {device_id} was not connected)")

    return {"status": "revoked", "token_id": token_id, "device_id": device_id}


@token_router.get("/hub-status")
def hub_status():
    """Get Device Hub connection status."""
    from app.services.device_hub import device_hub
    return device_hub.status
