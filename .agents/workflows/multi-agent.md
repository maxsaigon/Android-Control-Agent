---
description: Quy trình làm việc khi sử dụng nhiều sub-agent song song trên cùng codebase
---

# Multi-Agent Workflow Rules

## 🧠 Team Structure

```
🧠 AI Brain Agent ──── Strategy, decisions, campaigns
📱 TikTok Agent ────── TikTok automation (browse, like, comment, follow, upload)
📘 Facebook Agent ──── Facebook automation (post, like, comment, share, friend)
📷 Instagram Agent ─── Instagram automation (reels, like, comment, follow, stories)
🔍 Google Agent ────── YouTube + Google Ads automation
🎨 UI Dashboard Agent ─ Web dashboard UI/UX
⚙️ Platform Core Agent ─ Shared infrastructure (models, API, device mgmt)
```

---

## 🚨 NGUYÊN TẮC TUYỆT ĐỐI

### 1. Đọc RULES trước khi bắt đầu
```bash
# Mỗi agent PHẢI đọc:
cat .agents/RULES.md                          # Global rules
cat .agents/skills/<agent-name>/SKILL.md       # Agent-specific skill
```

### 2. KHÔNG BAO GIỜ chạm vào môi trường (venv)
- **KHÔNG** tạo/xóa/sửa `venv/`, `.venv/`
- **KHÔNG** chạy `pip install`, `python -m venv`
- Nếu cần package mới → ghi vào `pyproject.toml` và thông báo user

### 3. File Ownership — Nghiêm ngặt

| Agent | Files sở hữu |
|-------|-------------|
| **TikTok Agent** | `app/services/tiktok_controller.py`, `app/templates/tiktok_*.md` |
| **Facebook Agent** | `app/services/facebook_controller.py`, `app/templates/facebook_*.md` |
| **Google Agent** | `app/services/youtube_controller.py`, `app/services/google_ads_controller.py`, `app/templates/youtube_*.md` |
| **Instagram Agent** | `app/services/instagram_controller.py`, `app/templates/instagram_*.md` |
| **AI Brain Agent** | `app/services/ai_strategy.py`, `app/services/campaign_manager.py`, `app/services/content_analyzer.py` |
| **UI Dashboard** | `app/static/index.html`, `app/static/style.css`, `app/static/app.js` |
| **Platform Core** | `app/main.py`, `app/models.py`, `app/config.py`, `app/database.py`, `app/routers/*`, `app/services/task_queue.py`, `app/services/task_engine.py`, `app/services/device_manager.py`, `app/services/backend_manager.py`, `app/services/behavior.py`, `app/services/scheduler.py`, `app/services/template_manager.py` |

### Shared File: `script_runner.py`
Mỗi platform agent chỉ sửa **section được đánh dấu** của mình:
```python
# === TIKTOK SCRIPTS ===     → TikTok Agent
# === FACEBOOK SCRIPTS ===   → Facebook Agent
# === INSTAGRAM SCRIPTS ===  → Instagram Agent
# === YOUTUBE SCRIPTS ===    → Google Agent
```

### 4. Cross-Agent Communication
Khi cần thay đổi file thuộc agent khác → ghi vào `HANDOFF.md` + thông báo user.

---

## 📋 QUY TRÌNH LÀM VIỆC

### Bước 1: Mỗi agent đọc tài liệu
```bash
cat .agents/RULES.md                    # Global rules
cat .agents/skills/<name>/SKILL.md      # Skill documentation
cat <platform>-action.md                 # Knowledge base (nếu có)
```

### Bước 2: Git branch
```bash
# Branch naming: feat/<agent-name>/<feature>
git checkout -b feat/tiktok/upload-video
git checkout -b feat/facebook/controller-init
git checkout -b feat/ai-brain/campaign-manager
```

### Bước 3: Implement + Test
- Chỉ sửa files được phân công
- Anti-detection behaviors bắt buộc
- Post-action verification bắt buộc

### Bước 4: Update Knowledge Base
Gặp vấn đề mới? → Ghi vào `<platform>-action.md`

### Bước 5: Commit
```bash
git add -A
git commit -m "feat(<agent>): <mô tả>"
```

---

## ✅ COMMIT CONVENTION

Format: `<type>(<agent>): <mô tả>`

```
feat(tiktok): add upload video flow
feat(facebook): implement facebook_browse script
feat(ai-brain): add campaign manager with daily planning
fix(instagram): handle checkpoint detection
style(ui): add multi-platform stats overview
refactor(core): extract PlatformController base class
docs(tiktok): update tiktok-action.md with upload issues
```

---

## ⚠️ NHỮNG LỖI PHẢI TRÁNH

| ❌ KHÔNG làm | ✅ Thay vào đó |
|-------------|---------------|
| Tạo/xóa venv | Ghi deps vào `pyproject.toml` |
| 2 agents sửa cùng file | File ownership matrix |
| Commit vào main | Feature branch per agent |
| Sửa code không verify | Post-action verification |
| Hardcode paths | Relative paths / env vars |
| Skip anti-detection | `behavior.py` integration bắt buộc |
| Bỏ qua knowledge base | Update `<platform>-action.md` |

---

## 🔧 KHI AGENT ĐƯỢC GỌI

1. ✅ Đọc `.agents/RULES.md`
2. ✅ Đọc `.agents/skills/<name>/SKILL.md`
3. ✅ Đọc knowledge base (`<platform>-action.md`) nếu có
4. ✅ `git status` — check uncommitted changes
5. ✅ Xác nhận file ownership
6. ✅ **KHÔNG chạm venv**
7. ✅ Test / verify trước khi commit
8. ✅ Update knowledge base nếu gặp issue mới
9. ✅ Commit theo convention
