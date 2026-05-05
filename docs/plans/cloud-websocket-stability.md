# Cloud WebSocket Persistent Connection Stability — 🔄 DEPLOY BLOCKED (DOCKER DAEMON DOWN)
**Created**: 2026-04-29  
**Last Updated**: 2026-05-04  

## Mục tiêu

Fix toàn bộ các vấn đề khiến kết nối cloud WebSocket giữa Android Helper và server (`wss://m.buonme.com/ws/device/{token}`) không thể duy trì liên tục sau khi device được approve qua Device Linking flow.

**Symptom**: Device linking (approve/reject) hoạt động, Helper nhận được `device_token`, kết nối WebSocket thành công lần đầu — nhưng connection bị drop sau vài phút và không thể recovery ổn định.

---

## Root Cause Analysis

| ID | Priority | Layer | Root Cause | Impact |
|----|----------|-------|------------|--------|
| C1 | P0 | Server | Server **không gửi keepalive** — chỉ phản hồi message từ client. Cloudflare Tunnel có idle timeout ~100s, nếu client heartbeat bị delay/lost thì tunnel đóng WS | Connection chết im lặng sau idle period |
| C2 | P0 | Server | **Không detect stale connection** — `receive_text()` block vĩnh viễn nếu device mất mạng đột ngột (không gửi close frame). Device status "online" sai trong DB | Ghost device online, resource leak |
| C3 | P1 | Client | **Timeout quá nhạy** — `connectionLostTimeout=60s` + heartbeat check `2.5x` (75s) trigger false-positive trên mạng di động có jitter | Premature disconnect trên mobile network |
| C4 | P1 | Client | **Dual-client conflict** — `startCloudMode()` chỉ skip nếu `isOpen()`, client ở trạng thái reconnecting vẫn chạy song song với client mới → 2 clients compete | Unstable oscillation, connection flapping |
| C5 | P2 | Infra | **Uvicorn WS ping mặc định** — không có explicit ping config, Cloudflare có thể không count protocol-level frames là "activity" | Tunnel timeout despite uvicorn pings |

---

## Architecture After Fix

```
Android Helper                    Cloudflare Tunnel              Server (uvicorn)
     │                                  │                            │
     │                                  │                            │
     │── heartbeat (30s) ──────────────▶│───────────────────────────▶│
     │                                  │                            │── heartbeat_ack ──▶
     │◀─────────────────────────────────│◀───────────────────────────│
     │                                  │                            │
     │                                  │◀── server_ping (25s) ──────│ (NEW)
     │◀─────────────────────────────────│                            │
     │  (reset lastHeartbeatAckMs)      │                            │
     │                                  │                            │
     │                         max idle gap: ~30s                    │
     │                         (well within 100s limit)              │
     │                                  │                            │
     │── heartbeat (30s) ──────────────▶│───────────────────────────▶│
     │                                  │                            │── receive timeout 90s
     │                                  │                            │   (detects stale conn)
```

Timing parameters:

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| Server ping interval | ∞ (none) | 25s | Keep Cloudflare tunnel alive bidirectionally |
| Server receive timeout | ∞ (block forever) | 90s | Detect dead connections without close frame |
| Uvicorn `--ws-ping-interval` | 20s (default) | 25s | Explicit; match server ping |
| Uvicorn `--ws-ping-timeout` | 20s (default) | 30s | Generous for mobile latency |
| Client `connectionLostTimeout` | 60s | 90s | Match server receive timeout |
| Client heartbeat timeout | 2.5x = 75s | 3.5x = 105s | Tolerate mobile jitter |
| Client heartbeat interval | 30s | 30s | Unchanged |

---

## Task List

### Phase 1 — Server-side Keepalive & Stale Detection

Files:
- `app/routers/device_ws.py`

#### 1.1 Server-side periodic ping task

- [x] Thêm `_server_ping_loop()` coroutine gửi `{"type": "server_ping", "ts": "..."}` mỗi 25s
- [x] Chạy song song với receive loop bằng `asyncio.create_task()`
- [x] Cancel ping task trong `finally` block khi connection đóng
- [x] Handle `server_ping` message type trong receive loop (ignore echo)

#### 1.2 Stale connection detection

- [x] Wrap `websocket.receive_text()` với `asyncio.wait_for(timeout=90.0)`
- [x] Khi timeout → log warning + break loop → trigger cleanup
- [x] Cleanup correctly marks device offline qua existing `device_hub.unregister()` flow

#### 1.3 Uvicorn WebSocket ping config

Files:
- `Dockerfile`

- [x] Thêm `--ws-ping-interval 25 --ws-ping-timeout 30` vào uvicorn CMD

---

### Phase 2 — Client-side Resilience

Files:
- `android-helper/app/src/main/java/com/androidcontrol/helper/CloudWebSocketClient.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/WebSocketService.java`

#### 2.1 Tăng connection tolerance

- [x] Tăng `setConnectionLostTimeout` từ 60s lên 90s
- [x] Tăng heartbeat timeout multiplier từ 2.5x lên 3.5x (75s → 105s)

#### 2.2 Handle server_ping message

- [x] Nhận `server_ping` từ server, reset `lastHeartbeatAckMs` giống `heartbeat_ack`
- [x] Không cần gửi response lại (server chỉ cần biết tunnel active)

#### 2.3 Fix dual-client conflict

- [x] `startCloudMode()`: luôn `shutdown()` client cũ trước khi tạo mới
- [x] Loại bỏ guard `if (cloudClient != null && cloudClient.isOpen()) return`
- [x] Đảm bảo `shouldReconnect = false` khi shutdown để dừng reconnect loop cũ

---

### Phase 3 — Deploy & Verify

#### 3.1 Backend deploy

- [ ] Commit + push code changes *(optional for local deploy)*
- [ ] Rebuild Docker image: `docker compose -f docker-compose.cloud.yml build`
- [ ] Deploy: `docker compose -f docker-compose.cloud.yml up -d`
- [ ] Verify server logs: `docker logs android-control -f`
- [ ] Confirm keepalive/stability logs:
  - `server_ping sent (count=...)` tăng đều khi device connected
  - Session close summary có `uptime`, `server_pings`, `heartbeat_acks`
- [x] Blocker noted (2026-05-04): Docker daemon unavailable (`/var/run/docker.sock` và `~/.docker/run/docker.sock` đều không tồn tại)

#### 3.2 Android Helper APK build

- [ ] Build debug APK: `./gradlew :app:assembleDebug`
- [ ] Install lên physical device
- [ ] Verify cloud connection stable > 5 phút
- [ ] Verify notification status chuyển sang "connected ✅"

#### 3.3 Connection stability tests

- [ ] **Idle test**: Để device idle 10+ phút, connection không bị drop
- [ ] **Network toggle**: Tắt/bật WiFi, device reconnect tự động trong 30s
- [ ] **Server restart**: Restart Docker container, device reconnect trong 60s
- [ ] **Mobile jitter**: Di chuyển giữa WiFi ↔ 4G, connection recover
- [ ] **Stale detection**: Kill helper process trên device, server detect offline trong 90s

#### 3.4 Functional tests

- [ ] Dashboard hiển thị device "online" ổn định
- [ ] `device_hub.status` API trả đúng connected device
- [ ] Gửi command (tap/screenshot) qua cloud backend thành công
- [ ] TikTok Browse task chạy end-to-end qua cloud device
- [ ] Heartbeat ack + server_ping xuất hiện đều đặn trong Android logcat
- [ ] Webapp auto-refresh trạng thái device khi reconnect (không cần hard reload trang)

---

## Source Of Truth (Timeout Matrix)

| Layer | Parameter | Value |
|------|-----------|-------|
| Server app | server ping interval | 25s |
| Server app | stale receive timeout | 90s |
| Uvicorn | `--ws-ping-interval` | 25s |
| Uvicorn | `--ws-ping-timeout` | 30s |
| Android helper | `setConnectionLostTimeout` | 90s |
| Android helper | heartbeat interval | 30s |
| Android helper | heartbeat stale threshold | 105s (3.5x) |

Rule: khi thay đổi timeout trong tương lai, update đồng thời cả bảng này + code server + code helper trong cùng 1 PR.

---

## Acceptance Criteria (Go/No-Go)

- Device cloud connection giữ ổn định tối thiểu 10 phút idle, không tự drop.
- Sau network loss/recover, helper reconnect thành công trong <= 30 giây.
- Sau server restart, helper reconnect thành công trong <= 60 giây.
- Server không còn ghost-online quá 90 giây khi helper bị kill đột ngột.
- Dashboard/webapp phản ánh trạng thái reconnect đúng mà không cần reload thủ công.
- Có đủ log để truy vết: `server_ping` periodic + session summary (`uptime`, `server_pings`, `heartbeat_acks`).

---

## Files Changed Summary

| File | Changes |
|------|---------|
| `app/routers/device_ws.py` | Server ping loop, receive timeout, server_ping handler, ping/heartbeat session metrics logs |
| `Dockerfile` | Uvicorn `--ws-ping-interval 25 --ws-ping-timeout 30` |
| `android-helper/.../CloudWebSocketClient.java` | Timeout tuning, server_ping handler |
| `android-helper/.../WebSocketService.java` | Fix dual-client in `startCloudMode()` |

---

## Rollout Plan

1. Deploy backend first (backward compatible — old helpers just ignore `server_ping`)
2. Build + install updated Helper APK
3. Test connection stability trên 1 device physical
4. Monitor logs 24h cho connection drops
5. Nếu stable, release Helper APK version mới

---

## Open Questions

- Nếu Cloudflare Tunnel restart, server có cần logic reconnect notification cho client không?
- Cần thêm server-side metrics (connection uptime, drop count, reconnect count) cho monitoring dài hạn?
- Client có nên gửi `server_pong` response thay vì chỉ update `lastHeartbeatAckMs` silently?
