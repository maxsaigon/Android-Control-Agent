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
    """Represents a connected remote device."""

    def __init__(self, device_token: str, device_id: int,
                 user_id: int, ws: WebSocket):
        self.device_token = device_token
        self.device_id = device_id
        self.user_id = user_id
        self.ws = ws
        self.connected_at = datetime.now(timezone.utc)
        self.last_ping = datetime.now(timezone.utc)
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(self, action: str, params: dict = None) -> dict:
        """Send a command to the device and wait for response."""
        cmd_id = str(uuid.uuid4())[:8]
        command = {"id": cmd_id, "action": action, "params": params or {}}

        future = asyncio.get_event_loop().create_future()
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
            self._pending[cmd_id].set_result(data)
        else:
            # Unsolicited event (status update, heartbeat, etc.)
            logger.debug(f"Device {self.device_id} event: {data}")


class DeviceHub:
    """Central hub managing all remote device connections.

    Usage:
        # When device connects via WebSocket
        await hub.register(token, device_id, user_id, websocket)

        # To send command to a device
        result = await hub.send_command(device_id, "tap", {"x": 100, "y": 200})

        # When device disconnects
        hub.unregister(device_id)
    """

    def __init__(self):
        self._connections: dict[int, DeviceConnection] = {}  # device_id → connection
        self._token_map: dict[str, int] = {}  # device_token → device_id

    def register(self, device_token: str, device_id: int,
                 user_id: int, ws: WebSocket) -> DeviceConnection:
        """Register a new device connection."""
        # Close existing connection if any (device reconnected)
        if device_id in self._connections:
            logger.info(f"📱 Device {device_id} reconnecting, closing old connection")
            self._connections.pop(device_id)

        conn = DeviceConnection(device_token, device_id, user_id, ws)
        self._connections[device_id] = conn
        self._token_map[device_token] = device_id
        logger.info(f"📱 Device {device_id} connected via cloud (user={user_id})")
        return conn

    def unregister(self, device_id: int):
        """Remove a device connection."""
        conn = self._connections.pop(device_id, None)
        if conn:
            self._token_map.pop(conn.device_token, None)
            logger.info(f"📱 Device {device_id} disconnected from cloud")

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
                    "connected_at": conn.connected_at.isoformat(),
                    "last_ping": conn.last_ping.isoformat(),
                }
                for did, conn in self._connections.items()
            },
        }


# Singleton
device_hub = DeviceHub()
