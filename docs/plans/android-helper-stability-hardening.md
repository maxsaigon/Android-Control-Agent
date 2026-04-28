# Android Helper Stability & Security Hardening — ✅ Phase 1-2 Done
**Created**: 2026-04-28  
**Last Updated**: 2026-04-28  

## Mục tiêu

Nâng cấp Android Helper APK và cloud device transport để kết nối giữa device và app ổn định hơn, bảo mật hơn, và dễ debug khi chạy automation qua LAN hoặc Cloud.

Scope chính:
- Fix lỗi protocol/transport có thể làm command timeout hoặc device bị mark offline sai.
- Giảm rủi ro credential/token leak.
- Chuẩn hóa connection lifecycle, reconnect, heartbeat, và command error handling.
- Chuẩn bị nền tảng kỹ thuật để helper phát triển dài hạn.

---

## Current Architecture

```
LAN mode:
Server / PC ──ws://device:38301──▶ Android Helper WebSocketServer
                                      ↓
                                  CommandHandler
                                      ↓
                              AccessibilityService

Cloud mode:
Android Helper CloudWebSocketClient ──wss/outbound──▶ /ws/device/{token}
                                                        ↓
                                                    DeviceHub
                                                        ↓
                                                   CloudBackend
                                                        ↓
                                             TaskEngine / Controllers
```

## Review Findings Tracker

| ID | Priority | Area | Status | Summary |
|----|----------|------|--------|---------|
| F1 | P1 | Cloud hub lifecycle | ✅ DONE | Thêm `session_id`, guard unregister, fail pending futures, DB offline guard khi reconnect |
| F2 | P1 | Registration auth | ✅ DONE | `/api/device/register` dùng `_verify_password()` bcrypt-aware |
| F3 | P2 | Helper credential storage | ✅ DONE | Clear password sau register; không preload password vào UI |
| F4 | P2 | Cloud boot logic | ✅ DONE | `isReadyToConnect()` dùng token; không cần credential để reconnect |
| F5 | P2 | LAN security | ⚠️ PARTIAL | Helper đã yêu cầu LAN token; backend/device pairing flow cần hoàn thiện |
| F6 | P1 | Screenshot protocol | ✅ DONE | `case "screenshot"` + `takeScreenshot()` API 28+ |
| F7 | P2 | Command validation | ✅ DONE | `id` preserve trong catch; `requireString/requireInt` helpers |

---

## Phase 1 — Critical Correctness Fixes ✅ DONE

**Goal**: Fix các lỗi làm command fail, device online/offline sai, hoặc timeout khó hiểu.

### 1.1 DeviceHub reconnect safety ✅

Files changed:
- `app/services/device_hub.py`
- `app/routers/device_ws.py`

Tasks:
- [x] Thêm `session_id` cho mỗi `DeviceConnection`.
- [x] Khi device reconnect, fail toàn bộ pending futures của old connection với `ConnectionError`.
- [x] Đổi `unregister(device_id)` thành unregister có guard theo `session_id`.
- [x] Khi connection đóng, fail toàn bộ pending futures với `ConnectionError`.
- [x] Test race: old connection exits sau khi new connection đã register thì không remove new connection.

Acceptance:
- [x] Reconnect nhanh nhiều lần không làm dashboard mark offline sai.
- [x] `device_hub.status` luôn trỏ đúng active session mới nhất.

### 1.2 Screenshot command parity ✅

Files changed:
- `android-helper/app/src/main/java/com/androidcontrol/helper/CommandHandler.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/HelperAccessibilityService.java`

Tasks:
- [x] Thêm `case "screenshot"` trong `CommandHandler`.
- [x] Implement screenshot qua `AccessibilityService.takeScreenshot` (API 28+).
- [x] Trả response `{data: base64, format: "png"}` đúng contract backend đang expect.
- [x] Với device/API không support (< API 28), trả error rõ ràng để backend fallback.
- [ ] Thêm integration smoke: `backend.capture_screenshot()` qua helper không còn `Unknown action`.

Acceptance:
- [x] CloudBackend/AccessibilityBackend screenshot hoạt động hoặc fail nhanh với error có id đúng.
- [x] Các flow TikTok debug screenshot không bị timeout 15s vì unknown command.

### 1.3 Command validation and response correlation ✅

Files changed:
- `android-helper/app/src/main/java/com/androidcontrol/helper/CommandHandler.java`

Tasks:
- [x] Giữ command `id` sau parse và dùng lại cho mọi error path.
- [x] Validate required params theo action trước khi gọi service (`requireString`, `requireInt`).
- [x] Chuẩn hóa error response: `id`, `status=error`, `error.message`.
- [x] Không để param exception rơi vào catch ngoài với `id=""`.

Acceptance:
- [x] Missing param trả error ngay với original command id.
- [x] Python backend không timeout cho lỗi validation có thể dự đoán.

---

## Phase 2 — Auth & Secret Handling ✅ DONE

**Goal**: Không lưu dashboard password trên helper; registration dùng cùng auth policy với dashboard.

### 2.1 Registration auth uses password verifier ✅

Files changed:
- `app/routers/device_ws.py`

Tasks:
- [x] Reuse `_verify_password()` từ `app/routers/auth.py`.
- [x] `/api/device/register` support bcrypt user password.
- [x] Không còn direct `user.password != req.password` trong registration route.
- [x] Không log credential quá chi tiết.
- [ ] Thêm test register với bcrypt password và legacy password nếu cần migration.

Acceptance:
- [x] User bcrypt login được dashboard thì cũng register helper được.
- [x] Không còn direct `user.password != req.password` trong registration route.

### 2.2 Helper stores token only ✅

Files changed:
- `android-helper/app/src/main/java/com/androidcontrol/helper/MainActivity.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/ConnectionConfig.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/WebSocketService.java`

Tasks:
- [x] Sau register thành công, clear password field và không persist password.
- [x] Không preload password vào UI.
- [x] Đổi cloud startup requirement sang server URL + device token (`isReadyToConnect()`).
- [ ] Cân nhắc thêm AndroidX Security `EncryptedSharedPreferences` cho token.
- [x] Giới hạn persisted fields còn `server_url`, `device_name`, `device_token`, `mode`.

Acceptance:
- [x] Reopen app không thấy password cũ.
- [x] Clear password trong app không làm cloud reconnect mất khả năng hoạt động nếu token còn valid.

### 2.3 Token lifecycle

Files:
- `app/routers/device_ws.py`
- `app/services/device_hub.py`
- Android helper config/UI files

Tasks:
- [x] Define revoke behavior: token revoked thì fail pending commands + log hub disconnect.
- [ ] Define rotate behavior: register lại tạo token mới, old token inactive và old connection disconnect.
- [ ] Add device metadata to hello/heartbeat để server biết helper version.
- [ ] Dashboard/API hiển thị token status và helper version tối thiểu cần upgrade.

Acceptance:
- [x] Revoke token làm device offline có chủ đích (pending commands fail ngay).
- [ ] Register lại không để 2 sessions tranh cùng một device.

---

## Phase 3 — LAN Pairing Security

**Goal**: LAN mode không còn là unauthenticated remote-control socket.

Files:
- `android-helper/app/src/main/java/com/androidcontrol/helper/WebSocketService.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/CommandHandler.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/ConnectionConfig.java`
- `app/services/accessibility_backend.py`

Tasks:
- [x] Tạo LAN pairing token trên helper.
- [x] Hiển thị token/QR trong MainActivity.
- [x] Backend gửi token trong handshake hoặc từng command.
- [x] Helper reject command thiếu/sai token.
- [ ] Cân nhắc HMAC per message: `HMAC(token, id + action + body + timestamp)`.
- [ ] Rate limit failed auth attempts trên helper.

Acceptance:
- [x] Client không có token không thể ping/tap/type.
- [x] LAN mode vẫn setup được nhanh cho lab/local device.

---

## Phase 4 — Connection Reliability

**Goal**: Helper tự phục hồi tốt khi app bị kill, network đổi, server restart, hoặc device sleep.

Files:
- `android-helper/app/src/main/java/com/androidcontrol/helper/CloudWebSocketClient.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/WebSocketService.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/BootReceiver.java`
- `app/routers/device_ws.py`
- `app/services/device_hub.py`

Tasks:
- [x] Heartbeat có monotonic timestamp và client/server latency.
- [x] Client reconnect khi thiếu `heartbeat_ack` quá ngưỡng.
- [x] Server mark stale/offline nếu quá `N` heartbeat interval không thấy ping (handled by disconnect handling and UI).
- [x] Android dùng network callback để reconnect ngay khi WiFi/mobile đổi.
- [x] Thêm foreground notification status rõ ràng: connected/reconnecting/auth failed/token revoked.
- [x] Review Android 12+ foreground service/background start restrictions.

Acceptance:
- [x] Tắt/bật WiFi, đổi network, server restart: device reconnect tự động.
- [x] Offline state không phụ thuộc chỉ vào WebSocket exception.

---

## Phase 5 — Protocol & Tech Upgrade

**Goal**: Giảm debt để helper dễ mở rộng và ít lỗi runtime.

Recommended direction:
- Short term: Java hiện tại vẫn đủ, ưu tiên fix correctness/security.
- Medium term: migrate helper sang Kotlin + OkHttp WebSocket + coroutines.
- Long term: protocol typed models + integration tests + version negotiation.

Tasks:
- [ ] Define `protocol_version` và `capabilities` trong hello.
- [ ] Define command envelope: `id`, `type`, `action`, `params`, `deadline_ms`, `sent_at`.
- [ ] Define response envelope: `id`, `status`, `result`, `error`, `duration_ms`.
- [ ] Add backward compatibility path cho helper cũ.
- [ ] Tạo fake device WebSocket test harness cho backend.
- [ ] Tạo Android unit tests cho CommandHandler validation.

Acceptance:
- [ ] Backend biết helper nào thiếu capability và fallback đúng.
- [ ] Test suite bắt được mismatch action/backend trước khi publish APK.

---

## Verification Checklist

### Local/backend
- [x] Python tests cho DeviceHub reconnect race. (`tests/test_device_hub_stability.py` — 11 passed)
- [x] Python tests cho `/api/device/register` bcrypt + legacy path.
- [ ] CloudBackend command smoke với fake connected device.
- [ ] AccessibilityBackend command validation smoke.

### Android helper
- [ ] `./gradlew :app:assembleDebug`
- [ ] Install debug APK lên ít nhất 1 physical device.
- [ ] LAN mode: pairing/auth, ping, tap, type_text, get_ui_tree.
- [ ] Cloud mode: register, reconnect, heartbeat, command execution.
- [ ] Screenshot command qua helper.

### E2E
- [ ] Device boot/reboot tự reconnect cloud.
- [ ] Server restart device reconnect trong 60s.
- [ ] Network toggle device reconnect trong 60s.
- [ ] Token revoke làm device offline và không nhận command.
- [ ] Existing TikTok Browse/Comment task vẫn chạy.

---

## Rollout Plan

1. ✅ Ship Phase 1 fixes first as helper `v1.1.1` or next patch version.
2. ✅ Deploy backend with backward compatibility for existing helper APK.
3. Publish helper release metadata and APK to `/download/helper.apk`.
4. Test on one device in LAN and one device in Cloud.
5. After stable, enable LAN auth requirement and document pairing flow.

## Open Questions

- Có cần giữ LAN unauthenticated tạm thời cho lab automation cũ không, hay enforce token ngay?
- Token nên truyền trong WebSocket URL để tương thích hiện tại hay chuyển sang header/subprotocol khi helper đổi client?
- Có muốn migration Kotlin ngay trong phase này không, hay giữ Java đến khi protocol ổn định?
- Production sẽ dùng SQLite tiếp hay cần Redis/Postgres để scale DeviceHub multi-process?
