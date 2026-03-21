# Cloud Device System — Master Plan ✅ PHASE 1 COMPLETE
**Created**: 2026-03-20  
**Last Updated**: 2026-03-21  

## Tổng quan

Mục tiêu: Biến Android Control từ LAN-only thành **SaaS platform** — device từ bất kì đâu trên internet kết nối và nhận lệnh qua cloud server.

---

## Phase 1A: Cloud Connection Infrastructure ✅ COMPLETE

**Goal**: Xây dựng hạ tầng để device kết nối qua cloud thay vì LAN

### Đã hoàn thành

#### Server-side (Python)
| Component | File | Mô tả |
|-----------|------|--------|
| DeviceHub | `app/services/device_hub.py` | WebSocket hub quản lý kết nối reverse từ device |
| CloudBackend | `app/services/cloud_backend.py` | Implementation DeviceBackend interface — 13 commands (tap, swipe, type, screenshot, UI tree, etc.) |
| BackendManager | `app/services/backend_manager.py` | Router: `cloud:` prefix → CloudBackend, còn lại → ADB/Accessibility |
| WebSocket Endpoint | `app/routers/device_ws.py` | `wss://server/ws/device/{token}` — xác thực token, register device, route messages |
| Register API | `app/routers/device_ws.py` | `POST /api/device/register` — login-based auto-registration (thay thế manual token) |

#### Device-side (Android APK)
| Component | File | Mô tả |
|-----------|------|--------|
| CloudWebSocketClient | `CloudWebSocketClient.java` | WebSocket client kết nối OUT tới server, auto-reconnect |
| CommandHandler | `CommandHandler.java` | Route 13 commands: tap, swipe, long_press, type_text, click_node, global_action, get_ui_tree, screenshot, get_screen_size, get_device_info, get_foreground_app, launch_app, force_stop, list_packages |
| AccessibilityService | `HelperAccessibilityService.java` | Thực hiện gesture/UI inspection qua Android Accessibility API |
| MainActivity | `MainActivity.java` | Cloud mode UI: login form (username, password, device name) |
| ConnectionConfig | `ConnectionConfig.java` | Lưu trữ cấu hình kết nối + register URL builder |
| WebSocketService | `WebSocketService.java` | Foreground service giữ kết nối alive |
| BootReceiver | `BootReceiver.java` | Tự động reconnect khi boot |

#### Kiến trúc hoạt động
```
Device (Internet)                        Server (m.buonme.com)
┌──────────────┐                    ┌────────────────────────────┐
│ AC Helper APK│───WSS/outbound────▶│ /ws/device/{token}         │
│              │                    │   ↓                        │
│ CommandHandler│◀──commands────────│ DeviceHub                   │
│   ↓          │                    │   ↑                        │
│ Accessibility│                    │ CloudBackend                │
│  Service     │                    │   ↑                        │
│              │                    │ ScriptRunner / TaskEngine   │
└──────────────┘                    └────────────────────────────┘
```

---

## Phase 1B: Cloud Task Execution ✅ COMPLETE

**Goal**: Fix task execution pipeline để hoạt động với cloud device

### Đã fix
| File | Bug | Fix |
|------|-----|-----|
| `task_queue.py` | Dùng `device.ip_address` thô | Detect `adb_port==0` → format `cloud:{device_id}` |
| `task_engine.py` | Gọi ADB `ensure_connected()` | Skip ADB cho `cloud:` prefix |
| `script_runner.py` | `_resolve_package()` gọi ADB shell trực tiếp | Cloud: dùng `list_packages` qua backend |
| `script_runner.py` | `get_screen_size()` gọi ADB trực tiếp | Dùng `_backend_call("get_screen_size")` |
| `connection_watchdog.py` | Ping/reconnect cloud device via ADB | Skip device có `port==0` |

---

## Phase 1C: Cloud Server Deployment ✅ COMPLETE

**Goal**: Deploy lên server thật, expose qua internet

### Đã hoàn thành
- **Docker**: `Dockerfile` + `docker-compose.yml` (app + cloudflared)
- **Deploy script**: `deploy/cloud-setup.sh` (rsync → docker build → start)
- **Cloudflare Tunnel**: QUIC connections, route `m.buonme.com` → `localhost:8001`
- **Build**: Gradle 8.9 + APK committed to `app/static/downloads/ac-helper.apk`
- **Endpoint**: `/download/helper.apk` (474KB) + `/set` (onboarding page)
- **Health**: `https://m.buonme.com/api/health` ✅ healthy

---

## Phase 1D: Device Registration Simplification ✅ COMPLETE

**Goal**: Đơn giản hóa quy trình đăng ký device — bỏ manual token, dùng login

### Đã hoàn thành

#### Server-side
- [x] `User` model (username, password) trong `models.py`
- [x] `POST /api/device/register` — credential validation + auto tạo device/token
- [x] Default admin user (`admin/admin`) tạo tự động khi server start
- [x] Bỏ Token CRUD API / UI khỏi dashboard

#### Android APK  
- [x] Cloud mode UI: nhập server URL + username + password + device name
- [x] HTTP POST registration → nhận token → auto-connect WebSocket
- [x] Build APK thành công, install trên 2 physical devices

#### Dashboard Fixes
- [x] Live Task: REST polling fallback (`/api/tasks/running/live`) — ko phụ thuộc WebSocket
- [x] Incremental `steps_taken` update trong DB (real-time progress bar)
- [x] Auto-detect `ws://` vs `wss://` cho HTTPS pages
- [x] Try/catch WebSocket errors → fix dual-toast bug
- [x] Cache-busting `?v=` trên static JS/CSS (bypass Cloudflare cache)

### New User Flow
```
Old (5 bước):  Dashboard tạo device → tạo token → copy → paste vào phone → connect
New (2 bước):  Phone nhập login info + device name → tap Connect → xong!
```

---

## Phase 1E: End-to-End Cloud Testing ✅ COMPLETE

**Goal**: Test thực tế — cài APK lên phone, kết nối qua `m.buonme.com`, chạy task

### Kết quả

- [x] APK cài thành công trên 2 physical device (`357784090426808`, `357784090671791`)
- [x] Device kết nối thành công qua `wss://m.buonme.com/ws/device/{token}`
- [x] Dashboard hiển thị device online
- [x] Task TikTok Browse (#14) chạy thành công: 14 steps, 77 giây
- [x] Live Task hiển thị real-time progress (REST polling)
- [x] Task history + step logs đầy đủ
- [x] Automated tests: 7/7 passed (register, auth, reuse, WS, heartbeat, hub, cleanup)

---

## Tương lai (Phase 2+)

### Phase 2: Multi-tenancy & Auth
- User registration/login (email, password hashing)
- Mỗi user có device riêng, token riêng
- Role-based access (admin/operator)

### Phase 3: Dashboard Improvements  
- Real-time device status via WebSocket (không polling)
- Live screenshot preview từ cloud device
- Cloud device management UI riêng

### Phase 4: Scale
- Multiple cloud servers (load balancer)
- Redis for session/state sharing
- PostgreSQL thay SQLite
