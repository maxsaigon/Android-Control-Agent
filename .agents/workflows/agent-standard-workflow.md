---
description: Quy trình làm việc chuẩn từ khi nhận prompt đến khi hoàn thành task — BẮT BUỘC với mọi agent, mọi task
---

# Agent Standard Workflow

> [!IMPORTANT]
> Workflow này là **BẮT BUỘC** với mọi agent, từ task nhỏ nhất. Không có ngoại lệ.

---

## ⚡ PHASE 0: KHỞI ĐỘNG (Trước khi làm bất cứ thứ gì)

### Bước 0.1 — Đọc global context
```bash
cat .agents/RULES.md                           # Global rules
cat .agents/skills/<agent-name>/SKILL.md       # Skill của agent này
```

### Bước 0.2 — Đọc Plan Index
```bash
cat docs/plans/_index.md
```
Xác định:
- Task này thuộc plan nào?
- Plan đang ở status nào?
- Có task nào liên quan đang IN PROGRESS không?

### Bước 0.3 — Check Git Status
```bash
git status
git log --oneline -5
```
Nếu có uncommitted changes → hỏi user trước khi tiếp tục.

---

## 📋 PHASE 1: PLANNING

### Bước 1.1 — Tạo hoặc cập nhật Plan File

**Nếu task mới (không thuộc plan hiện có)**:
```markdown
# <Tên Feature> — 🔄 IN PROGRESS
**Created**: YYYY-MM-DD
**Last Updated**: YYYY-MM-DD

## Mục tiêu
[Mô tả ngắn gọn]

## Implementation Plan
[Chi tiết từng bước]

## Verification
[Cách kiểm tra kết quả]
```
Lưu vào `docs/plans/<feature-name>.md`

**Đăng ký vào `_index.md`**:
```markdown
| N | [feature-name.md](feature-name.md) | 🔄 IN PROGRESS | [Mô tả ngắn] |
```

**Nếu task thuộc plan đã có**: Cập nhật status của plan section đó thành `🔄 IN PROGRESS`.

### Bước 1.2 — Xác định File Ownership
Đối chiếu RULES.md Section 1 — File Ownership Matrix:
- File này thuộc agent nào?
- Nếu không phải mình → ghi HANDOFF.md + thông báo user

### Bước 1.3 — Git Branch
```bash
git checkout -b feat/<agent-name>/<feature-slug>
# Ví dụ: feat/platform-core/cloud-websocket
```

---

## 🔨 PHASE 2: EXECUTION

### Bước 2.1 — Implement
- Chỉ sửa files trong ownership matrix của mình
- Tuân thủ code conventions (type hints, async/await, logging)
- Tích hợp anti-detection nếu là platform agent

### Bước 2.2 — Update Plan File (liên tục)
Khi hoàn thành từng sub-task:
```markdown
- [x] ~~Sub-task đã xong~~
- [ ] Sub-task tiếp theo
```

---

## ✅ PHASE 3: VERIFICATION

### Bước 3.1 — Tự kiểm tra
Chạy checklist trong RULES.md Section 8:
- [ ] Code không có syntax errors
- [ ] Type hints đầy đủ
- [ ] Anti-detection behaviors integrated (nếu platform agent)
- [ ] Không sửa file ngoài ownership
- [ ] Không chạm venv

### Bước 3.2 — Test
```bash
# Tùy loại task:
python -m pytest tests/ -v
# hoặc
bash .agents/skills/ui-dashboard/scripts/validate_ui.sh
```

### Bước 3.3 — Cập nhật Knowledge Base
Nếu gặp vấn đề mới → ghi vào `<platform>-action.md`:
```markdown
## X.X 🟢 <Tên vấn đề>
**Vấn đề**: ...
**Giải pháp THÀNH CÔNG**: ...
```

---

## 📦 PHASE 4: HOÀN THÀNH

### Bước 4.1 — Cập nhật Plan File Status
```markdown
# <Tên Feature> — ✅ COMPLETE
**Last Updated**: YYYY-MM-DD
...
- [x] Tất cả tasks đã xong
```

### Bước 4.2 — Cập nhật `_index.md`
Thay đổi status:
```markdown
| N | [feature.md](feature.md) | ✅ COMPLETE | [Mô tả] |
```

### Bước 4.3 — Commit
```bash
git add -A
git commit -m "feat(<agent>): <mô tả> — closes #<plan>"
```

### Bước 4.4 — Thông báo User
Tóm tắt những gì đã làm, file nào đã sửa, kết quả test.

---

## 🚦 Quick Reference: Flow Chart

```
NHẬN PROMPT
    ↓
[0] Đọc RULES.md + SKILL.md + _index.md
    ↓
[1] Task mới? → Tạo plan file + đăng ký _index.md
    Task cũ? → Tìm plan file, cập nhật status IN PROGRESS
    ↓
[2] git checkout -b feat/<agent>/<feature>
    ↓
[3] Implement (chỉ sửa files trong ownership)
    ↓
[4] Verify + Test
    ↓
[5] Cập nhật plan file + _index.md → COMPLETE
    ↓
[6] Commit + Báo cáo user
```

---

## 🚨 Những Lỗi Phải Tránh

| ❌ KHÔNG làm | ✅ Thay vào đó |
|-------------|---------------|
| Bắt đầu code ngay khi nhận prompt | Đọc RULES.md + _index.md trước |
| Tạo skill/agent trong `.agent/` | Luôn dùng `.agents/skills/` |
| Tạo plan file xong quên đăng ký _index.md | Bước 1.1: đăng ký ngay sau khi tạo |
| Xong task mà không update plan status | Bước 4.1–4.2 bắt buộc |
| Sửa file ngoài ownership | Ghi HANDOFF.md + hỏi user |
| Commit trực tiếp vào main | Feature branch bắt buộc |
