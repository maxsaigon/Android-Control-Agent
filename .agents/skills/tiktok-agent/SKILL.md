---
name: tiktok-agent
description: Sub-agent chuyên xử lý TikTok automation — browse, like, comment, follow, upload. Sở hữu TikTokController và tất cả TikTok scripts/templates.
---

# TikTok Agent

Bạn là sub-agent chuyên trách **TikTok automation** cho dự án Android Control System.

> [!IMPORTANT]
> **TRƯỚC KHI BẮT ĐẦU**: Đọc `tiktok-action.md` trong root project — đó là knowledge base chứa tất cả vấn đề đã gặp và giải pháp. KHÔNG lặp lại những gì đã fail.

---

## 1. File Ownership

```
app/services/tiktok_controller.py      # UI-aware TikTok controller — BẠN SỞ HỮU
app/templates/tiktok_browse.md         # 7 templates — BẠN SỞ HỮU
app/templates/tiktok_warmup.md
app/templates/tiktok_like.md
app/templates/tiktok_comment.md
app/templates/tiktok_follow.md
app/templates/tiktok_upload.md
app/templates/tiktok_edit_profile.md
# script_runner.py: chỉ section # === TIKTOK SCRIPTS ===
```

---

## 2. TikTokController Architecture

**File**: `app/services/tiktok_controller.py` (~52KB, ~1400 lines)  
**Package**: `com.ss.android.ugc.trill`

### Key Methods

| Category | Methods |
|----------|---------|
| **Navigation** | `ensure_on_feed()`, `swipe_next()`, `dismiss_popups()`, `close_panel()`, `recover()` |
| **Video Info** | `get_video_info()` → author, description, sound, likes, comments |
| **Actions** | `tap_like()`, `tap_comment_icon()`, `send_comment()`, `tap_follow()`, `tap_avatar()` |
| **Detection** | `dump_ui()`, `find_element_by_desc()`, `is_tiktok_foreground()` |
| **Verification** | `verify_like_state()`, `verify_comment_posted()`, `verify_follow_state()` |
| **Special** | `_find_pink_send_button()`, `_realistic_tap()`, `type_text()`, `read_comments()` |

### Content-Desc Patterns (ỔN ĐỊNH qua versions)

```python
# UI Element Discovery — dùng content-desc, KHÔNG dùng resource-id
PATTERNS = {
    "like":       r"Like video",          # → "Unlike video" khi đã liked
    "comment":    r"Read or add comments",
    "share":      r"Share video",
    "follow":     r"^Follow\s",
    "profile":    r"profile$",
    "sound":      r"^Sound:",
    "home_tab":   r"^Home$",
    "inbox_tab":  r"^Inbox$",
    "profile_tab":r"^Profile$",
    "create_tab": r"^Create$",
}
```

> [!CAUTION]
> **resource-id TikTok bị obfuscate** thành mã 3 ký tự random — KHÔNG BAO GIỜ dùng resource-id.

---

## 3. Critical Patterns (PHẢI NHỚ)

### 3.1 Send Button — INVISIBLE cho uiautomator
- Nút Send comment **KHÔNG XUẤT HIỆN** trong UI dump
- **PHẢI** dùng screenshot pixel detection: tìm pixel hồng (R>230, G<120, B<140)
- Method: `_find_pink_send_button()`
- Scan zone: x > w*0.7, y: 40-80% screen height

### 3.2 Realistic Tap — Send button PHẢI dùng swipe
```python
# ❌ KHÔNG dùng input tap cho Send button
adb shell input tap x y     # 0ms → TikTok reject silently

# ✅ PHẢI dùng input swipe
adb shell input swipe x y x y 80   # 80ms → accepted
```
Chỉ áp dụng cho Send button, các button khác dùng `input tap` bình thường.

### 3.3 ENTER ≠ Send
`input keyevent 66` tạo **newline**, KHÔNG gửi comment.

### 3.4 Accessibility-First
Tất cả methods phải gọi `await self._get_backend()` trước khi check `self._backend`.

### 3.5 Verification Mandatory
Mọi action (like, comment, follow) PHẢI verify sau khi thực hiện bằng UI dump check.

---

## 4. Scripts Đã Implement

| Script | Status | Lines (script_runner.py) |
|--------|--------|--------------------------|
| `tiktok_browse` | ✅ | Browse feed, random like |
| `tiktok_warmup` | ✅ | Passive viewing, no interaction |
| `tiktok_like` | ✅ | Double-tap/heart + verify |
| `tiktok_comment` | ✅ | AI comment + verify (hybrid) |
| `tiktok_follow` | ✅ | Profile visit + follow + verify |
| `tiktok_upload` | 📋 Template only | Chưa implement |
| `tiktok_edit_profile` | 📋 Template only | Chưa implement |

---

## 5. AI Comment Pipeline

```
get_video_info() → tap_comment_icon() → read_comments()
   → DeepSeek generate (with full context)
   → type_text() via Accessibility
   → _find_pink_send_button() → _realistic_tap()
   → verify_comment_posted()
```

**Context gửi cho AI**:
- Creator username
- Video description + hashtags
- Background music
- 5-10 existing comments (scraped from UI)

**Rules cho AI comment**: CỤ THỂ, có GÓC NHÌN, đề cập chi tiết từ video. KHÔNG generic ("hay quá", "tuyệt vời").

---

## 6. Anti-Detection Đã Implement

| Rule | Implementation |
|------|----------------|
| Random delays | `human_behavior.random_delay()` + `_wait(lo, hi)` |
| Skip pattern | 2-3 video giữa mỗi comment |
| Scroll variance | Duration 250-450ms |
| Long pauses | 10% chance 8-20s; warmup 30-60s |
| Mixed behaviors | Profile visits 10-15%, read comments 40% |
| Like method | 70% double-tap, 30% heart icon |

---

## 7. TODO (Chưa implement)

1. `tiktok_upload` script — implement flow: gallery → select → edit → post
2. `tiktok_edit_profile` script — change avatar, bio, username
3. Search & engage — tìm kiếm keyword → interact
4. Comment verification delay — re-check sau 10-30s (TikTok async reject)
5. Accessibility migration cho `dump_ui()`, `_find_pink_send_button()`, `_capture_verify_screenshot()`
