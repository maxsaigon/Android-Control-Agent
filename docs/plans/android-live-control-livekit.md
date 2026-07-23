# Android Live Control with LiveKit

**Status:** MVP implemented; physical-device verification pending  
**Owner:** Platform Core  
**Created:** 2026-07-23

## Goal

Stream an Android device screen to the existing web dashboard and control it
with the existing Accessibility/WebSocket command path.

```text
Android Helper --WebRTC video--> LiveKit --video--> Dashboard
Android Helper <--device command-- DeviceHub <--REST-- Dashboard
```

LiveKit is the media plane only. `DeviceHub`, `CloudBackend`, and
`HelperAccessibilityService` remain the control plane.

## Assumptions

- Cloud devices already have an approved device token and an active
  `/ws/device/{token}` connection.
- LiveKit is deployed separately and is reachable from both Android devices
  and dashboard browsers.
- Android will request MediaProjection consent for every new capture session.
- MVP is video-only: 720p, 15 FPS, approximately 1.5 Mbps.
- A live session is started by an authenticated dashboard user and is scoped
  to one device room.

## Non-goals

- Audio streaming or microphone capture.
- Screen recording or LiveKit Egress.
- Replacing ADB, Accessibility, DeviceHub, or task automation.
- Bypassing Android MediaProjection consent or `FLAG_SECURE`.
- Simultaneous multi-user control arbitration in the MVP.

## Security model

- Room name: `android-device-{user_id}-{device_id}`.
- Android receives a short-lived publish-only token.
- Dashboard receives a short-lived subscribe-only token.
- FastAPI verifies device ownership before issuing either token.
- LiveKit API secret is server-side only.
- Existing authenticated device command APIs remain responsible for control.

## Implementation phases

### Phase 1 — Control-plane API

- Add optional LiveKit settings to application configuration.
- Add a token service using LiveKit's Python server SDK.
- Add endpoints:
  - `POST /api/devices/{id}/stream/start`
  - `POST /api/devices/{id}/stream/stop`
  - `POST /api/devices/{id}/stream/viewer-token`
- `stream/start` sends `start_stream` to the Helper with URL and a
  publish-only token.
- `stream/stop` sends `stop_stream`.
- Return an explicit `503` while LiveKit is not configured.

### Phase 2 — Android Helper

- Add LiveKit Android SDK.
- Add MediaProjection foreground-service permissions.
- Add a transparent capture-consent activity.
- Add a foreground stream service that joins a room and publishes the screen.
- Route `start_stream`, `stop_stream`, and `get_stream_status` in
  `CommandHandler`.
- Keep WebSocket connectivity in `WebSocketService` unchanged.

### Phase 3 — Dashboard

- Add a `Live Control` button to online device cards.
- Add a modal containing the LiveKit video track.
- Start/stop the stream through FastAPI.
- Convert video pointer coordinates to Android screen coordinates while
  accounting for letterboxing and rotation.
- Send tap, swipe, long-press, Back, Home, Recents, and Unicode text using the
  existing device command path.

### Phase 4 — Deployment and hardening

- Add LiveKit to the cloud deployment configuration.
- Expose WebRTC media ports directly; do not route UDP media through the
  existing HTTP-only Cloudflare Tunnel.
- Configure TURN/TLS for restrictive mobile networks.
- Add inactivity auto-stop and reconnect telemetry.
- Validate user/device isolation.

## Concrete task checklist

### Documentation and configuration

- [x] Record architecture, assumptions, non-goals, and acceptance criteria.
- [x] Add `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`.
- [x] Add local LiveKit Compose and document the production network constraint.

### FastAPI

- [x] Add LiveKit server SDK dependency.
- [x] Implement publish/viewer token generation.
- [x] Validate device existence, ownership, online state, and LiveKit config.
- [x] Implement start, stop, viewer-token, and live-control responses.
- [x] Add focused token grant/room scoping tests.
- [ ] Add endpoint integration tests for disabled config, offline device, and
      successful command routing.

### Android Helper

- [x] Add LiveKit Android dependency and Kotlin support.
- [x] Add Android 14+ MediaProjection foreground-service declarations.
- [x] Implement capture consent flow.
- [x] Implement video-only screen publishing.
- [x] Implement stop and cleanup.
- [x] Expose stream state through `get_stream_status`.
- [ ] Add stream state to Helper heartbeat metadata.
- [x] Build a debug APK.
- [ ] Install on one physical device and approve capture.

### Dashboard

- [x] Add Live Control entry point and modal.
- [x] Subscribe to the device room using a viewer token.
- [x] Implement pointer coordinate mapping with letterbox offsets.
- [x] Route input through existing authenticated control endpoints.
- [x] Handle media rotation, disconnect, and explicit stop.
- [ ] Surface permission rejection automatically in the dashboard.

### Infrastructure

- [x] Add local LiveKit container/configuration.
- [ ] Configure DNS/TLS and UDP/TCP media ports.
- [ ] Add TURN or validate LiveKit embedded TURN for mobile networks.
- [ ] Add health checks and resource limits.

## Acceptance criteria

- Stream starts within 3 seconds after the user grants capture permission.
- Target latency is below 250 ms on LAN and below 600 ms on normal Internet.
- Tap error is no more than 1% of device width/height.
- Rotation updates the rendered aspect ratio and coordinate mapping.
- Stopping or losing the stream does not disconnect device automation.
- No video is published until MediaProjection consent is granted.
- User A cannot obtain a token for user B's device room.
- Existing backend tests pass and `./gradlew assembleDebug` succeeds.

## Physical-device smoke test

1. Install the generated Helper APK over the existing version.
2. Re-enable Accessibility if Android disables it after install.
3. Connect the Helper to the cloud server.
4. Open Live Control in the dashboard.
5. Approve the Android screen-capture dialog.
6. Verify video, tap, swipe, text, Back/Home, rotation, stop, and reconnect.
