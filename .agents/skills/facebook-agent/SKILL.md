---
name: facebook-agent
description: Sub-agent chuyên xử lý Facebook automation — browse, like, comment, share, post. Sở hữu FacebookController và tất cả Facebook scripts/templates.
---

# Facebook Agent

Bạn là sub-agent chuyên trách **Facebook automation** cho dự án Android Control System.

> [!IMPORTANT]
> **TRƯỚC KHI BẮT ĐẦU**:
> 1. Đọc `.agents/RULES.md` — global rules  
> 2. Đọc `.agents/skills/platform-core/SKILL.md` — controller base pattern  
> 3. Đọc `tiktok-action.md` — học từ kinh nghiệm TikTok (nhiều patterns áp dụng được)
> 4. Nếu tồn tại `facebook-action.md` — đọc knowledge base

---

## 1. File Ownership

```
app/services/facebook_controller.py    # Facebook UI controller — BẠN SỞ HỮU [NEW]
app/templates/facebook_browse.md       # BẠN SỞ HỮU [UPDATE existing]
app/templates/facebook_like.md         # [NEW]
app/templates/facebook_comment.md      # [NEW]
app/templates/facebook_share.md        # [NEW]
app/templates/facebook_post.md         # [NEW]
app/templates/facebook_friend.md       # [NEW]
# script_runner.py: chỉ section # === FACEBOOK SCRIPTS ===
```

---

## 2. FacebookController Architecture

**Target Package**: `com.facebook.katana` (Facebook app)  
**Alternative**: `com.facebook.lite` (Facebook Lite — phổ biến ở VN)

### 2.1 Inheritance

```python
# Follow controller pattern từ platform-core SKILL.md
class FacebookController:
    PACKAGE_NAME = "com.facebook.katana"
    
    def __init__(self, adb, device_ip: str):
        # Same pattern as TikTokController
        ...
```

### 2.2 Key Methods to Implement

| Category | Methods | Priority |
|----------|---------|----------|
| **Navigation** | `ensure_on_feed()`, `dismiss_popups()`, `recover()` | P0 |
| **Feed** | `scroll_feed()`, `get_post_info()` | P0 |
| **Actions** | `like_post()`, `comment_post()`, `share_post()`, `add_friend()` | P1 |
| **Profile** | `visit_profile()`, `edit_profile()` | P2 |
| **Groups** | `join_group()`, `post_in_group()` | P2 |
| **Marketplace** | `browse_marketplace()` | P3 |
| **Verification** | `verify_like()`, `verify_comment()`, `verify_friend_request()` | P1 |

### 2.3 UI Element Discovery Strategy

Facebook UI khác TikTok:
- Facebook sử dụng **ReactNative** rendering → UI hierarchy phức tạp hơn
- `content-desc` thường rõ ràng hơn TikTok
- `resource-id` ổn định hơn TikTok (không obfuscate)

**Approach**:
1. **Đầu tiên**: Dump UI bằng `uiautomator dump` → phân tích patterns
2. **Map content-desc**: Like button, comment button, share button, etc.
3. **Ghi lại patterns vào** `resources/ui_patterns.md`
4. **Build fallback coords** nếu UI dump fail

> [!WARNING]
> **PHẢI** dump UI trên device thực trước khi code. Facebook UI thay đổi giữa các version và regions.

---

## 3. Scripts to Implement

### 3.1 `facebook_browse` (P0)
```
1. Launch Facebook app
2. Dismiss popups (cookies, notifications, login prompts)
3. Ensure on News Feed
4. Scroll through posts (random speed)
5. Occasionally pause on post (read simulation)
6. Random like (based on like_probability param)
```

### 3.2 `facebook_like` (P1)
```
1. Ensure on feed
2. For each post:
   a. Scroll to next post
   b. Read post info (author, content preview)
   c. Check if already liked
   d. Like with random method (tap Like button or long-press for reaction)
   e. Verify like state
   f. Anti-detection delay
```

### 3.3 `facebook_comment` (P1)
```
1. Ensure on feed
2. For target post:
   a. Get post info (author, content, existing comments)
   b. AI generate context-aware comment
   c. Tap comment button → comment input
   d. Type text via Accessibility
   e. Find & tap Send button
   f. Verify comment posted
```

### 3.4 `facebook_share` (P2)
```
1. Find target post
2. Tap Share button
3. Select "Share to Feed" or "Share to Group"
4. Add optional caption
5. Submit
6. Verify share posted
```

### 3.5 `facebook_friend` (P2)
```
1. Navigate to suggested friends / search
2. View profile
3. Tap "Add Friend" button
4. Verify request sent
```

---

## 4. Facebook-Specific Anti-Detection

| Rule | Details |
|------|---------|
| **Session length** | 10-30 min per session, max 3 sessions/day |
| **Like rate** | Max 25/hour, vary between 15-25 |
| **Comment rate** | Max 8/hour, space 3-10 min apart |
| **Friend requests** | Max 10/day, spread across sessions |
| **Reaction types** | Vary: Like 60%, Love 20%, Haha 10%, Wow 10% |
| **Scroll speed** | Slower than TikTok (Facebook posts are longer) |
| **Profile visits** | Visit 2-3 profiles per session |

---

## 5. Known Challenges (from TikTok experience)

### Áp dụng từ TikTok
- ✅ Accessibility-first pattern (type_text Unicode, tap, swipe)
- ✅ Post-action verification (dump UI check state change)
- ✅ Popup dismissal (cookies, notifications, GDPR)
- ✅ Recovery flow (detect foreground, re-launch if needed)
- ✅ Realistic tap có thể cần cho sensitive buttons

### Facebook-specific risks
- ⚠️ Facebook spam detection **mạnh hơn TikTok** → cần comment chất lượng cao hơn
- ⚠️ Facebook rate limiting per session (không chỉ per hour)
- ⚠️ Checkpoint/verification (phone number, captcha) — cần handle
- ⚠️ Facebook Marketplace và Groups có rules riêng

---

## 6. Development Workflow

1. **Phase 1**: Dump UI trên device thực → document patterns
2. **Phase 2**: Implement `facebook_browse` (simplest flow)
3. **Phase 3**: Add `like` + `comment` flows  
4. **Phase 4**: Friend requests + sharing
5. **Mỗi phase**: Update `facebook-action.md` knowledge base

> [!TIP]
> Start bằng cách clone TikTokController structure, thay `content-desc` patterns cho Facebook UI.
