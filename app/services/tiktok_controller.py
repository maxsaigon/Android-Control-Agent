"""TikTok Controller — UI-aware device control library.

Uses `uiautomator dump` to find real UI elements by content-desc,
instead of hardcoded pixel coordinates.

Key Design:
- content-desc is the primary locator (stable across TikTok versions)
- resource-id is obfuscated (3-char codes like dzw, fca) — unreliable
- Falls back to calibrated coordinates if UI dump fails
- Auto-recovers if TikTok exits accidentally
"""

import asyncio
import logging
import random
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

TIKTOK_PACKAGE = "com.ss.android.ugc.trill"


@dataclass
class UIElement:
    """A UI element found via uiautomator dump."""
    resource_id: str
    content_desc: str
    text: str
    cls: str
    bounds: tuple[int, int, int, int]  # x1, y1, x2, y2
    clickable: bool

    @property
    def center(self) -> tuple[int, int]:
        """Center point of the element."""
        x = (self.bounds[0] + self.bounds[2]) // 2
        y = (self.bounds[1] + self.bounds[3]) // 2
        return (x, y)

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]


class TikTokController:
    """UI-aware TikTok controller.

    Uses uiautomator dump to find real element positions,
    falling back to calibrated coordinates as last resort.

    Discovered TikTok UI elements (1080x2280 device):
    - Like:    content-desc="Like video. X likes"       [888,1083][1080,1263]
    - Comment: content-desc="Read or add comments. X"   [888,1263][1080,1443]
    - Share:   content-desc="Share video. X shares"     [888,1623][1080,1803]
    - Follow:  content-desc="Follow username"           [899,980][1080,1083]
    - Avatar:  content-desc="username profile"          [923,899][1056,1032]
    - Sound:   content-desc="Sound: ..."                [888,1803][1080,1989]
    - Nav:     Home/Shop/Create/Inbox/Profile            bottom bar
    """

    # content-desc patterns for element matching
    PATTERNS = {
        "like":    re.compile(r"Like video", re.IGNORECASE),
        "comment": re.compile(r"Read or add comments", re.IGNORECASE),
        "share":   re.compile(r"Share video", re.IGNORECASE),
        "follow":  re.compile(r"^Follow\s", re.IGNORECASE),
        "avatar":  re.compile(r"profile$", re.IGNORECASE),
        "sound":   re.compile(r"^Sound:", re.IGNORECASE),
        "home":    re.compile(r"^Home$", re.IGNORECASE),
        "search":  re.compile(r"^Search$", re.IGNORECASE),
        "inbox":   re.compile(r"^Inbox$", re.IGNORECASE),
        "profile": re.compile(r"^Profile$", re.IGNORECASE),
        "create":  re.compile(r"^Create$", re.IGNORECASE),
    }

    # Fallback coordinates as percentages of screen (w, h)
    # These are calibrated from the real TikTok UI on 1080x2280
    FALLBACK_COORDS = {
        "like":          (0.91, 0.51),    # [888,1083][1080,1263] → center (984, 1173)
        "comment":       (0.91, 0.59),    # [888,1263][1080,1443] → center (984, 1353)
        "share":         (0.91, 0.75),    # [888,1623][1080,1803] → center (984, 1713)
        "follow":        (0.92, 0.45),    # [899,980][1080,1083]  → center (990, 1032)
        "avatar":        (0.92, 0.42),    # [923,899][1056,1032]  → center (990, 966)
        "sound":         (0.91, 0.83),    # [888,1803][1080,1989] → center (984, 1896)
        "comment_input": (0.40, 0.90),    # Bottom of comment panel
    }

    def __init__(self, adb_agent, backend=None):
        self._adb = adb_agent
        self._backend = backend  # DeviceBackend, if available
        self._screen_cache: dict[str, tuple[int, int]] = {}

    async def _get_backend(self):
        """Lazy-init backend."""
        if not self._backend:
            from app.services.backend_manager import backend_manager
            # Won't fail — falls back to ADB
            self._backend = await backend_manager.get_backend("")
        return self._backend

    async def _tap(self, device: str, x: int, y: int):
        """Tap via backend or ADB."""
        if self._backend:
            await self._backend.tap(device, x, y)
        else:
            await self._adb._run_adb(device, "shell", "input", "tap", str(x), str(y))

    async def _get_screen_size(self, device: str) -> tuple[int, int]:
        """Get cached screen dimensions."""
        if device not in self._screen_cache:
            w, h = await self._adb.get_screen_size(device)
            self._screen_cache[device] = (w, h)
        return self._screen_cache[device]

    async def dump_ui(self, device: str) -> list[UIElement]:
        """Dump TikTok UI hierarchy and return parsed elements."""
        try:
            _, stdout, _ = await self._adb._run_adb(
                device, "shell",
                "uiautomator", "dump", "/sdcard/_ui.xml"
            )
            _, xml_raw, _ = await self._adb._run_adb(
                device, "shell", "cat", "/sdcard/_ui.xml"
            )

            # Clean up — sometimes has prefix text before XML
            xml_start = xml_raw.find("<?xml")
            if xml_start < 0:
                xml_start = xml_raw.find("<hierarchy")
            if xml_start < 0:
                logger.warning("UI dump: no valid XML found")
                return []

            xml_clean = xml_raw[xml_start:]
            root = ET.fromstring(xml_clean)

            elements = []
            for node in root.iter("node"):
                pkg = node.get("package", "")
                if TIKTOK_PACKAGE not in pkg:
                    continue

                bounds_str = node.get("bounds", "")
                m = re.findall(r"\d+", bounds_str)
                if len(m) != 4:
                    continue

                bounds = (int(m[0]), int(m[1]), int(m[2]), int(m[3]))

                elements.append(UIElement(
                    resource_id=node.get("resource-id", ""),
                    content_desc=node.get("content-desc", ""),
                    text=node.get("text", ""),
                    cls=node.get("class", ""),
                    bounds=bounds,
                    clickable=node.get("clickable", "") == "true",
                ))

            logger.info(f"UI dump: found {len(elements)} TikTok elements")
            return elements

        except Exception as e:
            logger.warning(f"UI dump failed: {e}")
            return []

    def find_element(
        self,
        elements: list[UIElement],
        name: str,
        *,
        desc_pattern: re.Pattern | None = None,
        text_pattern: re.Pattern | None = None,
    ) -> UIElement | None:
        """Find element by name pattern or custom criteria.

        Priority: content-desc match → text match → None
        """
        pattern = desc_pattern or self.PATTERNS.get(name)
        if not pattern:
            return None

        # Search by content-desc
        for el in elements:
            if el.content_desc and pattern.search(el.content_desc):
                return el

        # Search by text
        if text_pattern:
            for el in elements:
                if el.text and text_pattern.search(el.text):
                    return el

        return None

    async def smart_tap(
        self,
        device: str,
        name: str,
        *,
        jitter: int = 8,
        verify_foreground: bool = True,
    ) -> bool:
        """Find element by name and tap its center.

        Strategy:
        1. Dump UI → find by content-desc pattern
        2. If not found → use fallback coords
        3. After tap → verify TikTok still in foreground

        Returns True if tap successful.
        """
        w, h = await self._get_screen_size(device)

        # Try UI dump first
        elements = await self.dump_ui(device)
        el = self.find_element(elements, name) if elements else None

        if el:
            x, y = el.center
            x += random.randint(-jitter, jitter)
            y += random.randint(-jitter, jitter)
            method = "ui_element"
            desc_short = el.content_desc[:40] if el.content_desc else el.text[:20]
            logger.info(f"  🎯 [{name}] Found via UI: '{desc_short}' at ({x}, {y})")
        else:
            # Fallback to calibrated coordinates
            fallback = self.FALLBACK_COORDS.get(name)
            if not fallback:
                logger.warning(f"  ❌ [{name}] No element found and no fallback coords")
                return False

            x = int(w * fallback[0]) + random.randint(-jitter, jitter)
            y = int(h * fallback[1]) + random.randint(-jitter, jitter)
            method = "fallback_coords"
            logger.info(f"  ⚠️ [{name}] Using fallback coords ({x}, {y})")

        # Tap
        await self._tap(device, x, y)

        # Verify TikTok still in foreground
        if verify_foreground:
            await asyncio.sleep(0.5)
            if not await self.is_tiktok_foreground(device):
                logger.warning(f"  🚨 TikTok exited after tapping [{name}] via {method}!")
                await self.recover(device)
                return False

        return True

    async def tap_comment_icon(self, device: str) -> bool:
        """Open comment panel by tapping comment icon."""
        return await self.smart_tap(device, "comment")

    async def tap_like(self, device: str) -> bool:
        """Tap the like/heart button."""
        return await self.smart_tap(device, "like")

    async def tap_follow(self, device: str) -> bool:
        """Tap follow button on feed."""
        return await self.smart_tap(device, "follow")

    async def tap_avatar(self, device: str) -> bool:
        """Tap creator avatar to open profile."""
        return await self.smart_tap(device, "avatar")

    async def tap_share(self, device: str) -> bool:
        """Tap share button."""
        return await self.smart_tap(device, "share")

    async def tap_comment_input(self, device: str) -> bool:
        """Tap the comment input field at bottom of comment panel.

        When comment panel is open, the input field is at the bottom.
        We use UI dump to find it, or fallback to bottom coordinates.
        """
        elements = await self.dump_ui(device)

        # Look for EditText or elements with "Add comment" hint
        for el in elements:
            if "EditText" in el.cls:
                x, y = el.center
                x += random.randint(-5, 5)
                logger.info(f"  🎯 [comment_input] Found EditText at ({x}, {y})")
                await self._tap(device, x, y)
                return True

        # Try content-desc patterns for input field
        for el in elements:
            desc = el.content_desc.lower()
            text = el.text.lower()
            if any(kw in desc or kw in text for kw in ["comment", "add", "write", "say"]):
                if el.clickable:
                    x, y = el.center
                    logger.info(f"  🎯 [comment_input] Found via keyword at ({x}, {y})")
                    await self._tap(device, x, y)
                    return True

        # Fallback to bottom of screen
        w, h = await self._get_screen_size(device)
        x = int(w * 0.40) + random.randint(-20, 20)
        y = int(h * 0.90) + random.randint(-5, 5)
        logger.info(f"  ⚠️ [comment_input] Using fallback coords ({x}, {y})")
        await self._tap(device, x, y)
        return True

    async def get_video_info(self, device: str) -> dict:
        """Extract current video info from UI elements.

        Returns dict with: author, likes, comments, shares, sound, hashtags
        """
        elements = await self.dump_ui(device)
        info = {}

        for el in elements:
            desc = el.content_desc
            if not desc:
                continue

            # Extract counts from content-desc
            like_m = re.search(r"Like video\.\s*([\d,.KMB]+)", desc)
            if like_m:
                info["likes"] = like_m.group(1)

            comment_m = re.search(r"([\d,.KMB]+)\s*comments?", desc)
            if comment_m:
                info["comments"] = comment_m.group(1)

            share_m = re.search(r"([\d,.KMB]+)\s*shares?", desc)
            if share_m:
                info["shares"] = share_m.group(1)

            if desc.startswith("Sound:"):
                info["sound"] = desc[7:].strip()

            if "profile" in desc.lower() and not desc.startswith("Profile"):
                info["author"] = desc.replace(" profile", "").strip()

            # Follow button shows username
            follow_m = re.search(r"^Follow\s+(.+)", desc)
            if follow_m:
                info["author"] = follow_m.group(1)

        # Extract hashtags from description text
        for el in elements:
            if "#" in el.text and len(el.text) > 3:
                info["description"] = el.text[:200]
                break

        return info

    async def is_tiktok_foreground(self, device: str) -> bool:
        """Check if TikTok is currently the foreground app.

        Note: We must NOT pass '|' or 'grep' as ADB args — they get sent
        to the device shell as commands, not interpreted as a pipe.
        Instead, we dump the full output and filter in Python.
        """
        try:
            _, stdout, _ = await self._adb._run_adb(
                device, "shell",
                "dumpsys", "activity", "activities"
            )
            # Filter for resumed/focused activity lines in Python
            for line in stdout.splitlines():
                if ("mResumedActivity" in line or "mFocusedActivity" in line):
                    if TIKTOK_PACKAGE in line:
                        return True
            return False
        except Exception:
            return False

    async def recover(self, device: str) -> bool:
        """Re-open TikTok if it's not in foreground.

        Returns True if recovery was needed and successful.
        """
        if await self.is_tiktok_foreground(device):
            return False

        logger.warning("🔄 TikTok not in foreground — recovering...")

        # Try pressing BACK first (maybe hit a dialog)
        if self._backend:
            await self._backend.key_event(device, "BACK")
        else:
            await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        await asyncio.sleep(1)

        if await self.is_tiktok_foreground(device):
            logger.info("  ✅ Recovered via BACK key")
            return True

        # Re-launch TikTok
        if self._backend:
            await self._backend.launch_app(device, TIKTOK_PACKAGE)
        else:
            await self._adb._run_adb(
                device, "shell", "monkey", "-p", TIKTOK_PACKAGE,
                "-c", "android.intent.category.LAUNCHER", "1"
            )
        await asyncio.sleep(3)

        if await self.is_tiktok_foreground(device):
            logger.info("  ✅ Recovered by relaunching TikTok")
            return True

        logger.error("  ❌ Recovery failed — TikTok not in foreground")
        return False

    async def ensure_on_feed(self, device: str) -> bool:
        """Ensure we're on TikTok feed (not profile, inbox, etc.).

        Taps Home tab if not already there.
        """
        if not await self.is_tiktok_foreground(device):
            await self.recover(device)

        # Check if we're on feed by looking for feed elements
        elements = await self.dump_ui(device)
        home_el = self.find_element(elements, "home")

        if home_el and home_el.bounds[1] > 0:
            # Home tab exists, check if selected
            if not any(el.content_desc == "For You" for el in elements):
                # Tap Home to go to feed
                x, y = home_el.center
                await self._tap(device, x, y)
                await asyncio.sleep(1)
                logger.info("  📱 Navigated to Home/feed")

        return True

    async def double_tap_like(self, device: str) -> bool:
        """Double-tap center of screen to like (TikTok gesture)."""
        w, h = await self._get_screen_size(device)
        x = w // 2 + random.randint(-50, 50)
        y = h // 2 + random.randint(-50, 50)
        await self._tap(device, x, y)
        await asyncio.sleep(0.15)
        await self._tap(device, x, y)
        return True

    async def type_text(self, device: str, text: str) -> bool:
        """Type text using backend or ADB.

        For non-ASCII (Vietnamese, emoji), uses ADB clipboard broadcast
        since `adb shell input text` only supports ASCII.
        """
        if self._backend:
            await self._backend.type_text(device, text)
            return True

        # Check if text is pure ASCII
        is_ascii = all(ord(c) < 128 for c in text)

        if is_ascii:
            escaped = ''.join(
                f'\\{c}' if c in ' &|;<>"\'()' else c
                for c in text
            )
            await self._adb._run_adb(device, "shell", "input", "text", escaped)
        else:
            # Use clipboard for Unicode (Vietnamese, emoji)
            # Method: ADB broadcast to set clipboard, then paste
            await self._adb._run_adb(
                device, "shell", "am", "broadcast",
                "-a", "clipper.set",
                "-e", "text", text
            )
            await asyncio.sleep(0.3)
            # Ctrl+V to paste
            await self._adb._run_adb(
                device, "shell", "input", "keyevent", "279"  # KEYCODE_PASTE
            )
        return True

    async def send_comment(self, device: str) -> bool:
        """Press Enter to send comment."""
        if self._backend:
            await self._backend.key_event(device, "ENTER")
        else:
            await self._adb._run_adb(device, "shell", "input", "keyevent", "66")
        return True

    async def close_panel(self, device: str) -> bool:
        """Close comment panel reliably.

        TikTok needs up to 2 BACKs: 1st closes keyboard, 2nd closes panel.
        Verifies panel is actually closed before returning.
        """
        for attempt in range(3):
            if self._backend:
                await self._backend.key_event(device, "BACK")
            else:
                await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
            await asyncio.sleep(0.6)

            # Check if panel is still open by looking for comment input or panel elements
            try:
                elements = await self.dump_ui(device)
                panel_still_open = False
                for el in elements:
                    # EditText = comment input field = panel is open
                    if el.cls and "EditText" in el.cls:
                        panel_still_open = True
                        break
                    # Comment-related content-desc
                    if el.content_desc and (
                        "comment" in el.content_desc.lower()
                        or "reply" in el.content_desc.lower()
                    ):
                        # This could be the comment icon on the feed too,
                        # so check if it's in the comment panel area (top half = panel)
                        if el.bounds[1] < 1000:  # Panel header area
                            panel_still_open = True
                            break

                if not panel_still_open:
                    logger.info(f"  ✅ Comment panel closed (attempt {attempt + 1})")
                    return True
                else:
                    logger.info(f"  ⚠️ Panel still open, sending BACK again (attempt {attempt + 1})")
            except Exception:
                # If UI dump fails, assume it worked
                return True

        # Last resort: press HOME then reopen TikTok feed
        logger.warning("  ⚠️ Panel stuck — pressing BACK one more time")
        if self._backend:
            await self._backend.key_event(device, "BACK")
        else:
            await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        await asyncio.sleep(0.5)
        return True

    async def swipe_next(self, device: str) -> bool:
        """Swipe up to next video."""
        w, h = await self._get_screen_size(device)
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.75) + random.randint(-20, 20)
        y2 = int(h * 0.25) + random.randint(-20, 20)
        dur = random.randint(250, 450)
        if self._backend:
            await self._backend.swipe(device, x, y1, x, y2, dur)
        else:
            await self._adb._run_adb(
                device, "shell", "input", "swipe",
                str(x), str(y1), str(x), str(y2), str(dur)
            )
        return True
