"""Reverse WebSocket hub compatible with the existing Android Helper."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from .transports.base import DeviceTransport


class DeviceConnection(DeviceTransport):
    def __init__(self, device_id: int, websocket: WebSocket, timeout: float):
        self.device_id = device_id
        self.websocket = websocket
        self.timeout = timeout
        self.session_id = uuid.uuid4().hex[:12]
        self.connected_at = datetime.now(timezone.utc)
        self.pending: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def command(self, action: str, params: dict[str, Any] | None = None) -> Any:
        command_id = uuid.uuid4().hex[:10]
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.pending[command_id] = future
        try:
            await self.websocket.send_json(
                {"id": command_id, "action": action, "params": params or {}}
            )
            response = await asyncio.wait_for(future, timeout=self.timeout)
            if response.get("status") == "error":
                raise RuntimeError(response.get("error") or f"{action} failed")
            return response.get("result")
        finally:
            self.pending.pop(command_id, None)

    def receive(self, payload: dict[str, Any]) -> None:
        future = self.pending.get(str(payload.get("id", "")))
        if future and not future.done():
            future.set_result(payload)

    def fail_pending(self, message: str) -> None:
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError(message))
        self.pending.clear()


class DeviceHub:
    def __init__(self, timeout: float = 15):
        self.timeout = timeout
        self.connections: dict[int, DeviceConnection] = {}

    def register(self, device_id: int, websocket: WebSocket) -> DeviceConnection:
        previous = self.connections.get(device_id)
        if previous:
            previous.fail_pending("Device reconnected")
        connection = DeviceConnection(device_id, websocket, self.timeout)
        self.connections[device_id] = connection
        return connection

    def unregister(self, device_id: int, session_id: str) -> bool:
        current = self.connections.get(device_id)
        if current is None or current.session_id != session_id:
            return False
        current.fail_pending("Device disconnected")
        self.connections.pop(device_id, None)
        return True

    def get(self, device_id: int) -> DeviceConnection:
        connection = self.connections.get(device_id)
        if connection is None:
            raise ConnectionError(f"Device {device_id} is not connected")
        return connection
