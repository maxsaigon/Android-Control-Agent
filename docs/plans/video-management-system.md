# Video Management & Upload System — 📋 PLANNED

> **Created**: 2026-03-21 | **Updated**: 2026-03-22  
> **Status**: 🔄 IN PROGRESS — Đang implement

---

## Tổng quan

Hệ thống quản lý video từ **máy local (Mac/NAS)** → upload lên server → ADB push xuống device (cùng LAN) → upload lên MXH.  
Google Drive sẽ là **Phase 2** sau khi local workflow đã hoàn thiện.

---

## Phase 1: Local Workflow (Hiện tại)

### Kiến trúc

```
📂 Mac Local / NAS
    │
    │  HTTP Multipart Upload (API)
    ▼
🖥️ Ubuntu Server (192.168.x.x)
    ├── /data/videos/          (video cache)
    ├── SQLite DB              (Video + VideoAssignment + DeviceAccount)
    └── ADB (TCP/IP over LAN)
         │
         │  adb push → /sdcard/DCIM/
         ▼
    📱 Device 1 (@tiktok_A)
    📱 Device 2 (@tiktok_B)
    📱 Device 3 (@youtube_X)
```

### Workflow vận hành

```
Bước 1: Setup (1 lần)
  Dashboard → Device Account Settings
    Device 1 = TikTok @account_A
    Device 2 = TikTok @account_B
    Device 3 = YouTube @channel_X

Bước 2: Upload Video
  Mac → Dashboard "Upload Video"
    → POST /api/videos/upload (multipart)
    → Server lưu vào /data/videos/
    → Tạo Video record (SHA-256 hash → dedup)

Bước 3: Assign Video cho Device
  Dashboard → Video Library → chọn video
    → Chọn target device + platform
    → Hệ thống CHECK → UNIQUE(video_id, platform)
        ✅ Chưa assigned → tạo assignment
        ❌ Đã assigned platform này → BLOCK + hiển thị ai đang giữ
    Hoặc: "Auto-assign" → round-robin

Bước 4: Push lên Device (ADB)
  Dashboard → Assignments → "Push"
    → adb push /data/videos/xxx.mp4 device:/sdcard/DCIM/
    → Verify file trên device
    → Update status: pending → pushed

Bước 5: Upload Task
  Dashboard → tạo Task
    template: tiktok_upload
    video_path: /sdcard/DCIM/xxx.mp4
    → Script/AI mở app → chọn video → upload
    → Update status: pushed → uploaded
```

---

## Anti-Duplication Logic

**Rule**: 1 video chỉ thuộc 1 account per platform  
**DB Constraint**: `UNIQUE(video_id, platform)` trên bảng `VideoAssignment`

| Scenario | Kết quả |
|----------|---------|
| Video A → TikTok Device 1 | ✅ OK |
| Video A → TikTok Device 2 | ❌ BLOCK (đã có trên TikTok) |
| Video A → YouTube Device 3 | ✅ OK (khác platform) |
| Video B → TikTok Device 2 | ✅ OK (video khác) |

---

## Database (3 bảng mới)

### `Video`
| Column | Type | Mô tả |
|--------|------|-------|
| id | PK | |
| filename | str | Tên file gốc |
| filepath | str | `/data/videos/xxx.mp4` |
| file_hash | str INDEX | SHA-256 — phát hiện file trùng |
| file_size | int | Bytes |
| duration | float? | Seconds |
| title | str? | User-defined |
| tags | str? | Comma-separated |
| status | str | `available` / `archived` |
| created_at | datetime | |

### `VideoAssignment`
| Column | Type | Mô tả |
|--------|------|-------|
| id | PK | |
| video_id | FK→Video | |
| device_id | FK→Device | |
| platform | str | `tiktok` / `youtube` / `instagram` / `facebook` |
| push_status | str | `pending` → `pushed` → `uploaded` / `failed` |
| device_path | str? | `/sdcard/DCIM/xxx.mp4` |
| pushed_at | datetime? | |
| uploaded_at | datetime? | |
| task_id | int? FK→Task | Link tới upload task |
| error | str? | |
| created_at | datetime | |

> ⚠️ **UNIQUE(video_id, platform)** — 1 video per platform

### `DeviceAccount`
| Column | Type | Mô tả |
|--------|------|-------|
| id | PK | |
| device_id | FK→Device UNIQUE | 1 device = 1 account |
| platform | str | |
| account_name | str? | @username |
| notes | str? | |
| created_at | datetime | |

---

## Files thay đổi

| Action | File | Mô tả |
|--------|------|-------|
| **NEW** | `app/services/video_service.py` | Upload, assign, push, dedup |
| **NEW** | `app/routers/videos.py` | REST API endpoints |
| MODIFY | `app/models.py` | +3 models |
| MODIFY | `app/config.py` | +`VIDEO_STORAGE_DIR`, `DEVICE_VIDEO_PATH` |
| MODIFY | `app/main.py` | Register router, create storage dir |

---

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| `GET` | `/api/videos` | List videos (filter: status, unassigned, platform) |
| `POST` | `/api/videos/upload` | Upload file từ local |
| `GET` | `/api/videos/{id}` | Video detail + assignments |
| `DELETE` | `/api/videos/{id}` | Soft-delete |
| `POST` | `/api/videos/{id}/assign` | Assign → device (dedup check) |
| `POST` | `/api/videos/auto-assign` | Round-robin assign |
| `POST` | `/api/videos/assignments/{id}/push` | ADB push to device |
| `GET` | `/api/videos/assignments` | Full assignment matrix |
| `GET/POST` | `/api/device-accounts` | Device-account mappings |

---

## Dashboard UI — Tab "Video Library"

- **Upload panel**: Drag & drop / file picker → POST /api/videos/upload
- **Video grid**: Thumbnail, title, tags, assignment status badges
- **Assignment matrix**: Table video × device — badge ✅/⏳/❌ per assignment
- **Push button**: Trigger adb push từ dashboard
- **Device Account config**: Form map device ↔ MXH account

> UI sẽ được build sau khi backend hoàn chỉnh.

---

## Phase 2: Google Drive (Tương lai)

- Thêm `gdrive_file_id` vào model `Video`
- Thêm `app/services/gdrive_service.py` — Service Account API
- Thêm endpoint `POST /api/videos/sync` — sync từ GDrive về server
- User chỉ cần upload lên GDrive, server tự fetch xuống

---

## Verification Plan

### Automated Tests — `tests/test_video_service.py`
1. Upload video → verify DB record + SHA-256 hash
2. Upload **cùng file** lần 2 → detect duplicate (return existing record)
3. Assign video to TikTok Device A → ✅
4. Assign **same** video to TikTok Device B → ❌ reject 409
5. Assign same video to YouTube Device C → ✅
6. `get_available("tiktok")` → không trả về video đã assigned

### Manual
1. Upload video từ Mac → verify file trên server `/data/videos/`
2. Assign + Push → verify file visible trong gallery device
3. Full flow: upload → assign → push → tạo upload task
