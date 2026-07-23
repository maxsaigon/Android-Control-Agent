"""Small async ADB adapter used for bootstrap, fallback and media transfer."""

import asyncio
import base64
import shlex
from pathlib import Path
from typing import Any

from .base import DeviceTransport


class AdbTransport(DeviceTransport):
    def __init__(self, adb_path: str, address: str):
        if not address:
            raise ValueError("ADB device address is required")
        self.adb_path = adb_path
        self.address = address

    async def _run(self, *args: str, binary: bool = False) -> bytes | str:
        process = await asyncio.create_subprocess_exec(
            self.adb_path,
            "-s",
            self.address,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        if process.returncode:
            raise RuntimeError(stderr.decode(errors="replace").strip() or "ADB command failed")
        return stdout if binary else stdout.decode(errors="replace").strip()

    async def command(self, action: str, params: dict[str, Any] | None = None) -> Any:
        values = params or {}
        if action == "tap":
            return await self._run(
                "shell", "input", "tap", str(values["x"]), str(values["y"])
            )
        if action == "swipe":
            return await self._run(
                "shell",
                "input",
                "swipe",
                str(values["x1"]),
                str(values["y1"]),
                str(values["x2"]),
                str(values["y2"]),
                str(values.get("duration", 300)),
            )
        if action == "type_text":
            text = str(values["text"])
            if not text.isascii():
                raise ValueError("Unicode text requires the Android Helper transport")
            encoded = text.replace(" ", "%s")
            return await self._run("shell", "input", "text", encoded)
        if action == "global_action":
            key = str(values["action"]).lower()
            keycodes = {"back": "4", "home": "3", "recents": "187"}
            return await self._run("shell", "input", "keyevent", keycodes.get(key, key))
        if action == "launch_app":
            return await self._run(
                "shell",
                "monkey",
                "-p",
                str(values["package"]),
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )
        if action == "screenshot":
            image = await self._run("exec-out", "screencap", "-p", binary=True)
            return {"image_base64": base64.b64encode(image).decode(), "mime": "image/png"}
        if action == "get_ui_tree":
            await self._run("shell", "uiautomator", "dump", "/sdcard/window.xml")
            xml = await self._run("shell", "cat", "/sdcard/window.xml")
            return {"xml": xml}
        raise ValueError(f"Unsupported ADB action: {shlex.quote(action)}")

    async def push_media(self, local_path: Path, remote_name: str) -> Any:
        remote = f"/sdcard/DCIM/AndroidControl/{remote_name}"
        await self._run("shell", "mkdir", "-p", "/sdcard/DCIM/AndroidControl")
        await self._run("push", str(local_path), remote)
        await self._run(
            "shell",
            "am",
            "broadcast",
            "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d",
            f"file://{remote}",
        )
        return {"remote_path": remote}
