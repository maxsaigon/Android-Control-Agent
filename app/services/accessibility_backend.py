"""AccessibilityBackend — DeviceBackend via WebSocket to helper APK.

Connects to the helper APK's WebSocket server running on the Android
device. Commands are sent as JSON, responses received as JSON.

The helper APK runs an AccessibilityService that can:
- Read UI tree in real-time (getRootInActiveWindow)
- Perform gestures (dispatchGesture)
- Click/set text on nodes (performAction)
- Execute global actions (Back, Home, etc.)
- Capture screenshots
- Launch apps, get device info
"""

import asyncio
import base64
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from app.config import settings, SCREENSHOTS_DIR
from app.services.device_backend import DeviceBackend, UINode

logger = logging.getLogger(__name__)

# Default WebSocket port on the helper APK
DEFAULT_WS_PORT = 38301

# Command timeout (seconds)
CMD_TIMEOUT = 15


class AccessibilityBackend(DeviceBackend):
    """WebSocket-based device control via helper APK's AccessibilityService.

    Each device has a WebSocket connection managed by this backend.
    Commands are JSON-encoded with unique IDs for request/response matching.

    Protocol:
        Request:  {"id": "uuid", "action": "tap", "params": {"x": 100, "y": 200}}
        Response: {"id": "uuid", "status": "ok", "result": "tapped at (100, 200)"}
        Error:    {"id": "uuid", "status": "error", "error": "message"}
    """

    def __init__(self, ws_port: int = None):
        self._ws_port = ws_port or getattr(settings, 'accessibility_ws_port', DEFAULT_WS_PORT)
        self._connections: dict[str, "websockets.WebSocketClientProtocol"] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._listeners: dict[str, asyncio.Task] = {}
        self._screen_cache: dict[str, tuple[int, int]] = {}

    def _device_to_ws_url(self, device: str) -> str:
        """Convert device target (ip:port) to WebSocket URL."""
        ip = device.split(":")[0]
        return f"ws://{ip}:{self._ws_port}"

    @staticmethod
    def _is_ws_open(ws) -> bool:
        """Check if WebSocket is open (compatible with websockets 14-16+)."""
        try:
            from websockets.protocol import State
            return ws.state is State.OPEN
        except (ImportError, AttributeError):
            pass
        try:
            return ws.open
        except AttributeError:
            return False

    async def _ensure_connected(self, device: str) -> "websockets.WebSocketClientProtocol":
        """Get or create WebSocket connection to device."""
        if device in self._connections:
            ws = self._connections[device]
            if self._is_ws_open(ws):
                return ws
            else:
                # Connection closed — clean up
                logger.warning(f"WebSocket to {device} was closed, reconnecting...")
                del self._connections[device]
                if device in self._listeners:
                    self._listeners[device].cancel()
                    del self._listeners[device]

        import websockets

        url = self._device_to_ws_url(device)
        try:
            ws = await asyncio.wait_for(
                websockets.connect(url, ping_interval=20, ping_timeout=10),
                timeout=5,
            )
            self._connections[device] = ws
            self._listeners[device] = asyncio.create_task(
                self._listen(device, ws)
            )
            logger.info(f"🔌 Connected to Accessibility backend: {url}")
            return ws
        except Exception as e:
            raise ConnectionError(
                f"Cannot connect to Accessibility helper on {device}: {e}"
            ) from e

    async def _listen(self, device: str, ws):
        """Background listener for WebSocket responses."""
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    cmd_id = data.get("id", "")
                    if cmd_id in self._pending:
                        self._pending[cmd_id].set_result(data)
                    else:
                        # Unsolicited event (e.g., accessibility event push)
                        logger.debug(f"Accessibility event from {device}: {data}")
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON from {device}: {message[:100]}")
        except Exception as e:
            logger.warning(f"WebSocket listener for {device} error: {e}")
        finally:
            self._connections.pop(device, None)
            self._listeners.pop(device, None)

    async def _send_command(self, device: str, action: str, params: dict = None) -> dict:
        """Send a command and wait for response."""
        ws = await self._ensure_connected(device)
        cmd_id = str(uuid.uuid4())[:8]
        command = {"id": cmd_id, "action": action, "params": params or {}}

        future = asyncio.get_event_loop().create_future()
        self._pending[cmd_id] = future

        try:
            await ws.send(json.dumps(command))
            result = await asyncio.wait_for(future, timeout=CMD_TIMEOUT)
            if result.get("status") == "error":
                raise RuntimeError(f"Device error: {result.get('error', 'unknown')}")
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command '{action}' timed out on {device}")
        finally:
            self._pending.pop(cmd_id, None)

    # --- Input actions ---

    async def tap(self, device: str, x: int, y: int) -> str:
        result = await self._send_command(device, "tap", {"x": x, "y": y})
        return result.get("result", f"Tapped at ({x}, {y})")

    async def swipe(
        self, device: str,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300,
    ) -> str:
        result = await self._send_command(device, "swipe", {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "duration": duration_ms,
        })
        return result.get("result", f"Swiped ({x1},{y1}) → ({x2},{y2})")

    async def type_text(self, device: str, text: str) -> str:
        result = await self._send_command(device, "type_text", {"text": text})
        return result.get("result", f"Typed: {text}")

    async def key_event(self, device: str, keycode: str) -> str:
        result = await self._send_command(device, "global_action", {"action": keycode.lower()})
        return result.get("result", f"Pressed key: {keycode}")

    # --- UI inspection ---

    async def get_ui_tree(self, device: str) -> list[UINode]:
        """Get UI tree — much faster than ADB dump+pull approach."""
        result = await self._send_command(device, "get_ui_tree")
        elements_data = result.get("result", {}).get("elements", [])

        nodes = []
        for i, el in enumerate(elements_data):
            bounds_raw = el.get("bounds", [0, 0, 0, 0])
            if isinstance(bounds_raw, list) and len(bounds_raw) == 4:
                bounds = tuple(bounds_raw)
            else:
                bounds = (0, 0, 0, 0)

            nodes.append(UINode(
                index=i,
                text=el.get("text", ""),
                resource_id=el.get("resource_id", ""),
                class_name=el.get("class", ""),
                package=el.get("package", ""),
                content_desc=el.get("content_desc", ""),
                clickable=el.get("clickable", False),
                scrollable=el.get("scrollable", False),
                bounds=bounds,
            ))

        return nodes

    async def capture_screenshot(self, device: str, save_path: str = None) -> bytes:
        """Capture screenshot via Accessibility helper."""
        result = await self._send_command(device, "screenshot")
        img_b64 = result.get("result", {}).get("data", "")
        img_format = result.get("result", {}).get("format", "png")

        if not img_b64:
            raise RuntimeError("Empty screenshot data from device")

        img_bytes = base64.b64decode(img_b64)

        if save_path:
            Path(save_path).write_bytes(img_bytes)

        # Compress to JPEG if needed
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            if img.width > 750:
                ratio = 750 / img.width
                img = img.resize((750, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            return buf.getvalue()
        except ImportError:
            return img_bytes

    async def get_screen_size(self, device: str) -> tuple[int, int]:
        if device not in self._screen_cache:
            result = await self._send_command(device, "get_screen_size")
            w = result.get("result", {}).get("width", 1080)
            h = result.get("result", {}).get("height", 2400)
            self._screen_cache[device] = (w, h)
        return self._screen_cache[device]

    # --- App management ---

    async def launch_app(self, device: str, package: str) -> str:
        result = await self._send_command(device, "launch_app", {"package": package})
        return result.get("result", f"Launched: {package}")

    async def force_stop(self, device: str, package: str) -> str:
        """Force-stop via Accessibility is limited.

        The helper app can try to use am force-stop via shell,
        but if that fails, falls back to opening Settings.
        """
        result = await self._send_command(device, "force_stop", {"package": package})
        return result.get("result", f"Stopped: {package}")

    async def list_packages(self, device: str, third_party_only: bool = False) -> list[str]:
        result = await self._send_command(device, "list_packages", {
            "third_party_only": third_party_only,
        })
        return result.get("result", [])

    # --- Device info ---

    async def get_foreground_app(self, device: str) -> str:
        result = await self._send_command(device, "get_foreground_app")
        return result.get("result", "")

    async def get_device_info(self, device: str) -> dict:
        result = await self._send_command(device, "get_device_info")
        return result.get("result", {})

    async def ping(self, device: str) -> bool:
        try:
            result = await self._send_command(device, "ping")
            return result.get("status") == "ok"
        except Exception:
            return False

    # --- Connection management ---

    async def disconnect(self, device: str):
        """Close WebSocket connection to device."""
        if device in self._connections:
            ws = self._connections.pop(device)
            await ws.close()
        if device in self._listeners:
            self._listeners[device].cancel()
            del self._listeners[device]
        logger.info(f"🔌 Disconnected from {device}")

    async def disconnect_all(self):
        """Close all WebSocket connections."""
        for device in list(self._connections.keys()):
            await self.disconnect(device)

    def is_connected(self, device: str) -> bool:
        """Check if WebSocket is currently connected."""
        ws = self._connections.get(device)
        return ws is not None and self._is_ws_open(ws)


# Singleton
accessibility_backend = AccessibilityBackend()
