# Cloud Device System — Master Plan 🔄 IN PROGRESS
**Created**: 2026-03-20  
**Last Updated**: 2026-03-20  

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
| Token API | `app/routers/device_ws.py` | CRUD endpoints: create/list/revoke device tokens |
| Token UI | `app/static/app.js` + `index.html` | Token management UI trong Devices tab |

#### Device-side (Android APK)
| Component | File | Mô tả |
|-----------|------|--------|
| CloudWebSocketClient | `CloudWebSocketClient.java` | WebSocket client kết nối OUT tới server, auto-reconnect |
| CommandHandler | `CommandHandler.java` | Route 13 commands: tap, swipe, long_press, type_text, click_node, global_action, get_ui_tree, screenshot, get_screen_size, get_device_info, get_foreground_app, launch_app, force_stop, list_packages |
| AccessibilityService | `HelperAccessibilityService.java` | Thực hiện gesture/UI inspection qua Android Accessibility API |
| MainActivity | `MainActivity.java` | UI cấu hình server URL + token + mode (LAN/Cloud) |
| ConnectionConfig | `ConnectionConfig.java` | Lưu trữ cấu hình kết nối |
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

### Vấn đề gốc
Task runner luôn dùng ADB cho mọi device — không nhận ra cloud device cần route qua CloudBackend.

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
- **Docker**: `Dockerfile` + `docker-compose.cloud.yml` (app + cloudflared)
- **Deploy script**: `deploy/cloud-setup.sh` (rsync → docker build → start)
- **Cloudflare Tunnel**: 4 QUIC connections, route `m.buonme.com` → `localhost:8080`
- **SSH key auth**: Passwordless access tới `max@max.local`
- **Endpoint**: `/download/helper.apk` (478KB) + `/set` (onboarding page)
- **Health**: `https://m.buonme.com/api/health` ✅ healthy

---

## Phase 1D: End-to-End Cloud Testing 📋 PLANNED

**Goal**: Test thực tế — cài APK lên phone, kết nối qua `m.buonme.com`, chạy task

### Tasks cần làm

#### 1D.1: Chuẩn bị Device Token trên Cloud Server
- [ ] Tạo device trong DB trên cloud server (không phải local)
- [ ] Tạo token cho device đó
- [ ] Verify token API hoạt động qua `m.buonme.com`

#### 1D.2: Cài và Test APK trên Phone
- [ ] Download APK từ `m.buonme.com/download/helper.apk`
- [ ] Cài đặt APK, enable Accessibility Service
- [ ] Cấu hình Cloud mode: server URL = `m.buonme.com`, nhập token
- [ ] Verify WebSocket connection thành công (check hub-status)

#### 1D.3: Chạy Task qua Cloud
- [ ] Giao task TikTok Browse cho cloud device từ dashboard
- [ ] Verify task execution: open app → browse → swipe
- [ ] Check task history: đầy đủ steps + logs
- [ ] Test screenshot capture qua cloud

#### 1D.4: Stability Testing  
- [ ] Test auto-reconnect khi mất internet tạm thời
- [ ] Test heartbeat hoạt động liên tục
- [ ] Test multiple tasks liên tiếp
- [ ] Verify device status update (online/offline) trên dashboard

### Acceptance Criteria
- ✅ Phone connect qua `wss://m.buonme.com/ws/device/{token}`
- ✅ Dashboard hiển thị device online
- ✅ Task chạy thành công trên cloud device
- ✅ Screenshot capture hoạt động
- ✅ Auto-reconnect khi mất kết nối

---

## Tương lai (sau Phase 1D)

### Phase 2: Multi-tenancy & Auth
- User registration/login
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
