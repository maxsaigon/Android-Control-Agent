"""
Connection Watchdog — Keeps ADB WiFi connections alive.

Runs as a background task in the FastAPI server. Periodically pings all
registered devices and auto-reconnects any that drop off.

Works without root and without any custom app on the Android device.
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.services.device_manager import device_manager

logger = logging.getLogger(__name__)

# How often to check device connectivity (seconds)
PING_INTERVAL = 30

# How often to send a lightweight keep-alive (seconds)
KEEPALIVE_INTERVAL = 15

# Max consecutive failures before marking offline
MAX_FAILURES = 3


class ConnectionWatchdog:
    """
    Background service that monitors and maintains ADB WiFi connections.

    Strategy:
    1. Keep-alive: Send lightweight ADB commands every 15s to prevent
       the WiFi stack from idling the connection.
    2. Ping & Reconnect: Every 30s, check if devices respond. If not,
       attempt `adb connect` to re-establish.
    3. Pre-task Guard: Before any task execution, verify connectivity
       and reconnect if needed (already in task_engine.py).
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._devices: dict[str, dict] = {}  # ip:port -> {failures, last_seen}
        self._running = False

    def register_device(self, ip: str, port: int = 5555):
        """Register a device for monitoring."""
        key = f"{ip}:{port}"
        if key not in self._devices:
            self._devices[key] = {
                "ip": ip,
                "port": port,
                "failures": 0,
                "last_seen": None,
                "status": "unknown",
            }
            logger.info(f"🔗 Watchdog: Registered {key}")

    def unregister_device(self, ip: str, port: int = 5555):
        """Remove a device from monitoring."""
        key = f"{ip}:{port}"
        self._devices.pop(key, None)
        logger.info(f"🔗 Watchdog: Unregistered {key}")

    def start(self):
        """Start the watchdog background tasks."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info("🐕 Connection Watchdog started")

    def stop(self):
        """Stop the watchdog."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._keepalive_task:
            self._keepalive_task.cancel()
        logger.info("🐕 Connection Watchdog stopped")

    async def _monitor_loop(self):
        """Main monitoring loop — ping devices and reconnect if needed."""
        while self._running:
            try:
                await asyncio.sleep(PING_INTERVAL)
                for key, info in list(self._devices.items()):
                    await self._check_device(key, info)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Watchdog monitor error: {e}")
                await asyncio.sleep(5)

    async def _keepalive_loop(self):
        """
        Send lightweight keep-alive commands to prevent WiFi idle disconnect.

        Uses `adb shell echo ok` — minimal overhead, keeps the TCP socket active.
        """
        while self._running:
            try:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                for key, info in list(self._devices.items()):
                    if info["status"] == "online":
                        try:
                            target = f"{info['ip']}:{info['port']}"
                            proc = await asyncio.create_subprocess_exec(
                                settings.adb_path, "-s", target,
                                "shell", "echo", "keepalive",
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            await asyncio.wait_for(proc.communicate(), timeout=5)
                        except (asyncio.TimeoutError, Exception):
                            pass  # Monitor loop will handle failures
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    async def _check_device(self, key: str, info: dict):
        """Check a single device and reconnect if needed."""
        ip, port = info["ip"], info["port"]
        reachable = await device_manager.ping(ip, port)

        if reachable:
            info["failures"] = 0
            info["last_seen"] = datetime.now(timezone.utc)
            if info["status"] != "online":
                info["status"] = "online"
                logger.info(f"✅ Watchdog: {key} is online")
        else:
            info["failures"] += 1
            logger.warning(
                f"⚠️ Watchdog: {key} not responding "
                f"(failure {info['failures']}/{MAX_FAILURES})"
            )

            if info["failures"] >= MAX_FAILURES:
                info["status"] = "offline"
                logger.warning(f"❌ Watchdog: {key} marked offline")

            # Try to reconnect
            logger.info(f"🔄 Watchdog: Attempting reconnect to {key}...")
            success = await device_manager.connect(ip, port)
            if success:
                info["failures"] = 0
                info["status"] = "online"
                info["last_seen"] = datetime.now(timezone.utc)
                logger.info(f"✅ Watchdog: Reconnected to {key}")
            else:
                logger.warning(f"❌ Watchdog: Reconnect to {key} failed")

    @property
    def status(self) -> dict:
        """Get current watchdog status."""
        return {
            "running": self._running,
            "devices": {
                key: {
                    "status": info["status"],
                    "failures": info["failures"],
                    "last_seen": info["last_seen"].isoformat() if info["last_seen"] else None,
                }
                for key, info in self._devices.items()
            },
        }


# Singleton
watchdog = ConnectionWatchdog()
