"""CloudBackend — DeviceBackend implementation that routes through DeviceHub.

This backend sends commands to devices that are connected via the cloud
WebSocket hub (reverse connection from device → server).

Implements the same DeviceBackend interface as ADBBackend and
AccessibilityBackend, so controllers/scripts work transparently.
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Optional

from app.services.device_backend import DeviceBackend, UINode
from app.services.device_hub import device_hub

logger = logging.getLogger(__name__)


class CloudBackend(DeviceBackend):
    """Routes commands through the DeviceHub to remote devices.

    The 'device' parameter in all methods is the device_id (as string)
    rather than an IP address, since cloud devices don't expose IPs.
    """

    def __init__(self):
        self._screen_cache: dict[str, tuple[int, int]] = {}

    def _device_id(self, device: str) -> int:
        """Extract numeric device_id from device string."""
        # device can be "cloud:123" or just "123"
        if device.startswith("cloud:"):
            return int(device.split(":")[1])
        return int(device)

    async def _send(self, device: str, action: str, params: dict = None) -> dict:
        """Send command through device hub."""
        did = self._device_id(device)
        return await device_hub.send_command(did, action, params)

    # --- Input actions ---

    async def tap(self, device: str, x: int, y: int) -> str:
        result = await self._send(device, "tap", {"x": x, "y": y})
        return result.get("result", f"Tapped at ({x}, {y})")

    async def swipe(
        self, device: str,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300,
    ) -> str:
        result = await self._send(device, "swipe", {
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "duration": duration_ms,
        })
        return result.get("result", f"Swiped ({x1},{y1}) → ({x2},{y2})")

    async def type_text(self, device: str, text: str) -> str:
        result = await self._send(device, "type_text", {"text": text})
        return result.get("result", f"Typed: {text}")

    async def key_event(self, device: str, keycode: str) -> str:
        result = await self._send(device, "global_action", {"action": keycode.lower()})
        return result.get("result", f"Pressed key: {keycode}")

    # --- UI inspection ---

    async def get_ui_tree(self, device: str) -> list[UINode]:
        result = await self._send(device, "get_ui_tree")
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
        result = await self._send(device, "screenshot")
        img_b64 = result.get("result", {}).get("data", "")

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
            result = await self._send(device, "get_screen_size")
            w = result.get("result", {}).get("width", 1080)
            h = result.get("result", {}).get("height", 2400)
            self._screen_cache[device] = (w, h)
        return self._screen_cache[device]

    # --- App management ---

    async def launch_app(self, device: str, package: str) -> str:
        result = await self._send(device, "launch_app", {"package": package})
        return result.get("result", f"Launched: {package}")

    async def force_stop(self, device: str, package: str) -> str:
        result = await self._send(device, "force_stop", {"package": package})
        return result.get("result", f"Stopped: {package}")

    async def list_packages(self, device: str, third_party_only: bool = False) -> list[str]:
        result = await self._send(device, "list_packages", {
            "third_party_only": third_party_only,
        })
        return result.get("result", [])

    # --- Device info ---

    async def get_foreground_app(self, device: str) -> str:
        result = await self._send(device, "get_foreground_app")
        return result.get("result", "")

    async def get_device_info(self, device: str) -> dict:
        result = await self._send(device, "get_device_info")
        return result.get("result", {})

    async def ping(self, device: str) -> bool:
        try:
            result = await self._send(device, "ping")
            return result.get("status") == "ok"
        except Exception:
            return False


# Singleton
cloud_backend = CloudBackend()
