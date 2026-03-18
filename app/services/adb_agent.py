"""
ADB Agent — Custom AI agent using pure ADB commands for Android control.

Works on Android 7.0+ (no Portal app needed).
Uses:
  - `adb shell uiautomator dump` for UI hierarchy extraction
  - `adb shell screencap` for screenshots
  - `adb shell input` for tap/swipe/text/keyevent
  - GPT-4o with vision for screen understanding and decision making
"""

import asyncio
import base64
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings, SCREENSHOTS_DIR

logger = logging.getLogger(__name__)


@dataclass
class UIElement:
    """Parsed UI element from uiautomator dump."""
    index: int
    text: str
    resource_id: str
    class_name: str
    package: str
    content_desc: str
    clickable: bool
    scrollable: bool
    bounds: tuple[int, int, int, int]  # x1, y1, x2, y2

    @property
    def center(self) -> tuple[int, int]:
        """Center point of the element."""
        return (
            (self.bounds[0] + self.bounds[2]) // 2,
            (self.bounds[1] + self.bounds[3]) // 2,
        )

    def __str__(self) -> str:
        parts = []
        if self.text:
            parts.append(f'"{self.text}"')
        if self.content_desc:
            parts.append(f'[{self.content_desc}]')
        if self.resource_id:
            short_id = self.resource_id.split("/")[-1] if "/" in self.resource_id else self.resource_id
            parts.append(f'#{short_id}')
        label = " ".join(parts) if parts else self.class_name.split(".")[-1]
        flags = ""
        if self.clickable:
            flags += "●"
        if self.scrollable:
            flags += "⇕"
        return f"[{self.index}]{flags} {label}"


@dataclass
class AgentStep:
    """A single step in the agent execution."""
    step_num: int
    action: str
    detail: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentResult:
    """Result of agent execution."""
    success: bool
    reason: str
    steps: int
    step_log: list[AgentStep] = field(default_factory=list)
    error: Optional[str] = None


class ADBAgent:
    """
    AI Agent that controls Android devices using pure ADB commands + LLM.

    Supports OpenAI (GPT-4o with vision), DeepSeek, and other OpenAI-compatible APIs.

    Flow per step:
    1. Capture screenshot
    2. Dump UI hierarchy
    3. Send screenshot + UI elements + task to LLM
    4. LLM returns next action (tap, swipe, type, etc.)
    5. Execute action via ADB
    6. Repeat until task is done or max_steps reached
    """

    # Name → package search keywords (multiple variants per app)
    PACKAGE_HINTS = {
        "tiktok": ["tiktok", "musically", "trill", "ugc"],
        "youtube": ["youtube"],
        "facebook": ["facebook", "katana"],
        "instagram": ["instagram"],
        "chrome": ["chrome"],
        "settings": ["settings"],
        "camera": ["camera"],
        "messages": ["messaging", "mms"],
        "phone": ["dialer", "phone"],
        "gmail": [".gm"],
        "shopee": ["shopee"],
        "maps": ["maps"],
        "whatsapp": ["whatsapp"],
        "telegram": ["telegram"],
        "zalo": ["zalo"],
        "line": ["line"],
        "twitter": ["twitter", "x.android"],
    }

    SYSTEM_PROMPT = (
        'Android agent. Screenshot has RED numbered labels. Reply with ONE JSON object.\n'
        '\n'
        'Format: {"action":"<name>", ...params}. Examples:\n'
        '{"action":"open_app","name":"TikTok"} - launch app by name\n'
        '{"action":"tap_text","text":"OK"} - tap by visible text\n'
        '{"action":"tap","index":5} - tap by RED number on screenshot\n'
        '{"action":"tap_id","id":"btn"} - tap by resource ID\n'
        '{"action":"swipe","direction":"up"} - swipe up/down/left/right\n'
        '{"action":"type","text":"hello"} - type text\n'
        '{"action":"key","keycode":"BACK"} - BACK/HOME/ENTER\n'
        '{"action":"wait","seconds":5} - wait N seconds\n'
        '{"action":"long_press","text":"item"} - long press\n'
        '{"action":"scroll_down"} / {"action":"scroll_up"}\n'
        '{"action":"complete","success":true,"reason":"done"}\n'
        '\n'
        'Prefer tap_text>tap_id>tap>tap_xy. Dismiss popups first. '
        'Check counts for progress. NEVER repeat same action 3x.'
    )

    def __init__(self, adb_path: str = None):
        self.adb_path = adb_path or settings.adb_path
        self._openai_client = None
        self._supports_vision = "openai" in settings.llm_base_url.lower() or "gpt" in settings.llm_model.lower()
        self._screen_dims: dict[str, tuple[int, int]] = {}  # device -> (w, h)
        self._package_cache: dict[str, dict[str, str]] = {}  # device -> {name -> package}

    async def resolve_package(self, device: str, name: str) -> str:
        """Resolve app name to package. Search installed packages on device."""
        name_lower = name.lower().strip()

        # 1. Check cache
        cache_key = f"{device}:{name_lower}"
        if device in self._package_cache and name_lower in self._package_cache[device]:
            return self._package_cache[device][name_lower]

        # 2. Get all installed packages from device
        _, result, _ = await self._run_adb(device, "shell", "pm", "list", "packages", "-3")
        # Also include system packages for things like settings, chrome
        _, result_sys, _ = await self._run_adb(device, "shell", "pm", "list", "packages")
        all_packages = set()
        for line in (result + "\n" + result_sys).strip().split("\n"):
            if line.startswith("package:"):
                all_packages.add(line.split(":", 1)[1].strip())

        # 3. Search using PACKAGE_HINTS keywords
        found = ""
        hints = self.PACKAGE_HINTS.get(name_lower, [name_lower])
        for pkg in all_packages:
            pkg_lower = pkg.lower()
            for hint in hints:
                if hint in pkg_lower:
                    found = pkg
                    break
            if found:
                break

        # 4. Fallback: direct name search in package string
        if not found:
            for pkg in all_packages:
                if name_lower in pkg.lower():
                    found = pkg
                    break

        # 5. Cache and return
        if found:
            if device not in self._package_cache:
                self._package_cache[device] = {}
            self._package_cache[device][name_lower] = found
            logger.info(f"  📦 Resolved '{name}' → {found}")
        else:
            logger.warning(f"  ❌ Could not find package for '{name}'")

        return found
    @property
    def openai_client(self):
        if self._openai_client is None:
            import openai
            self._openai_client = openai.AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.llm_base_url if settings.llm_base_url else None,
            )
        return self._openai_client

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
        return proc.returncode or 0, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()

    # --- Screen dimensions ---

    async def get_screen_size(self, device: str) -> tuple[int, int]:
        """Get device screen dimensions, cached per device."""
        if device not in self._screen_dims:
            _, out, _ = await self._run_adb(device, "shell", "wm", "size")
            match = re.search(r'(\d+)x(\d+)', out)
            if match:
                self._screen_dims[device] = (int(match.group(1)), int(match.group(2)))
            else:
                self._screen_dims[device] = (1080, 2400)  # fallback
        return self._screen_dims[device]

    # --- Screen capture (JPEG compressed) ---

    async def capture_screenshot(self, device: str, save_path: str = None) -> bytes:
        """Capture screenshot, compress to JPEG for reduced token cost."""
        code, _, err = await self._run_adb(device, "shell", "screencap", "-p", "/sdcard/screen.png")
        if code != 0:
            raise RuntimeError(f"screencap failed: {err}")

        # Pull the file
        if save_path is None:
            save_path = str(SCREENSHOTS_DIR / f"screen_{device.replace(':', '_')}.png")

        code, _, err = await self._run_adb(device, "pull", "/sdcard/screen.png", save_path)
        if code != 0:
            raise RuntimeError(f"pull screenshot failed: {err}")

        # Compress to JPEG — reduces ~80% token cost for GPT-4o vision
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
            self._last_pil_image = img  # Keep for annotation
            self._last_jpg_path = jpg_path
            return Path(jpg_path).read_bytes()
        except ImportError:
            logger.debug("Pillow not installed, using raw PNG")
            self._last_pil_image = None
            self._last_jpg_path = None
            return Path(save_path).read_bytes()

    def annotate_screenshot(
        self, screenshot_bytes: bytes, elements: list[UIElement]
    ) -> bytes:
        """Draw bounding boxes + index numbers on screenshot for AI clarity."""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io

            img = Image.open(io.BytesIO(screenshot_bytes))
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            draw = ImageDraw.Draw(img)

            # Scale factor if image was resized
            scale = img.width / 1080 if hasattr(self, '_last_pil_image') else 1.0

            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", max(12, int(14 * scale)))
            except Exception:
                font = ImageFont.load_default()

            # Only annotate clickable elements (limit to 30)
            clickable = [e for e in elements if e.clickable][:30]

            for elem in clickable:
                x1 = int(elem.bounds[0] * scale)
                y1 = int(elem.bounds[1] * scale)
                x2 = int(elem.bounds[2] * scale)
                y2 = int(elem.bounds[3] * scale)

                # Draw red bounding box
                draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)

                # Draw red circle with index number
                r = max(10, int(12 * scale))
                cx, cy = x1 - r, y1 - r
                draw.ellipse([cx, cy, cx + r * 2, cy + r * 2], fill=(255, 0, 0))
                draw.text((cx + r - 4, cy + 2), str(elem.index), fill=(255, 255, 255), font=font)

            # Save annotated version
            buf = io.BytesIO()
            img.save(buf, 'JPEG', quality=85)
            return buf.getvalue()

        except Exception as e:
            logger.debug(f"Annotation failed: {e}, using raw screenshot")
            return screenshot_bytes

    # --- UI hierarchy ---

    async def dump_ui(self, device: str) -> list[UIElement]:
        """Dump UI hierarchy and parse into UIElement list."""
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

    def _parse_ui_xml(self, xml_path: str) -> list[UIElement]:
        """Parse uiautomator XML dump into UIElement objects."""
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
            bounds = self._parse_bounds(bounds_str)
            if bounds is None:
                continue

            elem = UIElement(
                index=idx,
                text=node.get("text", ""),
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                package=node.get("package", ""),
                content_desc=node.get("content-desc", ""),
                clickable=node.get("clickable", "false") == "true",
                scrollable=node.get("scrollable", "false") == "true",
                bounds=bounds,
            )
            elements.append(elem)
            idx += 1

        return elements

    # --- Smart element finding (self-healing navigator) ---

    def find_by_text(self, elements: list[UIElement], text: str) -> Optional[UIElement]:
        """Find element by text or content_desc (case-insensitive, exact then partial)."""
        text_lower = text.lower()
        for e in elements:
            if e.text.lower() == text_lower or e.content_desc.lower() == text_lower:
                return e
        for e in elements:
            if text_lower in e.text.lower() or text_lower in e.content_desc.lower():
                return e
        return None

    def find_by_id(self, elements: list[UIElement], resource_id: str) -> Optional[UIElement]:
        """Find element by resource ID (partial match on the ID part after /)."""
        rid_lower = resource_id.lower()
        for e in elements:
            eid = e.resource_id.split('/')[-1].lower() if '/' in e.resource_id else e.resource_id.lower()
            if eid == rid_lower:
                return e
        for e in elements:
            eid = e.resource_id.split('/')[-1].lower() if '/' in e.resource_id else e.resource_id.lower()
            if rid_lower in eid:
                return e
        return None

    def find_element_smart(self, elements: list[UIElement], text: str = None,
                           resource_id: str = None) -> Optional[UIElement]:
        """Self-healing find: cascades text → resource_id → content_desc."""
        if text:
            found = self.find_by_text(elements, text)
            if found:
                return found
        if resource_id:
            found = self.find_by_id(elements, resource_id)
            if found:
                return found
        # Fallback: if text was given but not found, try as resource_id
        if text and not resource_id:
            found = self.find_by_id(elements, text)
            if found:
                logger.info(f"Self-healed: found '{text}' via resource_id")
                return found
        return None

    # --- Intelligent waiting (polling-based) ---

    async def wait_for_element(self, device: str, text: str, timeout: int = 15) -> Optional[UIElement]:
        """Poll UI tree until element with text appears."""
        elapsed = 0
        while elapsed < timeout:
            elements = await self.dump_ui(device)
            found = self.find_by_text(elements, text)
            if found:
                logger.info(f"✅ Found '{text}' at {found.center}")
                return found
            await asyncio.sleep(2)
            elapsed += 2
        logger.warning(f"⏰ Timeout: '{text}' not found after {timeout}s")
        return None

    async def wait_gone_element(self, device: str, text: str, timeout: int = 30) -> bool:
        """Poll UI tree until element with text disappears."""
        elapsed = 0
        while elapsed < timeout:
            elements = await self.dump_ui(device)
            found = self.find_by_text(elements, text)
            if not found:
                logger.info(f"✅ '{text}' disappeared")
                return True
            await asyncio.sleep(2)
            elapsed += 2
        logger.warning(f"⏰ Timeout: '{text}' still visible after {timeout}s")
        return False

    @staticmethod
    def _parse_bounds(bounds_str: str) -> Optional[tuple[int, int, int, int]]:
        """Parse '[x1,y1][x2,y2]' format."""
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
        if match:
            return tuple(int(x) for x in match.groups())  # type: ignore
        return None

    # --- Action execution ---

    async def execute_action(self, device: str, action: dict) -> str:
        """Execute a single action on the device. Returns description."""
        act = action.get("action", "")

        if act == "tap":
            idx = action.get("index", 0)
            # We'll need elements context — caller should provide
            x, y = action.get("x", 0), action.get("y", 0)
            await self._run_adb(device, "shell", "input", "tap", str(x), str(y))
            return f"Tapped at ({x}, {y})"

        elif act == "tap_xy":
            x, y = action["x"], action["y"]
            await self._run_adb(device, "shell", "input", "tap", str(x), str(y))
            return f"Tapped at ({x}, {y})"

        elif act == "tap_text":
            text = action.get("text", "")
            if not text:
                return "tap_text: no text specified"
            found = self.find_element_smart(action.get("_elements", []), text=text)
            if found:
                from app.services.behavior import human_behavior
                cx, cy = human_behavior.jitter_tap(*found.center)
                await self._run_adb(device, "shell", "input", "tap", str(cx), str(cy))
                return f"Tapped '{text}' at ({cx}, {cy})"
            else:
                return f"NOT_FOUND: '{text}'"

        elif act == "tap_id":
            rid = action.get("id", "")
            if not rid:
                return "tap_id: no id specified"
            found = self.find_by_id(action.get("_elements", []), rid)
            if found:
                from app.services.behavior import human_behavior
                cx, cy = human_behavior.jitter_tap(*found.center)
                await self._run_adb(device, "shell", "input", "tap", str(cx), str(cy))
                return f"Tapped id='{rid}' at ({cx}, {cy})"
            else:
                return f"NOT_FOUND: id='{rid}'"

        elif act == "long_press":
            text = action.get("text", "")
            if not text:
                return "long_press: no text specified"
            found = self.find_element_smart(action.get("_elements", []), text=text)
            if found:
                from app.services.behavior import human_behavior
                cx, cy = human_behavior.jitter_tap(*found.center)
                # Long press = swipe to same point with 1s duration
                await self._run_adb(
                    device, "shell", "input", "swipe",
                    str(cx), str(cy), str(cx), str(cy), "1000"
                )
                return f"Long pressed '{text}' at ({cx}, {cy})"
            else:
                return f"NOT_FOUND: '{text}'"

        elif act == "swipe":
            direction = action.get("direction", "")
            if direction:
                # Dynamic swipe based on screen size
                w, h = await self.get_screen_size(device)
                mid_x, mid_y = w // 2, h // 2
                margin = w // 5
                from app.services.behavior import human_behavior
                dur = human_behavior.jitter_swipe_duration(350)
                swipe_map = {
                    "left":  (w - margin, mid_y, margin, mid_y),
                    "right": (margin, mid_y, w - margin, mid_y),
                    "up":    (mid_x, h * 3 // 4, mid_x, h // 4),
                    "down":  (mid_x, h // 4, mid_x, h * 3 // 4),
                }
                coords = swipe_map.get(direction, (mid_x, h * 3 // 4, mid_x, h // 4))
                await self._run_adb(
                    device, "shell", "input", "swipe",
                    str(coords[0]), str(coords[1]), str(coords[2]), str(coords[3]), str(dur)
                )
                return f"Swiped {direction}"
            else:
                # Legacy: explicit coordinates
                x1, y1 = action["x1"], action["y1"]
                x2, y2 = action["x2"], action["y2"]
                dur = action.get("duration_ms", 300)
                await self._run_adb(
                    device, "shell", "input", "swipe",
                    str(x1), str(y1), str(x2), str(y2), str(dur)
                )
                return f"Swiped ({x1},{y1}) → ({x2},{y2})"

        elif act == "type":
            text = action["text"]
            # Proper escaping — handle spaces, special chars (android-adb-skill pattern)
            escaped = ''.join(
                f'\\{c}' if c in ' &|;()<>"\'\\\'\n' else c
                for c in text
            )
            await self._run_adb(device, "shell", "input", "text", escaped)
            return f"Typed: {text}"

        elif act == "key":
            keycode = action["keycode"]
            key_map = {
                "BACK": "4", "HOME": "3", "RECENT": "187",
                "ENTER": "66", "DELETE": "67", "TAB": "61",
                "VOLUME_UP": "24", "VOLUME_DOWN": "25",
                "POWER": "26", "MENU": "82",
            }
            code = key_map.get(keycode.upper(), keycode)
            await self._run_adb(device, "shell", "input", "keyevent", code)
            return f"Pressed key: {keycode}"

        elif act == "wait":
            seconds = action.get("seconds", 2)
            await asyncio.sleep(seconds)
            return f"Waited {seconds}s"

        elif act == "wait_for":
            text = action.get("text", "")
            timeout = action.get("timeout", 15)
            found = await self.wait_for_element(device, text, timeout)
            return f"Found '{text}'" if found else f"Timeout: '{text}' not found"

        elif act == "wait_gone":
            text = action.get("text", "")
            timeout = action.get("timeout", 30)
            gone = await self.wait_gone_element(device, text, timeout)
            return f"'{text}' disappeared" if gone else f"Timeout: '{text}' still visible"

        elif act == "open_app":
            # Support both name-based and package-based
            name = action.get("name", "")
            package = action.get("package", "")
            if name and not package:
                package = await self.resolve_package(device, name)
                if not package:
                    return f"App not found: {name}"
            # Kill app first to ensure clean start from home screen
            await self._run_adb(device, "shell", "am", "force-stop", package)
            await asyncio.sleep(0.5)
            await self._run_adb(
                device, "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1"
            )
            logger.info(f"  📦 force-stop + launch: {package}")
            return f"Opened: {name or package}"

        elif act == "scroll_down":
            w, h = await self.get_screen_size(device)
            mid_x = w // 2
            from app.services.behavior import human_behavior
            dur = human_behavior.jitter_swipe_duration(400)
            await self._run_adb(
                device, "shell", "input", "swipe",
                str(mid_x), str(h * 3 // 4), str(mid_x), str(h // 4), str(dur)
            )
            return "Scrolled down"

        elif act == "scroll_up":
            w, h = await self.get_screen_size(device)
            mid_x = w // 2
            from app.services.behavior import human_behavior
            dur = human_behavior.jitter_swipe_duration(400)
            await self._run_adb(
                device, "shell", "input", "swipe",
                str(mid_x), str(h // 4), str(mid_x), str(h * 3 // 4), str(dur)
            )
            return "Scrolled up"

        elif act == "complete":
            return f"Task complete: {action.get('reason', 'done')}"

        else:
            return f"Unknown action: {act}"

    # --- GPT-4o interaction ---

    async def ask_gpt4o(
        self,
        task: str,
        screenshot_bytes: bytes,
        ui_elements: list[UIElement],
        history: list[AgentStep],
        action_counts: dict[str, int] = None,
        max_steps: int = 20,
    ) -> dict:
        """Ask GPT-4o what action to take next."""
        # Filter to useful elements only — clickable or has text/desc (max 25)
        useful = [e for e in ui_elements if e.clickable or e.text or e.content_desc]
        elements_text = "\n".join(str(e) for e in useful[:25])

        # Compact history — last 5 steps, short format
        hist = ""
        if history:
            def _short(s: AgentStep) -> str:
                # Extract key info: "5:tap_text 'TikTok'"
                d = s.detail.split(" at ")[0] if " at " in s.detail else s.detail[:40]
                return f"{s.step_num}:{s.action} {d}"
            hist = "\nH:" + "||".join(_short(s) for s in history[-5:])

        # Compact counter
        ctr = ""
        if action_counts:
            ctr = "\n📊" + ",".join(f"{k}:{v}" for k, v in sorted(action_counts.items()) if v > 0)

        user_message = (
            f"Task:{task}\n"
            f"UI:{elements_text}{hist}{ctr}\n"
            f"[{len(history)+1}/{max_steps}] Next action?"
        )

        # Build message content
        if self._supports_vision:
            # Vision-capable model: send screenshot
            img_b64 = base64.b64encode(screenshot_bytes).decode()
            # Detect format from bytes (JPEG starts with FFD8)
            mime = "image/jpeg" if screenshot_bytes[:2] == b'\xff\xd8' else "image/png"
            user_content = [
                {"type": "text", "text": user_message},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{img_b64}",
                        "detail": "low",
                    },
                },
            ]
        else:
            # Text-only model: rely on UI elements only
            user_content = user_message

        response = await self.openai_client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=150,  # Actions are short JSON — 150 is plenty
            temperature=0.3,
        )

        # Log token usage
        usage = response.usage
        if usage:
            logger.info(
                f"  💰 Tokens: in={usage.prompt_tokens} out={usage.completion_tokens} "
                f"total={usage.total_tokens}"
            )

        # Parse response
        content = response.choices[0].message.content or "{}"
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in GPT response: {content[:200]}")
                return {"action": "wait", "seconds": 2}
        else:
            logger.warning(f"Could not parse GPT response: {content[:200]}")
            # Return wait instead of complete-fail — give AI another chance
            return {"action": "wait", "seconds": 2}

    # --- Main execution loop ---

    async def run(
        self,
        device: str,
        task: str,
        max_steps: int = 20,
        on_step: callable = None,
    ) -> AgentResult:
        """
        Execute a task on the device using the AI agent loop.

        Args:
            device: ADB device target (e.g., "192.168.1.150:5555")
            task: Natural language task description
            max_steps: Maximum number of steps
            on_step: Optional callback(step: AgentStep) for progress

        Returns:
            AgentResult with success/failure status and step log
        """
        steps_log: list[AgentStep] = []
        action_counts: dict[str, int] = {}  # Track all action types
        logger.info(f"🤖 Starting task on {device}: {task}")

        for step_num in range(1, max_steps + 1):
            try:
                # 1. Capture screenshot
                screenshot_path = str(
                    SCREENSHOTS_DIR / f"step_{device.replace(':', '_')}_{step_num}.png"
                )
                screenshot_bytes = await self.capture_screenshot(device, screenshot_path)

                # 2. Dump UI hierarchy
                ui_elements = await self.dump_ui(device)

                # 2.5 Annotate screenshot with red boxes + numbers
                annotated_bytes = self.annotate_screenshot(screenshot_bytes, ui_elements)

                # 3. Detect stuck loop — inject warning or force-break
                stuck_warning = ""
                stuck_count = 0
                if len(steps_log) >= 3:
                    # Count consecutive same-type actions from the end
                    last_action = steps_log[-1].action
                    for s in reversed(steps_log):
                        if s.action == last_action:
                            stuck_count += 1
                        else:
                            break

                    if stuck_count >= 5:
                        # FORCE BREAK: override AI decision with BACK key
                        logger.warning(
                            f"🚨 Force-breaking stuck loop at step {step_num}: "
                            f"{stuck_count}x {last_action} — pressing BACK"
                        )
                        action = {"action": "key", "keycode": "BACK"}
                        detail = await self.execute_action(device, action)
                        step = AgentStep(
                            step_num=step_num, action="key", detail="FORCE BREAK: " + detail
                        )
                        steps_log.append(step)
                        if on_step:
                            await on_step(step) if asyncio.iscoroutinefunction(on_step) else on_step(step)
                        from app.services.behavior import human_behavior
                        await human_behavior.random_delay("key")
                        continue  # Skip AI call, go to next step

                    elif stuck_count >= 3:
                        stuck_warning = (
                            "\n\n⚠️ WARNING: You are STUCK in a loop! "
                            f"The last {stuck_count} actions were all '{last_action}'. "
                            "You MUST try a completely DIFFERENT action type NOW. "
                            "Try: swipe up on the screen, press BACK key, "
                            "or report the task as complete with success=false."
                        )
                        logger.warning(
                            f"🔄 Stuck loop detected at step {step_num}: "
                            f"{stuck_count}x {last_action}"
                        )

                # 4. Ask GPT-4o (with stuck warning + action counts)
                action = await self.ask_gpt4o(
                    task + stuck_warning, annotated_bytes, ui_elements, steps_log,
                    action_counts=action_counts, max_steps=max_steps
                )
                logger.info(f"  Step {step_num}: {action}")

                # 5. Resolve tap by index → coordinates + anti-detection jitter
                from app.services.behavior import human_behavior
                if action.get("action") == "tap" and "index" in action:
                    idx = action["index"]
                    if 0 <= idx < len(ui_elements):
                        cx, cy = ui_elements[idx].center
                        action["x"], action["y"] = human_behavior.jitter_tap(cx, cy)
                    else:
                        logger.warning(f"Element index {idx} out of range")
                        action["x"] = 540
                        action["y"] = 960

                # 5.5 Inject UI elements for text/id-based actions
                if action.get("action") in ("tap_text", "tap_id", "long_press"):
                    action["_elements"] = ui_elements

                # 6. Execute action
                detail = await self.execute_action(device, action)
                act_type = action.get("action", "unknown")
                # Update action counter
                if act_type == "swipe":
                    direction = action.get("direction", "unknown")
                    counter_key = f"swipe_{direction}"
                else:
                    counter_key = act_type
                action_counts[counter_key] = action_counts.get(counter_key, 0) + 1

                step = AgentStep(step_num=step_num, action=act_type, detail=detail)
                steps_log.append(step)

                if on_step:
                    await on_step(step) if asyncio.iscoroutinefunction(on_step) else on_step(step)

                # 6. Check if task is complete
                if action.get("action") == "complete":
                    success = action.get("success", True)
                    reason = action.get("reason", "Task completed")
                    # Return to home screen — natural behavior after finishing
                    await self._run_adb(device, "shell", "input", "keyevent", "3")
                    logger.info(f"✅ Task {'succeeded' if success else 'failed'}: {reason} → HOME")
                    return AgentResult(
                        success=success,
                        reason=reason,
                        steps=step_num,
                        step_log=steps_log,
                    )

                # Anti-detection: randomized delay between steps
                await human_behavior.random_delay(action.get('action', 'default'))

            except Exception as e:
                logger.exception(f"Error at step {step_num}")
                step = AgentStep(step_num=step_num, action="error", detail=str(e))
                steps_log.append(step)
                await self._run_adb(device, "shell", "input", "keyevent", "3")
                return AgentResult(
                    success=False,
                    reason="Execution error",
                    steps=step_num,
                    step_log=steps_log,
                    error=str(e),
                )

        await self._run_adb(device, "shell", "input", "keyevent", "3")
        return AgentResult(
            success=False,
            reason=f"Max steps ({max_steps}) reached without completing task",
            steps=max_steps,
            step_log=steps_log,
        )


# Singleton
adb_agent = ADBAgent()
