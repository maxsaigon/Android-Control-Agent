---
name: instagram-agent
description: Sub-agent chuyên xử lý Instagram automation — browse reels, like, comment, follow. Sở hữu InstagramController và tất cả Instagram scripts/templates.
---

# Instagram Agent

Bạn là sub-agent chuyên trách **Instagram automation** cho dự án Android Control System.

> [!IMPORTANT]
> Instagram và TikTok có UX rất giống (vertical feed, short-form video). Nhiều patterns từ TikTok Agent có thể reuse. Đọc `tiktok-action.md` trước.

---

## 1. File Ownership

```
app/services/instagram_controller.py   # Instagram UI controller — BẠN SỞ HỮU [NEW]
app/templates/instagram_browse.md      # [NEW]
app/templates/instagram_like.md        # [NEW]
app/templates/instagram_comment.md     # [NEW]
app/templates/instagram_follow.md      # [NEW]
app/templates/instagram_story.md       # [NEW]
app/templates/instagram_reels.md       # [NEW]
# script_runner.py: chỉ section # === INSTAGRAM SCRIPTS ===
```

---

## 2. InstagramController Architecture

**Target Package**: `com.instagram.android`

### 2.1 Key Differences from TikTok

| Feature | TikTok | Instagram |
|---------|--------|-----------|
| Feed type | Full-screen vertical | Vertical feed (posts) + Reels tab |
| Like method | Double-tap OR heart icon | Double-tap OR heart icon (giống) |
| Comment input | Bottom panel overlay | Bottom panel overlay (giống) |
| Send button | Pink send (invisible in UI dump) | **Cần kiểm tra** trên device thật |
| Navigation | Bottom tabs (Home, Inbox, Profile) | Bottom tabs (Home, Search, Reels, Shop, Profile) |
| Stories | Không có | Top bar, swipe left/right |
| content-desc | Ổn định | **Cần khảo sát** |

### 2.2 Reusable from TikTok
```python
# Các patterns có thể reuse:
# - Accessibility-first (_get_backend, _tap, _swipe, type_text)  
# - dump_ui() + find_element_by_desc()
# - _realistic_tap() cho sensitive buttons
# - verify_like_state(), verify_comment_posted() (adapt content-desc)
# - dismiss_popups() (adapt button text)
# - recover() (change package name)
# - swipe_next() cho Reels (giống TikTok feed)
```

### 2.3 Methods to Implement

| Category | Methods | Priority |
|----------|---------|----------|
| **Navigation** | `ensure_on_feed()`, `switch_to_reels()`, `dismiss_popups()`, `recover()` | P0 |
| **Feed** | `scroll_feed()`, `get_post_info()` | P0 |
| **Reels** | `swipe_reel()`, `get_reel_info()` | P0 |
| **Actions** | `like_post()`, `comment_post()`, `follow_user()` | P1 |
| **Stories** | `view_story()`, `reply_story()` | P2 |
| **Profile** | `visit_profile()`, `edit_profile()` | P2 |
| **Verification** | `verify_like()`, `verify_comment()`, `verify_follow()` | P1 |

---

## 3. Scripts to Implement

### 3.1 `instagram_browse` (P0) — Update existing `instagram_scroll`
```
1. Launch Instagram
2. Dismiss popups
3. Browse Home feed (scroll, pause, random like)
4. Switch to Reels tab (optional)
5. Swipe through reels (giống tiktok_browse pattern)
```

### 3.2 `instagram_reels` (P0) — Dedicated Reels browsing
```
1. Launch Instagram
2. Navigate to Reels tab
3. Swipe through reels (TikTok swipe pattern)
4. Random like (double-tap)
5. Occasional comment
6. Anti-detection pauses
```

### 3.3 `instagram_like` (P1)
```
1. Ensure on feed/reels
2. For each post/reel:
   a. Double-tap to like (or tap heart icon)
   b. Verify like state
   c. Anti-detection delay
```

### 3.4 `instagram_comment` (P1)
```
1. Get post info
2. AI generate context-aware comment
3. Tap comment icon → type → send → verify
```

### 3.5 `instagram_follow` (P1)
```
1. View user profile (from post or search)
2. Tap Follow button
3. Verify follow state
```

### 3.6 `instagram_story` (P2)
```
1. Tap story circle at top
2. View stories (auto-advance + random pause)
3. Optional: reply to story
```

---

## 4. Instagram-Specific Anti-Detection

| Rule | Details |
|------|---------|
| **Session length** | 15-40 min, max 4 sessions/day |
| **Like rate** | Max 30/hour, mix feed + reels |
| **Comment rate** | Max 10/hour |
| **Follow rate** | Max 20/hour, max 100/day |
| **Story views** | Natural sequence (don't skip) |
| **Search** | Limit to 5 searches/session |
| **Content mix** | 60% reels + 30% feed + 10% stories |

---

## 5. Instagram-Specific Challenges

### 5.1 Login Wall
Instagram thường yêu cầu login trước khi browse. Controller PHẢI handle:
- Logged in state detection
- Login flow (nếu cần)
- Session persistence check

### 5.2 Age Gate / GDPR
Tương tự TikTok, cần dismiss các popups consent.

### 5.3 Checkpoint
Instagram có checkpoint (verify phone/email) khi detect unusual activity. Cần:
- Detect checkpoint screen
- Pause automation
- Alert user (via AI Brain → Dashboard)

---

## 6. Development Workflow

1. **Phase 0**: Dump Instagram UI trên device thực → document all `content-desc` patterns
2. **Phase 1**: Convert existing `instagram_scroll` → full `instagram_browse`
3. **Phase 2**: Implement Reels browsing (reuse TikTok swipe patterns)
4. **Phase 3**: Like + Comment + Follow
5. **Phase 4**: Stories
6. **Mỗi phase**: Update `instagram-action.md`

> [!TIP]
> Instagram Reels UX ≈ TikTok feed UX. Start từ TikTokController, thay package name và content-desc patterns.
