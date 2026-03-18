"""Device Manager — ADB device discovery, connection, and health monitoring."""

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages ADB connections and device health."""

    def __init__(self):
        self.adb_path = settings.adb_path

    async def _run_adb(self, *args: str) -> tuple[int, str, str]:
        """Run an ADB command and return (returncode, stdout, stderr)."""
        cmd = [self.adb_path, *args]
        logger.debug(f"Running: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode().strip(),
            stderr.decode().strip(),
        )

    async def connect(self, ip: str, port: int = 5555) -> bool:
        """Connect to an Android device via ADB TCP/IP."""
        target = f"{ip}:{port}"
        code, out, err = await self._run_adb("connect", target)
        success = "connected" in out.lower()
        if success:
            logger.info(f"Connected to {target}")
        else:
            logger.warning(f"Failed to connect to {target}: {out} {err}")
        return success

    async def disconnect(self, ip: str, port: int = 5555) -> bool:
        """Disconnect a device."""
        target = f"{ip}:{port}"
        code, out, err = await self._run_adb("disconnect", target)
        return "disconnected" in out.lower()

    async def ping(self, ip: str, port: int = 5555) -> bool:
        """Check if device is reachable via ADB."""
        target = f"{ip}:{port}"
        code, out, err = await self._run_adb(
            "-s", target, "shell", "echo", "ping"
        )
        return code == 0 and "ping" in out

    async def get_device_info(self, ip: str, port: int = 5555) -> dict:
        """Get device model, Android version, battery level."""
        target = f"{ip}:{port}"
        info = {}

        # Android version
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "getprop", "ro.build.version.release"
        )
        if code == 0:
            info["android_version"] = out

        # Device model
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "getprop", "ro.product.model"
        )
        if code == 0:
            info["device_model"] = out

        # Battery level
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "dumpsys", "battery"
        )
        if code == 0:
            for line in out.splitlines():
                if "level:" in line.lower():
                    try:
                        info["battery_level"] = int(
                            line.split(":")[-1].strip()
                        )
                    except ValueError:
                        pass
                    break

        info["last_seen"] = datetime.now(timezone.utc)
        return info

    async def list_connected(self) -> list[str]:
        """List currently connected ADB devices."""
        code, out, _ = await self._run_adb("devices")
        devices = []
        for line in out.splitlines()[1:]:  # Skip "List of devices attached"
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    async def ensure_connected(self, ip: str, port: int = 5555) -> bool:
        """Ensure device is connected, reconnect if needed."""
        if await self.ping(ip, port):
            return True
        return await self.connect(ip, port)


# Singleton
device_manager = DeviceManager()
