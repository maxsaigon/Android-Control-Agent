"""Transport-neutral device command contract."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class DeviceTransport(ABC):
    @abstractmethod
    async def command(self, action: str, params: dict[str, Any] | None = None) -> Any:
        """Deliver a command and return the helper/ADB result."""

    async def tap(self, x: int, y: int) -> Any:
        return await self.command("tap", {"x": x, "y": y})

    async def press(self, x: int, y: int, duration_ms: int = 80) -> Any:
        return await self.command(
            "swipe",
            {"x1": x, "y1": y, "x2": x, "y2": y, "duration": duration_ms},
        )

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ) -> Any:
        return await self.command(
            "swipe",
            {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration_ms},
        )

    async def type_text(self, text: str) -> Any:
        return await self.command("type_text", {"text": text})

    async def key(self, key: str) -> Any:
        return await self.command("global_action", {"action": key.lower()})

    async def screenshot(self) -> Any:
        return await self.command("screenshot")

    async def ui_tree(self) -> Any:
        return await self.command("get_ui_tree")

    async def launch_app(self, package: str) -> Any:
        return await self.command("launch_app", {"package": package})

    async def push_media(self, local_path: Path, remote_name: str) -> Any:
        raise NotImplementedError("This transport cannot push media yet")
