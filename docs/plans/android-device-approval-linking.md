# Android Device Approval Linking — 🔄 IN PROGRESS
**Created**: 2026-04-29  
**Last Updated**: 2026-04-29  

## Mục tiêu

Đơn giản hoá authorize giữa Android Helper và WebApp:

- Android không nhập password.
- Android không nhập server URL.
- Android chỉ nhập `username`.
- WebApp/admin sẽ thấy pending device và quyết định `Accept` hoặc `Reject`.
- Chỉ sau khi admin accept thì server mới cấp `device_token` cho Helper.
- Sau khi được accept, device tự reconnect bằng cached token, không cần nhập lại.

---

## Target Flow

```
Android Helper                         WebApp / Server
────────────────────────────────────────────────────────────────
Open app
Input username = "admin"
Tap Request Access
        │
        ├── POST /api/device/link/request ───────────────▶
        │                                                  Create pending request
        │                                                  Show in Pending Devices
        │
Waiting for admin approval...
        │
        ├── GET /api/device/link/status/{request_id} ─────▶ pending
        │
        │                                      Admin clicks Accept / Reject
        │
        ├── GET /api/device/link/status/{request_id} ─────▶ approved + device_token
        │
Save device_token
Connect cloud WS
        └── wss://m.buonme.com/ws/device/{device_token} ─▶ DeviceHub online
```

## UX Contract

### Android Helper

Only one required input:

```text
Username
[Request Access]
```

Server is fixed/default:

```text
HTTPS API: https://m.buonme.com
WebSocket: wss://m.buonme.com/ws/device/{token}
```

Status states:

```text
Not linked
Requesting access...
Waiting for admin approval...
Approved. Connecting...
Connected
Rejected by admin
Request expired
```

### WebApp

Admin dashboard gets a `Pending Devices` section:

```text
Device Name | Model | Android | Helper Version | Requested At | Actions
Samsung A54 | SM-A546E | 14 | 1.1.1 | 2m ago | Accept / Reject
```

---

## Data Model

### DeviceLinkRequest

New SQLModel table:

```text
id: int primary key
request_id: str unique indexed
username: str indexed
user_id: int nullable indexed
device_name: str
device_model: str nullable
android_version: str nullable
sdk_int: int nullable
manufacturer: str nullable
helper_version_name: str nullable
helper_version_code: int nullable
helper_build_sha: str nullable
status: pending | approved | rejected | expired
claimed_device_id: int nullable
created_at: datetime
expires_at: datetime
reviewed_at: datetime nullable
reviewed_by_user_id: int nullable
reject_reason: str nullable
client_fingerprint: str nullable
```

Notes:
- `username` is a routing hint, not authentication.
- `user_id` is resolved from username if user exists.
- Requests expire automatically after 10-15 minutes.

---

## API Plan

### Android Public APIs

#### `POST /api/device/link/request`

Called by Android Helper.

Request:

```json
{
  "username": "admin",
  "device_name": "Samsung A54",
  "device_model": "SM-A546E",
  "android_version": "14",
  "sdk_int": 34,
  "manufacturer": "samsung",
  "helper": {
    "version_name": "1.1.1",
    "version_code": 3,
    "build_sha": "abc123"
  }
}
```

Response:

```json
{
  "request_id": "lrq_abc123",
  "status": "pending",
  "expires_at": "2026-04-29T10:15:00Z"
}
```

Rules:
- If username does not exist, return a generic pending-looking error or clear `404` depending UX decision.
- Rate limit by IP + username + device fingerprint.
- If same device submits repeatedly, expire old pending request and create latest one.

#### `GET /api/device/link/status/{request_id}`

Called by Android Helper every 2-5 seconds while waiting.

Pending:

```json
{
  "status": "pending"
}
```

Approved:

```json
{
  "status": "approved",
  "device_id": 12,
  "device_name": "Samsung A54",
  "device_token": "secret-token",
  "ws_url": "wss://m.buonme.com/ws/device/secret-token"
}
```

Rejected:

```json
{
  "status": "rejected",
  "message": "Rejected by admin"
}
```

Expired:

```json
{
  "status": "expired"
}
```

### WebApp Authenticated APIs

#### `GET /api/device/link/requests`

List pending requests for current admin/user.

Filters:
- `status=pending`
- `username=current_user.username` unless admin role later allows all

#### `POST /api/device/link/requests/{request_id}/accept`

Actions:
- Validate current user can approve this username.
- Create or reuse cloud device.
- Create new `DeviceToken`.
- Mark request approved.
- Return accepted device.

#### `POST /api/device/link/requests/{request_id}/reject`

Actions:
- Mark request rejected.
- Store optional reason.
- Android polling receives rejected status.

---

## Android Helper Plan

Files likely touched:

- `android-helper/app/src/main/java/com/androidcontrol/helper/MainActivity.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/ConnectionConfig.java`
- `android-helper/app/src/main/java/com/androidcontrol/helper/WebSocketService.java`
- New helper class: `DeviceLinkClient.java`

Tasks:

- [x] Hardcode/default server URL to `https://m.buonme.com`.
- [x] Remove/hide server URL input from normal UX.
- [x] Remove/hide password input from normal UX.
- [x] Main screen only asks for `Username` if no cached `device_token`.
- [x] Add `Request Access` button.
- [x] Implement `POST /api/device/link/request`.
- [x] Collect device metadata from `Build.*` and `HelperBuildInfo`.
- [x] Poll `GET /api/device/link/status/{request_id}` every 3 seconds.
- [x] On approved, save `device_token`, `device_id`, `device_name`, `username`.
- [x] On rejected/expired, show clear state and allow retry.
- [x] On app start, if token exists, connect cloud directly.
- [x] Keep old username/password registration code temporarily behind fallback/debug path if needed.

Android storage:

```text
connection_mode = cloud
username
device_name
device_id
device_token
link_request_id only while pending
```

Never store:

```text
password
manual server_url
manual ws_url
```

---

## WebApp Dashboard Plan

Files likely touched:

- `app/static/index.html`
- `app/static/app.js`
- `app/static/style.css`
- Possibly `app/routers/devices.py` or new `app/routers/device_link.py`

Tasks:

- [x] Add `Pending Devices` panel in Devices section.
- [x] Poll/list pending requests.
- [x] Show device metadata compactly.
- [x] Add `Accept` button.
- [x] Add `Reject` button.
- [x] After accept, refresh device list and remove pending row.
- [x] After reject, update row status or remove row.
- [x] Add empty state: `No pending device requests`.

---

## Backend Implementation Tasks

### Phase 1 — Model & Migration

- [x] Add `DeviceLinkStatus` enum.
- [x] Add `DeviceLinkRequest` SQLModel.
- [x] Add migration support through `SQLModel.metadata.create_all()` for new table.
- [x] Add indexes for `request_id`, `username`, `user_id`, `expires_at`.

### Phase 2 — APIs

- [x] Add router `app/routers/device_link.py`.
- [x] Implement `POST /api/device/link/request`.
- [x] Implement `GET /api/device/link/status/{request_id}`.
- [x] Implement `GET /api/device/link/requests`.
- [x] Implement `POST /api/device/link/requests/{request_id}/accept`.
- [x] Implement `POST /api/device/link/requests/{request_id}/reject`.
- [x] Include router in `app/main.py`.
- [x] Add auth middleware public allowlist for Android public endpoints:
  - `/api/device/link/request`
  - `/api/device/link/status/`

### Phase 3 — Approval Semantics

- [x] On accept, create/reuse `Device` with `ip_address="cloud"`, `adb_port=0`.
- [x] On accept, deactivate old active tokens for that device if re-linking same name/fingerprint.
- [x] On accept, create `DeviceToken`.
- [x] On reject, never create `DeviceToken`.
- [x] Expired request cannot be accepted.
- [x] Already approved/rejected request cannot be changed.

### Phase 4 — Security

- [ ] Treat username as routing hint only.
- [ ] Require dashboard session auth for list/accept/reject.
- [ ] Prevent one user from approving another user's requests.
- [ ] Add basic rate limits or throttling guard.
- [ ] Use non-guessable `request_id` via `secrets.token_urlsafe`.
- [ ] Do not return `device_token` except once to Android status call after approval.
- [ ] Consider masking device metadata in logs.

---

## Test Plan

### Backend Unit/Integration

- [ ] Request link with valid username returns pending request.
- [ ] Request link with missing username returns validation error.
- [ ] Status pending before approval.
- [ ] Accept creates device + token.
- [ ] Status approved returns token once approved.
- [ ] Reject makes status rejected and no token created.
- [ ] Expired request cannot be accepted.
- [ ] Wrong logged-in user cannot accept another user's request.
- [ ] Old password registration tests still pass during migration.

### Cloud Connect E2E Test

Extend `tests/test_cloud_device_connect.py`:

- [ ] Simulate Android request link.
- [ ] Simulate WebApp admin accept.
- [ ] Simulate Android status polling receives `device_token`.
- [ ] Simulate Android WebSocket connect using returned token.
- [ ] Verify DeviceHub sees online device.

### Android Manual Test

- [ ] Install APK.
- [ ] Open Helper.
- [ ] Enter `admin`.
- [ ] WebApp shows pending device.
- [ ] Accept in WebApp.
- [ ] Helper switches to `Connected`.
- [ ] Reboot app/device.
- [ ] Helper auto reconnects without username input.

---

## Rollout Plan

1. Implement backend model/API behind new endpoints.
2. Add tests for request/approve/connect flow.
3. Add WebApp pending-device panel.
4. Update Android Helper UI to username-only.
5. Build helper `v1.2.0`.
6. Deploy backend first.
7. Publish helper APK.
8. Test with one physical Android device.
9. Keep old `/api/device/register` path for one release as fallback.
10. After stable, remove username/password registration from Android UI.

---

## Acceptance Criteria

- [x] Android Helper default server is `m.buonme.com`.
- [x] Android Helper only requires `username` for first-time linking.
- [x] Dashboard shows pending device request within a few seconds.
- [x] Admin can accept or reject.
- [x] Accepted device receives token and connects cloud automatically.
- [x] Rejected device never receives token.
- [x] Cached accepted device reconnects after app restart without input.
- [x] No dashboard password is entered or stored on Android.
- [x] Existing cloud WebSocket command flow still works.

---

## Open Questions

- Should username be case-sensitive?
- Should unknown username return clear error or generic pending state?
- Should admin see all pending requests or only requests for their username?
- How should we identify duplicate devices before approval: name, model, Android ID, generated install ID?
- Should status endpoint return token only once, or allow repeated reads until helper confirms connected?
