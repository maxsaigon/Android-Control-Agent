---
description: Quy trình làm việc khi sử dụng nhiều sub-agent song song trên cùng codebase
---

# Multi-Agent Workflow Rules

## 🚨 NGUYÊN TẮC TUYỆT ĐỐI

### 1. KHÔNG BAO GIỜ chạm vào môi trường (venv)
- **KHÔNG** tạo/xóa/sửa thư mục `venv/`, `.venv/`, hoặc bất kỳ virtual environment nào
- **KHÔNG** chạy `python -m venv`, `pip install`, hoặc bất kỳ lệnh nào thay đổi packages
- Nếu cần package mới, **ghi vào `pyproject.toml`** và thông báo user tự cài

### 2. Git PHẢI được sử dụng
```bash
# Trước khi bắt đầu bất kỳ thay đổi nào
git status
git stash  # nếu có changes chưa commit

# Sau mỗi feature hoàn thành
git add -A
git commit -m "feat: <mô tả ngắn>"
```

### 3. File Ownership — Mỗi agent SỞ HỮU file riêng
Khi có 2+ agents làm việc song song:
- **Agent A** chỉ sửa files được giao (VD: backend files)
- **Agent B** chỉ sửa files được giao (VD: frontend files)
- **KHÔNG BAO GIỜ** 2 agents sửa cùng 1 file

| Agent | Files được phép sửa |
|-------|---------------------|
| Backend | `app/models.py`, `app/services/`, `app/routers/`, `app/main.py` |
| Frontend | `app/static/index.html`, `app/static/style.css`, `app/static/app.js` |
| DevOps | `Dockerfile`, `docker-compose.yml`, `config.yaml`, `.env.example` |

---

## 📋 QUY TRÌNH LÀM VIỆC

### Bước 1: Khởi tạo Git (lần đầu)
```bash
cd /path/to/Android-Control
git init
git add -A
git commit -m "init: current state before multi-agent work"
```

### Bước 2: Tạo branch cho mỗi feature
```bash
# Mỗi agent/feature tạo branch riêng
git checkout -b feat/scheduler
git checkout -b feat/ui-redesign
git checkout -b feat/docker-setup
```

### Bước 3: Agent làm việc trên branch riêng
- Mỗi agent chỉ commit vào branch của mình
- Không merge vào main cho đến khi feature hoàn thành và test xong

### Bước 4: Merge khi hoàn thành
```bash
git checkout main
git merge feat/scheduler
git merge feat/ui-redesign  # resolve conflicts nếu có
```

---

## ✅ COMMIT CONVENTION

Format: `<type>: <mô tả ngắn>`

| Type | Khi nào |
|------|---------|
| `feat` | Thêm tính năng mới |
| `fix` | Sửa bug |
| `style` | Chỉ thay đổi CSS/UI |
| `refactor` | Tái cấu trúc code |
| `docs` | Thêm/sửa documentation |
| `chore` | Config, build, devops |

Ví dụ:
```
feat: add task scheduler with anti-detection timing
fix: resolve venv path issue on macOS
style: redesign dashboard with sidebar navigation
chore: add Dockerfile and docker-compose.yml
```

---

## 🐳 DOCKER WORKFLOW

### Build & Run
```bash
# Build image
docker compose build

# Run
docker compose up -d

# Xem logs
docker compose logs -f app

# Rebuild sau khi sửa code
docker compose up -d --build
```

### Development (không cần rebuild)
Các file sau được mount volume, sửa là có hiệu lực ngay:
- `app/templates/` — task templates
- `config.yaml` — LLM config

Các file sau cần rebuild:
- `app/*.py` — Python code
- `app/static/*` — Frontend (HTML/CSS/JS)

### Deploy lên Ubuntu Server
```bash
# 1. Push code lên git
git push origin main

# 2. SSH vào server
ssh user@server

# 3. Pull và chạy
cd /opt/android-control
git pull
docker compose up -d --build
```

---

## ⚠️ NHỮNG LỖI PHẢI TRÁNH

| ❌ KHÔNG làm | ✅ Thay vào đó |
|-------------|---------------|
| Tạo/xóa venv | Ghi deps vào pyproject.toml |
| 2 agents sửa cùng file | Phân chia file ownership |
| Commit trực tiếp vào main | Tạo feature branch |
| Sửa code không test | Chạy server test trước khi commit |
| Xóa/di chuyển data/ | Mount data/ bằng volume |
| Hardcode paths | Dùng relative paths hoặc env vars |

---

## 🔧 KHI AGENT ĐƯỢC GỌI

Mỗi agent khi bắt đầu công việc PHẢI:

1. **Kiểm tra git status** — có uncommitted changes không?
2. **Đọc file này** — tuân thủ các quy tắc
3. **Xác nhận file ownership** — chỉ sửa files được phân công
4. **KHÔNG chạm venv** — không install, không tạo, không xóa
5. **Test trước khi xong** — `curl localhost:8000/api/...` hoặc browser
6. **Commit khi hoàn thành** — theo convention ở trên
