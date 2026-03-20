# Controller Base Pattern

## Tổng quan

Mọi platform controller (`TikTokController`, `FacebookController`, etc.) đều follow cùng 1 pattern: **Accessibility-first, ADB fallback**.

## Template Code

```python
import asyncio
import logging
import re
import random
from app.services.behavior import HumanBehavior

logger = logging.getLogger(__name__)

class PlatformController:
    """Base controller cho platform automation.
    
    Pattern:
    1. Tất cả actions ưu tiên Accessibility backend
    2. ADB chỉ dùng khi Accessibility unavailable
    3. Post-action verification bắt buộc
    4. Anti-detection delays giữa actions
    """
    
    PACKAGE_NAME = "com.example.app"  # OVERRIDE trong subclass
    
    def __init__(self, adb, device_ip: str):
        self._adb = adb
        self._device_ip = device_ip
        self._backend = None
        self._screen_w = 0
        self._screen_h = 0
        self._behavior = HumanBehavior()
    
    # ─── Backend Init ───────────────────────────
    
    async def _get_backend(self):
        if self._backend:
            return
        try:
            from app.services.backend_manager import BackendManager
            mgr = BackendManager()
            self._backend = await mgr.get_backend(self._device_ip)
        except Exception as e:
            logger.debug(f"Accessibility not available: {e}")
    
    # ─── Core Actions ───────────────────────────
    
    async def _tap(self, x: int, y: int):
        await self._get_backend()
        if self._backend:
            await self._backend.tap(x, y)
        else:
            await self._adb._run_adb(self._device_ip, f"shell input tap {x} {y}")
    
    async def _swipe(self, x1, y1, x2, y2, duration=300):
        await self._get_backend()
        if self._backend:
            await self._backend.swipe(x1, y1, x2, y2, duration)
        else:
            await self._adb._run_adb(self._device_ip, 
                f"shell input swipe {x1} {y1} {x2} {y2} {duration}")
    
    async def _realistic_tap(self, x: int, y: int):
        """Human-like tap — dùng cho sensitive buttons."""
        duration = random.randint(60, 100)
        await self._get_backend()
        if self._backend:
            await self._backend.swipe(x, y, x, y, duration)
        else:
            await self._adb._run_adb(self._device_ip,
                f"shell input swipe {x} {y} {x} {y} {duration}")
    
    async def type_text(self, text: str) -> bool:
        await self._get_backend()
        if self._backend:
            await self._backend.type_text(text)
            return True
        safe = text.encode("ascii", errors="ignore").decode()
        if safe:
            escaped = safe.replace(" ", "%s").replace("'", "\\'")
            await self._adb._run_adb(self._device_ip, f"shell input text '{escaped}'")
            return True
        return False
    
    # ─── UI Analysis ────────────────────────────
    
    async def dump_ui(self) -> str:
        await self._adb._run_adb(self._device_ip, "shell uiautomator dump /sdcard/ui.xml")
        result = await self._adb._run_adb(self._device_ip, "shell cat /sdcard/ui.xml")
        return result
    
    async def _get_screen_size(self) -> tuple[int, int]:
        if self._screen_w and self._screen_h:
            return self._screen_w, self._screen_h
        await self._get_backend()
        if self._backend:
            size = await self._backend.get_screen_size()
            self._screen_w, self._screen_h = size["width"], size["height"]
        else:
            result = await self._adb._run_adb(self._device_ip, "shell wm size")
            match = re.search(r'(\d+)x(\d+)', result)
            if match:
                self._screen_w, self._screen_h = int(match.group(1)), int(match.group(2))
        return self._screen_w, self._screen_h
    
    # ─── App Lifecycle ──────────────────────────
    
    async def is_app_foreground(self) -> bool:
        await self._get_backend()
        if self._backend:
            fg = await self._backend.get_foreground_app()
            return self.PACKAGE_NAME in (fg or "")
        result = await self._adb._run_adb(self._device_ip, "shell dumpsys activity activities")
        return self.PACKAGE_NAME in result
    
    async def launch_app(self):
        await self._get_backend()
        if self._backend:
            await self._backend.launch_app(self.PACKAGE_NAME)
        else:
            await self._adb._run_adb(self._device_ip, 
                f"shell monkey -p {self.PACKAGE_NAME} -c android.intent.category.LAUNCHER 1")
    
    async def recover(self) -> bool:
        if await self.is_app_foreground():
            return True
        await self._get_backend()
        if self._backend:
            await self._backend.key_event("BACK")
        else:
            await self._adb._run_adb(self._device_ip, "shell input keyevent 4")
        await asyncio.sleep(1)
        if await self.is_app_foreground():
            return True
        await self.launch_app()
        await asyncio.sleep(3)
        return await self.is_app_foreground()
    
    # ─── Navigation ─────────────────────────────
    
    async def swipe_next(self):
        """Swipe lên — next item trong feed."""
        w, h = await self._get_screen_size()
        x = w // 2 + random.randint(-30, 30)
        start_y = int(h * 0.75)
        end_y = int(h * 0.25)
        duration = random.randint(250, 450)
        await self._swipe(x, start_y, x, end_y, duration)
    
    async def dismiss_popups(self, max_attempts: int = 5) -> int:
        """Dismiss common popups. Returns number dismissed."""
        dismissed = 0
        patterns = [
            "Got it", "Accept", "OK", "Allow", "Agree", 
            "Continue", "Not now", "Skip", "Close", "Dismiss", "Yes",
            "Đồng ý", "Bỏ qua", "Tiếp tục", "Đóng",
        ]
        for _ in range(max_attempts):
            xml = await self.dump_ui()
            found = False
            for pattern in patterns:
                match = re.search(
                    rf'text="{pattern}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                    xml, re.IGNORECASE
                )
                if match:
                    x = (int(match.group(1)) + int(match.group(3))) // 2
                    y = (int(match.group(2)) + int(match.group(4))) // 2
                    await self._tap(x, y)
                    dismissed += 1
                    found = True
                    await asyncio.sleep(1.5)
                    break
            if not found:
                break
        return dismissed
    
    # ─── Helpers ────────────────────────────────
    
    async def _wait(self, lo: float = 1.0, hi: float = 3.0):
        await asyncio.sleep(random.uniform(lo, hi))
    
    def _find_bounds(self, xml: str, content_desc_pattern: str) -> tuple[int,int] | None:
        """Tìm center coordinates của element theo content-desc regex."""
        match = re.search(
            rf'content-desc="[^"]*{content_desc_pattern}[^"]*"[^>]*'
            rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
            xml, re.IGNORECASE
        )
        if match:
            x = (int(match.group(1)) + int(match.group(3))) // 2
            y = (int(match.group(2)) + int(match.group(4))) // 2
            return (x, y)
        return None
```

## Subclass Example

```python
class FacebookController(PlatformController):
    PACKAGE_NAME = "com.facebook.katana"
    
    async def ensure_on_feed(self):
        if not await self.is_app_foreground():
            await self.recover()
        await self.dismiss_popups()
        # Check if on News Feed...
```
