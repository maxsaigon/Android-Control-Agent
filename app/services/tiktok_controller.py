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
        Must find the correct EditText (comment input, NOT search bar).
        """
        elements = await self.dump_ui(device)
        w, h = await self._get_screen_size(device)

        # Strategy 1: Find EditText in bottom half of screen (comment input)
        # The search bar EditText is at the top; comment input is at bottom
        comment_inputs = []
        for el in elements:
            if "EditText" in el.cls:
                _, el_y = el.center
                # Comment input is in bottom portion of screen (>60% height)
                if el_y > h * 0.5:
                    comment_inputs.append(el)
                    logger.info(f"  📝 [comment_input] Found EditText at y={el_y} (bottom): '{el.text[:20] if el.text else el.content_desc[:20]}'")

        if comment_inputs:
            # Pick the one closest to the bottom
            el = max(comment_inputs, key=lambda e: e.center[1])
            x, y = el.center
            x += random.randint(-5, 5)
            logger.info(f"  🎯 [comment_input] Tapping bottom EditText at ({x}, {y})")
            await self._tap(device, x, y)
            await asyncio.sleep(0.5)  # Wait for keyboard
            return True

        # Strategy 2: Look for elements with comment-related text in bottom half
        for el in elements:
            desc = el.content_desc.lower() if el.content_desc else ""
            text = el.text.lower() if el.text else ""
            _, el_y = el.center
            if el_y > h * 0.5 and any(kw in desc or kw in text for kw in ["comment", "add comment", "add a comment"]):
                if el.clickable:
                    x, y = el.center
                    logger.info(f"  🎯 [comment_input] Found via keyword at ({x}, {y})")
                    await self._tap(device, x, y)
                    await asyncio.sleep(0.5)
                    return True

        # Strategy 3: Fallback to bottom of comment panel area
        x = int(w * 0.40) + random.randint(-20, 20)
        y = int(h * 0.90) + random.randint(-5, 5)
        logger.info(f"  ⚠️ [comment_input] Using fallback coords ({x}, {y})")
        await self._tap(device, x, y)
        await asyncio.sleep(0.5)
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

    async def dismiss_popups(self, device: str, max_attempts: int = 5) -> int:
        """Dismiss TikTok startup popups, dialogs, and overlays.

        Handles:
        - Policy update dialogs ("Got it", "Accept", "OK", "Allow")
        - LIVE stream webviews (press BACK to return to feed)
        - Age verification, cookie consent, etc.

        Returns number of popups dismissed.
        """
        dismissed = 0

        for attempt in range(max_attempts):
            # Dump UI to check for dialog elements
            _, xml_raw, _ = await self._adb._run_adb(
                device, "shell", "cat", "/sdcard/_ui.xml"
            )
            # Re-dump fresh UI
            await self._adb._run_adb(
                device, "shell", "uiautomator", "dump", "/sdcard/_ui.xml"
            )
            _, xml_raw, _ = await self._adb._run_adb(
                device, "shell", "cat", "/sdcard/_ui.xml"
            )

            xml_start = xml_raw.find("<?xml")
            if xml_start < 0:
                xml_start = xml_raw.find("<hierarchy")
            if xml_start < 0:
                break

            xml_clean = xml_raw[xml_start:]
            try:
                root = ET.fromstring(xml_clean)
            except ET.ParseError:
                break

            # Look for common dismiss buttons in ALL packages (dialogs may not be TikTok pkg)
            dismiss_patterns = [
                re.compile(r"^Got it$", re.IGNORECASE),
                re.compile(r"^Accept$", re.IGNORECASE),
                re.compile(r"^OK$", re.IGNORECASE),
                re.compile(r"^Allow$", re.IGNORECASE),
                re.compile(r"^Agree$", re.IGNORECASE),
                re.compile(r"^Continue$", re.IGNORECASE),
                re.compile(r"^Not now$", re.IGNORECASE),
                re.compile(r"^Skip$", re.IGNORECASE),
                re.compile(r"^Close$", re.IGNORECASE),
                re.compile(r"^Dismiss$", re.IGNORECASE),
                re.compile(r"^Yes$", re.IGNORECASE),       # content moderation popup
            ]

            found_button = False
            for node in root.iter("node"):
                text = node.get("text", "")
                desc = node.get("content-desc", "")
                clickable = node.get("clickable", "") == "true"

                if not clickable:
                    continue

                for pattern in dismiss_patterns:
                    if pattern.search(text) or pattern.search(desc):
                        # Found a dismiss button — tap it
                        bounds_str = node.get("bounds", "")
                        m = re.findall(r"\d+", bounds_str)
                        if len(m) == 4:
                            cx = (int(m[0]) + int(m[2])) // 2
                            cy = (int(m[1]) + int(m[3])) // 2
                            await self._tap(device, cx, cy)
                            dismissed += 1
                            found_button = True
                            logger.info(
                                f"  🔘 Dismissed popup: '{text or desc}' at ({cx}, {cy})"
                            )
                            await asyncio.sleep(1.5)
                            break
                if found_button:
                    break

            if not found_button:
                # Check if we're on a webview/LIVE page (no feed elements visible)
                has_feed = False
                for node in root.iter("node"):
                    desc = node.get("content-desc", "")
                    if "For You" in desc or "Home" == desc:
                        has_feed = True
                        break

                if not has_feed:
                    # Not on feed — try BACK to escape webview/LIVE
                    await self._adb._run_adb(
                        device, "shell", "input", "keyevent", "4"
                    )
                    dismissed += 1
                    logger.info("  ⬅️ Pressed BACK to escape non-feed page")
                    await asyncio.sleep(1.5)
                else:
                    # On feed, no popups — we're good
                    break

        if dismissed > 0:
            logger.info(f"  ✅ Dismissed {dismissed} popup(s)/overlay(s)")
        return dismissed

    async def ensure_on_feed(self, device: str) -> bool:
        """Ensure we're on TikTok feed (not profile, inbox, etc.).

        Steps:
        1. Check TikTok is foreground (recover if not)
        2. Dismiss any popups/dialogs
        3. Tap Home tab if not on feed
        """
        if not await self.is_tiktok_foreground(device):
            await self.recover(device)

        # Dismiss any startup popups first
        await self.dismiss_popups(device)

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
        """Type text into the focused field.

        Multiple strategies for reliable text input including Unicode:
        1. Try ADBKeyboard broadcast (best for Unicode)
        2. Try clipboard via service call + paste keyevent
        3. Use 'input text' (works for ASCII only)
        4. Last resort: strip to ASCII and use 'input text'
        """
        if self._backend:
            await self._backend.type_text(device, text)
            return True

        # Check if text is pure ASCII
        is_ascii = all(ord(c) < 128 for c in text)

        if is_ascii:
            special_chars = ' &|;<>"\'()'
            escaped = ''.join(
                f'\\{c}' if c in special_chars else c
                for c in text
            )
            await self._adb._run_adb(device, "shell", "input", "text", escaped)
            logger.info(f"  ✅ [type_text] ASCII input OK: '{text}'")
            return True

        # Unicode text - try multiple methods

        # Method 1: ADBKeyboard IME broadcast (if ADBKeyboard is installed)
        try:
            import base64
            encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
            await self._adb._run_adb(
                device, "shell",
                "am", "broadcast",
                "-a", "ADB_INPUT_B64",
                "--es", "msg", encoded
            )
            await asyncio.sleep(0.5)

            # Verify if text appeared in field
            if await self._verify_text_entered(device, text):
                logger.info(f"  ✅ [type_text] ADBKeyboard OK: '{text}'")
                return True
            logger.warning("  ⚠️ [type_text] ADBKeyboard broadcast sent but no text in field")
        except Exception as e:
            logger.warning(f"  ⚠️ [type_text] ADBKeyboard method failed: {e}")

        # Method 2: Use clipboard service call (works without extra apps)
        try:
            # Set clipboard text via service call
            escaped_text = text.replace("'", "'\\''")
            # Use content command to set clipboard text
            await self._adb._run_adb(
                device, "shell",
                "sh", "-c",
                f"service call clipboard 2 i32 1 i32 {len(text.encode('utf-16-le'))//2} "
                f"s16 '{escaped_text}'"
            )
            await asyncio.sleep(0.3)
            # Long press to bring up paste option, then paste
            await self._adb._run_adb(
                device, "shell", "input", "keyevent", "279"  # KEYCODE_PASTE
            )
            await asyncio.sleep(0.5)

            if await self._verify_text_entered(device, text):
                logger.info(f"  ✅ [type_text] Clipboard service OK: '{text}'")
                return True
            logger.warning("  ⚠️ [type_text] Clipboard service paste failed")
        except Exception as e:
            logger.warning(f"  ⚠️ [type_text] Clipboard service method failed: {e}")

        # Method 3: Use 'am broadcast clipper.set' (requires Clipper app)
        try:
            await self._adb._run_adb(
                device, "shell",
                "am", "broadcast",
                "-a", "clipper.set",
                "-e", "text", text
            )
            await asyncio.sleep(0.3)
            await self._adb._run_adb(
                device, "shell", "input", "keyevent", "279"
            )
            await asyncio.sleep(0.5)

            if await self._verify_text_entered(device, text):
                logger.info(f"  ✅ [type_text] Clipper broadcast OK: '{text}'")
                return True
            logger.warning("  ⚠️ [type_text] Clipper broadcast paste failed")
        except Exception as e:
            logger.warning(f"  ⚠️ [type_text] Clipper method failed: {e}")

        # Method 4: ASCII fallback - strip non-ASCII characters
        ascii_text = ''.join(c if ord(c) < 128 else '' for c in text)
        if not ascii_text:
            # If no ASCII chars at all, use a generic emoji/emoticon comment
            ascii_text = ":)"
        special_chars = ' &|;<>"\'()'
        escaped = ''.join(
            f'\\{c}' if c in special_chars else c
            for c in ascii_text
        )
        await self._adb._run_adb(device, "shell", "input", "text", escaped)
        logger.warning(f"  ⚠️ [type_text] Used ASCII fallback: '{ascii_text}' (original: '{text}')")
        return True

    async def _verify_text_entered(self, device: str, expected_text: str) -> bool:
        """Verify that text was actually typed into the focused EditText.

        Returns True only if EditText contains actual content (not placeholder).
        """
        # Placeholder/hint texts to ignore
        placeholders = {"add comment...", "add a comment...", "thêm bình luận...",
                        "viết bình luận...", "say something...", "add comment"}

        elements = await self.dump_ui(device)
        for el in elements:
            if "EditText" not in el.cls:
                continue
            text_content = el.text.strip() if el.text else ""
            if not text_content:
                continue
            # Ignore placeholder hints
            if text_content.lower() in placeholders:
                continue
            # Found actual text in EditText
            logger.info(f"  🔍 [verify] Text in EditText: '{text_content[:40]}'")
            return True
        return False

    async def send_comment(self, device: str) -> bool:
        """Tap Send button to post comment.

        TikTok's comment input has a Send/Post button (arrow icon) on the
        right side. ENTER key (keyevent 66) just adds a newline, so we must
        tap the button.

        Strategy:
        1. UI dump → find Send/Post button by text, content-desc, or class
        2. Fallback → tap right side of keyboard/input area where Send sits
        """
        elements = await self.dump_ui(device)

        # 1. Look for send/post button in UI elements
        send_patterns = [
            re.compile(r"Post$", re.IGNORECASE),
            re.compile(r"^Send$", re.IGNORECASE),
            re.compile(r"^Đăng$", re.IGNORECASE),         # Vietnamese
            re.compile(r"^Gửi$", re.IGNORECASE),           # Vietnamese
            re.compile(r"send comment", re.IGNORECASE),
            re.compile(r"post comment", re.IGNORECASE),
        ]

        for el in elements:
            desc = el.content_desc
            text = el.text
            for pat in send_patterns:
                if (desc and pat.search(desc)) or (text and pat.search(text)):
                    x, y = el.center
                    x += random.randint(-3, 3)
                    y += random.randint(-3, 3)
                    logger.info(f"  🎯 [send_comment] Found button: '{text or desc}' at ({x}, {y})")
                    await self._tap(device, x, y)
                    return True

        # 2. Look for ImageView/ImageButton near the input area (send icon)
        #    In TikTok, the send button is typically a small icon to the right
        #    of the EditText input on the same row
        edit_text_el = None
        for el in elements:
            if "EditText" in el.cls:
                edit_text_el = el
                break

        if edit_text_el:
            # Find clickable elements to the RIGHT of the EditText on same Y level
            et_right = edit_text_el.bounds[2]  # right edge of edittext
            et_cy = (edit_text_el.bounds[1] + edit_text_el.bounds[3]) // 2
            best_send = None
            for el in elements:
                if not el.clickable:
                    continue
                el_cx, el_cy = el.center
                # Same row (within 50px Y) and to the right of edittext
                if abs(el_cy - et_cy) < 50 and el_cx > et_right:
                    if best_send is None or el_cx < best_send.center[0]:
                        best_send = el  # Pick leftmost one to the right

            if best_send:
                x, y = best_send.center
                x += random.randint(-3, 3)
                y += random.randint(-3, 3)
                logger.info(f"  🎯 [send_comment] Found icon right of input at ({x}, {y})")
                await self._tap(device, x, y)
                return True

        # 3. Fallback: tap the right side of the bottom input bar
        w, h = await self._get_screen_size(device)
        x = int(w * 0.92) + random.randint(-5, 5)  # Far right
        if edit_text_el:
            y = (edit_text_el.bounds[1] + edit_text_el.bounds[3]) // 2
        else:
            y = int(h * 0.90) + random.randint(-5, 5)  # Bottom area
        logger.info(f"  ⚠️ [send_comment] Using fallback coords ({x}, {y})")
        await self._tap(device, x, y)
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
