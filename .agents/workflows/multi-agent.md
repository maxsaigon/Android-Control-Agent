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
cat .agents/skills/karpathy-guidelines/SKILL.md  # Assumptions, scope, verification
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
cat .agents/workflows/agent-standard-workflow.md   # ← ĐỌC TRƯỚC TIÊN
cat .agents/RULES.md                               # Global rules
cat .agents/skills/<name>/SKILL.md                 # Skill documentation
cat .agents/skills/karpathy-guidelines/SKILL.md   # Execution guardrails
cat docs/plans/_index.md                           # Plan registry — task này thuộc plan nào?
cat <platform>-action.md                           # Knowledge base (nếu có)
```

### Bước 1.1: Tách task theo goal rõ ràng
Mỗi sub-agent chỉ nhận task khi có đủ 4 phần:
- **Goal**: kết quả cần đạt
- **Write scope**: file nào được sửa
- **Non-goals**: file hay hành vi nào không được đụng
- **Verify**: test/check nào chứng minh xong

Nếu task chưa tách được như trên, chưa dispatch song song.

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
- Không “tiện tay” cleanup ngoài scope của mình
- Không 2 agent cùng sửa 1 file trừ khi có handoff rõ ràng và tuần tự

### Bước 4a: Update Knowledge Base
Gặp vấn đề mới? → Ghi vào `<platform>-action.md`

### Bước 4b: Update Plan File + _index.md
- Nếu task thuộc plan đang có → cập nhật status các checkbox trong plan file
- Khi hoàn thành → đổi status `docs/plans/_index.md` sang `✅ COMPLETE`

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

1. ✅ Đọc `.agents/workflows/agent-standard-workflow.md` ← **ĐỌC TRƯỚC TIÊN**
2. ✅ Đọc `.agents/RULES.md`
3. ✅ Đọc `.agents/skills/<name>/SKILL.md`
4. ✅ Đọc `docs/plans/_index.md` — xác định task thuộc plan nào
5. ✅ Đọc knowledge base (`<platform>-action.md`) nếu có
6. ✅ `git status` — check uncommitted changes
7. ✅ Xác nhận file ownership
8. ✅ **KHÔNG chạm venv**
9. ✅ Ghi assumptions + non-goals + verify trước khi sửa
10. ✅ Test / verify trước khi commit
11. ✅ Update knowledge base nếu gặp issue mới
12. ✅ Cập nhật plan file + `_index.md` khi hoàn thành
13. ✅ Commit theo convention
