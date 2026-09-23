"""Device Manager — ADB device discovery, connection, and health monitoring."""

import asyncio
import logging
import shutil
from datetime import datetime, timezone

from app.config import settings
from app.services.helper_release import resolve_helper_apk_path

logger = logging.getLogger(__name__)


class DeviceManager:
    """Manages ADB connections and device health."""

    def __init__(self):
        self.adb_path = settings.adb_path
        self._resolved_adb_path = self._resolve_adb_path(settings.adb_path)

    def _resolve_adb_path(self, configured_path: str) -> str:
        """Resolve an executable ADB path, with fallback to PATH lookup."""
        if configured_path and shutil.which(configured_path):
            return configured_path

        fallback = shutil.which("adb")
        if fallback:
            logger.warning(
                "Configured ADB_PATH '%s' not found; falling back to '%s'",
                configured_path,
                fallback,
            )
            return fallback

        return configured_path

    async def _run_adb(self, *args: str, timeout_s: float = 20.0) -> tuple[int, str, str]:
        """Run an ADB command and return (returncode, stdout, stderr)."""
        cmd = [self._resolved_adb_path, *args]
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            msg = (
                f"ADB executable not found: configured='{self.adb_path}', "
                f"resolved='{self._resolved_adb_path}'"
            )
            logger.error(msg)
            return 127, "", msg
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await proc.communicate()
            except Exception:
                pass
            msg = (
                f"ADB command timed out after {timeout_s:.0f}s: "
                f"{' '.join(cmd)}"
            )
            logger.warning(msg)
            return 124, "", msg
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

    async def _check_adb_port(self, ip: str, port: int = 5555, timeout: float = 1.5) -> bool:
        """Check if ADB port is open on the given IP."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            return False

    async def _get_quick_info(self, ip: str, port: int = 5555) -> dict:
        """Get basic device info quickly (model + android version)."""
        target = f"{ip}:{port}"
        info = {"ip": ip, "port": port, "status": "unknown"}

        # Try to connect
        code, out, err = await self._run_adb("connect", target)
        if "connected" in out.lower():
            info["status"] = "connected"
        elif "unauthorized" in out.lower():
            info["status"] = "unauthorized"
        else:
            info["status"] = "refused"
            return info

        # Get model
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "getprop", "ro.product.model"
        )
        if code == 0 and out:
            info["model"] = out

        # Get Android version
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "getprop", "ro.build.version.release"
        )
        if code == 0 and out:
            info["android_version"] = out

        # Disconnect after scan (don't keep connection)
        await self._run_adb("disconnect", target)

        return info

    async def scan_subnet(
        self, subnet: str, port: int = 5555, timeout: float = 1.5
    ) -> list[dict]:
        """Scan a /24 subnet for ADB-enabled devices.

        Args:
            subnet: Base subnet like '192.168.1' or '192.168.1.0/24'
            port: ADB port to check (default 5555)
            timeout: TCP connect timeout in seconds

        Returns:
            List of dicts with ip, port, status, model, android_version
        """
        # Parse subnet — accept "192.168.1", "192.168.1.0", "192.168.1.0/24"
        base = subnet.replace("/24", "").strip()
        parts = base.split(".")
        if len(parts) == 4:
            base = ".".join(parts[:3])
        elif len(parts) != 3:
            raise ValueError(f"Invalid subnet format: {subnet}")

        logger.info(f"🔍 Scanning subnet {base}.0/24 on port {port}...")

        # Phase 1: Async TCP port scan (fast, concurrent)
        async def probe(ip):
            if await self._check_adb_port(ip, port, timeout):
                return ip
            return None

        tasks = [probe(f"{base}.{i}") for i in range(1, 255)]
        results = await asyncio.gather(*tasks)
        open_ips = [ip for ip in results if ip]

        logger.info(f"🔍 Found {len(open_ips)} IPs with port {port} open: {open_ips}")

        if not open_ips:
            return []

        # Phase 2: Get ADB info for each open IP
        info_tasks = [self._get_quick_info(ip, port) for ip in open_ips]
        devices = await asyncio.gather(*info_tasks)

        return [d for d in devices if d.get("status") != "refused"]

    # --- Helper APK management ---

    HELPER_PACKAGE = "com.androidcontrol.helper"
    HELPER_SERVICE = (
        "com.androidcontrol.helper/"
        "com.androidcontrol.helper.HelperAccessibilityService"
    )

    @staticmethod
    def _helper_apk_path() -> str | None:
        path = resolve_helper_apk_path()
        return str(path) if path else None

    async def _is_helper_installed(self, ip: str, port: int = 5555) -> bool:
        """Check if AC Helper APK is installed on device."""
        target = f"{ip}:{port}"
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "pm", "list", "packages", self.HELPER_PACKAGE
        )
        return self.HELPER_PACKAGE in out

    async def _enable_accessibility_service(self, ip: str, port: int = 5555) -> bool:
        """Enable the AccessibilityService on device via ADB settings."""
        target = f"{ip}:{port}"

        # Preserve other enabled accessibility services.
        code, current, _ = await self._run_adb(
            "-s", target, "shell", "settings", "get", "secure", "enabled_accessibility_services"
        )
        if code != 0:
            return False
        services = [v for v in current.strip().split(":") if v and v != "null"]
        if self.HELPER_SERVICE not in services:
            services.append(self.HELPER_SERVICE)

        # Set the enabled accessibility services
        await self._run_adb(
            "-s", target, "shell", "settings", "put", "secure",
            "enabled_accessibility_services", ":".join(services),
        )
        # Enable accessibility globally
        await self._run_adb(
            "-s", target, "shell", "settings", "put", "secure",
            "accessibility_enabled", "1",
        )

        # Verify
        code, out, _ = await self._run_adb(
            "-s", target, "shell", "settings", "get", "secure",
            "enabled_accessibility_services",
        )
        enabled = self.HELPER_PACKAGE in out
        if enabled:
            logger.info(f"  ✅ Accessibility service enabled on {target}")
        else:
            logger.warning(f"  ⚠️ Failed to enable accessibility on {target}")
        return enabled

    async def helper_version(self, ip: str, port: int = 5555) -> int | None:
        import re
        code, out, _ = await self._run_adb("-s", f"{ip}:{port}", "shell", "dumpsys", "package", self.HELPER_PACKAGE)
        match = re.search(r"versionCode=(\d+)", out) if code == 0 else None
        return int(match.group(1)) if match else None

    async def install_helper_release(self, ip: str, port: int, release: dict) -> dict:
        """Caller owns the device lock. Verify pinned artifact and installed health."""
        import hashlib
        from pathlib import Path
        from app.services.helper_release import helper_downloads_dir
        name = release["artifact_name"]
        if Path(name).name != name:
            raise ValueError("Invalid helper artifact name")
        apk = helper_downloads_dir() / name
        if (apk.stat().st_size != release["file_size_bytes"]
                or hashlib.sha256(apk.read_bytes()).hexdigest() != release["sha256"]):
            raise ValueError("Helper artifact checksum/size mismatch")
        installed = await self.helper_version(ip, port)
        if installed is not None and installed > release["version_code"]:
            raise ValueError("Refusing helper downgrade")
        target = f"{ip}:{port}"
        # Android enforces the installed package's signing certificate on replacement.
        code, out, err = await self._run_adb("-s", target, "install", "-r", str(apk), timeout_s=180)
        if code != 0 or "Success" not in out:
            raise RuntimeError(f"Install failed: {out} {err}")
        enabled = await self._enable_accessibility_service(ip, port)
        await self._run_adb("-s", target, "shell", "am", "start", "-n", f"{self.HELPER_PACKAGE}/.MainActivity")
        actual = await self.helper_version(ip, port)
        bound = False
        for _ in range(10):
            code, dump, _ = await self._run_adb("-s", target, "shell", "dumpsys", "accessibility")
            # Enabled in settings alone does not mean the service actually bound.
            bound = code == 0 and any(
                self.HELPER_PACKAGE in line and ("Bound services:" in line or "boundServices:" in line)
                for line in dump.splitlines()
            )
            if bound:
                break
            await asyncio.sleep(1)
        verified = actual == release["version_code"] and enabled and bound
        return {"installed": True, "enabled": enabled, "version_code": actual,
                "verified": verified, "error": None if verified else "Installed but accessibility health check failed"}

    async def ensure_helper_apk(self, ip: str, port: int = 5555) -> dict:
        """Ensure AC Helper APK is installed and running on device.

        Steps:
        1. Check if package is installed
        2. Install if missing (via adb install)
        3. Enable Accessibility Service
        4. Launch helper app (starts WebSocket foreground service)
        5. Verify WebSocket port is reachable

        Returns dict with: installed, enabled, ws_reachable, error
        """
        import asyncio
        target = f"{ip}:{port}"
        result = {
            "installed": False,
            "enabled": False,
            "ws_reachable": False,
            "error": None,
        }

        try:
            from app.services.helper_release import validated_helper_release
            installed = await self.helper_version(ip, port)
            release = validated_helper_release()
            if installed is None or installed < release["version_code"]:
                return await self.install_helper_release(ip, port, release)
            result["installed"] = True
            result["version_code"] = installed

            # Step 3: Enable Accessibility Service
            result["enabled"] = await self._enable_accessibility_service(ip, port)

            # Step 4: Launch the helper app
            await self._run_adb(
                "-s", target, "shell", "monkey",
                "-p", self.HELPER_PACKAGE,
                "-c", "android.intent.category.LAUNCHER", "1",
            )
            await asyncio.sleep(2)  # Wait for WS server to start

            # Step 5: Check WebSocket reachable
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, 38301),
                    timeout=3,
                )
                writer.close()
                await writer.wait_closed()
                result["ws_reachable"] = True
                logger.info(f"  🔌 WebSocket server reachable on {ip}:38301")
            except Exception:
                logger.warning(f"  ⚠️ WebSocket not reachable on {ip}:38301")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"  ❌ ensure_helper_apk failed: {e}")

        return result


# Singleton
device_manager = DeviceManager()
