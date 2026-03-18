"""Script Runner — executes hard-coded task scripts at zero AI cost."""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Optional

from app.services.behavior import human_behavior

logger = logging.getLogger(__name__)


@dataclass
class ScriptResult:
    """Result from a script execution."""

    success: bool
    reason: str
    steps: int
    step_log: list = field(default_factory=list)
    error: Optional[str] = None


# --- Package hints for common apps ---
APP_PACKAGES = {
    "tiktok": ["tiktok", "musically", "trill", "ugc"],
    "youtube": ["youtube"],
    "facebook": ["facebook.katana", "facebook.lite"],
    "instagram": ["instagram"],
    "twitter": ["twitter", "android.twitter"],
    "zalo": ["zing.zalo"],
    "shopee": ["shopee"],
}


class ScriptRunner:
    """Executes deterministic task scripts — zero AI cost.

    Each script follows the pattern:
    1. force-stop app (clean start)
    2. launch app
    3. wait for load
    4. repeat: view content → swipe/scroll
    5. press HOME (cleanup)
    """

    # Registry of available scripts
    AVAILABLE_SCRIPTS = {
        "tiktok_browse",
        "youtube_watch",
        "facebook_scroll",
        "instagram_scroll",
        "generic_scroll",
    }

    def __init__(self):
        self._package_cache: dict[str, dict[str, str]] = {}

    async def run(
        self,
        device: str,
        script_name: str,
        params: dict | None = None,
        adb_agent=None,
        on_step=None,
    ) -> ScriptResult:
        """Execute a named script on a device.

        Args:
            device: ADB device target (ip:port)
            script_name: Name of the script to run
            params: Script parameters (count, view_time, etc.)
            adb_agent: ADBAgent instance for ADB commands
            on_step: Callback for step progress
        """
        if not adb_agent:
            from app.services.adb_agent import adb_agent as _agent
            adb_agent = _agent

        params = params or {}
        self._adb = adb_agent
        self._device = device
        self._on_step = on_step
        self._step_num = 0
        self._step_log = []

        scripts = {
            "tiktok_browse": self._tiktok_browse,
            "youtube_watch": self._youtube_watch,
            "facebook_scroll": self._facebook_scroll,
            "instagram_scroll": self._instagram_scroll,
            "generic_scroll": self._generic_scroll,
        }

        handler = scripts.get(script_name)
        if not handler:
            return ScriptResult(
                success=False,
                reason=f"Unknown script: {script_name}",
                steps=0,
                error=f"Available: {', '.join(scripts.keys())}",
            )

        try:
            logger.info(f"🔧 Script '{script_name}' starting on {device}")
            result = await handler(**params)
            # Always go HOME after script
            await self._adb_cmd("shell", "input", "keyevent", "3")
            logger.info(
                f"🔧 Script '{script_name}' done: "
                f"{'✅' if result.success else '❌'} {result.reason} → HOME"
            )
            return result
        except Exception as e:
            logger.exception(f"Script '{script_name}' error on {device}")
            await self._adb_cmd("shell", "input", "keyevent", "3")
            return ScriptResult(
                success=False,
                reason="Script error",
                steps=self._step_num,
                step_log=self._step_log,
                error=str(e),
            )

    # --- Helper methods ---

    async def _adb_cmd(self, *args: str) -> str:
        """Run an ADB command and return stdout."""
        _, stdout, _ = await self._adb._run_adb(self._device, *args)
        return stdout

    async def _step(self, action: str, detail: str = ""):
        """Log a step and notify callback."""
        self._step_num += 1
        log_entry = {"step": self._step_num, "action": action, "detail": detail}
        self._step_log.append(log_entry)
        logger.info(f"  📍 Step {self._step_num}: {action} {detail}")
        if self._on_step:
            from app.services.adb_agent import AgentStep
            step = AgentStep(step_num=self._step_num, action=action, detail=detail)
            if asyncio.iscoroutinefunction(self._on_step):
                await self._on_step(step)
            else:
                self._on_step(step)

    async def _open_app(self, app_name: str) -> str:
        """Force-stop and launch an app by name. Returns package name."""
        package = await self._resolve_package(app_name)
        if not package:
            raise RuntimeError(f"App not found: {app_name}")

        await self._adb_cmd("shell", "am", "force-stop", package)
        await asyncio.sleep(0.5)
        await self._adb_cmd(
            "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1"
        )
        await self._step("open_app", f"{app_name} ({package})")
        return package

    async def _resolve_package(self, name: str) -> str:
        """Find package name for an app."""
        name_lower = name.lower().strip()

        # Check cache
        if self._device in self._package_cache:
            cached = self._package_cache.get(self._device, {}).get(name_lower)
            if cached:
                return cached

        # Get installed packages
        result = await self._adb_cmd("shell", "pm", "list", "packages")
        packages = set()
        for line in result.strip().split("\n"):
            if line.startswith("package:"):
                packages.add(line.split(":", 1)[1].strip())

        # Search with hints
        hints = APP_PACKAGES.get(name_lower, [name_lower])
        for pkg in packages:
            for hint in hints:
                if hint in pkg.lower():
                    # Cache it
                    if self._device not in self._package_cache:
                        self._package_cache[self._device] = {}
                    self._package_cache[self._device][name_lower] = pkg
                    return pkg

        return ""

    async def _wait(self, lo: float, hi: float, label: str = "viewing"):
        """Wait a randomized duration."""
        duration = random.uniform(lo, hi)
        await self._step("wait", f"{duration:.1f}s ({label})")
        await asyncio.sleep(duration)

    async def _swipe_up(self):
        """Swipe up to next content."""
        w, h = await self._adb.get_screen_size(self._device)
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.75) + random.randint(-20, 20)
        y2 = int(h * 0.25) + random.randint(-20, 20)
        dur = random.randint(250, 450)
        await self._adb_cmd(
            "shell", "input", "swipe",
            str(x), str(y1), str(x), str(y2), str(dur)
        )
        await self._step("swipe_up", "next content")
        await human_behavior.random_delay("swipe")

    async def _scroll_down(self):
        """Scroll down (shorter swipe than full page)."""
        w, h = await self._adb.get_screen_size(self._device)
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.65) + random.randint(-20, 20)
        y2 = int(h * 0.35) + random.randint(-20, 20)
        dur = random.randint(300, 500)
        await self._adb_cmd(
            "shell", "input", "swipe",
            str(x), str(y1), str(x), str(y2), str(dur)
        )
        await self._step("scroll_down", "scroll feed")
        await human_behavior.random_delay("scroll_down")

    async def _tap_random_like(self, chance: float = 0.3):
        """Randomly double-tap to like (TikTok style)."""
        if random.random() > chance:
            return
        w, h = await self._adb.get_screen_size(self._device)
        x = w // 2 + random.randint(-50, 50)
        y = h // 2 + random.randint(-50, 50)
        await self._adb_cmd("shell", "input", "tap", str(x), str(y))
        await asyncio.sleep(0.15)
        await self._adb_cmd("shell", "input", "tap", str(x), str(y))
        await self._step("double_tap", "liked")

    # --- Built-in scripts ---

    async def _tiktok_browse(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Browse TikTok: open → view videos → swipe."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        for i in range(count):
            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}/{count}")
            # Maybe like
            await self._tap_random_like(like_chance)
            # Swipe to next
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Browsed {count} TikTok videos",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _youtube_watch(
        self,
        count: int = 3,
        view_time_min: float = 10.0,
        view_time_max: float = 30.0,
        **_,
    ) -> ScriptResult:
        """Watch YouTube: open → watch shorts/videos → swipe."""
        await self._open_app("youtube")
        await self._wait(3, 6, "app loading")

        # Tap on first video or Shorts tab
        w, h = await self._adb.get_screen_size(self._device)
        await self._adb_cmd(
            "shell", "input", "tap",
            str(w // 2), str(int(h * 0.4))
        )
        await self._step("tap", "first video/shorts")
        await self._wait(2, 4, "video loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"watching {i+1}/{count}")
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Watched {count} YouTube videos",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _facebook_scroll(
        self,
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 10.0,
        like_chance: float = 0.2,
        **_,
    ) -> ScriptResult:
        """Scroll Facebook feed."""
        await self._open_app("facebook")
        await self._wait(4, 7, "app loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"reading post {i+1}/{count}")
            # Randomly like a post
            if random.random() < like_chance:
                # Facebook like button is usually on bottom-left area of post
                w, h = await self._adb.get_screen_size(self._device)
                await self._adb_cmd(
                    "shell", "input", "tap",
                    str(int(w * 0.15)), str(int(h * 0.55))
                )
                await self._step("tap", "liked post")
                await asyncio.sleep(random.uniform(0.5, 1.5))
            await self._scroll_down()

        return ScriptResult(
            success=True,
            reason=f"Scrolled {count} Facebook posts",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _instagram_scroll(
        self,
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 8.0,
        **_,
    ) -> ScriptResult:
        """Scroll Instagram feed."""
        return await self._generic_scroll(
            app_name="instagram",
            count=count,
            view_time_min=view_time_min,
            view_time_max=view_time_max,
        )

    async def _generic_scroll(
        self,
        app_name: str = "tiktok",
        count: int = 5,
        view_time_min: float = 3.0,
        view_time_max: float = 8.0,
        **_,
    ) -> ScriptResult:
        """Generic app scroll: open → scroll N times → home."""
        await self._open_app(app_name)
        await self._wait(3, 6, "app loading")

        for i in range(count):
            await self._wait(view_time_min, view_time_max, f"viewing {i+1}/{count}")
            await self._scroll_down()

        return ScriptResult(
            success=True,
            reason=f"Scrolled {count} items in {app_name}",
            steps=self._step_num,
            step_log=self._step_log,
        )


# Singleton
script_runner = ScriptRunner()
