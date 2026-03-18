"""ADBBackend — DeviceBackend implementation using ADB subprocess calls.

Wraps all existing ADB logic from the original adb_agent.py into the
DeviceBackend interface. Zero behavior change — same subprocess exec
pattern, just behind a clean abstraction.
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from app.config import settings, SCREENSHOTS_DIR
from app.services.device_backend import DeviceBackend, UINode

logger = logging.getLogger(__name__)


class ADBBackend(DeviceBackend):
    """ADB subprocess-based device control backend.

    This is the original transport — every action goes through:
      adb -s <device> shell <command>
    """

    def __init__(self, adb_path: str = None):
        self.adb_path = adb_path or settings.adb_path
        self._screen_cache: dict[str, tuple[int, int]] = {}

    async def _run_adb(self, device: str, *args: str) -> tuple[int, str, str]:
        """Run an ADB command targeting a specific device."""
        cmd = [self.adb_path, "-s", device, *args]
        logger.debug(f"ADB: {' '.join(cmd)}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )

    # --- Input actions ---

    async def tap(self, device: str, x: int, y: int) -> str:
        await self._run_adb(device, "shell", "input", "tap", str(x), str(y))
        return f"Tapped at ({x}, {y})"

    async def swipe(
        self, device: str,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300,
    ) -> str:
        await self._run_adb(
            device, "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        )
        return f"Swiped ({x1},{y1}) → ({x2},{y2})"

    async def type_text(self, device: str, text: str) -> str:
        # ADB requires shell escaping for special characters
        escaped = ''.join(
            f'\\{c}' if c in ' &|;()<>"\'\\' else c
            for c in text
        )
        await self._run_adb(device, "shell", "input", "text", escaped)
        return f"Typed: {text}"

    async def key_event(self, device: str, keycode: str) -> str:
        key_map = {
            "BACK": "4", "HOME": "3", "RECENT": "187",
            "ENTER": "66", "DELETE": "67", "TAB": "61",
            "VOLUME_UP": "24", "VOLUME_DOWN": "25",
            "POWER": "26", "MENU": "82",
        }
        code = key_map.get(keycode.upper(), keycode)
        await self._run_adb(device, "shell", "input", "keyevent", code)
        return f"Pressed key: {keycode}"

    # --- UI inspection ---

    async def get_ui_tree(self, device: str) -> list[UINode]:
        """Dump UI hierarchy via uiautomator and parse into UINode list."""
        import xml.etree.ElementTree as ET

        # Dump to device
        code, out, err = await self._run_adb(
            device, "shell", "uiautomator", "dump", "/sdcard/ui.xml"
        )
        if code != 0:
            logger.warning(f"uiautomator dump failed: {err}")
            return []

        # Pull XML
        xml_path = str(SCREENSHOTS_DIR / f"ui_{device.replace(':', '_')}.xml")
        code, _, err = await self._run_adb(device, "pull", "/sdcard/ui.xml", xml_path)
        if code != 0:
            logger.warning(f"pull ui.xml failed: {err}")
            return []

        # Parse XML
        return self._parse_ui_xml(xml_path)

    def _parse_ui_xml(self, xml_path: str) -> list[UINode]:
        """Parse uiautomator XML dump into UINode objects."""
        import xml.etree.ElementTree as ET

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.warning(f"XML parse error: {e}")
            return []

        elements = []
        idx = 0
        for node in root.iter("node"):
            bounds_str = node.get("bounds", "[0,0][0,0]")
            match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
            if not match:
                continue
            bounds = tuple(int(x) for x in match.groups())

            elements.append(UINode(
                index=idx,
                text=node.get("text", ""),
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                package=node.get("package", ""),
                content_desc=node.get("content-desc", ""),
                clickable=node.get("clickable", "false") == "true",
                scrollable=node.get("scrollable", "false") == "true",
                bounds=bounds,
            ))
            idx += 1

        return elements

    async def capture_screenshot(self, device: str, save_path: str = None) -> bytes:
        """Capture screenshot via screencap + pull."""
        code, _, err = await self._run_adb(
            device, "shell", "screencap", "-p", "/sdcard/screen.png"
        )
        if code != 0:
            raise RuntimeError(f"screencap failed: {err}")

        if save_path is None:
            save_path = str(SCREENSHOTS_DIR / f"screen_{device.replace(':', '_')}.png")

        code, _, err = await self._run_adb(device, "pull", "/sdcard/screen.png", save_path)
        if code != 0:
            raise RuntimeError(f"pull screenshot failed: {err}")

        # Compress to JPEG for reduced token cost
        try:
            from PIL import Image
            img = Image.open(save_path)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            if img.width > 750:
                ratio = 750 / img.width
                img = img.resize((750, int(img.height * ratio)), Image.LANCZOS)
            jpg_path = save_path.replace('.png', '.jpg')
            img.save(jpg_path, 'JPEG', quality=85)
            return Path(jpg_path).read_bytes()
        except ImportError:
            logger.debug("Pillow not installed, using raw PNG")
            return Path(save_path).read_bytes()

    async def get_screen_size(self, device: str) -> tuple[int, int]:
        if device not in self._screen_cache:
            _, out, _ = await self._run_adb(device, "shell", "wm", "size")
            match = re.search(r'(\d+)x(\d+)', out)
            if match:
                self._screen_cache[device] = (int(match.group(1)), int(match.group(2)))
            else:
                self._screen_cache[device] = (1080, 2400)
        return self._screen_cache[device]

    # --- App management ---

    async def launch_app(self, device: str, package: str) -> str:
        await self._run_adb(
            device, "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )
        return f"Launched: {package}"

    async def force_stop(self, device: str, package: str) -> str:
        await self._run_adb(device, "shell", "am", "force-stop", package)
        return f"Stopped: {package}"

    async def list_packages(self, device: str, third_party_only: bool = False) -> list[str]:
        args = ["shell", "pm", "list", "packages"]
        if third_party_only:
            args.append("-3")
        _, out, _ = await self._run_adb(device, *args)
        packages = []
        for line in out.strip().split("\n"):
            if line.startswith("package:"):
                packages.append(line.split(":", 1)[1].strip())
        return packages

    # --- Device info ---

    async def get_foreground_app(self, device: str) -> str:
        _, stdout, _ = await self._run_adb(
            device, "shell", "dumpsys", "activity", "activities"
        )
        for line in stdout.splitlines():
            if "mResumedActivity" in line or "mFocusedActivity" in line:
                # Extract package name: "com.package.name/.ActivityName"
                match = re.search(r'(\S+)/\S+', line)
                if match:
                    return match.group(1)
        return ""

    async def get_device_info(self, device: str) -> dict:
        info = {}

        _, out, _ = await self._run_adb(
            device, "shell", "getprop", "ro.build.version.release"
        )
        if out:
            info["android_version"] = out

        _, out, _ = await self._run_adb(
            device, "shell", "getprop", "ro.product.model"
        )
        if out:
            info["device_model"] = out

        _, out, _ = await self._run_adb(device, "shell", "dumpsys", "battery")
        for line in out.splitlines():
            if "level:" in line.lower():
                try:
                    info["battery_level"] = int(line.split(":")[-1].strip())
                except ValueError:
                    pass
                break

        return info

    async def ping(self, device: str) -> bool:
        code, out, _ = await self._run_adb(device, "shell", "echo", "ping")
        return code == 0 and "ping" in out

    # --- Raw command support ---

    async def raw_shell(self, device: str, *args: str) -> tuple[int, str, str]:
        """ADB backend supports raw shell commands natively."""
        return await self._run_adb(device, *args)


# Singleton
adb_backend = ADBBackend()
