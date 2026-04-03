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
import hashlib
import json
import logging
import os
import random
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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
        "create":  re.compile(r"^(Create|Tạo)$", re.IGNORECASE),
        "upload_gallery": re.compile(r"^(Upload|Tải lên)$", re.IGNORECASE),
        "next_btn": re.compile(r"^(Next|Tiếp)$", re.IGNORECASE),
        "post_btn": re.compile(r"^(Post|Đăng)$", re.IGNORECASE),
    }
    DURATION_PATTERN = re.compile(r"^\d{1,2}:\d{2}$")

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
        "create":        (0.50, 0.88),    # Nav bar (+) button
        "upload_gallery":(0.82, 0.75),    # Camera screen gallery thumbnail
        "video_checkbox":(0.28, 0.19),    # First video checkbox in gallery
        "next_btn":      (0.74, 0.87),    # Next button
        "post_btn":      (0.74, 0.87),    # Post button
    }

    def __init__(self, adb_agent, backend=None, device_hint: str = ""):
        self._adb = adb_agent
        self._backend = backend  # DeviceBackend, if available
        self._device_hint = device_hint
        self._screen_cache: dict[str, tuple[int, int]] = {}
        self._helper_service_issue: dict[str, str] = {}

    @staticmethod
    def _is_service_not_running_error(exc: Exception) -> bool:
        return "service not running" in str(exc).lower()

    async def _record_backend_issue(self, device: str, exc: Exception) -> None:
        """Track helper service dropouts so callers can trigger self-healing."""
        if not self._is_service_not_running_error(exc):
            return
        self._helper_service_issue[device] = str(exc)
        logger.warning("  🚨 [helper] Accessibility service degraded on %s: %s", device, exc)

    def has_helper_service_issue(self, device: str) -> bool:
        return device in self._helper_service_issue

    def clear_helper_service_issue(self, device: str) -> None:
        self._helper_service_issue.pop(device, None)

    async def _get_backend(self, device: str | None = None):
        """Lazy-init backend."""
        if not self._backend:
            from app.services.backend_manager import backend_manager
            # Won't fail — falls back to ADB
            target_device = device or self._device_hint
            self._backend = await backend_manager.get_backend(target_device)
        return self._backend

    async def recover_helper_service(self, device: str) -> bool:
        """Re-enable helper accessibility + websocket service after runtime dropouts."""
        from app.services.backend_manager import backend_manager

        logger.warning("  🔄 [helper] Attempting helper service recovery on %s", device)
        service_component = (
            "com.androidcontrol.helper/"
            "com.androidcontrol.helper.HelperAccessibilityService"
        )
        ws_component = "com.androidcontrol.helper/.WebSocketService"
        previous_foreground = ""

        try:
            try:
                previous_foreground = await self.get_foreground_app(device)
            except Exception:
                previous_foreground = ""

            try:
                await backend_manager.accessibility.disconnect(device)
            except Exception:
                pass

            backend_manager.clear_cache(device)
            self._backend = None

            await self._adb._run_adb(
                device,
                "shell",
                "settings",
                "put",
                "secure",
                "enabled_accessibility_services",
                service_component,
            )
            await self._adb._run_adb(
                device,
                "shell",
                "settings",
                "put",
                "secure",
                "accessibility_enabled",
                "1",
            )
            await self._adb._run_adb(
                device,
                "shell",
                "am",
                "start-foreground-service",
                "-n",
                ws_component,
            )
            await self._adb._run_adb(
                device,
                "shell",
                "monkey",
                "-p",
                "com.androidcontrol.helper",
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            )

            for _ in range(6):
                await asyncio.sleep(1.0)
                try:
                    if await backend_manager.accessibility.ping(device):
                        backend_manager.set_backend(device, "accessibility")
                        self._backend = backend_manager.accessibility
                        current_foreground = ""
                        try:
                            current_foreground = await self.get_foreground_app(device)
                        except Exception:
                            current_foreground = ""

                        if (
                            "com.androidcontrol.helper" in (current_foreground or "")
                            or TIKTOK_PACKAGE in (previous_foreground or "")
                        ):
                            logger.info(
                                "  🔁 [helper] Restoring TikTok foreground after helper recovery"
                            )
                            await self.recover(device)
                        self.clear_helper_service_issue(device)
                        logger.info("  ✅ [helper] Accessibility service recovered on %s", device)
                        return True
                except Exception:
                    continue
        except Exception as exc:
            logger.warning("  ⚠️ [helper] Recovery command failed on %s: %s", device, exc)

        logger.error("  ❌ [helper] Accessibility service recovery failed on %s", device)
        return False

    async def _tap(self, device: str, x: int, y: int):
        """Tap via backend (preferred) or ADB (fallback)."""
        await self._get_backend(device)
        if self._backend:
            try:
                await self._backend.tap(device, x, y)
                return
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [tap] Backend failed, fallback to ADB: {e}")
                self._backend = None

        # FALLBACK: ADB — when Accessibility backend unavailable/unhealthy
        await self._adb._run_adb(device, "shell", "input", "tap", str(x), str(y))

    async def _swipe(
        self,
        device: str,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
    ):
        """Swipe via backend (preferred) or ADB (fallback)."""
        await self._get_backend(device)
        if self._backend:
            try:
                await self._backend.swipe(device, x1, y1, x2, y2, duration_ms)
                return
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [swipe] Backend failed, fallback to ADB: {e}")
                self._backend = None

        await self._adb._run_adb(
            device,
            "shell",
            "input",
            "swipe",
            str(x1),
            str(y1),
            str(x2),
            str(y2),
            str(duration_ms),
        )

    async def _get_screen_size(self, device: str) -> tuple[int, int]:
        """Get cached screen dimensions (Accessibility preferred, ADB fallback)."""
        if device not in self._screen_cache:
            await self._get_backend(device)
            if self._backend:
                try:
                    w, h = await self._backend.get_screen_size(device)
                    self._screen_cache[device] = (w, h)
                    return (w, h)
                except Exception as e:
                    await self._record_backend_issue(device, e)
                    logger.warning(
                        f"  ⚠️ [screen_size] Backend failed, fallback raw ADB: {e}"
                    )
                    self._backend = None
            # FALLBACK: raw ADB command (bypass ADBAgent backend auto-routing)
            _, out, err = await self._adb._run_adb(device, "shell", "wm", "size")
            text = out or err
            m = re.search(r"(\d+)\s*x\s*(\d+)", text)
            if not m:
                logger.warning(
                    f"  ⚠️ [screen_size] Could not parse wm size output: {text}"
                )
                w, h = 1080, 2280
            else:
                w, h = int(m.group(1)), int(m.group(2))
            self._screen_cache[device] = (w, h)
        return self._screen_cache[device]

    async def dump_ui(self, device: str) -> list[UIElement]:
        """Dump TikTok UI hierarchy and return parsed elements.

        TODO: [ACCESSIBILITY-MIGRATE] Use backend.get_ui_tree() instead of
        uiautomator dump. Requires format adapter: Accessibility returns JSON
        with flat list of UINode objects, this method returns UIElement from
        XML parsing. Both contain same info (text, content_desc, bounds, etc.)
        but in different data classes.
        """
        async def _dump_via_accessibility() -> list[UIElement]:
            try:
                from app.services.backend_manager import backend_manager

                if not await backend_manager.accessibility.ping(device):
                    return []
                nodes = await backend_manager.accessibility.get_ui_tree(device)
            except Exception as backend_error:
                await self._record_backend_issue(device, backend_error)
                logger.warning(f"UI tree fallback failed: {backend_error}")
                return []

            elements = [
                UIElement(
                    resource_id=node.resource_id,
                    content_desc=node.content_desc,
                    text=node.text,
                    cls=node.class_name,
                    bounds=node.bounds,
                    clickable=node.clickable,
                )
                for node in nodes
                if TIKTOK_PACKAGE in (node.package or "")
            ]
            logger.info(f"UI tree fallback: found {len(elements)} TikTok elements")
            return elements

        try:
            await asyncio.wait_for(
                self._adb._run_adb(
                    device, "shell",
                    "uiautomator", "dump", "/sdcard/_ui.xml"
                ),
                timeout=8.0,
            )
            _, xml_raw, _ = await asyncio.wait_for(
                self._adb._run_adb(
                    device, "shell", "cat", "/sdcard/_ui.xml"
                ),
                timeout=8.0,
            )

            # Clean up — sometimes has prefix text before XML
            xml_start = xml_raw.find("<?xml")
            if xml_start < 0:
                xml_start = xml_raw.find("<hierarchy")
            if xml_start < 0:
                logger.warning("UI dump: no valid XML found")
                return await _dump_via_accessibility()

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

            if elements:
                logger.info(f"UI dump: found {len(elements)} TikTok elements")
                return elements

            logger.warning("UI dump returned 0 TikTok elements; trying accessibility tree")
            return await _dump_via_accessibility()

        except Exception as e:
            logger.warning(f"UI dump failed: {e}")
            return await _dump_via_accessibility()

    async def dump_ui_xml(self, device: str, save_path: str | None = None) -> str:
        """Dump raw UI XML and optionally persist it locally."""
        try:
            await asyncio.wait_for(
                self._adb._run_adb(
                    device, "shell", "uiautomator", "dump", "/sdcard/_ui.xml"
                ),
                timeout=8.0,
            )
            _, xml_raw, _ = await asyncio.wait_for(
                self._adb._run_adb(
                    device, "shell", "cat", "/sdcard/_ui.xml"
                ),
                timeout=8.0,
            )

            xml_start = xml_raw.find("<?xml")
            if xml_start < 0:
                xml_start = xml_raw.find("<hierarchy")
            if xml_start < 0:
                return ""

            xml_clean = xml_raw[xml_start:]
            if save_path:
                Path(save_path).write_text(xml_clean, encoding="utf-8")
            return xml_clean
        except Exception as e:
            logger.warning(f"UI XML dump failed: {e}")
            return ""

    async def _dump_all_ui_nodes(self, device: str) -> list[dict]:
        """Dump UI nodes from all packages for cross-app popup detection."""
        xml_raw = await self.dump_ui_xml(device)
        if not xml_raw:
            try:
                from app.services.backend_manager import backend_manager

                if await backend_manager.accessibility.ping(device):
                    nodes = await backend_manager.accessibility.get_ui_tree(device)
                    all_nodes = [
                        {
                            "text": (node.text or "").strip(),
                            "desc": (node.content_desc or "").strip(),
                            "pkg": node.package or "",
                            "cls": node.class_name or "",
                            "clickable": bool(node.clickable),
                            "bounds": node.bounds,
                        }
                        for node in nodes
                    ]
                    logger.info(
                        "UI node fallback via accessibility: found %s nodes",
                        len(all_nodes),
                    )
                    return all_nodes
            except Exception as backend_error:
                await self._record_backend_issue(device, backend_error)
                logger.warning("UI node fallback failed: %s", backend_error)
            return []

        try:
            root = ET.fromstring(xml_raw)
        except ET.ParseError:
            return []

        nodes = []
        for node in root.iter("node"):
            bounds_str = node.get("bounds", "")
            m = re.findall(r"\d+", bounds_str)
            bounds = None
            if len(m) == 4:
                bounds = (int(m[0]), int(m[1]), int(m[2]), int(m[3]))
            nodes.append(
                {
                    "text": (node.get("text", "") or "").strip(),
                    "desc": (node.get("content-desc", "") or "").strip(),
                    "pkg": node.get("package", ""),
                    "cls": node.get("class", ""),
                    "clickable": node.get("clickable", "") == "true",
                    "bounds": bounds,
                }
            )
        return nodes

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

    def _contains_bounds(
        self,
        outer: tuple[int, int, int, int],
        inner: tuple[int, int, int, int],
    ) -> bool:
        return (
            outer[0] <= inner[0]
            and outer[1] <= inner[1]
            and outer[2] >= inner[2]
            and outer[3] >= inner[3]
        )

    def _bounds_area(self, bounds: tuple[int, int, int, int]) -> int:
        return max(0, bounds[2] - bounds[0]) * max(0, bounds[3] - bounds[1])

    def _find_smallest_clickable_container(
        self,
        elements: list[UIElement],
        target: UIElement,
        *,
        require_long_clickable: bool = False,
    ) -> UIElement | None:
        candidates: list[UIElement] = []
        for el in elements:
            if not el.clickable:
                continue
            if require_long_clickable and el.cls != "android.widget.FrameLayout":
                continue
            if self._contains_bounds(el.bounds, target.bounds):
                candidates.append(el)

        if not candidates:
            return None

        return min(candidates, key=lambda el: self._bounds_area(el.bounds))

    def _matches_any_pattern(
        self,
        text: str,
        patterns: tuple[re.Pattern[str], ...],
    ) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    def _fold_text(self, value: str) -> str:
        """Fold text for accent-insensitive matching."""
        lowered = (value or "").lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        folded = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return folded.replace("đ", "d")

    def _normalize_comment_text(self, value: str) -> str:
        """Normalize comment text for reliable cross-checking."""
        folded = self._fold_text(value or "")
        folded = re.sub(r"\s+", " ", folded)
        return folded.strip(" \t\r\n.,!?:;-'\"`()[]{}")

    def _normalize_fingerprint_text(self, value: str) -> str:
        """Normalize visible feed text for stable video fingerprinting."""
        folded = self._fold_text(value or "")
        folded = re.sub(r"\s+", " ", folded)
        folded = re.sub(r"[^0-9a-z# ]+", " ", folded)
        folded = re.sub(r"\s+", " ", folded)
        return folded.strip()

    def _collect_feed_signature_texts(
        self,
        elements: list[UIElement],
        *,
        max_count: int = 6,
    ) -> list[str]:
        """Collect stable visible feed texts that help fingerprint a video."""
        ignore_tokens = (
            "home", "shop", "friends", "inbox", "profile",
            "follow", "like video", "read or add comments", "share video",
            "add comment", "replying to", "comment history",
            "newest to oldest", "oldest to newest", "totally awesome",
            "first comment",
        )

        signatures: list[str] = []
        seen = set()
        for el in elements:
            if "EditText" in el.cls:
                continue

            x1, y1, x2, y2 = el.bounds
            if y1 < 140 or y2 > 2060:
                continue
            if x1 > 920:
                continue

            for raw in (el.text or "", el.content_desc or ""):
                cleaned = self._normalize_fingerprint_text(raw)
                if len(cleaned) < 4:
                    continue
                if cleaned in seen:
                    continue
                if re.fullmatch(r"[\d,.kmb ]+", cleaned):
                    continue
                if any(token in cleaned for token in ignore_tokens):
                    continue
                seen.add(cleaned)
                signatures.append(cleaned[:120])
                if len(signatures) >= max_count:
                    return signatures
        return signatures

    def _extract_video_info_from_elements(self, elements: list[UIElement]) -> dict:
        """Extract visible current-video metadata from a feed screen."""
        info = {}

        for el in elements:
            desc = el.content_desc
            if not desc:
                continue

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

            follow_m = re.search(r"^Follow\s+(.+)", desc)
            if follow_m:
                info["author"] = follow_m.group(1)

        for el in elements:
            if "#" in el.text and len(el.text) > 3:
                info["description"] = el.text[:200]
                break

        return info

    def build_video_fingerprint(
        self,
        elements: list[UIElement],
        *,
        video_info: dict | None = None,
    ) -> str:
        """Build a stable fingerprint for the currently visible feed item."""
        info = dict(video_info or {})
        if not info:
            info = self._extract_video_info_from_elements(elements)

        parts: list[str] = []
        for key in ("author", "description", "sound", "likes", "comments", "shares"):
            value = self._normalize_fingerprint_text(str(info.get(key) or ""))
            if value:
                parts.append(f"{key}:{value[:160]}")

        for text in self._collect_feed_signature_texts(elements):
            parts.append(f"text:{text[:160]}")

        unique_parts: list[str] = []
        seen = set()
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            unique_parts.append(part)

        meaningful_parts = [
            part for part in unique_parts
            if part.startswith(("author:", "description:", "sound:", "text:"))
        ]
        if len(meaningful_parts) < 2:
            return ""

        digest = hashlib.sha1("|".join(unique_parts).encode("utf-8")).hexdigest()[:16]
        return digest

    def _expected_text_tokens(self, expected_text: str) -> list[str]:
        """Build stable verification tokens from expected input text."""
        if not expected_text:
            return []

        tokens: list[str] = []

        # Prioritize hashtags — they are highly stable and visible in caption field.
        for token in re.findall(r"#[^\s#]+", expected_text, flags=re.UNICODE):
            cleaned = token.strip()
            if cleaned:
                tokens.append(cleaned)

        # Add meaningful words for fallback verification.
        for token in re.findall(r"[0-9A-Za-zÀ-ỹ_]{3,}", expected_text, flags=re.UNICODE):
            cleaned = token.strip()
            if not cleaned or cleaned.startswith("#"):
                continue
            tokens.append(cleaned)

        # Keep order, remove duplicates, and cap for speed.
        deduped: list[str] = []
        seen = set()
        for token in tokens:
            folded = self._fold_text(token)
            if not folded or folded in seen:
                continue
            seen.add(folded)
            deduped.append(token)
            if len(deduped) >= 8:
                break
        return deduped

    def _collect_comment_panel_texts(
        self,
        elements: list[UIElement],
        *,
        max_count: int = 25,
    ) -> list[str]:
        """Collect visible comment-like texts from the open comment panel."""
        ignore_patterns = {
            "reply", "replies", "like", "likes", "report",
            "view more", "see more", "hide", "got it",
            "add comment", "newest", "oldest", "most relevant",
        }

        texts: list[str] = []
        for el in elements:
            text = el.text.strip() if el.text else ""
            if not text:
                continue

            if len(text) <= 3 and not any(c.isalpha() for c in text):
                continue

            if self._normalize_comment_text(text) in ignore_patterns:
                continue

            if re.match(r"^[\d,.KMB]+$", text):
                continue

            _, el_y = el.center
            if el_y < 100 or el_y > 1800:
                continue

            desc = el.content_desc.lower() if el.content_desc else ""
            if any(kw in desc for kw in ["profile", "follow", "share", "like"]):
                continue

            texts.append(text)
            if len(texts) >= max_count:
                break

        return texts

    def _comment_match_strength(
        self,
        expected_text: str,
        candidate_text: str,
    ) -> bool:
        """Return True only for high-confidence visible comment matches."""
        expected = self._normalize_comment_text(expected_text)
        candidate = self._normalize_comment_text(candidate_text)
        if not expected or not candidate:
            return False
        if expected == candidate:
            return True

        shorter = min(len(expected), len(candidate))
        longer = max(len(expected), len(candidate))
        if shorter < 8:
            return False
        if shorter / max(longer, 1) < 0.72:
            return False

        return expected in candidate or candidate in expected

    def _comment_already_visible(
        self,
        candidate_text: str,
        baseline_texts: set[str],
    ) -> bool:
        """Check whether a visible candidate was already present before send."""
        candidate = self._normalize_comment_text(candidate_text)
        if not candidate:
            return False

        for baseline in baseline_texts:
            if not baseline:
                continue
            if baseline == candidate:
                return True

            shorter = min(len(candidate), len(baseline))
            longer = max(len(candidate), len(baseline))
            if shorter < 8:
                continue
            if shorter / max(longer, 1) < 0.8:
                continue
            if candidate in baseline or baseline in candidate:
                return True
        return False

    def _get_comment_input_bounds(
        self,
        elements: list[UIElement],
    ) -> tuple[int, int, int, int] | None:
        """Return active comment input bounds when the panel is open."""
        for el in elements:
            if "EditText" in el.cls:
                return el.bounds
        return None

    def _looks_like_feed_signature(
        self,
        texts_lower: set[str],
        descs_lower: set[str],
    ) -> bool:
        """Heuristic feed detector resilient to TikTok UI variations."""
        has_for_you = "for you" in descs_lower
        has_home = "home" in descs_lower
        has_like = any("like" in desc for desc in descs_lower)
        has_comment = any("comment" in desc for desc in descs_lower)
        has_share = any("share" in desc for desc in descs_lower)
        has_add_comment = any("add comment" in text for text in texts_lower)

        # Feed UIs vary by locale/version; use engagement controls as stable signal.
        return (
            has_for_you
            or (has_like and has_comment and has_share)
            or (has_home and has_like and has_comment)
            or (has_add_comment and has_like)
        )

    def classify_upload_state(self, elements: list[UIElement]) -> str:
        """Classify the current TikTok upload screen from a UI dump."""
        texts = {el.text.strip() for el in elements if el.text.strip()}
        descs = {el.content_desc.strip() for el in elements if el.content_desc.strip()}
        texts_lower = {text.lower() for text in texts}
        descs_lower = {desc.lower() for desc in descs}
        labels_lower = texts_lower | descs_lower

        if (
            "Add description..." in texts
            or {"Drafts", "Post"} <= texts
            or any("view this post" in text.lower() for text in texts)
            or (
                any(
                    any(marker in label for label in labels_lower)
                    for marker in {
                        "add description",
                        "add caption",
                        "describe your post",
                        "describe your video",
                        "mô tả video",
                        "viết chú thích",
                    }
                )
                and any(post_label in labels_lower for post_label in {"post", "đăng"})
            )
        ):
            return "post_form"

        has_your_story = any("your story" in label for label in labels_lower)
        has_next = any(
            token in label for label in labels_lower for token in ("next", "tiếp")
        )
        editor_markers = {
            "add sound",
            "templates",
            "text",
            "stickers",
            "effects",
            "filters",
            "crop",
            "edit",
            "adjust clips",
        }
        if has_your_story and has_next and (
            any(any(marker in label for label in labels_lower) for marker in editor_markers)
            or not (
                any("recents" in label for label in labels_lower)
                or any("select multiple" in label for label in labels_lower)
            )
        ):
            return "video_editor"

        if (
            "Recents" in texts
            and "Select multiple" in texts
            and ("Next" in texts or "AutoCut" in texts)
        ):
            return "gallery_picker"

        if (
            "Add sound" in texts
            and ({"POST", "CREATE"} <= texts or {"15s", "60s"} <= texts)
        ):
            return "camera_create"

        if self._looks_like_feed_signature(texts_lower, descs_lower):
            return "feed"

        return "unknown"

    async def detect_upload_state(self, device: str) -> str:
        """Detect the current upload state from the active UI hierarchy."""
        elements = await self.dump_ui(device)
        return self.classify_upload_state(elements)

    async def wait_for_upload_state(
        self,
        device: str,
        expected_states: set[str],
        *,
        timeout: float = 8.0,
        poll_interval: float = 0.5,
    ) -> str | None:
        """Wait until the current upload screen matches one of the expected states."""
        deadline = asyncio.get_event_loop().time() + timeout
        last_state = "unknown"

        while asyncio.get_event_loop().time() < deadline:
            last_state = await self.detect_upload_state(device)
            if last_state in expected_states:
                return last_state
            await asyncio.sleep(poll_interval)

        logger.warning(
            f"  ⚠️ [upload_state] Timed out waiting for {sorted(expected_states)}; last={last_state}"
        )
        return None

    def _looks_like_selected_gallery_preview(self, nodes: list[dict]) -> bool:
        """Return True when gallery is showing the single-item preview UI."""
        labels_lower = {
            self._fold_text((node.get("text") or node.get("desc") or "").strip())
            for node in nodes
            if (node.get("text") or node.get("desc"))
        }
        return {"select", "next", "autocut"} <= labels_lower

    def _looks_like_invalid_gallery_preview_image(self, image) -> bool:
        """Detect the broken black preview used by TikTok for missing media."""
        rgb = image.convert("RGB")
        w, h = rgb.size

        preview = rgb.crop((0, int(h * 0.10), w, int(h * 0.75)))
        preview_total = preview.width * preview.height
        if preview_total <= 0:
            return False
        preview_pixels = preview.load()
        preview_dark_count = 0
        for py in range(preview.height):
            for px in range(preview.width):
                r, g, b = preview_pixels[px, py]
                if r < 25 and g < 25 and b < 25:
                    preview_dark_count += 1
        preview_dark = preview_dark_count / preview_total
        if preview_dark < 0.92:
            return False

        center = rgb.crop(
            (int(w * 0.30), int(h * 0.32), int(w * 0.70), int(h * 0.58))
        )
        center_total = center.width * center.height
        if center_total <= 0:
            return False
        center_pixels = center.load()
        center_dark_count = 0
        center_gray_count = 0
        for py in range(center.height):
            for px in range(center.width):
                r, g, b = center_pixels[px, py]
                if r < 40 and g < 40 and b < 40:
                    center_dark_count += 1
                if abs(r - g) < 15 and abs(g - b) < 15 and 50 < r < 180:
                    center_gray_count += 1
        center_dark = center_dark_count / center_total
        center_gray = center_gray_count / center_total
        return center_dark > 0.78 and center_gray > 0.08

    async def detect_invalid_gallery_preview(self, device: str) -> bool:
        """Detect TikTok's broken preview before tapping Next again."""
        if await self.detect_upload_state(device) != "gallery_picker":
            return False

        nodes = await self._dump_all_ui_nodes(device)
        if not self._looks_like_selected_gallery_preview(nodes):
            return False

        image = await self._capture_analysis_image(device, prefix="gallery_preview")
        if image is None:
            return False

        matched = self._looks_like_invalid_gallery_preview_image(image)
        if matched:
            logger.warning(
                "  ⚠️ [gallery_preview] Broken preview detected; media looks missing"
            )
        return matched

    async def recover_invalid_gallery_preview(self, device: str) -> bool:
        """Back out of a broken preview and return to the gallery grid."""
        ok = await self.return_to_gallery_grid(device)
        if not ok:
            logger.warning("  ⚠️ [gallery_preview] Could not recover to gallery grid")
            return False
        return not await self.detect_invalid_gallery_preview(device)

    async def detect_post_publish_state(self, device: str) -> str:
        """Detect post-submit completion, follow-up popups, or blocking overlays."""
        foreground = await self.get_foreground_app(device)
        nodes = await self._dump_all_ui_nodes(device)
        texts = {node["text"] for node in nodes if node["text"]}
        lower_texts = {text.lower() for text in texts}
        lower_descs = {
            (node["desc"] or "").lower()
            for node in nodes
            if node.get("desc")
        }

        if (
            foreground == "jp.co.sharp.android.launcher3"
            and "Add to Home screen" in texts
            and "TikTok Camera" in texts
        ):
            return "launcher_popup"

        if any(text.startswith("Video posted!") for text in texts):
            return "completed_share_sheet"

        if (
            any("facebook friends list and email" in text for text in lower_texts)
            and "Don't allow" in texts
        ):
            return "completed_permission_popup"

        if any(
            token in lower_texts
            for token in {
                "uploading",
                "processing",
                "posting",
                "your video is being uploaded",
            }
        ):
            return "uploading"

        upload_state = self.classify_upload_state(await self.dump_ui(device))
        if upload_state == "post_form":
            return "post_form"
        if upload_state == "feed":
            return "completed_feed"

        # Some TikTok builds navigate to Inbox/Profile/Home right after posting.
        # If we are clearly on main navigation and no longer in upload flow,
        # treat this as completion.
        has_main_nav = (
            any(token in lower_texts for token in {"home", "inbox", "profile", "shop"})
            or any(token in lower_descs for token in {"home", "inbox", "profile", "shop"})
        )
        if has_main_nav and upload_state not in {
            "post_form",
            "video_editor",
            "gallery_picker",
            "camera_create",
        }:
            return "completed_main_nav"

        return "unknown"

    async def dismiss_post_publish_obstacles(self, device: str) -> bool:
        """Dismiss launcher/share/permission overlays that appear after posting."""
        nodes = await self._dump_all_ui_nodes(device)
        texts = {node["text"] for node in nodes if node["text"]}

        targets = [
            "CANCEL",
            "Cancel",
            "Don't allow",
        ]
        for target_text in targets:
            for node in nodes:
                if not node["clickable"] or node["text"] != target_text or not node["bounds"]:
                    continue
                x1, y1, x2, y2 = node["bounds"]
                await self._tap(device, (x1 + x2) // 2, (y1 + y2) // 2)
                await asyncio.sleep(1.0)
                return True

        if any(text.startswith("Video posted!") for text in texts):
            await self.dismiss_keyboard(device)
            return True

        return False

    async def wait_for_post_completion(
        self,
        device: str,
        *,
        timeout: float = 45.0,
        poll_interval: float = 1.0,
    ) -> str | None:
        """Wait for a reliable post-submit completion signal."""
        success_states = {
            "completed_share_sheet",
            "completed_permission_popup",
            "completed_feed",
            "completed_main_nav",
        }
        recoverable_states = {"launcher_popup"}
        deadline = asyncio.get_event_loop().time() + timeout
        last_state = "unknown"

        while asyncio.get_event_loop().time() < deadline:
            state = await self.detect_post_publish_state(device)
            last_state = state

            if state in success_states:
                return state

            if state in recoverable_states:
                await self.dismiss_post_publish_obstacles(device)

            await asyncio.sleep(poll_interval)

        logger.warning(f"  ⚠️ [post_publish] Timed out waiting for completion; last={last_state}")
        return None

    async def tap_labeled_button(
        self,
        device: str,
        labels: tuple[str, ...],
        *,
        prefer_top: bool = False,
        use_realistic_tap: bool = True,
    ) -> bool:
        """Tap a button identified by visible label text, using its clickable container."""
        elements = await self.dump_ui(device)
        patterns = tuple(re.compile(rf"^{re.escape(label)}$", re.IGNORECASE) for label in labels)
        candidates: list[UIElement] = []

        for el in elements:
            label_text = el.text.strip() if el.text else ""
            desc_text = el.content_desc.strip() if el.content_desc else ""
            matches = (
                label_text and self._matches_any_pattern(label_text, patterns)
            ) or (
                desc_text and self._matches_any_pattern(desc_text, patterns)
            )
            if not matches:
                continue

            tappable = el if el.clickable else self._find_smallest_clickable_container(elements, el)
            if tappable:
                candidates.append(tappable)

        if not candidates:
            return False

        ordered = sorted(
            candidates,
            key=lambda el: (
                el.center[1] if prefer_top else -el.center[1],
                el.center[0],
                self._bounds_area(el.bounds),
            ),
        )
        target = ordered[0]
        x, y = target.center
        x += random.randint(-4, 4)
        y += random.randint(-3, 3)
        logger.info(f"  🎯 [button] Tapping {labels} at ({x}, {y})")
        if use_realistic_tap:
            await self._realistic_tap(device, x, y)
        else:
            await self._tap(device, x, y)
        return True

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

    # --- Upload Flow Actions ---
    
    async def tap_create(self, device: str) -> bool:
        """Tap the central '+' Create button on the home feed."""
        return await self.smart_tap(device, "create")

    async def open_create_entry(
        self,
        device: str,
        *,
        timeout: float = 10.0,
    ) -> str | None:
        """Open TikTok create flow and wait until camera/gallery entry appears."""
        expected_states = {"camera_create", "gallery_picker"}

        current = await self.wait_for_upload_state(
            device, expected_states, timeout=1.0, poll_interval=0.25
        )
        if current:
            return current

        # Strategy 1: semantic tap by UI locator/fallback map.
        if await self.tap_create(device):
            state = await self.wait_for_upload_state(
                device, expected_states, timeout=min(timeout, 4.0)
            )
            if state:
                return state

        # Strategy 2/3: force bottom-center taps where Create tab commonly sits.
        w, h = await self._get_screen_size(device)
        fallback_points = [
            (0.50, 0.93, "fallback_bottom_nav"),
            (0.50, 0.88, "fallback_create_center"),
        ]
        for xr, yr, label in fallback_points:
            if not await self.is_tiktok_foreground(device):
                await self.recover(device)
                await asyncio.sleep(1.0)

            x = int(w * xr) + random.randint(-10, 10)
            y = int(h * yr) + random.randint(-8, 8)
            logger.info(f"  ⚠️ [create_entry] {label} tap at ({x}, {y})")
            await self._realistic_tap(device, x, y)
            await asyncio.sleep(0.8)

            state = await self.wait_for_upload_state(
                device, expected_states, timeout=min(timeout, 4.0)
            )
            if state:
                return state

        logger.warning(
            "  ⚠️ [create_entry] Failed to enter camera/gallery after create taps"
        )
        return None

    async def tap_upload_gallery(self, device: str) -> bool:
        """Tap the Upload (Gallery) thumbnail on the Camera screen."""
        # Wait a bit longer as the camera UI can be heavy to load
        await asyncio.sleep(1.0)
        return await self.smart_tap(device, "upload_gallery", verify_foreground=False)

    def _collect_gallery_video_tiles(self, elements: list[UIElement]) -> list[dict]:
        """Collect visible gallery video tiles ordered top-to-bottom, left-to-right."""
        seen_bounds = set()
        tiles: list[dict] = []

        for el in elements:
            label = el.text.strip() if el.text else ""
            if not self.DURATION_PATTERN.match(label):
                continue

            container = self._find_smallest_clickable_container(
                elements, el, require_long_clickable=True
            ) or self._find_smallest_clickable_container(elements, el)
            if not container:
                continue

            if container.bounds in seen_bounds:
                continue
            seen_bounds.add(container.bounds)
            tiles.append(
                {
                    "bounds": container.bounds,
                    "center": container.center,
                    "duration": label,
                }
            )

        return sorted(tiles, key=lambda item: (item["bounds"][1], item["bounds"][0]))

    async def select_first_video(self, device: str) -> bool:
        """Select the first real video tile in the gallery grid.

        The first tile in Recents is often an image or a broken placeholder.
        We instead look for the first tile with a visible duration overlay.
        """
        await asyncio.sleep(1.0)
        elements = await self.dump_ui(device)

        video_tiles = self._collect_gallery_video_tiles(elements)

        if video_tiles:
            tile = video_tiles[0]
            x, y = tile["center"]
            x += random.randint(-8, 8)
            y += random.randint(-8, 8)
            logger.info(
                f"  🎯 [gallery_video] Selecting {tile['duration']} tile at ({x}, {y})"
            )
            await self._realistic_tap(device, x, y)
            await asyncio.sleep(1.0)
            return True

        w, h = await self._get_screen_size(device)
        x = int(w * 0.50) + random.randint(-10, 10)
        y = int(h * 0.28) + random.randint(-10, 10)
        logger.warning(f"  ⚠️ [gallery_video] No duration tile found, falling back to ({x}, {y})")
        await self._realistic_tap(device, x, y)
        await asyncio.sleep(1.0)
        return True

    async def _query_media_store_videos(self, device: str) -> list[dict]:
        """Query MediaStore videos visible to Android and normalize the rows."""
        projection = (
            "_id:_display_name:relative_path:date_added:date_modified:"
            "_size:duration:width:height"
        )
        ret, stdout, stderr = await self._adb._run_adb(
            device,
            "shell",
            "content",
            "query",
            "--uri",
            "content://media/external/video/media",
            "--projection",
            projection,
        )
        if ret != 0:
            logger.warning("  ⚠️ [mediastore] content query failed: %s", stderr or stdout)
            return []

        rows: list[dict] = []
        for line in (stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("Row:"):
                continue
            payload = line.split(" ", 2)[2] if " " in line else ""
            row: dict[str, str] = {}
            for part in payload.split(", "):
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                row[key.strip()] = value.strip()
            if row:
                rows.append(row)
        return rows

    async def get_media_store_video(
        self,
        device: str,
        *,
        filename: str | None = None,
        device_path: str | None = None,
    ) -> dict | None:
        """Return the MediaStore row that matches the pushed upload video."""
        rows = await self._query_media_store_videos(device)
        if not rows:
            return None

        relative_path = None
        if device_path:
            pure = Path(device_path)
            filename = filename or pure.name
            parent = str(pure.parent).replace("\\", "/").strip("/")
            if parent:
                relative_path = f"{parent}/"

        candidates = rows
        if filename:
            folded_name = self._fold_text(filename)
            candidates = [
                row
                for row in candidates
                if self._fold_text(row.get("_display_name", "")) == folded_name
            ]
        if relative_path:
            folded_rel = self._fold_text(relative_path)
            narrowed = [
                row
                for row in candidates
                if self._fold_text(row.get("relative_path", "")) == folded_rel
            ]
            if narrowed:
                candidates = narrowed

        if not candidates:
            logger.warning(
                "  ⚠️ [mediastore] Could not find %s in MediaStore (path=%s)",
                filename,
                relative_path or "",
            )
            return None

        def _numeric(row: dict, key: str) -> int:
            raw = (row.get(key) or "").strip()
            try:
                return int(raw)
            except ValueError:
                return 0

        best = max(
            candidates,
            key=lambda row: (_numeric(row, "date_added"), _numeric(row, "date_modified")),
        )
        logger.info(
            "  📼 [mediastore] Target row: %s",
            {
                "display_name": best.get("_display_name"),
                "relative_path": best.get("relative_path"),
                "date_added": best.get("date_added"),
                "duration": best.get("duration"),
            },
        )
        return best

    def _gallery_album_name_from_media(self, media_row: dict | None) -> str | None:
        """Extract the gallery album/folder label from MediaStore relative_path."""
        if not media_row:
            return None
        relative_path = (media_row.get("relative_path") or "").strip().strip("/")
        if not relative_path:
            return None
        return relative_path.split("/")[-1] or None

    def _detect_gallery_album_label(self, elements: list[UIElement]) -> str | None:
        """Detect the current album label shown in the gallery header."""
        ignored = {
            "all",
            "videos",
            "photos",
            "ai gallery",
            "text",
            "select multiple",
            "next",
            "autocut",
            "select",
        }
        candidates: list[tuple[int, str]] = []
        for el in elements:
            if not el.text:
                continue
            label = el.text.strip()
            if not label:
                continue
            folded = self._fold_text(label)
            if folded in ignored:
                continue
            x, y = el.center
            if y > 280:
                continue
            if not (220 <= x <= 860):
                continue
            candidates.append((y, label))

        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item[0])[0][1]

    async def _tap_text_match(
        self,
        device: str,
        patterns: tuple[str, ...],
        *,
        prefer_top: bool = True,
        contains: bool = False,
        use_realistic_tap: bool = False,
    ) -> bool:
        """Tap a visible text/desc match using its clickable container."""
        elements = await self.dump_ui(device)
        folded_patterns = tuple(self._fold_text(pattern) for pattern in patterns if pattern)
        candidates: list[UIElement] = []

        for el in elements:
            for raw in (el.text or "", el.content_desc or ""):
                folded = self._fold_text(raw.strip())
                if not folded:
                    continue
                matched = any(
                    pattern in folded if contains else pattern == folded
                    for pattern in folded_patterns
                )
                if not matched:
                    continue
                tappable = (
                    el if el.clickable else self._find_smallest_clickable_container(elements, el)
                )
                if tappable:
                    candidates.append(tappable)
                break

        if not candidates:
            return False

        ordered = sorted(
            candidates,
            key=lambda el: (
                el.center[1] if prefer_top else -el.center[1],
                el.center[0],
                self._bounds_area(el.bounds),
            ),
        )
        target = ordered[0]
        x, y = target.center
        x += random.randint(-4, 4)
        y += random.randint(-3, 3)
        if use_realistic_tap:
            await self._realistic_tap(device, x, y)
        else:
            await self._tap(device, x, y)
        await asyncio.sleep(0.8)
        return True

    async def ensure_gallery_video_context(
        self,
        device: str,
        *,
        album_name: str | None = None,
    ) -> None:
        """Bias the TikTok picker toward the intended video gallery context."""
        await self._tap_text_match(device, ("Videos",), prefer_top=True)
        if not album_name:
            return

        elements = await self.dump_ui(device)
        current_album = self._detect_gallery_album_label(elements)
        if not current_album:
            return
        if self._fold_text(current_album) == self._fold_text(album_name):
            return

        if not await self._tap_text_match(
            device,
            (current_album,),
            prefer_top=True,
        ):
            return

        if await self._tap_text_match(
            device,
            (album_name,),
            prefer_top=True,
            contains=True,
        ):
            logger.info("  📁 [gallery] Switched album to %s", album_name)
            return

        logger.warning("  ⚠️ [gallery] Album '%s' not visible after picker open", album_name)
        await self.return_to_gallery_grid(device)

    def _load_reference_thumbnail(self, thumbnail_path: str | None):
        """Load the expected video thumbnail image if available."""
        if not thumbnail_path:
            return None
        from PIL import Image

        path = Path(thumbnail_path)
        if not path.exists():
            logger.warning("  ⚠️ [gallery_match] Thumbnail missing: %s", thumbnail_path)
            return None
        try:
            with Image.open(path) as image:
                return image.convert("RGB")
        except Exception as e:
            logger.warning("  ⚠️ [gallery_match] Failed to open thumbnail %s: %s", thumbnail_path, e)
            return None

    def _image_similarity(self, left, right) -> float:
        """Return a soft visual similarity score between two images."""
        from PIL import ImageOps

        fitted_left = ImageOps.fit(left.convert("RGB"), (32, 32))
        fitted_right = ImageOps.fit(right.convert("RGB"), (32, 32))

        total_pixels = fitted_left.width * fitted_left.height
        total_channels = total_pixels * 3
        total_diff = 0
        left_pixels = fitted_left.load()
        right_pixels = fitted_right.load()
        for py in range(fitted_left.height):
            for px in range(fitted_left.width):
                lr, lg, lb = left_pixels[px, py]
                rr, rg, rb = right_pixels[px, py]
                total_diff += abs(lr - rr) + abs(lg - rg) + abs(lb - rb)
        grid_similarity = 1.0 - (total_diff / max(total_channels * 255, 1))

        gray_left = ImageOps.fit(left.convert("L"), (16, 16))
        gray_right = ImageOps.fit(right.convert("L"), (16, 16))
        gray_total = gray_left.width * gray_left.height
        left_gray_pixels = gray_left.load()
        right_gray_pixels = gray_right.load()

        left_sum = 0
        right_sum = 0
        for py in range(gray_left.height):
            for px in range(gray_left.width):
                left_sum += left_gray_pixels[px, py]
                right_sum += right_gray_pixels[px, py]
        left_avg = left_sum / max(gray_total, 1)
        right_avg = right_sum / max(gray_total, 1)

        hash_diff = 0
        for py in range(gray_left.height):
            for px in range(gray_left.width):
                if (left_gray_pixels[px, py] >= left_avg) != (
                    right_gray_pixels[px, py] >= right_avg
                ):
                    hash_diff += 1
        hash_similarity = 1.0 - (hash_diff / max(gray_total, 1))

        return max(0.0, min(1.0, (grid_similarity * 0.65) + (hash_similarity * 0.35)))

    def _crop_gallery_preview_image(self, image):
        """Crop the large preview area shown after tapping a gallery tile."""
        w, h = image.size
        return image.crop((0, int(h * 0.10), w, int(h * 0.75)))

    async def verify_selected_gallery_preview(
        self,
        device: str,
        *,
        reference_image=None,
        min_similarity: float = 0.42,
    ) -> tuple[bool, float | None]:
        """Verify the currently selected gallery preview against the reference image."""
        nodes = await self._dump_all_ui_nodes(device)
        if not self._looks_like_selected_gallery_preview(nodes):
            return False, None
        if await self.detect_invalid_gallery_preview(device):
            return False, 0.0
        if reference_image is None:
            return True, None

        image = await self._capture_analysis_image(device, prefix="gallery_preview_verify")
        if image is None:
            return False, None

        preview = self._crop_gallery_preview_image(image)
        similarity = self._image_similarity(preview, reference_image)
        logger.info("  🔎 [gallery_preview] Similarity %.3f", similarity)
        return similarity >= min_similarity, similarity

    async def return_to_gallery_grid(self, device: str) -> bool:
        """Leave the single-item preview and return to the gallery grid."""
        for _ in range(2):
            await self._get_backend(device)
            if self._backend:
                try:
                    await self._backend.key_event(device, "BACK")
                except Exception as e:
                    await self._record_backend_issue(device, e)
                    logger.warning(
                        "  ⚠️ [gallery_grid] Backend BACK failed, fallback ADB: %s",
                        e,
                    )
                    self._backend = None
                    await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
            else:
                await self._adb._run_adb(device, "shell", "input", "keyevent", "4")

            await asyncio.sleep(1.0)
            if await self.detect_upload_state(device) != "gallery_picker":
                continue
            nodes = await self._dump_all_ui_nodes(device)
            if not self._looks_like_selected_gallery_preview(nodes):
                return True
        return False

    async def _select_gallery_video_by_visual_match(
        self,
        device: str,
        *,
        reference_image,
        max_pages: int = 2,
    ) -> bool:
        """Select the best-matching visible video tile and verify its preview."""
        tried_candidates: set[tuple[int, int, int, int]] = set()
        w, h = await self._get_screen_size(device)

        for page in range(max_pages):
            elements = await self.dump_ui(device)
            candidates = self._collect_gallery_video_tiles(elements)
            if not candidates:
                logger.warning("  ⚠️ [gallery_match] No visible video tiles on page %s", page)
            image = await self._capture_analysis_image(device, prefix=f"gallery_page_{page}")
            if image is None:
                return False

            ranked: list[dict] = []
            for candidate in candidates:
                bounds = candidate["bounds"]
                if bounds in tried_candidates:
                    continue
                crop = image.crop(bounds)
                candidate["tile_similarity"] = self._image_similarity(crop, reference_image)
                ranked.append(candidate)

            ranked.sort(key=lambda item: item.get("tile_similarity", 0.0), reverse=True)
            if ranked:
                logger.info(
                    "  🧭 [gallery_match] Page %s top tile similarities: %s",
                    page,
                    [
                        f"{item['duration']}@{item['bounds']}={item['tile_similarity']:.3f}"
                        for item in ranked[:3]
                    ],
                )

            for candidate in ranked[:4]:
                tried_candidates.add(candidate["bounds"])
                x, y = candidate["center"]
                x += random.randint(-6, 6)
                y += random.randint(-6, 6)
                logger.info(
                    "  🎯 [gallery_match] Trying tile %s at (%s, %s) similarity=%.3f",
                    candidate["duration"],
                    x,
                    y,
                    candidate["tile_similarity"],
                )
                await self._realistic_tap(device, x, y)
                await asyncio.sleep(1.1)

                preview_ok, preview_similarity = await self.verify_selected_gallery_preview(
                    device,
                    reference_image=reference_image,
                )
                if preview_ok:
                    logger.info(
                        "  ✅ [gallery_match] Preview verified with similarity %.3f",
                        preview_similarity if preview_similarity is not None else -1.0,
                    )
                    return True

                if not await self.return_to_gallery_grid(device):
                    logger.warning("  ⚠️ [gallery_match] Could not return to gallery grid")
                    return False

            if page >= max_pages - 1:
                break

            await self._swipe(
                device,
                w // 2,
                int(h * 0.76),
                w // 2,
                int(h * 0.34),
                duration_ms=420,
            )
            await asyncio.sleep(0.8)

        logger.warning("  ⚠️ [gallery_match] No confident visual gallery match found")
        return False

    async def select_video_for_upload(
        self,
        device: str,
        *,
        filename: str | None = None,
        device_path: str | None = None,
        thumbnail_path: str | None = None,
    ) -> bool:
        """Select the intended upload video using MediaStore + visual verification."""
        media_row = await self.get_media_store_video(
            device,
            filename=filename,
            device_path=device_path,
        )
        reference_image = self._load_reference_thumbnail(thumbnail_path)

        if filename and await self.select_video_by_name(device, filename, allow_scroll=False):
            preview_ok, _ = await self.verify_selected_gallery_preview(
                device,
                reference_image=reference_image,
            )
            if preview_ok:
                return True
            await self.return_to_gallery_grid(device)

        await self.ensure_gallery_video_context(
            device,
            album_name=self._gallery_album_name_from_media(media_row),
        )

        if reference_image is not None:
            return await self._select_gallery_video_by_visual_match(
                device,
                reference_image=reference_image,
            )

        if filename:
            logger.warning(
                "  ⚠️ [gallery_match] No thumbnail available; using name-based gallery search only"
            )
            return await self.select_video_by_name(device, filename, allow_scroll=True)

        return False

    async def select_video_by_name(
        self,
        device: str,
        filename: str,
        *,
        allow_scroll: bool = True,
    ) -> bool:
        """Select a specific video tile in the gallery by matching filename.

        Strategy:
        1. Dump UI — search for an element whose content-desc or text contains the
           filename (case-insensitive, supports partial match without extension).
        2. If not found on current screen, scroll down once and retry.
        3. Falls back gracefully by returning False so the caller can switch to
           select_first_video() as a safety net.

        Args:
            device: ADB device serial / cloud:{id}
            filename: Filename of the pushed video, e.g. "my_video.mp4"
        """
        await asyncio.sleep(1.0)

        # Build search tokens: full name + stem without extension
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        tokens = {filename.lower(), stem.lower()}

        for attempt in range(2 if allow_scroll else 1):  # Try current view, then after one scroll
            elements = await self.dump_ui(device)
            for el in elements:
                desc = (el.content_desc or "").lower()
                text = (el.text or "").lower()
                if any(tok in desc or tok in text for tok in tokens):
                    container = (
                        self._find_smallest_clickable_container(elements, el, require_long_clickable=True)
                        or self._find_smallest_clickable_container(elements, el)
                        or (el if el.clickable else None)
                    )
                    if container:
                        x, y = container.center
                        x += random.randint(-8, 8)
                        y += random.randint(-8, 8)
                        logger.info(
                            f"  🎯 [gallery_by_name] Found '{filename}' via "
                            f"{'desc' if any(tok in desc for tok in tokens) else 'text'} "
                            f"at ({x}, {y})"
                        )
                        await self._realistic_tap(device, x, y)
                        await asyncio.sleep(1.0)
                        return True

            if attempt == 0:
                # Scroll down slightly to reveal more gallery tiles
                w, h = await self._get_screen_size(device)
                await self._swipe(device, w // 2, int(h * 0.7), w // 2, int(h * 0.3), duration_ms=400)
                await asyncio.sleep(0.8)

        logger.warning(f"  ⚠️ [gallery_by_name] Could not find '{filename}' in gallery")
        return False


    async def tap_next(self, device: str) -> bool:
        """Tap the 'Next' button on Gallery, Edit, and Post screens."""
        await asyncio.sleep(1.0)

        if await self.tap_labeled_button(
            device,
            ("Next", "Tiếp"),
            use_realistic_tap=False,
        ):
            return True

        # Fallback to legacy pattern matching if text/container lookup fails.
        return await self.smart_tap(device, "next_btn", verify_foreground=False)

    async def tap_post(self, device: str) -> bool:
        """Tap the final huge 'Post' button to upload the video."""
        await asyncio.sleep(1.0)
        # Prefer the lower/bottom Post CTA first — this is the main submit button.
        if await self.tap_labeled_button(
            device,
            ("Post", "Đăng"),
            prefer_top=False,
            use_realistic_tap=False,
        ):
            return True
        if await self.smart_tap(device, "post_btn", verify_foreground=False):
            return True

        # Hard fallback: tap bottom-center submit area directly.
        w, h = await self._get_screen_size(device)
        x = int(w * 0.74) + random.randint(-8, 8)
        y = int(h * 0.87) + random.randint(-8, 8)
        logger.warning(f"  ⚠️ [tap_post] Using hard fallback at ({x}, {y})")
        await self._tap(device, x, y)
        return True

    async def fill_post_metadata(self, device: str, title: str, description: str) -> bool:
        """Fill in the caption/description and title on the Post screen."""
        await asyncio.sleep(1.5)

        elements = await self.dump_ui(device)
        w, h = await self._get_screen_size(device)

        # Strategy: Build candidate targets in priority order.
        candidates: list[tuple[int, int, int, str]] = []

        # 1) Prefer top EditText fields (most stable when post form is ready).
        for el in elements:
            if "EditText" in el.cls:
                cx, cy = el.center
                if cy < h * 0.45:
                    candidates.append((0, cx, cy, "edittext_top"))

        # 2) Fallback to hint labels like "Add description..." or "Add caption".
        hint_patterns = (
            re.compile(r"add description", re.IGNORECASE),
            re.compile(r"add caption", re.IGNORECASE),
            re.compile(r"describe your", re.IGNORECASE),
            re.compile(r"caption", re.IGNORECASE),
            re.compile(r"mô tả", re.IGNORECASE),
            re.compile(r"chú thích", re.IGNORECASE),
        )
        for el in elements:
            txt = (el.text or "").strip()
            desc = (el.content_desc or "").strip()
            haystack = f"{txt} {desc}".strip()
            if not haystack:
                continue
            if not self._matches_any_pattern(haystack, hint_patterns):
                continue
            tappable = (
                el if el.clickable else self._find_smallest_clickable_container(elements, el)
            )
            if not tappable:
                continue
            cx, cy = tappable.center
            candidates.append((1, cx, cy, f"hint:{haystack[:40]}"))

        # 3) Last-resort coordinate.
        fallback_x = int(w * 0.30) + random.randint(-12, 12)
        fallback_y = int(h * 0.12) + random.randint(-8, 8)
        candidates.append((2, fallback_x, fallback_y, "fallback_coord"))

        full_text = f"{title}\n\n{description}".strip() if title else (description or "").strip()
        if not full_text:
            return True

        # De-duplicate nearby candidates.
        deduped: list[tuple[int, int, int, str]] = []
        seen = set()
        for item in sorted(candidates, key=lambda x: (x[0], x[2], x[1])):
            _, cx, cy, label = item
            key = (cx // 24, cy // 24)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= 4:
                break

        for priority, x, y, label in deduped:
            logger.info(
                f"  📝 [fill_metadata] Try target p{priority} '{label}' at ({x}, {y})"
            )
            await self._tap(device, x, y)
            await asyncio.sleep(0.5)

            typed = await self.type_text(device, full_text)
            await asyncio.sleep(0.6)
            if typed and await self._verify_text_entered(device, full_text):
                logger.info("  ✅ [fill_metadata] Caption metadata verified")
                return True

        logger.warning("  ⚠️ [fill_metadata] Could not verify caption metadata input")
        return False

    async def dismiss_keyboard(self, device: str) -> bool:
        """Dismiss the active keyboard with a single BACK keypress."""
        await self._get_backend(device)
        if self._backend:
            await self._backend.key_event(device, "BACK")
        else:
            await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        await asyncio.sleep(0.5)
        return True

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

    async def get_comment_input_text(self, device: str) -> str:
        """Return the current user-entered text in the bottom comment EditText."""
        placeholders = {
            "add comment...", "add a comment...", "thêm bình luận...",
            "viết bình luận...", "say something...", "add comment",
        }
        elements = await self.dump_ui(device)
        inputs = [el for el in elements if "EditText" in el.cls]
        if not inputs:
            return ""

        target = max(inputs, key=lambda e: e.center[1])
        text_content = (target.text or "").strip()
        if text_content.lower() in placeholders:
            return ""
        return text_content

    async def clear_comment_input(self, device: str, max_deletes: int = 160) -> bool:
        """Clear existing comment text before typing a new value."""
        existing = await self.get_comment_input_text(device)
        if not existing:
            return True

        logger.info("  🧹 [comment_input] Clearing existing text: '%s'", existing[:40])
        await self.tap_comment_input(device)
        await asyncio.sleep(0.2)

        delete_presses = min(max(len(existing) + 12, 16), max_deletes)
        for _ in range(delete_presses):
            await self._adb._run_adb(device, "shell", "input", "keyevent", "67")
        await asyncio.sleep(0.35)

        remaining = await self.get_comment_input_text(device)
        if remaining:
            logger.warning(
                "  ⚠️ [comment_input] Text remained after clear attempt: '%s'",
                remaining[:40],
            )
            return False

        logger.info("  ✅ [comment_input] Input cleared")
        return True

    async def is_comment_panel_open(self, device: str) -> bool:
        """Best-effort detector for an open TikTok comment panel."""
        elements = await self.dump_ui(device)
        if not elements:
            return False

        _, h = await self._get_screen_size(device)
        for el in elements:
            if "EditText" in el.cls and el.center[1] > h * 0.5:
                return True

            text = (el.text or "").strip().lower()
            desc = (el.content_desc or "").strip().lower()
            if text.startswith("replying to") or desc.startswith("replying to"):
                return True
            if "comment" in text and el.center[1] < h * 0.35:
                return True
        return False

    async def get_video_info(self, device: str) -> dict:
        """Extract current video info from UI elements.

        Returns dict with: author, likes, comments, shares, sound, hashtags
        """
        elements = await self.dump_ui(device)
        return self._extract_video_info_from_elements(elements)

    async def get_video_fingerprint(
        self,
        device: str,
        *,
        video_info: dict | None = None,
    ) -> str:
        """Return a stable fingerprint for the current feed video."""
        elements = await self.dump_ui(device)
        return self.build_video_fingerprint(elements, video_info=video_info)

    async def wait_for_new_video(
        self,
        device: str,
        previous_fingerprint: str,
        *,
        timeout: float = 3.0,
        poll_interval: float = 0.5,
    ) -> str | None:
        """Wait until TikTok feed changes away from a previous fingerprint."""
        if not previous_fingerprint:
            return None

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            current = await self.get_video_fingerprint(device)
            if current and current != previous_fingerprint:
                return current
            await asyncio.sleep(poll_interval)
        return None

    async def read_comments(self, device: str, max_count: int = 10) -> list[dict]:
        """Read visible comments from the open comment panel.

        Scrapes comment text from UI hierarchy when comment panel is open.
        Returns list of dicts: [{"user": "username", "text": "comment"}, ...]

        Used to provide context to AI for generating relevant, opinionated
        comments that reference the discussion happening in the video.
        """
        elements = await self.dump_ui(device)
        comments = [{"text": text} for text in self._collect_comment_panel_texts(
            elements,
            max_count=max_count * 2,
        )]

        # Post-process: try to identify username vs comment text pairs
        # Typical pattern: username is shorter, comment is longer
        paired = []
        i = 0
        while i < len(comments):
            text = comments[i]["text"]
            # If this looks like a username (short, no spaces)
            if len(text) < 20 and " " not in text and i + 1 < len(comments):
                paired.append({
                    "user": text,
                    "text": comments[i + 1]["text"]
                })
                i += 2
            else:
                paired.append({"user": "?", "text": text})
                i += 1

        logger.info(f"  📖 [read_comments] Found {len(paired)} comments")
        return paired

    async def is_live_session(self, device: str) -> bool:
        """Detect whether the current TikTok screen is a LIVE session.

        `tiktok_comment` is meant for video comments that should appear in
        comment history. LIVE chat uses a different UI and different posting
        semantics, so we explicitly skip it.
        """
        elements = await self.dump_ui(device)
        if not elements:
            return False

        markers = 0
        for el in elements:
            text = (el.text or "").strip().lower()
            desc = (el.content_desc or "").strip().lower()
            haystack = f"{text} {desc}".strip()
            if not haystack:
                continue

            if "shopping ranking" in haystack:
                markers += 1
            elif text == "type..." or " type..." in haystack:
                markers += 1
            elif " joined" in haystack or haystack.endswith("joined"):
                markers += 1
            elif text == "follow" and el.center[1] < 260:
                markers += 1
            elif "live" == text or haystack.startswith("live "):
                markers += 1

            if markers >= 2:
                logger.info("  📺 [live_detect] LIVE session markers=%s", markers)
                return True

        return False

    async def is_tiktok_foreground(self, device: str) -> bool:
        """Check if TikTok is currently the foreground app.

        Prioritizes Accessibility backend (get_foreground_app) over ADB.

        TODO: [ACCESSIBILITY-MIGRATE] Once Accessibility is stable, remove
        ADB dumpsys fallback path entirely.
        """
        pkg = await self.get_foreground_app(device)
        return TIKTOK_PACKAGE in pkg

    async def get_foreground_app(self, device: str) -> str:
        """Get the current foreground package."""
        backend_pkg = ""

        # Try Accessibility first
        await self._get_backend(device)
        if self._backend:
            try:
                backend_pkg = await self._backend.get_foreground_app(device)
            except Exception:
                pass

        # Prefer ADB window focus (more reliable for current screen ownership).
        try:
            _, stdout, _ = await self._adb._run_adb(
                device, "shell",
                "dumpsys", "window", "windows"
            )
            for line in stdout.splitlines():
                if "mCurrentFocus=" in line or "mFocusedApp=" in line:
                    match = re.search(r'([a-zA-Z0-9._]+)/[a-zA-Z0-9._$]+', line)
                    if match:
                        return match.group(1)
        except Exception:
            pass

        # Fallback ADB activity dump.
        try:
            _, stdout, _ = await self._adb._run_adb(
                device, "shell",
                "dumpsys", "activity", "activities"
            )
            for line in stdout.splitlines():
                if ("mResumedActivity" in line or "mFocusedActivity" in line):
                    match = re.search(r'(\S+)/\S+', line)
                    if match:
                        return match.group(1)
            return backend_pkg or ""
        except Exception:
            return backend_pkg or ""

    async def capture_debug_snapshot(
        self,
        device: str,
        artifact_dir: str,
        label: str,
        note: str = "",
    ) -> dict:
        """Capture a debug bundle: screenshot, UI XML, and foreground app."""
        artifact_root = Path(artifact_dir)
        artifact_root.mkdir(parents=True, exist_ok=True)

        safe_label = re.sub(r"[^a-zA-Z0-9_.-]+", "_", label).strip("._") or "snapshot"
        png_path = artifact_root / f"{safe_label}.png"
        jpg_path = artifact_root / f"{safe_label}.jpg"
        xml_path = artifact_root / f"{safe_label}.xml"
        meta_path = artifact_root / f"{safe_label}.json"

        foreground_app = ""
        screenshot_path = ""
        screenshot_error = ""
        xml_error = ""

        try:
            await self._get_backend(device)
            if self._backend:
                try:
                    await self._backend.capture_screenshot(device, str(png_path))
                except Exception as backend_error:
                    logger.warning(
                        f"  ⚠️ [debug_snapshot] Backend screenshot unavailable for {label}: {backend_error}; falling back to ADB"
                    )
                    await self._adb._run_adb(
                        device, "shell", "screencap", "-p", "/sdcard/_debug_screen.png"
                    )
                    await self._adb._run_adb(
                        device, "pull", "/sdcard/_debug_screen.png", str(png_path)
                    )
                    await self._adb._run_adb(
                        device, "shell", "rm", "-f", "/sdcard/_debug_screen.png"
                    )
            else:
                await self._adb._run_adb(
                    device, "shell", "screencap", "-p", "/sdcard/_debug_screen.png"
                )
                await self._adb._run_adb(
                    device, "pull", "/sdcard/_debug_screen.png", str(png_path)
                )
                await self._adb._run_adb(
                    device, "shell", "rm", "-f", "/sdcard/_debug_screen.png"
                )

            screenshot_path = str(jpg_path if jpg_path.exists() else png_path)
        except Exception as e:
            screenshot_error = str(e)
            logger.warning(f"  ⚠️ [debug_snapshot] Screenshot failed for {label}: {e}")

        try:
            await self.dump_ui_xml(device, str(xml_path))
        except Exception as e:
            xml_error = str(e)
            logger.warning(f"  ⚠️ [debug_snapshot] UI XML failed for {label}: {e}")

        try:
            foreground_app = await self.get_foreground_app(device)
        except Exception as e:
            logger.warning(f"  ⚠️ [debug_snapshot] Foreground app failed for {label}: {e}")

        metadata = {
            "label": label,
            "note": note,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "device": device,
            "foreground_app": foreground_app,
            "screenshot_path": screenshot_path,
            "ui_xml_path": str(xml_path) if xml_path.exists() else "",
            "screenshot_error": screenshot_error,
            "ui_xml_error": xml_error,
        }
        meta_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata

    async def recover(self, device: str) -> bool:
        """Re-open TikTok if it's not in foreground.

        Returns True if recovery was needed and successful.
        """
        if await self.is_tiktok_foreground(device):
            return False

        logger.warning("🔄 TikTok not in foreground — recovering...")
        await self._get_backend(device)

        # Try pressing BACK first (maybe hit a dialog)
        if self._backend:
            try:
                await self._backend.key_event(device, "BACK")
            except Exception as e:
                logger.warning(f"  ⚠️ [recover] Backend BACK failed, fallback ADB: {e}")
                self._backend = None
                await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        else:
            # FALLBACK: ADB
            await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        await asyncio.sleep(1)

        if await self.is_tiktok_foreground(device):
            logger.info("  ✅ Recovered via BACK key")
            return True

        # Re-launch TikTok
        if self._backend:
            try:
                await self._backend.launch_app(device, TIKTOK_PACKAGE)
            except Exception as e:
                logger.warning(f"  ⚠️ [recover] Backend launch failed, fallback ADB: {e}")
                self._backend = None
                await self._adb._run_adb(
                    device, "shell", "monkey", "-p", TIKTOK_PACKAGE,
                    "-c", "android.intent.category.LAUNCHER", "1"
                )
        else:
            # FALLBACK: ADB monkey launch
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
            if not await self.is_tiktok_foreground(device):
                await self.recover(device)
                await asyncio.sleep(1.0)
                if not await self.is_tiktok_foreground(device):
                    logger.warning("  ⚠️ [dismiss_popups] TikTok not foreground; skip")
                    break

            # Re-dump fresh UI
            try:
                await asyncio.wait_for(
                    self._adb._run_adb(
                        device, "shell", "uiautomator", "dump", "/sdcard/_ui.xml"
                    ),
                    timeout=8.0,
                )
                _, xml_raw, _ = await asyncio.wait_for(
                    self._adb._run_adb(
                        device, "shell", "cat", "/sdcard/_ui.xml"
                    ),
                    timeout=8.0,
                )
            except Exception as e:
                logger.warning(f"  ⚠️ [dismiss_popups] UI dump timeout/error: {e}")
                continue

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
                texts_lower: set[str] = set()
                descs_lower: set[str] = set()
                for node in root.iter("node"):
                    text = (node.get("text", "") or "").strip().lower()
                    desc = (node.get("content-desc", "") or "").strip().lower()
                    if text:
                        texts_lower.add(text)
                    if desc:
                        descs_lower.add(desc)

                has_feed = self._looks_like_feed_signature(texts_lower, descs_lower)

                if not has_feed:
                    # Not on feed — try BACK to escape webview/LIVE
                    if self._backend:
                        try:
                            await self._backend.key_event(device, "BACK")
                        except Exception as e:
                            logger.warning(
                                f"  ⚠️ [dismiss_popups] Backend BACK failed, fallback ADB: {e}"
                            )
                            self._backend = None
                            await self._adb._run_adb(
                                device, "shell", "input", "keyevent", "4"
                            )
                    else:
                        # FALLBACK: ADB
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
        deadline = asyncio.get_event_loop().time() + 25.0
        for attempt in range(3):
            if asyncio.get_event_loop().time() > deadline:
                break

            if not await self.is_tiktok_foreground(device):
                await self.recover(device)
                await asyncio.sleep(1.0)
                if not await self.is_tiktok_foreground(device):
                    continue

            # Dismiss startup overlays/popups first.
            await self.dismiss_popups(device, max_attempts=2)

            state = await self.detect_upload_state(device)
            if state == "feed":
                return True

            # Try Home tab by semantic locator.
            elements = await self.dump_ui(device)
            home_el = self.find_element(elements, "home")
            if home_el and home_el.bounds[1] > 0:
                x, y = home_el.center
                await self._realistic_tap(device, x, y, duration_ms=90)
                await asyncio.sleep(1.2)
                if await self.detect_upload_state(device) == "feed":
                    logger.info("  📱 Navigated to Home/feed")
                    return True

            # Last fallback: tap typical bottom-left Home nav area.
            w, h = await self._get_screen_size(device)
            fx = int(w * 0.12) + random.randint(-8, 8)
            fy = int(h * 0.96) + random.randint(-6, 6)
            logger.info(f"  ⚠️ [ensure_feed] Fallback Home tap at ({fx}, {fy})")
            await self._realistic_tap(device, fx, fy, duration_ms=90)
            await asyncio.sleep(1.2)
            if await self.detect_upload_state(device) == "feed":
                return True

        logger.warning("  ⚠️ [ensure_feed] Could not confirm TikTok feed")
        return False

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
        0. Try AccessibilityBackend (ACTION_SET_TEXT — full Unicode support!)
        1. Try ADBKeyboard broadcast (best for Unicode)
        2. Try clipboard via service call + paste keyevent
        3. Use 'input text' (works for ASCII only)
        4. Last resort: strip to ASCII and use 'input text'
        """
        is_ascii = all(ord(c) < 128 for c in text)

        # For Unicode text, force-attempt Accessibility type path first
        # even when current run is pinned to ADB backend.
        if not is_ascii:
            try:
                from app.services.backend_manager import backend_manager

                if await backend_manager.accessibility.ping(device):
                    await backend_manager.accessibility.type_text(device, text)
                    await asyncio.sleep(0.4)
                    if await self._verify_text_entered(device, text):
                        logger.info("  ✅ [type_text] Accessibility Unicode input verified")
                        return True
                    logger.warning(
                        "  ⚠️ [type_text] Accessibility Unicode input not visible, falling back"
                    )
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [type_text] Accessibility Unicode path failed: {e}")

        # Lazy-init run backend (often ADB for upload flow).
        await self._get_backend(device)

        if self._backend:
            try:
                await self._backend.type_text(device, text)
                await asyncio.sleep(0.4)
                if await self._verify_text_entered(device, text):
                    logger.info("  ✅ [type_text] Backend input verified")
                    return True
                logger.warning(
                    "  ⚠️ [type_text] Backend input not visible in EditText, trying fallbacks"
                )
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [type_text] Backend failed, fallback ADB: {e}")
                self._backend = None

        if is_ascii:
            normalized = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
            special_chars = ' &|;<>"\'()'
            escaped = ''.join(
                ("%s" if c == " " else (f'\\{c}' if c in special_chars else c))
                for c in normalized
            )
            await self._adb._run_adb(device, "shell", "input", "text", escaped)
            await asyncio.sleep(0.4)
            if await self._verify_text_entered(device, text):
                logger.info(f"  ✅ [type_text] ASCII input OK: '{normalized}'")
                return True
            logger.warning("  ⚠️ [type_text] ASCII input sent but not verified")

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
        ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        ascii_text = re.sub(r"\s+", " ", ascii_text.replace("\n", " ")).strip()
        if not ascii_text:
            # If no ASCII chars at all, use a generic emoji/emoticon comment
            ascii_text = ":)"
        special_chars = ' &|;<>"\'()'
        escaped = ''.join(
            ("%s" if c == " " else (f'\\{c}' if c in special_chars else c))
            for c in ascii_text
        )
        await self._adb._run_adb(device, "shell", "input", "text", escaped)
        await asyncio.sleep(0.4)
        ok = await self._verify_text_entered(device, text) or await self._verify_text_entered(device, ascii_text)
        if ok:
            logger.warning(
                f"  ⚠️ [type_text] Used ASCII fallback: '{ascii_text}' (original: '{text}')"
            )
        else:
            logger.warning("  ❌ [type_text] All input methods exhausted without verification")
        return ok

    async def _verify_text_entered(
        self,
        device: str,
        expected_text: str | None = None,
        *,
        strict: bool = False,
    ) -> bool:
        """Verify that text was actually typed into the focused EditText.

        Returns True only if EditText contains actual content (not placeholder).
        """
        # Placeholder/hint texts to ignore
        placeholders = {"add comment...", "add a comment...", "thêm bình luận...",
                        "viết bình luận...", "say something...", "add comment"}
        expected_tokens = self._expected_text_tokens(expected_text or "")
        expected_tokens_folded = {self._fold_text(token) for token in expected_tokens}
        expected_raw = re.sub(r"\s+", " ", (expected_text or "").strip())
        expected_folded = self._fold_text(expected_raw)

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

            if expected_text is None:
                logger.info(f"  🔍 [verify] Text in EditText: '{text_content[:40]}'")
                return True

            content_folded = self._fold_text(text_content)
            if expected_raw and content_folded == expected_folded:
                logger.info("  🔍 [verify] Exact EditText match: '%s'", text_content[:40])
                return True

            if expected_text and self._comment_match_strength(expected_text, text_content):
                logger.info("  🔍 [verify] Strong text match in EditText")
                return True

            if strict:
                logger.warning("  ⚠️ [verify] Strict text check failed for EditText")
                continue

            for token in expected_tokens_folded:
                if token and token in content_folded:
                    logger.info(
                        "  🔍 [verify] Matched caption token in EditText: '%s'",
                        token[:24],
                    )
                    return True
        if expected_text is not None:
            logger.warning("  ⚠️ [verify] Expected text tokens not found in EditText")
        return False

    async def _find_pink_send_button(self, device: str) -> tuple[int, int] | None:
        """Find TikTok's active Send button via screenshot color analysis.

        The Send button is invisible to the UI tree, so we detect the bright
        pink/red circle from a PNG screenshot. Raw `screencap` bytes proved
        unreliable across devices because channel ordering can differ; using a
        decoded PNG/JPEG image is much more stable.
        """
        try:
            input_bounds = None
            try:
                elements = await self.dump_ui(device)
                input_bounds = self._get_comment_input_bounds(elements)
            except Exception:
                input_bounds = None

            image = await self._capture_send_scan_image(device)
            if image is None:
                return None
            return self._locate_send_button_in_image(image, input_bounds=input_bounds)
        except Exception as e:
            logger.warning(f"  ⚠️ [find_pink] Error: {e}")
            return None

    async def _capture_analysis_image(self, device: str, *, prefix: str):
        """Capture a decoded screenshot image for lightweight visual heuristics."""
        from PIL import Image

        local_path = os.path.join(
            tempfile.gettempdir(),
            f"_{prefix}_{device.replace(':', '_')}_{random.randint(1000, 9999)}.png",
        )
        remote_path = f"/sdcard/_{prefix}.png"

        try:
            await self._get_backend(device)
            if self._backend:
                try:
                    await self._backend.capture_screenshot(device, local_path)
                    with Image.open(local_path) as image:
                        return image.convert("RGB")
                except Exception as e:
                    await self._record_backend_issue(device, e)
                    logger.warning(
                        "  ⚠️ [find_pink] Backend screenshot failed, fallback ADB: %s",
                        e,
                    )

            ret, _, stderr = await self._adb._run_adb(
                device, "shell", "screencap", "-p", remote_path
            )
            if ret != 0:
                logger.warning("  ⚠️ [find_pink] screencap failed: %s", stderr)
                return None

            ret, _, stderr = await self._adb._run_adb(device, "pull", remote_path, local_path)
            if ret != 0:
                logger.warning("  ⚠️ [find_pink] pull failed: %s", stderr)
                return None

            with Image.open(local_path) as image:
                return image.convert("RGB")
        finally:
            try:
                os.remove(local_path)
            except OSError:
                pass
            try:
                await self._adb._run_adb(device, "shell", "rm", "-f", remote_path)
            except Exception:
                pass

    async def _capture_send_scan_image(self, device: str):
        """Capture a PNG-like screenshot for send-button detection."""
        return await self._capture_analysis_image(device, prefix="send_scan")

    def _locate_send_button_in_image(
        self,
        image,
        *,
        input_bounds: tuple[int, int, int, int] | None = None,
    ) -> tuple[int, int] | None:
        """Locate the pink send button from a decoded screenshot image."""
        rgb = image.convert("RGB")
        w, h = rgb.size

        windows: list[tuple[int, int, int, int, str]] = []
        if input_bounds:
            _, top, right, bottom = input_bounds
            lane_top = max(int(h * 0.42), top - 120)
            lane_bottom = min(int(h * 0.86), bottom + 140)
            windows.append((
                max(int(w * 0.82), right - 140),
                lane_top,
                w,
                lane_bottom,
                "tight_lane",
            ))
            windows.append((
                max(int(w * 0.78), right - 220),
                lane_top,
                w,
                min(int(h * 0.88), bottom + 220),
                "expanded_lane",
            ))

        windows.append((int(w * 0.80), int(h * 0.44), w, int(h * 0.86), "fallback_right"))

        for x_start, y_start, x_end, y_end, label in windows:
            pink_points: list[tuple[int, int]] = []
            for y in range(y_start, y_end, 2):
                for x in range(x_start, x_end, 2):
                    r, g, b = rgb.getpixel((x, y))
                    if r > 205 and g < 135 and b < 190 and (r - g) > 55 and (r - b) > 20:
                        pink_points.append((x, y))

            if len(pink_points) < 20:
                logger.warning(
                    "  ⚠️ [find_pink] Too few pink pixels (%s) in %s",
                    len(pink_points),
                    label,
                )
                continue

            remaining = set(pink_points)
            components: list[list[tuple[int, int]]] = []
            while remaining:
                seed = remaining.pop()
                stack = [seed]
                component = [seed]
                while stack:
                    px, py = stack.pop()
                    for dx in (-2, 0, 2):
                        for dy in (-2, 0, 2):
                            if dx == 0 and dy == 0:
                                continue
                            neighbor = (px + dx, py + dy)
                            if neighbor in remaining:
                                remaining.remove(neighbor)
                                stack.append(neighbor)
                                component.append(neighbor)
                components.append(component)

            best: tuple[int, int] | None = None
            best_score = -1
            for component in components:
                xs = [pt[0] for pt in component]
                ys = [pt[1] for pt in component]
                cx = (min(xs) + max(xs)) // 2
                cy = (min(ys) + max(ys)) // 2
                bw = max(xs) - min(xs)
                bh = max(ys) - min(ys)

                if bw < 30 or bw > 180 or bh < 30 or bh > 180:
                    continue
                if cx < int(w * 0.80):
                    continue

                score = len(component)
                if score > best_score:
                    best = (cx, cy)
                    best_score = score

            if best:
                logger.info(
                    "  🎯 [find_pink] Send button via %s at (%s,%s) component_pixels=%s",
                    label,
                    best[0],
                    best[1],
                    best_score,
                )
                return best

        return None

    async def _find_text_send_button(self, device: str) -> tuple[int, int] | None:
        """Find a visible text-based Send/Post button for non-overlay variants."""
        elements = await self.dump_ui(device)
        send_patterns = [
            re.compile(r"Post$", re.IGNORECASE),
            re.compile(r"^Send$", re.IGNORECASE),
            re.compile(r"^Đăng$", re.IGNORECASE),
            re.compile(r"^Gửi$", re.IGNORECASE),
            re.compile(r"send comment", re.IGNORECASE),
            re.compile(r"post comment", re.IGNORECASE),
        ]

        for el in elements:
            desc = el.content_desc
            text = el.text
            for pat in send_patterns:
                if (desc and pat.search(desc)) or (text and pat.search(text)):
                    logger.info(
                        "  🎯 [find_send_text] Found text button '%s' at (%s, %s)",
                        text or desc,
                        el.center[0],
                        el.center[1],
                    )
                    return el.center
        return None

    async def _get_send_button_target(self, device: str) -> tuple[tuple[int, int] | None, str]:
        """Return the active send button target and detection source."""
        pos = await self._find_pink_send_button(device)
        if pos:
            return pos, "pink"

        pos = await self._find_text_send_button(device)
        if pos:
            return pos, "text"

        return None, "none"

    async def _adb_input_ascii_fragment(self, device: str, text: str) -> bool:
        """Inject a tiny ASCII fragment via raw ADB to trigger real IME watchers."""
        normalized = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
        if text == " ":
            normalized = "%s"
        elif not normalized:
            return False

        special_chars = ' &|;<>"\'()'
        escaped = ''.join(
            ("%s" if c == " " else (f'\\{c}' if c in special_chars else c))
            for c in normalized
        )
        code, _, stderr = await self._adb._run_adb(
            device, "shell", "input", "text", escaped
        )
        if code != 0:
            logger.warning("  ⚠️ [comment_nudge] ADB text fragment failed: %s", stderr)
            return False
        return True

    async def ensure_comment_send_ready(self, device: str, comment_text: str) -> bool:
        """Ensure TikTok has actually enabled the Send button after text entry.

        TikTok sometimes displays text in the EditText but keeps the Send
        button disabled because the field was populated programmatically.
        We detect the active send target first; if absent, force a tiny real
        input change via ADB (insert char + delete) to trigger TextWatcher.
        """
        pos, source = await self._get_send_button_target(device)
        if pos:
            logger.info("  ✅ [send_ready] Active send button via %s", source)
            return True

        logger.warning(
            "  ⚠️ [send_ready] Text is present but no active send button for '%s'",
            comment_text[:40],
        )

        # Re-focus to make sure the field still owns the IME.
        await self.tap_comment_input(device)
        await asyncio.sleep(0.3)

        nudges = [
            ("ascii-char", "x"),
            ("space", " "),
        ]
        for label, fragment in nudges:
            logger.info("  🔄 [send_ready] Trying %s nudge", label)
            injected = await self._adb_input_ascii_fragment(device, fragment)
            if not injected:
                continue
            await asyncio.sleep(0.2)
            await self._adb._run_adb(device, "shell", "input", "keyevent", "67")
            await asyncio.sleep(0.5)

            pos, source = await self._get_send_button_target(device)
            if pos:
                logger.info(
                    "  ✅ [send_ready] Send button activated after %s nudge via %s",
                    label,
                    source,
                )
                return True

        logger.warning("  ❌ [send_ready] Send button never activated after nudges")
        await self.capture_verification_screenshot(device, "comment_send_inactive")
        return False

    async def _realistic_tap(self, device: str, x: int, y: int, duration_ms: int = 80):
        """Tap with realistic press duration.

        TikTok SILENTLY REJECTS instant 0ms taps from 'input tap' as bot
        behavior. Uses a swipe-to-same-point with duration to simulate a
        real finger press-and-release that TikTok accepts.

        Prioritizes Accessibility backend (dispatchGesture with duration)
        over ADB 'input swipe' for consistency.
        """
        dur = duration_ms + random.randint(-20, 20)
        dur = max(40, dur)
        await self._get_backend(device)
        if self._backend:
            try:
                # Accessibility: swipe to same point = press with duration
                await self._backend.swipe(device, x, y, x, y, dur)
                return
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [realistic_tap] Backend failed, fallback ADB: {e}")
                self._backend = None

        # FALLBACK: ADB input swipe
        await self._adb._run_adb(
            device, "shell", "input", "swipe",
            str(x), str(y), str(x), str(y), str(dur)
        )

    async def send_comment(self, device: str, allow_blind_fallback: bool = True) -> bool:
        """Tap Send button to post comment.

        TikTok's Send button (pink arrow ↑ icon) is INVISIBLE to uiautomator
        dump — it's rendered as a SurfaceView overlay that the UI hierarchy
        cannot see. We use raw screencap pixel analysis to find it.

        CRITICAL: Must use _realistic_tap (80ms swipe-tap) instead of
        _tap (0ms instant). TikTok silently rejects 0ms taps as bot behavior.

        Strategy:
        1. Screenshot → find pink Send button via pixel color detection
        2. UI dump → find Send/Post button by text (fallback for other TikTok versions)
        3. Hardcoded fallback coordinates
        """
        # 1-2. Prefer detected active send targets only.
        pos, source = await self._get_send_button_target(device)
        if pos:
            x, y = pos
            x += random.randint(-3, 3)
            y += random.randint(-3, 3)
            logger.info(f"  🎯 [send_comment] {source} button at ({x}, {y})")
            await self._realistic_tap(device, x, y)
            return True

        if not allow_blind_fallback:
            logger.warning("  ❌ [send_comment] No active send target detected; refusing blind tap")
            return False

        # 3. LAST RESORT: hardcoded position for 1080-wide screens
        w, h = await self._get_screen_size(device)
        # Send button is at ~89% X, ~57% Y (when keyboard is open)
        x = int(w * 0.89) + random.randint(-5, 5)
        y = int(h * 0.575) + random.randint(-5, 5)
        logger.warning(f"  ⚠️ [send_comment] Using hardcoded fallback ({x}, {y})")
        await self._realistic_tap(device, x, y)
        return True

    async def close_panel(self, device: str) -> bool:
        """Close comment panel reliably.

        TikTok needs up to 2 BACKs: 1st closes keyboard, 2nd closes panel.
        Verifies panel is actually closed before returning.
        """
        for attempt in range(3):
            await self._get_backend(device)
            if self._backend:
                try:
                    await self._backend.key_event(device, "BACK")
                except Exception as e:
                    await self._record_backend_issue(device, e)
                    logger.warning(f"  ⚠️ [close_panel] Backend BACK failed, fallback ADB: {e}")
                    self._backend = None
                    await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
            else:
                # FALLBACK: ADB
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
            try:
                await self._backend.key_event(device, "BACK")
            except Exception as e:
                await self._record_backend_issue(device, e)
                logger.warning(f"  ⚠️ [close_panel] Last BACK failed, fallback ADB: {e}")
                self._backend = None
                await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        else:
            # FALLBACK: ADB
            await self._adb._run_adb(device, "shell", "input", "keyevent", "4")
        await asyncio.sleep(0.5)
        return True

    async def swipe_next(self, device: str) -> bool:
        """Swipe up to next video (Accessibility preferred)."""
        w, h = await self._get_screen_size(device)
        x = w // 2 + random.randint(-30, 30)
        y1 = int(h * 0.75) + random.randint(-20, 20)
        y2 = int(h * 0.25) + random.randint(-20, 20)
        dur = random.randint(250, 450)
        await self._get_backend(device)
        if self._backend:
            await self._backend.swipe(device, x, y1, x, y2, dur)
        else:
            # FALLBACK: ADB
            await self._adb._run_adb(
                device, "shell", "input", "swipe",
                str(x), str(y1), str(x), str(y2), str(dur)
            )
        return True

    # ---- Post-action verification methods ----

    async def get_like_button_state(self, device: str) -> dict:
        """Get the current state of the like button.

        Returns dict with:
        - found: bool — whether button was found
        - liked: bool — whether video is currently liked
        - desc: str — raw content-desc text
        """
        elements = await self.dump_ui(device)
        el = self.find_element(elements, "like")
        if not el:
            return {"found": False, "liked": False, "desc": ""}

        desc = el.content_desc.lower() if el.content_desc else ""
        # TikTok uses "Unlike" or "Liked" when already liked
        is_liked = any(kw in desc for kw in ["unlike", "liked", "bỏ thích"])
        return {"found": True, "liked": is_liked, "desc": el.content_desc}

    async def verify_like_state(
        self, device: str, expected_liked: bool = True
    ) -> bool:
        """Verify the like button is in the expected state.

        Call AFTER tapping like. Checks if content-desc changed to
        "Unlike video" (= liked) vs "Like video" (= not liked).

        Returns True if button state matches expected.
        """
        await asyncio.sleep(1)  # Give UI time to update
        state = await self.get_like_button_state(device)
        if not state["found"]:
            logger.warning("  ❓ [verify_like] Like button not found in UI dump")
            return False

        matched = state["liked"] == expected_liked
        if matched:
            logger.info(f"  ✅ [verify_like] Confirmed: liked={state['liked']} ('{state['desc'][:40]}')")
        else:
            logger.warning(
                f"  ❌ [verify_like] State mismatch: expected liked={expected_liked}, "
                f"got liked={state['liked']} ('{state['desc'][:40]}')"
            )
        return matched

    async def verify_comment_posted(
        self,
        device: str,
        comment_text: str,
        timeout: float = 3.0,
        baseline_comments: list[dict] | None = None,
        attempts: int = 3,
        poll_interval: float = 1.2,
    ) -> bool:
        """Verify a comment was successfully posted.

        Success requires strong evidence that the new comment is visible in the
        current panel after tapping Send. Input cleared alone is NOT enough.

        Args:
            device: ADB device target
            comment_text: The text that was sent
            timeout: Max seconds to wait before checking
        """
        await asyncio.sleep(timeout)
        baseline_texts = {
            self._normalize_comment_text((item or {}).get("text", ""))
            for item in (baseline_comments or [])
            if isinstance(item, dict)
        }
        baseline_texts = {text for text in baseline_texts if text}

        placeholders = {
            "add comment...", "add a comment...", "thêm bình luận...",
            "viết bình luận...", "say something...", "add comment",
            "replying to", "",
        }

        for attempt in range(max(1, attempts)):
            if attempt:
                await asyncio.sleep(poll_interval)

            elements = await self.dump_ui(device)

            has_edit_text = False
            edit_cleared = False
            edit_still_has_text = False
            for el in elements:
                if "EditText" not in el.cls:
                    continue
                has_edit_text = True
                text_content = (el.text or "").strip().lower()
                if text_content in placeholders or text_content.startswith("replying"):
                    edit_cleared = True
                elif self._comment_match_strength(comment_text, text_content):
                    edit_still_has_text = True
                break

            if not has_edit_text:
                logger.warning("  ❌ [verify_comment] Panel closed (no EditText) — send likely missed")
                return False

            if edit_still_has_text:
                logger.warning("  ❌ [verify_comment] Text still in field — send button missed")
                return False

            visible_texts = self._collect_comment_panel_texts(elements, max_count=30)
            matched_text = None
            for text in visible_texts:
                if not self._comment_match_strength(comment_text, text):
                    continue
                if self._comment_already_visible(text, baseline_texts):
                    logger.warning(
                        "  ⚠️ [verify_comment] Matched text already existed before send: '%s'",
                        text[:60],
                    )
                    continue
                matched_text = text
                break

            if matched_text:
                logger.info(
                    "  ✅ [verify_comment] CONFIRMED visible new comment: '%s'",
                    matched_text[:60],
                )
                return True

            if edit_cleared:
                logger.info(
                    "  ⏳ [verify_comment] Input cleared but comment not yet visible (%s/%s)",
                    attempt + 1,
                    max(1, attempts),
                )
            else:
                logger.warning(
                    "  ⚠️ [verify_comment] Input not cleared and comment not visible (%s/%s)",
                    attempt + 1,
                    max(1, attempts),
                )

        logger.warning("  ❌ [verify_comment] FAILED: no new visible comment after send")
        return False

    async def verify_follow_state(self, device: str) -> bool:
        """Verify follow action succeeded.

        After tapping Follow, the button text changes to:
        - "Following" / "Friends" (English)
        - "Đang follow" / "Bạn bè" (Vietnamese)
        - Or the Follow button disappears entirely

        Returns True if follow appears to have worked.
        """
        await asyncio.sleep(1.5)
        elements = await self.dump_ui(device)

        # Check if follow button still shows "Follow" (= not followed yet)
        follow_el = self.find_element(elements, "follow")
        if not follow_el:
            # Follow button gone = likely changed to "Following"
            # Look for Following/Friends text
            for el in elements:
                desc = (el.content_desc or "").lower()
                text = (el.text or "").lower()
                if any(kw in desc or kw in text for kw in
                       ["following", "friends", "đang follow", "bạn bè", "unfollow"]):
                    logger.info(f"  ✅ [verify_follow] Confirmed: '{el.text or el.content_desc}'")
                    return True

            # Follow button gone but no "Following" found — ambiguous
            logger.info("  ✅ [verify_follow] Follow button gone (likely succeeded)")
            return True

        # Follow button still present — check if it now says "Following"
        desc = (follow_el.content_desc or "").lower()
        text = (follow_el.text or "").lower()
        if any(kw in desc or kw in text for kw in ["following", "friends", "đang follow"]):
            logger.info(f"  ✅ [verify_follow] Confirmed via button text change")
            return True

        logger.warning(f"  ❌ [verify_follow] Still showing Follow button: '{follow_el.content_desc}'")
        return False

    async def capture_verification_screenshot(
        self, device: str, action_name: str
    ) -> str:
        """Capture a debug screenshot for verification failures.

        Saves to /sdcard/_verify_{action}_{timestamp}.png on device,
        then pulls to local screenshots/ directory.

        TODO: [ACCESSIBILITY-MIGRATE] Use backend.capture_screenshot()
        which sends screenshot via WebSocket (no file I/O on device).

        Returns local file path or empty string on failure.
        """
        import time
        ts = int(time.time())
        remote_path = f"/sdcard/_verify_{action_name}_{ts}.png"
        local_dir = "screenshots"

        try:
            import os
            os.makedirs(local_dir, exist_ok=True)
            local_path = os.path.join(local_dir, f"verify_{action_name}_{ts}.png")

            await self._adb._run_adb(
                device, "shell", "screencap", "-p", remote_path
            )
            await self._adb._run_adb(
                device, "pull", remote_path, local_path
            )
            # Clean up remote file
            await self._adb._run_adb(
                device, "shell", "rm", "-f", remote_path
            )
            logger.info(f"  📸 [verify_screenshot] Saved: {local_path}")
            return local_path
        except Exception as e:
            logger.warning(f"  ⚠️ [verify_screenshot] Failed to capture: {e}")
            return ""

    async def get_comment_count(self, device: str) -> int | None:
        """Get current comment count from the comment icon.

        Returns int count or None if not found.
        """
        elements = await self.dump_ui(device)
        el = self.find_element(elements, "comment")
        if not el or not el.content_desc:
            return None

        # Parse count from "Read or add comments. 1234"
        m = re.search(r"([\d,.]+)", el.content_desc)
        if m:
            count_str = m.group(1).replace(",", "").replace(".", "")
            try:
                return int(count_str)
            except ValueError:
                pass
        return None
