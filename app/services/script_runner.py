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
        "tiktok_warmup",
        "tiktok_like",
        "tiktok_comment",
        "tiktok_follow",
        "youtube_watch",
        "facebook_scroll",
        "instagram_scroll",
        "generic_scroll",
    }

    # Comment pool for TikTok engagement scripts
    TIKTOK_COMMENTS = [
        ":))", "hay quá", "tuyệt vời!", "😂😂", "ủa gì đây",
        "real", "🔥", "nhìn ngon quá", "cười xỉu", "đỉnh",
        "save lại coi tiếp", "cho xin nhạc", "follow rồi nha",
        "quá hay", "hhh", ":3", "💀💀", "giỏi quá",
    ]

    def __init__(self):
        self._package_cache: dict[str, dict[str, str]] = {}
        self._tiktok: "TikTokController | None" = None

    def _get_tiktok_controller(self):
        """Lazy-init TikTok controller."""
        if self._tiktok is None:
            from app.services.tiktok_controller import TikTokController
            self._tiktok = TikTokController(self._adb)
        return self._tiktok

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
        self._backend = None  # will be initialized async

        scripts = {
            "tiktok_browse": self._tiktok_browse,
            "tiktok_warmup": self._tiktok_warmup,
            "tiktok_like": self._tiktok_like,
            "tiktok_comment": self._tiktok_comment,
            "tiktok_follow": self._tiktok_follow,
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
            # Initialize backend for this run
            from app.services.backend_manager import backend_manager
            self._backend = await backend_manager.get_backend(device)
            result = await handler(**params)
            # Always go HOME after script
            await self._safe_key_event("HOME")
            logger.info(
                f"🔧 Script '{script_name}' done: "
                f"{'✅' if result.success else '❌'} {result.reason} → HOME"
            )
            return result
        except Exception as e:
            logger.exception(f"Script '{script_name}' error on {device}")
            try:
                await self._safe_key_event("HOME")
            except Exception:
                pass
            return ScriptResult(
                success=False,
                reason="Script error",
                steps=self._step_num,
                step_log=self._step_log,
                error=str(e),
            )

    # --- Helper methods ---

    async def _backend_call(self, method_name: str, *args, **kwargs):
        """Call backend method with auto-fallback to ADB on Accessibility failure."""
        if self._backend:
            try:
                method = getattr(self._backend, method_name)
                return await method(self._device, *args, **kwargs)
            except RuntimeError as e:
                err_msg = str(e)
                if "Service not running" in err_msg or "not connected" in err_msg.lower():
                    logger.warning(
                        f"⚠️ Accessibility failed ({err_msg}), falling back to ADB"
                    )
                    await self._fallback_to_adb()
                    method = getattr(self._backend, method_name)
                    return await method(self._device, *args, **kwargs)
                raise
        # No backend — use ADB agent directly
        method = getattr(self._adb, method_name)
        return await method(self._device, *args, **kwargs)

    async def _fallback_to_adb(self):
        """Switch backend from Accessibility to ADB for this run."""
        from app.services.backend_manager import backend_manager
        backend_manager.set_backend(self._device, "adb")
        self._backend = backend_manager.adb
        logger.info(f"🔄 Switched {self._device} to ADB backend")

    async def _safe_key_event(self, key: str):
        """Send key event with backend fallback."""
        try:
            await self._backend_call("key_event", key)
        except Exception:
            # Last resort: ADB directly
            try:
                key_map = {"HOME": "3", "BACK": "4", "ENTER": "66"}
                keycode = key_map.get(key.upper(), key)
                await self._adb._run_adb("-s", self._device, "shell", "input", "keyevent", keycode)
            except Exception:
                pass

    async def _adb_cmd(self, *args: str) -> str:
        """Run an ADB command via backend raw_shell or direct _run_adb."""
        if self._backend:
            try:
                _, stdout, _ = await self._backend.raw_shell(self._device, *args)
                return stdout
            except (NotImplementedError, RuntimeError):
                pass
        # Fallback to direct adb
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

        try:
            await self._backend_call("force_stop", package)
            await asyncio.sleep(0.5)
            await self._backend_call("launch_app", package)
        except Exception:
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

    async def _adb_screencap(self) -> bytes:
        """Capture screenshot via ADB directly (bypasses backend)."""
        proc = await asyncio.create_subprocess_exec(
            self._adb.adb_path, "-s", self._device,
            "shell", "screencap", "-p",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if not stdout:
            raise RuntimeError("ADB screencap returned empty data")
        return stdout

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
        try:
            await self._backend_call("swipe", x, y1, x, y2, dur)
        except Exception:
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
        try:
            await self._backend_call("swipe", x, y1, x, y2, dur)
        except Exception:
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
        try:
            await self._backend_call("tap", x, y)
            await asyncio.sleep(0.15)
            await self._backend_call("tap", x, y)
        except Exception:
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

    async def _tiktok_warmup(
        self,
        count: int = 8,
        view_time_min: float = 10.0,
        view_time_max: float = 30.0,
        **_,
    ) -> ScriptResult:
        """Warm-up TikTok account: open → view videos passively → no interactions."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        for i in range(count):
            # View current video — longer than normal browsing
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}/{count}")

            # Occasionally pause extra long (20% chance) — simulate watching full video
            if random.random() < 0.2:
                extra = random.uniform(15, 45)
                await self._step("wait", f"{extra:.1f}s (watching full video)")
                await asyncio.sleep(extra)

            # Occasionally view creator profile (15% chance)
            if random.random() < 0.15:
                w, h = await self._adb.get_screen_size(self._device)
                # Tap avatar area (right side, middle)
                avatar_x = int(w * 0.93) + random.randint(-10, 10)
                avatar_y = int(h * 0.45) + random.randint(-15, 15)
                await self._adb_cmd("shell", "input", "tap", str(avatar_x), str(avatar_y))
                await self._step("tap", "view creator profile")
                await self._wait(3, 8, "browsing profile")
                # Go back to feed
                await self._adb_cmd("shell", "input", "keyevent", "4")
                await self._step("key", "back to feed")
                await self._wait(1, 2, "returning")

            # Swipe to next video
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Warmed up TikTok: viewed {count} videos passively",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _tiktok_like(
        self,
        count: int = 10,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Like TikTok videos: browse feed + double-tap or tap heart."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        likes_done = 0
        consecutive_likes = 0

        for i in range(count * 3):  # Browse more videos than target likes
            if likes_done >= count:
                break

            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            # Decide to like
            should_like = random.random() < like_chance and consecutive_likes < 5

            if should_like:
                w, h = await self._adb.get_screen_size(self._device)

                if random.random() < 0.7:
                    # Double-tap to like (70% — most natural)
                    x = w // 2 + random.randint(-50, 50)
                    y = h // 2 + random.randint(-50, 50)
                    await self._adb_cmd("shell", "input", "tap", str(x), str(y))
                    await asyncio.sleep(random.uniform(0.1, 0.2))
                    await self._adb_cmd("shell", "input", "tap", str(x), str(y))
                    await self._step("double_tap", f"liked video (double-tap) [{likes_done+1}/{count}]")
                else:
                    # Tap heart icon (30%)
                    heart_x = int(w * 0.93) + random.randint(-8, 8)
                    heart_y = int(h * 0.38) + random.randint(-8, 8)
                    await self._adb_cmd("shell", "input", "tap", str(heart_x), str(heart_y))
                    await self._step("tap", f"liked video (heart icon) [{likes_done+1}/{count}]")

                likes_done += 1
                consecutive_likes += 1
                await self._wait(0.5, 1.5, "post-like pause")

                # Occasionally view profile after liking (10% chance)
                if random.random() < 0.1:
                    avatar_x = int(w * 0.93) + random.randint(-10, 10)
                    avatar_y = int(h * 0.45) + random.randint(-15, 15)
                    await self._adb_cmd("shell", "input", "tap", str(avatar_x), str(avatar_y))
                    await self._step("tap", "view creator profile")
                    await self._wait(2, 5, "browsing profile")
                    await self._adb_cmd("shell", "input", "keyevent", "4")
                    await self._step("key", "back to feed")
                    await self._wait(1, 2, "returning")
            else:
                consecutive_likes = 0

            # Swipe to next
            await self._swipe_up()

            # Anti-detection: occasional long pause
            if random.random() < 0.1:
                await self._wait(8, 20, "natural pause")

        return ScriptResult(
            success=True,
            reason=f"Liked {likes_done}/{count} TikTok videos",
            steps=self._step_num,
            step_log=self._step_log,
        )

    # Shared prompt for AI comment generation
    _COMMENT_SYSTEM_PROMPT = (
        "Bạn là người Việt Nam đang lướt TikTok. "
        "Viết MỘT comment ngắn, tự nhiên, SÁNG TẠO cho video này. "
        "Quy tắc:\n"
        "- Ngắn gọn (2-8 từ)\n"
        "- Tự nhiên như gen Z Việt Nam\n"
        "- MỖI LẦN viết comment KHÁC NHAU, không lặp lại\n"
        "- Phù hợp nội dung video (dựa vào mô tả, nhạc, creator)\n"
        "- KHÔNG dùng hashtag, KHÔNG quá formal\n"
        "- Đa dạng phong cách: hài hước, khen, hỏi, bày tỏ cảm xúc\n"
        "- Có thể dùng emoji, viết tắt, slang VN\n"
        "Chỉ trả về comment text, không giải thích."
    )

    async def _ai_generate_comment(self, fallback_pool: list[str] = None) -> str:
        """Hybrid: AI generates contextual comment.

        Priority (cost-optimized):
        1. DeepSeek (primary) — text-only with video info → ~$0.00006/comment
        2. GPT-4o (fallback) — vision + screenshot → ~$0.003/comment
        3. Random pool (last resort)
        """
        from app.config import settings
        import openai

        # 1. Get video info from UI hierarchy (cheap, no API call)
        video_info = {}
        tiktok = self._get_tiktok_controller()
        try:
            video_info = await tiktok.get_video_info(self._device)
        except Exception:
            pass

        # --- Try DeepSeek (primary — text-only, ~$0.00006/comment) ---
        if settings.deepseek_api_key:
            try:
                client = openai.AsyncOpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                )

                context_parts = []
                if video_info.get("author"):
                    context_parts.append(f"Creator: {video_info['author']}")
                if video_info.get("description"):
                    context_parts.append(f"Mô tả: {video_info['description']}")
                if video_info.get("sound"):
                    context_parts.append(f"Nhạc: {video_info['sound']}")
                if video_info.get("likes"):
                    context_parts.append(f"Likes: {video_info['likes']}")

                context = "\n".join(context_parts) if context_parts else "Video TikTok bất kỳ"

                response = await client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": self._COMMENT_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Video info:\n{context}\n\nViết comment (khác với các comment trước):"},
                    ],
                    max_tokens=40,
                    temperature=1.1,
                )

                comment = response.choices[0].message.content.strip().strip('"\'')
                logger.info(f"  🧠 [deepseek] comment: {comment}")
                await self._step("ai_comment", f"[deepseek] {comment}")
                return comment

            except Exception as e:
                logger.warning(f"DeepSeek failed: {e}")

        # --- Try GPT-4o (fallback — vision, ~$0.003/comment) ---
        if settings.openai_api_key:
            try:
                import base64
                # Capture screenshot via ADB directly (Accessibility may not support it)
                screenshot_bytes = await self._adb_screencap()
                await self._step("screenshot", "captured for GPT-4o fallback")

                client = openai.AsyncOpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.llm_base_url or None,
                )
                img_b64 = base64.b64encode(screenshot_bytes).decode()
                mime = "image/jpeg" if screenshot_bytes[:2] == b'\xff\xd8' else "image/png"

                response = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": self._COMMENT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Viết comment cho video TikTok này:"},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime};base64,{img_b64}",
                                        "detail": "low",
                                    },
                                },
                            ],
                        },
                    ],
                    max_tokens=30,
                    temperature=0.8,
                )

                comment = response.choices[0].message.content.strip().strip('"\'')
                usage = response.usage
                if usage:
                    logger.info(
                        f"  🧠 [gpt-4o-fallback] comment: in={usage.prompt_tokens} "
                        f"out={usage.completion_tokens}"
                    )
                await self._step("ai_comment", f"[gpt-4o] {comment}")
                return comment

            except Exception as e:
                logger.warning(f"GPT-4o fallback failed: {e}")

        # --- Last resort: random pool ---
        await self._step("ai_fallback", "Both AI providers unavailable")
        pool = fallback_pool or self.TIKTOK_COMMENTS
        return random.choice(pool)

    async def _tiktok_comment(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 15.0,
        like_after_comment: float = 0.5,
        use_ai: bool = True,
        **_,
    ) -> ScriptResult:
        """Hybrid comment: script navigates, AI generates contextual comments.

        Flow:
        1. [Script] Open TikTok, browse feed
        2. [Script] Decide when to comment (random chance)
        3. [AI]     Capture screenshot → AI analyzes → generates relevant comment
        4. [Script] Open comment panel, type AI comment, send
        5. [Script] Swipe to next video

        Cost: ~1 AI call per comment (not per step). 5 comments = ~5 API calls.
        """
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        comments_done = 0
        used_comments = set()
        videos_since_last_comment = 0

        for i in range(count * 4):  # Browse many more videos than comments
            if comments_done >= count:
                break
            # Safety: prevent runaway loops (each comment ~15 steps)
            if self._step_num > 80:
                logger.warning(f"⚠️ Step limit reached ({self._step_num}), ending script")
                break

            # [Script] View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            # [Script] Only comment if skipped at least 2 videos since last comment
            should_comment = (
                videos_since_last_comment >= 2
                and random.random() < 0.4
            )

            if should_comment:
                tiktok = self._get_tiktok_controller()

                # [AI] Generate contextual comment from screenshot
                if use_ai:
                    comment_text = await self._ai_generate_comment(self.TIKTOK_COMMENTS)
                else:
                    # Fallback: random from pool
                    available = [c for c in self.TIKTOK_COMMENTS if c not in used_comments]
                    if not available:
                        available = list(self.TIKTOK_COMMENTS)
                        used_comments.clear()
                    comment_text = random.choice(available)
                    used_comments.add(comment_text)

                # [Controller] Tap comment icon (UI-hierarchy-based)
                tapped = await tiktok.tap_comment_icon(self._device)
                await self._step("tap", f"open comments ({'ui' if tapped else 'failed'})")
                if not tapped:
                    videos_since_last_comment += 1
                    await self._swipe_up()
                    continue
                await self._wait(1.5, 3, "comments loading")

                # [Script] Sometimes read others' comments first (40% chance)
                if random.random() < 0.4:
                    await self._wait(2, 5, "reading comments")

                # [Controller] Tap comment input field
                await tiktok.tap_comment_input(self._device)
                await self._step("tap", "comment input field")
                await self._wait(0.5, 1, "keyboard opening")

                # [Controller] Type the comment
                await tiktok.type_text(self._device, comment_text)
                await self._step("type", f"typed: {comment_text}")
                await self._wait(1, 3, "reviewing comment")

                # [Controller] Send comment
                await tiktok.send_comment(self._device)
                await self._step("key", f"sent comment [{comments_done+1}/{count}]")
                await self._wait(1, 2, "comment sent")

                # [Controller] Close comments
                await tiktok.close_panel(self._device)
                await self._step("key", "close comments")
                await self._wait(1, 2, "panel closing animation")

                # [Script] Maybe like the video too
                if random.random() < like_after_comment:
                    await tiktok.double_tap_like(self._device)
                    await self._step("double_tap", "liked")

                comments_done += 1
                videos_since_last_comment = 0
            else:
                videos_since_last_comment += 1

            # [Script] Swipe to next
            await self._swipe_up()

        mode_label = "hybrid AI+script" if use_ai else "script-only"
        return ScriptResult(
            success=True,
            reason=f"Commented on {comments_done}/{count} TikTok videos ({mode_label})",
            steps=self._step_num,
            step_log=self._step_log,
        )

    async def _tiktok_follow(
        self,
        count: int = 5,
        view_time_min: float = 5.0,
        view_time_max: float = 12.0,
        follow_chance: float = 0.3,
        **_,
    ) -> ScriptResult:
        """Follow TikTok accounts from feed: browse → tap avatar → follow."""
        await self._open_app("tiktok")
        await self._wait(3, 5, "app loading")

        follows_done = 0
        videos_since_last_follow = 0

        for i in range(count * 5):  # Browse many videos per follow
            if follows_done >= count:
                break

            # View current video
            await self._wait(view_time_min, view_time_max, f"watching video {i+1}")

            # Only follow if skipped some videos
            should_follow = (
                videos_since_last_follow >= 3
                and random.random() < follow_chance
            )

            if should_follow:
                tiktok = self._get_tiktok_controller()
                w, h = await self._adb.get_screen_size(self._device)

                # [Controller] Tap avatar to go to profile
                tapped = await tiktok.tap_avatar(self._device)
                await self._step("tap", f"open creator profile ({'ui' if tapped else 'fallback'})")
                if not tapped:
                    videos_since_last_follow += 1
                    await self._swipe_up()
                    continue
                await self._wait(2, 4, "profile loading")

                # Sometimes watch a video on profile (40% chance)
                if random.random() < 0.4:
                    vid_x = int(w * 0.2) + random.randint(-10, 10)
                    vid_y = int(h * 0.65) + random.randint(-10, 10)
                    await self._adb_cmd("shell", "input", "tap", str(vid_x), str(vid_y))
                    await self._step("tap", "watch profile video")
                    await self._wait(3, 8, "watching profile video")
                    await tiktok.close_panel(self._device)
                    await self._step("key", "back to profile")
                    await self._wait(1, 2, "returning to profile")

                # Sometimes decide NOT to follow (30% chance — natural)
                if random.random() < 0.3:
                    await self._step("skip", "decided not to follow")
                else:
                    # [Controller] Tap Follow button
                    followed = await tiktok.tap_follow(self._device)
                    if followed:
                        await self._step("tap", f"followed account [{follows_done+1}/{count}]")
                        follows_done += 1
                    else:
                        await self._step("skip", "follow button not found")
                    await self._wait(1, 2, "post-follow pause")

                # Go back to feed
                await tiktok.close_panel(self._device)
                await self._step("key", "back to feed")
                await self._wait(1, 3, "returning to feed")
                videos_since_last_follow = 0
            else:
                videos_since_last_follow += 1

            # Swipe to next
            await self._swipe_up()

        return ScriptResult(
            success=True,
            reason=f"Followed {follows_done}/{count} TikTok accounts",
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
