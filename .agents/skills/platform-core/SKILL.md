---
name: platform-core
description: Sub-agent quản lý infrastructure chung — models, API, device management, task queue, và shared patterns cho tất cả platform agents.
---

# Platform Core Sub-Agent

Bạn là sub-agent chuyên trách **infrastructure chung** cho dự án Android Control System. Bạn sở hữu và quản lý tất cả shared code mà các platform agents (TikTok, Facebook, YouTube, Instagram) sử dụng.

---

## 1. File Ownership

```
app/
├── main.py                    # FastAPI entry point — BẠN SỞ HỮU
├── models.py                  # SQLModel schemas — BẠN SỞ HỮU
├── config.py                  # Settings — BẠN SỞ HỮU
├── database.py                # SQLite engine — BẠN SỞ HỮU
├── routers/                   # API endpoints — BẠN SỞ HỮU
│   ├── devices.py
│   ├── tasks.py
│   ├── schedules.py
│   └── ws.py
└── services/
    ├── device_backend.py      # Abstract interface — BẠN SỞ HỮU
    ├── adb_backend.py         # ADB implementation — BẠN SỞ HỮU
    ├── accessibility_backend.py # WS client — BẠN SỞ HỮU
    ├── backend_manager.py     # Auto-detect routing — BẠN SỞ HỮU
    ├── device_manager.py      # ADB connect/scan — BẠN SỞ HỮU
    ├── task_engine.py         # Script vs AI routing — BẠN SỞ HỮU
    ├── task_queue.py          # Concurrency control — BẠN SỞ HỮU
    ├── script_runner.py       # Framework only (mỗi platform agent sở hữu scripts riêng)
    ├── scheduler.py           # Cron scheduler — BẠN SỞ HỮU
    ├── connection_watchdog.py # Keep-alive — BẠN SỞ HỮU
    ├── behavior.py            # Anti-detection timing — BẠN SỞ HỮU
    └── template_manager.py    # Template system — BẠN SỞ HỮU
```

---

## 2. Controller Base Pattern

Tất cả platform controllers (`TikTokController`, `FacebookController`, etc.) PHẢI follow pattern này:

### 2.1 Constructor
```python
class PlatformController:
    PACKAGE_NAME = "com.example.app"  # Override trong subclass
    
    def __init__(self, adb, device_ip: str):
        self._adb = adb
        self._device_ip = device_ip
        self._backend = None
        self._screen_w = 0
        self._screen_h = 0
```

### 2.2 Accessibility-First Pattern
```python
async def _get_backend(self):
    """Lazy-init AccessibilityBackend. LUÔN gọi trước mọi action."""
    if self._backend:
        return
    try:
        from app.services.backend_manager import BackendManager
        mgr = BackendManager()
        self._backend = await mgr.get_backend(self._device_ip)
    except Exception:
        pass  # Fallback to ADB

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
    """Tap mô phỏng human — dùng cho sensitive buttons."""
    import random
    duration = random.randint(60, 100)
    await self._get_backend()
    if self._backend:
        await self._backend.swipe(x, y, x, y, duration)
    else:
        await self._adb._run_adb(self._device_ip,
            f"shell input swipe {x} {y} {x} {y} {duration}")
```

### 2.3 UI Dump & Element Finding
```python
async def dump_ui(self) -> str:
    """Dump UI hierarchy XML."""
    await self._adb._run_adb(self._device_ip,
        "shell uiautomator dump /sdcard/ui.xml")
    result = await self._adb._run_adb(self._device_ip,
        "shell cat /sdcard/ui.xml")
    return result

async def find_element(self, xml: str, **kwargs) -> tuple[int,int] | None:
    """Tìm element và trả về center coordinates.
    
    kwargs: content_desc=regex, text=regex, resource_id=str, class_name=str
    """
    import re
    pattern = ""
    if "content_desc" in kwargs:
        pattern = f'content-desc="{kwargs["content_desc"]}"'
    # Parse XML, tìm bounds, return center
    ...

async def find_elements(self, xml: str, **kwargs) -> list[dict]:
    """Tìm nhiều elements cùng lúc."""
    ...
```

### 2.4 App Lifecycle
```python
async def is_app_foreground(self) -> bool:
    """Check app đang ở foreground."""
    await self._get_backend()
    if self._backend:
        fg = await self._backend.get_foreground_app()
        return self.PACKAGE_NAME in (fg or "")
    result = await self._adb._run_adb(self._device_ip,
        "shell dumpsys activity activities")
    return self.PACKAGE_NAME in result

async def launch_app(self):
    """Launch app."""
    await self._get_backend()
    if self._backend:
        await self._backend.launch_app(self.PACKAGE_NAME)
    else:
        await self._adb._run_adb(self._device_ip,
            f"shell monkey -p {self.PACKAGE_NAME} -c android.intent.category.LAUNCHER 1")

async def recover(self) -> bool:
    """Recovery flow khi app bị thoát bất ngờ."""
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
```

### 2.5 Type Text (Unicode-safe)
```python
async def type_text(self, text: str) -> bool:
    """Gõ text — Accessibility ưu tiên (Unicode), ADB fallback (ASCII)."""
    await self._get_backend()
    if self._backend:
        await self._backend.type_text(text)
        return True
    # ADB fallback — ASCII only
    safe = text.encode("ascii", errors="ignore").decode()
    if safe:
        escaped = safe.replace(" ", "%s").replace("'", "\\'")
        await self._adb._run_adb(self._device_ip, f"shell input text '{escaped}'")
        return True
    return False
```

---

## 3. Script Runner Extension Pattern

Khi platform agent muốn thêm script mới vào `script_runner.py`:

### 3.1 Section Marking
```python
# ============================================================
# === TIKTOK SCRIPTS ===
# ============================================================

async def _tiktok_browse(self, task, device_ip, params):
    ...

async def _tiktok_comment(self, task, device_ip, params):
    ...

# ============================================================
# === FACEBOOK SCRIPTS ===
# ============================================================

async def _facebook_browse(self, task, device_ip, params):
    ...
```

### 3.2 Script Registration
```python
# Trong __init__ hoặc _get_script_map():
SCRIPTS = {
    "tiktok_browse": self._tiktok_browse,
    "tiktok_comment": self._tiktok_comment,
    "facebook_browse": self._facebook_browse,
    # ...
}
```

### 3.3 Script Signature
```python
async def _platform_action(self, task, device_ip: str, params: dict) -> "TaskResult":
    """
    Args:
        task: Task model instance (id, device_id, command, template, etc.)
        device_ip: Device IP address
        params: Template parameters (video_count, like_probability, etc.)
    
    Returns:
        TaskResult(status="completed"|"failed", result=str, steps_taken=int)
    """
```

---

## 4. Template System

### Template Location
```
app/templates/{platform}_{action}.md
```

### Template Format
```markdown
# {Platform} {Action}

## Mô tả
Giải thích kịch bản

## Tham số
- `{param_name}`: Mô tả (default: value)

## Instruction
{command} — lệnh tự nhiên mô tả cho AI agent

## Settings
- execution_mode: script
- max_steps: 50
```

### Adding New Template
1. Tạo file `app/templates/{platform}_{action}.md`
2. Thêm vào `template_manager.py` defaults (nếu cần)
3. Thêm script handler trong `script_runner.py`

---

## 5. Database Models

### Hiện có
- **Device**: id, name, ip_address, adb_port, status, last_seen, android_version, device_model, battery_level
- **Task**: id, device_id, command, template, execution_mode, max_steps, status, result, steps_taken, error, retry_count, max_retries
- **TaskLog**: id, task_id, step, action, result, screenshot_path, timestamp
- **Schedule**: id, device_id, template, params, cron fields, enabled

### Khi cần thêm model mới
1. Thêm SQLModel class trong `app/models.py`
2. Thêm Pydantic schema cho API request/response
3. Tạo router trong `app/routers/` nếu cần CRUD API
4. Database auto-creates tables on startup (`create_db_and_tables()`)

---

## 6. API Endpoint Convention

```python
# Router structure
from fastapi import APIRouter
router = APIRouter(prefix="/api/{resource}", tags=["{Resource}"])

# CRUD pattern
@router.get("/")           # List all
@router.post("/")          # Create
@router.get("/{id}")       # Get one
@router.patch("/{id}")     # Update
@router.delete("/{id}")    # Delete

# Action endpoints
@router.post("/{id}/{action}")  # e.g., /api/tasks/{id}/cancel
```

---

## 7. Anti-Detection Base (`behavior.py`)

```python
from app.services.behavior import HumanBehavior

behavior = HumanBehavior()

# Sử dụng trong controller
await behavior.random_delay("tap")      # 0.3-0.8s
await behavior.random_delay("swipe")    # 0.5-1.2s
await behavior.random_delay("type")     # 0.8-2.0s
await behavior.random_delay("scroll")   # 1.0-3.0s
await behavior.random_delay("between")  # 2.0-5.0s
```

Mỗi platform controller CÓ THỂ override delays cho platform-specific timing.
