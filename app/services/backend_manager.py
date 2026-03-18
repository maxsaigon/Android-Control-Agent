"""Backend Manager — selects and provides the right DeviceBackend.

Routes devices to either ADBBackend or AccessibilityBackend based on:
1. Config setting (default_backend)
2. Per-device override
3. Auto-detection (try Accessibility first, fallback to ADB)
"""

import asyncio
import logging
from typing import Optional

from app.config import settings
from app.services.device_backend import DeviceBackend

logger = logging.getLogger(__name__)


class BackendManager:
    """Manages backend selection per device.

    Usage:
        backend = await backend_manager.get_backend("192.168.1.150:5555")
        await backend.tap(device, x, y)
    """

    def __init__(self):
        self._adb: Optional[DeviceBackend] = None
        self._accessibility: Optional[DeviceBackend] = None
        self._device_backends: dict[str, str] = {}  # device → "adb" | "accessibility"

    @property
    def adb(self) -> DeviceBackend:
        """Lazy-init ADB backend."""
        if self._adb is None:
            from app.services.adb_backend import ADBBackend
            self._adb = ADBBackend()
        return self._adb

    @property
    def accessibility(self) -> DeviceBackend:
        """Lazy-init Accessibility backend."""
        if self._accessibility is None:
            from app.services.accessibility_backend import AccessibilityBackend
            self._accessibility = AccessibilityBackend()
        return self._accessibility

    async def get_backend(self, device: str) -> DeviceBackend:
        """Get the best backend for a device.

        Priority:
        1. Cached per-device choice
        2. Config default_backend
        3. Auto-detect (try Accessibility → fallback ADB)
        """
        # Check cached choice
        if device in self._device_backends:
            backend_type = self._device_backends[device]
            return self.adb if backend_type == "adb" else self.accessibility

        # Use config setting
        mode = settings.default_backend

        if mode == "adb":
            self._device_backends[device] = "adb"
            return self.adb
        elif mode == "accessibility":
            self._device_backends[device] = "accessibility"
            return self.accessibility
        else:
            # Auto-detect: try Accessibility, fallback to ADB
            return await self._auto_detect(device)

    async def _auto_detect(self, device: str) -> DeviceBackend:
        """Try Accessibility backend first, fall back to ADB."""
        try:
            if await self.accessibility.ping(device):
                self._device_backends[device] = "accessibility"
                logger.info(f"🔌 Auto-detected: {device} → Accessibility backend")
                return self.accessibility
        except Exception as e:
            logger.debug(f"Accessibility backend unavailable for {device}: {e}")

        self._device_backends[device] = "adb"
        logger.info(f"🔧 Auto-detected: {device} → ADB backend")
        return self.adb

    def set_backend(self, device: str, backend_type: str):
        """Manually set backend for a device."""
        if backend_type not in ("adb", "accessibility"):
            raise ValueError(f"Unknown backend type: {backend_type}")
        self._device_backends[device] = backend_type
        logger.info(f"Backend for {device} set to: {backend_type}")

    def get_backend_type(self, device: str) -> str:
        """Get current backend type for a device."""
        return self._device_backends.get(device, "unknown")

    def clear_cache(self, device: str = None):
        """Clear backend cache for a device or all devices."""
        if device:
            self._device_backends.pop(device, None)
        else:
            self._device_backends.clear()

    @property
    def status(self) -> dict:
        """Get backend status for all devices."""
        return {
            "default_backend": settings.default_backend,
            "devices": dict(self._device_backends),
        }


# Singleton
backend_manager = BackendManager()
