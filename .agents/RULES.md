# 🏗️ Android Control — Global Rules

> Rules này áp dụng cho **TẤT CẢ agents** làm việc trên project Android Control.
> Mỗi agent PHẢI đọc file này trước khi bắt đầu bất kỳ công việc nào.

---

## 1. File Ownership Matrix

> [!CAUTION]
> **2 agents KHÔNG BAO GIỜ được sửa cùng 1 file.** Nếu cần sửa file thuộc agent khác, ghi yêu cầu vào `HANDOFF.md` và thông báo user.

| Agent | Files sở hữu | Skill |
|-------|--------------|-------|
| **TikTok Agent** | `app/services/tiktok_controller.py`, `app/templates/tiktok_*.md`, TikTok scripts trong `script_runner.py` | `.agents/skills/tiktok-agent/` |
| **Facebook Agent** | `app/services/facebook_controller.py`, `app/templates/facebook_*.md`, Facebook scripts trong `script_runner.py` | `.agents/skills/facebook-agent/` |
| **Google/YouTube Agent** | `app/services/youtube_controller.py`, `app/services/google_ads_controller.py`, `app/templates/youtube_*.md` | `.agents/skills/google-agent/` |
| **Instagram Agent** | `app/services/instagram_controller.py`, `app/templates/instagram_*.md`, Instagram scripts trong `script_runner.py` | `.agents/skills/instagram-agent/` |
| **AI Brain Agent** | `app/services/ai_strategy.py`, `app/services/campaign_manager.py`, `app/services/content_analyzer.py` | `.agents/skills/ai-brain/` |
| **UI Dashboard Agent** | `app/static/index.html`, `app/static/style.css`, `app/static/app.js` | `.agents/skills/ui-dashboard/` |
| **Platform Core Agent** | `app/main.py`, `app/models.py`, `app/database.py`, `app/config.py`, `app/routers/*`, `app/services/task_queue.py`, `app/services/task_engine.py`, `app/services/script_runner.py` (shared framework), `app/services/device_manager.py`, `app/services/backend_manager.py`, `app/services/behavior.py`, `app/services/scheduler.py` | `.agents/skills/platform-core/` |

### Shared Files (cần coordination)

| File | Ai được sửa | Điều kiện |
|------|-------------|-----------|
| `app/services/script_runner.py` | Platform agents + Core | Mỗi agent chỉ sửa **section scripts của mình** (marked bằng `# === TIKTOK SCRIPTS ===`, `# === FACEBOOK SCRIPTS ===`, etc.) |
| `app/models.py` | Core Agent | Platform agents đề xuất model changes qua `HANDOFF.md` |
| `app/main.py` | Core Agent | Platform agents đề xuất endpoint changes qua `HANDOFF.md` |

---

## 2. Environment Protection

> [!CAUTION]
> **KHÔNG BAO GIỜ:**
> - Tạo/xóa/sửa `venv/`, `.venv/`
> - Chạy `pip install`, `python -m venv`, hoặc bất kỳ lệnh thay đổi packages
> - Xóa/di chuyển `data/` directory
> - Hardcode absolute paths

Nếu cần package mới → ghi vào `pyproject.toml` + thông báo user.

---

## 3. Git Workflow

```bash
# Trước khi bắt đầu
git status
git stash  # nếu có changes

# Branch naming: feat/<agent-name>/<feature>
git checkout -b feat/tiktok/upload-video
git checkout -b feat/facebook/comment-flow
git checkout -b feat/ai-brain/campaign-manager

# Commit convention
feat: add facebook comment flow
fix: resolve tiktok send button detection on new TikTok version
style: redesign dashboard multi-platform layout
refactor: extract PlatformController base class
docs: update tiktok-agent SKILL.md with new patterns
```

---

## 4. Coding Conventions

### Python
- **Type hints** bắt buộc cho tất cả function signatures
- **Async/await** cho tất cả device interactions
- **Logging**: `logger = logging.getLogger(__name__)` — KHÔNG dùng `print()`
- **Error handling**: try/except cụ thể, log error, return meaningful status
- **Docstrings**: Google style cho public methods

### Controller Pattern (Platform Agents PHẢI tuân thủ)
```python
class PlatformController:
    """Base pattern cho tất cả platform controllers."""
    
    def __init__(self, adb, device_ip: str):
        self._adb = adb
        self._device_ip = device_ip
        self._backend = None  # Lazy-init Accessibility
        
    async def _get_backend(self):
        """Lazy-init AccessibilityBackend — PHẢI gọi trước mọi action."""
        if not self._backend:
            # Init from BackendManager
            ...
    
    async def _tap(self, x: int, y: int):
        """Accessibility-first tap."""
        await self._get_backend()
        if self._backend:
            await self._backend.tap(x, y)
        else:
            await self._adb._run_adb(self._device_ip, f"shell input tap {x} {y}")
    
    async def dump_ui(self) -> str:
        """Dump UI hierarchy — ưu tiên Accessibility."""
        ...
    
    async def is_app_foreground(self, package: str) -> bool:
        """Check app đang ở foreground."""
        ...
    
    async def recover(self, package: str):
        """Recovery flow khi app bị thoát."""
        ...
```

### Anti-Detection (BẮT BUỘC cho mọi platform)
- Random delays giữa actions: `await behavior.random_delay(action_type)`
- Không lặp cùng action liên tục (like → xem → like, KHÔNG like → like → like)
- Tap jitter: ±5px
- Scroll speed variance: ±30%
- Session length variance: ±20%
- Realistic tap cho sensitive buttons: `input swipe x y x y 80`

---

## 5. Knowledge Base Rules

Mỗi platform agent PHẢI duy trì file knowledge base:

| Platform | File |
|----------|------|
| TikTok | `tiktok-action.md` (đã có) |
| Facebook | `facebook-action.md` |
| YouTube | `youtube-action.md` |
| Instagram | `instagram-action.md` |

### Format knowledge base
```markdown
## X.X 🔴/🟡/🟢 <Tên vấn đề>

**Vấn đề**: Mô tả ngắn

**Các giải pháp ĐÃ THỬ và THẤT BẠI**:
1. ❌ Cách 1: lý do fail
2. ❌ Cách 2: lý do fail

**Giải pháp THÀNH CÔNG** ✅:
- Chi tiết implementation

**Bằng chứng**: Log/screenshot xác nhận
```

---

## 6. AI Cost Optimization

| Model | Dùng khi | Chi phí ước tính |
|-------|----------|-----------------|
| **Script (deterministic)** | Actions đã biết flow | $0 |
| **DeepSeek** | Comment generation, content analysis | ~$0.00006/call |
| **GPT-4o-mini** | Simple decisions, text classification | ~$0.0003/call |
| **GPT-4o** | Complex vision tasks, unknown UI | ~$0.003/call |

> [!IMPORTANT]
> **Ưu tiên Script > DeepSeek > GPT-4o-mini > GPT-4o.** Chỉ dùng model đắt hơn khi model rẻ hơn không đủ capability.

---

## 7. Cross-Agent Communication

Khi agent A cần thay đổi ở file thuộc agent B:

1. Tạo file `HANDOFF.md` trong root project (nếu chưa có)
2. Thêm entry:
```markdown
## [Ngày] Agent A → Agent B

**Yêu cầu**: Mô tả thay đổi cần thiết
**File**: path/to/file
**Lý do**: Tại sao cần thay đổi
**Ưu tiên**: High/Medium/Low
**Status**: Pending/Done
```
3. Thông báo user để dispatch agent B

---

## 8. Testing Checklist

Trước khi commit, mỗi agent PHẢI:

- [ ] Code không có syntax errors
- [ ] Type hints đầy đủ
- [ ] Anti-detection behaviors đã integrate
- [ ] Knowledge base đã cập nhật (nếu gặp vấn đề mới)
- [ ] Không sửa file ngoài ownership
- [ ] Không chạm venv
