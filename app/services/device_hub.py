"""Device Hub — WebSocket hub that accepts connections from remote devices.

In SaaS mode, the Android Helper APK connects OUT to this hub
(reverse of the current LAN architecture where server connects TO device).

Each device authenticates with a device_token, and the hub maintains
a persistent bidirectional WebSocket connection per device.

Server-side code can send commands to devices through the hub,
and devices push results/events back.

Protocol (same JSON format as AccessibilityBackend):
    Command:  {"id": "uuid", "action": "tap", "params": {"x": 100, "y": 200}}
    Response: {"id": "uuid", "status": "ok", "result": "tapped at (100, 200)"}
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Command timeout (seconds)
CMD_TIMEOUT = 15


class DeviceConnection:
    """Represents a connected remote device.

    Each connection gets a unique session_id so that reconnect races
    (old connection exit after new connection registered) are handled
    safely: unregister only removes the connection whose session_id
    matches the one that is closing.
    """

    def __init__(self, device_token: str, device_id: int,
                 user_id: int, ws: WebSocket):
        self.device_token = device_token
        self.device_id = device_id
        self.user_id = user_id
        self.ws = ws
        # Unique ID per session — used to guard unregister on reconnect
        self.session_id: str = str(uuid.uuid4())[:12]
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = datetime.now(timezone.utc)
        self.metadata: dict = {}
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(self, action: str, params: dict = None) -> dict:
        """Send a command to the device and wait for response."""
        cmd_id = str(uuid.uuid4())[:8]
        command = {"id": cmd_id, "action": action, "params": params or {}}

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending[cmd_id] = future

        try:
            await self.ws.send_json(command)
            result = await asyncio.wait_for(future, timeout=CMD_TIMEOUT)
            if result.get("status") == "error":
                raise RuntimeError(f"Device error: {result.get('error', 'unknown')}")
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command '{action}' timed out on device {self.device_id}")
        finally:
            self._pending.pop(cmd_id, None)

    def handle_response(self, data: dict):
        """Handle an incoming response from the device."""
        cmd_id = data.get("id", "")
        if cmd_id in self._pending:
            future = self._pending[cmd_id]
            if not future.done():
                future.set_result(data)
        else:
            # Unsolicited event (status update, heartbeat, etc.)
            logger.debug(f"Device {self.device_id} event: {data}")

    def fail_all_pending(self, reason: str = "Connection closed"):
        """Fail all in-flight command futures when the connection closes.

        Prevents callers from blocking until CMD_TIMEOUT when device
        disconnects mid-command.
        """
        for cmd_id, future in list(self._pending.items()):
            if not future.done():
                future.set_exception(ConnectionError(reason))
        self._pending.clear()

    def update_metadata(self, metadata: dict | None):
        """Merge helper/device metadata reported by the remote helper."""
        if not metadata:
            return
        for key, value in metadata.items():
            if value is None:
                continue
            self.metadata[key] = value


class DeviceHub:
    """Central hub managing all remote device connections.

    Usage:
        # When device connects via WebSocket
        conn = hub.register(token, device_id, user_id, websocket)

        # To send command to a device
        result = await hub.send_command(device_id, "tap", {"x": 100, "y": 200})

        # When device disconnects (pass session_id to guard against race)
        hub.unregister(device_id, session_id=conn.session_id)
    """

    def __init__(self):
        self._connections: dict[int, DeviceConnection] = {}  # device_id → connection
        self._token_map: dict[str, int] = {}  # device_token → device_id

    def register(self, device_token: str, device_id: int,
                 user_id: int, ws: WebSocket) -> DeviceConnection:
        """Register a new device connection.

        If a previous connection exists for the same device_id, its
        pending futures are immediately failed so callers don't wait
        for CMD_TIMEOUT.  The old WebSocket is NOT closed here — the
        caller (device_connect endpoint) owns the old WS lifecycle.
        """
        old_conn = self._connections.get(device_id)
        if old_conn:
            logger.info(
                f"📱 Device {device_id} reconnecting (old_session={old_conn.session_id}), "
                "failing pending commands on old connection"
            )
            old_conn.fail_all_pending("Device reconnected — old session superseded")

        conn = DeviceConnection(device_token, device_id, user_id, ws)
        self._connections[device_id] = conn
        self._token_map[device_token] = device_id
        logger.info(
            f"📱 Device {device_id} connected via cloud "
            f"(user={user_id}, session={conn.session_id})"
        )
        return conn

    def unregister(self, device_id: int, session_id: str | None = None) -> bool:
        """Remove a device connection.

        If session_id is provided, the connection is only removed when
        its session_id matches — this prevents a reconnect race where
        the OLD connection's finally-block removes the NEW connection.

        Example race (without guard):
            t=0  Device A reconnects → new conn registered
            t=1  Old WS reader loop exits → unregister(device_id)
            t=2  New conn incorrectly removed ❌

        With session_id guard, unregister at t=1 is a no-op because
        session_id of the old conn no longer matches the active conn.
        """
        current = self._connections.get(device_id)
        if current is None:
            return False

        if session_id is not None and current.session_id != session_id:
            logger.debug(
                f"📱 Device {device_id}: unregister skipped "
                f"(session {session_id} != active {current.session_id})"
            )
            return False

        # Fail any remaining pending commands before removing
        current.fail_all_pending("Connection closed")

        self._connections.pop(device_id, None)
        self._token_map.pop(current.device_token, None)
        logger.info(f"📱 Device {device_id} disconnected from cloud")
        return True

    def is_connected(self, device_id: int) -> bool:
        """Check if a device is connected via cloud."""
        return device_id in self._connections

    def get_connection(self, device_id: int) -> Optional[DeviceConnection]:
        """Get the connection for a device."""
        return self._connections.get(device_id)

    async def send_command(self, device_id: int, action: str,
                           params: dict = None) -> dict:
        """Send a command to a device through its WebSocket connection."""
        conn = self._connections.get(device_id)
        if not conn:
            raise ConnectionError(f"Device {device_id} is not connected via cloud")
        return await conn.send_command(action, params)

    @property
    def connected_devices(self) -> list[int]:
        """List of currently connected device IDs."""
        return list(self._connections.keys())

    @property
    def status(self) -> dict:
        """Get hub status for dashboard."""
        return {
            "connected_devices": len(self._connections),
            "devices": {
                did: {
                    "user_id": conn.user_id,
                    "session_id": conn.session_id,
                    "connected_at": conn.connected_at.isoformat(),
                    "last_ping": conn.last_ping.isoformat(),
                    "pending_commands": len(conn._pending),
                    "metadata": conn.metadata,
                }
                for did, conn in self._connections.items()
            },
        }


# Singleton
device_hub = DeviceHub()
