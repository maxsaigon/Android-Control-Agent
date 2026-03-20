# Script Runner Extension Pattern

## Thêm Script Mới

### 1. Tạo template file

```
app/templates/<platform>_<action>.md
```

Ví dụ: `app/templates/facebook_comment.md`

```markdown
# Facebook Comment

## Mô tả
Duyệt Facebook feed, đọc bài viết, AI sinh comment phù hợp, post và verify.

## Tham số
- `comment_count`: Số comment tối đa (default: 3)
- `scroll_between`: Số bài lướt giữa 2 comment (default: 2-4)

## Instruction
Browse Facebook feed and leave thoughtful, context-aware comments on interesting posts.

## Settings
- execution_mode: script
- max_steps: 80
```

### 2. Thêm script method vào `script_runner.py`

Tìm section đúng cho platform:

```python
# ============================================================
# === FACEBOOK SCRIPTS ===
# ============================================================

async def _facebook_comment(self, task, device_ip: str, params: dict) -> "TaskResult":
    """Facebook comment script.
    
    Flow:
    1. Init FacebookController
    2. Ensure on feed
    3. For each target post:
       a. Scroll to post
       b. Read post info
       c. AI generate comment
       d. Comment + verify
    4. Return results
    """
    from app.services.facebook_controller import FacebookController
    
    fb = FacebookController(self._adb, device_ip)
    comment_count = int(params.get("comment_count", 3))
    
    steps = 0
    comments_made = 0
    
    # Ensure on feed
    await fb.ensure_on_feed()
    steps += 3
    
    for i in range(comment_count * 3):  # Extra iterations for skipped posts
        if comments_made >= comment_count:
            break
        
        # Scroll to next post
        await fb.swipe_next()
        await fb._wait(2, 4)
        steps += 1
        
        # Get post info
        post_info = await fb.get_post_info()
        steps += 1
        
        # Skip some posts (anti-detection)
        if random.random() < 0.4:
            continue
        
        # AI generate comment
        comment_text = await self._generate_ai_comment(post_info, platform="facebook")
        steps += 1
        
        # Post comment
        success = await fb.comment_post(comment_text)
        steps += 2
        
        if success:
            comments_made += 1
            logger.info(f"Comment #{comments_made}: {comment_text[:50]}...")
        
        await fb._wait(3, 8)
    
    return TaskResult(
        status="completed",
        result=f"Commented on {comments_made} posts",
        steps_taken=steps
    )
```

### 3. Đăng ký script trong SCRIPTS map

```python
# Trong ScriptRunner.__init__() hoặc _get_script_map():
self.SCRIPTS["facebook_comment"] = self._facebook_comment
```

### 4. Cập nhật `template_manager.py` (nếu cần defaults)

```python
# Trong TemplateManager._default_templates
"facebook_comment": {
    "name": "Facebook Comment",
    "command": "Browse Facebook and comment on posts",
    "execution_mode": "script",
    "max_steps": 80,
    "params": {"comment_count": "3"}
}
```
