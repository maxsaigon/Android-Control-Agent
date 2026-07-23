"""First small TikTok workflow built from device primitives."""

import asyncio
import random
from typing import Any, Awaitable, Callable

from ..transports.base import DeviceTransport

StepEmitter = Callable[[str, str, bool], Awaitable[None]]

TIKTOK_PACKAGE = "com.ss.android.ugc.trill"


async def browse(
    transport: DeviceTransport,
    params: dict[str, Any],
    emit: StepEmitter,
) -> None:
    count = max(1, min(int(params.get("count", 5)), 30))
    view_seconds = max(0.5, min(float(params.get("view_seconds", 2.0)), 30.0))

    await transport.launch_app(TIKTOK_PACKAGE)
    await emit("launch", "TikTok launch command delivered", True)
    await asyncio.sleep(min(view_seconds, 2))

    for index in range(count):
        await asyncio.sleep(view_seconds + random.uniform(0, min(view_seconds * 0.2, 1)))
        await emit("observe", f"Viewed feed item {index + 1}/{count}", True)
        if index < count - 1:
            await transport.swipe(540, 1700, 540, 520, random.randint(280, 420))
            await emit("swipe", "Advanced to the next feed item", True)


WORKFLOWS = {
    "tiktok.browse": {
        "title": "Browse TikTok feed",
        "description": "Launch TikTok and browse a bounded number of feed items.",
        "parameters": {"count": 5, "view_seconds": 2},
        "runner": browse,
    }
}
