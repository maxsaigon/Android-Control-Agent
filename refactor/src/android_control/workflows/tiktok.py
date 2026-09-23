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
    await emit("launch", "TikTok launch command delivered", False)
    await asyncio.sleep(min(view_seconds, 2))

    tree = await transport.ui_tree()
    if TIKTOK_PACKAGE not in str(tree):
        raise RuntimeError("TikTok foreground not verified from UI tree")
    await emit("verify", "TikTok UI observed; feed content is not independently verified", True)
    size = await transport.command("get_screen_size")
    width, height = int(size["width"]), int(size["height"])
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid display size")

    for index in range(count):
        await asyncio.sleep(view_seconds + random.uniform(0, min(view_seconds * 0.2, 1)))
        await emit("observe", f"Waited on feed item {index + 1}/{count}; viewing not verified", False)
        if index < count - 1:
            await transport.swipe(width // 2, int(height * .8), width // 2, int(height * .25), random.randint(280, 420))
            await emit("swipe", "Swipe delivered; new feed item not independently verified", False)


WORKFLOWS = {
    "tiktok.browse": {
        "title": "Browse TikTok feed",
        "description": "Launch TikTok and browse a bounded number of feed items.",
        "parameters": {"count": 5, "view_seconds": 2},
        "runner": browse,
    }
}
