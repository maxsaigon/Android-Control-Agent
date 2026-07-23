# Android Device Media Control — Refactor Plan

> Status: implementation started in `refactor/`  
> Date: 2026-07-23  
> Production domain: `https://m.buonme.com`

## 1. Product definition

The refactored product has one job:

> Observe and control Android devices, move media to them, and run small,
> deterministic workflows with verifiable results.

TikTok is the first platform adapter because it contains the most field-tested
automation knowledge. It is not the architecture of the core.

### In scope

- LAN and reverse-cloud device connections.
- Screenshot, UI tree, tap, press, swipe, Unicode text and Android global keys.
- Application launch/recovery.
- Media catalog and transfer to ADB-connected devices.
- One active run per device, cancellation, progress and forensic artifacts.
- Deterministic TikTok workflows built from observable states.
- A focused operations dashboard.
- Compatibility with `m.buonme.com` and `/ws/device/{token}`.

### Explicit non-goals for v1

- Generic natural-language AI agent.
- Campaign management and cross-platform marketing intelligence.
- Facebook, Instagram and YouTube placeholder automation.
- Multi-tenant SaaS billing.
- Advanced scheduler and distributed queues.
- AI video metadata and performance analytics.
- Microservices, Redis, Celery, Kafka or Kubernetes.

## 2. Current-system inventory

The legacy application has grown into six products in one:

| Area | Current implementation |
|---|---|
| Device control | ADB, Accessibility WebSocket and reverse Cloud WebSocket |
| Execution | Task engine, queue, scheduler, script templates and AI routing |
| TikTok | Browse, warmup, like, comment, follow, upload and metrics sync |
| Media | Video storage, metadata, assignment and distribution |
| SaaS | Login, device linking, tokens and cloud device hub |
| Remote operation | LiveKit screen streaming and a large dashboard |

The largest concentration points are:

- `app/services/tiktok_controller.py`: 4,642 lines.
- `app/static/app.js`: 3,797 lines.
- `app/services/script_runner.py`: 2,549 lines.
- Application files inspected: approximately 23,248 lines.

The legacy suite currently passes when invoked through the correct environment:

```text
PYTHONPATH=. ./venv/bin/pytest -q
72 passed, 1 skipped, 9 subtests passed
```

## 3. Proven techniques to preserve

### Device kernel

1. Accessibility-first control with ADB as bootstrap and fallback.
2. Reverse WebSocket protocol:

   ```json
   {"id":"...","action":"tap","params":{"x":100,"y":200}}
   ```

3. Stable cloud endpoint: `/ws/device/{token}`.
4. Heartbeat, server ping, reconnect backoff and reconnect-race protection.
5. Unicode entry through Accessibility `ACTION_SET_TEXT`.
6. Decoded PNG/JPEG screenshots rather than treating binary output as text.

### Automation rules

1. Prefer semantic `content-desc`/text locators over obfuscated resource IDs.
2. Combine UI hierarchy and screenshot analysis.
3. Model workflows as `observe -> locate -> act -> verify`.
4. Treat a transport acknowledgement as delivery, not business success.
5. Keep step history and failure artifacts even on timeout.
6. Recover through foreground check, BACK and relaunch.

### TikTok-specific knowledge

- Package: `com.ss.android.ugc.trill`.
- The comment Send control can be absent from the UI hierarchy.
- Detect active Send from a decoded screenshot using connected color components.
- A zero-duration tap may be silently rejected; use a press gesture around 80 ms
  for Send.
- ENTER inserts a newline and does not submit a comment.
- Verify comment input, send-ready state and eventual posted state separately.
- A cleared input alone is not proof of a posted comment.
- Re-check comments after the asynchronous rejection window.

AI-generated comments and long-term anti-detection effectiveness remain
unproven and do not belong in the v1 core.

## 4. Resources to preserve

Secret values must never be copied into this document or source control.

| Resource | Known state | Migration action |
|---|---|---|
| Production domain | `m.buonme.com` | Reuse after staging smoke tests |
| Cloud endpoint | `wss://m.buonme.com/ws/device/{token}` | Preserve protocol |
| Cloudflare tunnel | Used by cloud compose | Export token/config from production |
| Production host | `max@max.lan` | Preserve SSH deployment profile |
| Production path | `/home/max/android-control` | Back up config, DB and artifacts |
| Git repository | `maxsaigon/Android-Control-Agent` | Keep as legacy source/archive |
| OpenAI key | Present in local `.env` | Import only if optional AI is enabled |
| DeepSeek key | Present in local `.env` | Import only if optional AI is enabled |
| ADB path | Custom path configured | Map to `ANDROID_ADB_PATH` |
| ADB host keys | Mounted from `~/.android` | Preserve to avoid re-authorization |
| SQLite DB | Production path under `data/` | Snapshot, dump, then selective import |
| Helper APK | v1.3.0+6 available | Preserve APK, checksum and source |
| LiveKit | Compose/config placeholders | Do not migrate unless retained explicitly |
| Screenshots/videos | Persistent runtime directories | Move to new artifact store |

Current helper release:

```text
version_name: 1.3.0
version_code: 6
build_sha: d7f9f21-dirty
sha256: ee29a6974685abcc57861b7e8a72b0dae9bee4573ed14ea0554dd78e16042a74
```

The dirty build and its roughly 60 MB size must be investigated before it is
declared the clean refactor release.

Local `data/android_control.db` and `data/app.db` are empty. The authoritative
database is expected on the production host and must be inventoried there.

### Pre-cutover resource checklist

- [ ] Export production `.env` names and copy values through a secure channel.
- [ ] Export Cloudflare tunnel configuration/token and confirm DNS ownership.
- [ ] Snapshot production SQLite DB and create a SQL dump.
- [ ] Record safe table row counts and migration decisions.
- [ ] Archive video files, screenshots and recordings.
- [ ] Back up ADB private/public keys securely.
- [ ] Export active device identities; rotate or hash device tokens.
- [ ] Record APK version installed on every device.
- [ ] Tag and clean-build the Helper APK.
- [ ] Inventory external cron/systemd jobs and Docker volumes.
- [ ] Remove the legacy `admin/admin` bootstrap credential.
- [ ] Rotate third-party keys after cutover.

## 5. Target architecture

```text
Browser
  |
FastAPI modular monolith
  |-- device registry + token hashes (SQLite)
  |-- reverse WebSocket device hub
  |-- ADB transport
  |-- one-lock-per-device workflow runner
  |-- media/artifact storage
  `-- TikTok adapter
         |
Android Helper (primary) / ADB (fallback)
```

Core boundaries:

- `devices`: sessions, transports and observations.
- `workflows`: run lifecycle and step events.
- `platforms/tiktok`: locators, actions, verification and workflows.
- `media`: server catalog and transfer.
- `web`: operations UI only.

No platform module imports FastAPI. No workflow writes directly to the
database. No transport contains TikTok knowledge.

## 6. Technology stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 |
| Dependency management | `uv` |
| API and WebSocket | FastAPI + Pydantic |
| Persistence | SQLite via a small repository; Alembic when schema stabilizes |
| Concurrency | `asyncio`, per-device locks |
| Android | Existing Helper protocol; Kotlin migration only when touched |
| ADB | Small asynchronous subprocess adapter |
| Image work | Pillow; add OpenCV only for demonstrated need |
| UI | Semantic HTML, CSS and small vanilla JavaScript |
| Tests | pytest + pytest-asyncio + FastAPI TestClient |
| Quality | Ruff and Pyright |
| Deployment | One container, one data volume, existing Cloudflare route |

## 7. Dashboard redesign

The UI is an operations workspace, not a marketing dashboard.

Primary flow:

```text
Select device -> inspect live state -> control or send media
              -> launch workflow -> watch verified steps/artifacts
```

Layout:

- Compact left rail: product navigation and server state.
- Device column: searchable device fleet and connection health.
- Main workspace: selected-device screen with direct controls.
- Context rail: quick workflows, active run and recent activity.

Design system:

- OLED charcoal/navy surfaces.
- Teal for connected/healthy; blue for primary actions.
- Amber for degraded and red for failed/destructive states.
- System sans typography for high-density operational readability.
- SVG icons only, visible keyboard focus, 44 px touch targets where practical.
- Responsive at 375, 768, 1024 and 1440 px.
- Respect `prefers-reduced-motion`.

## 8. Delivery task list

### Foundation

- [x] Create `docs/refactor.md`.
- [x] Create isolated `refactor/` application.
- [x] Add typed configuration with legacy-domain defaults.
- [x] Add SQLite device/run repository.
- [x] Add safe health/resource summary.
- [ ] Add Alembic after the minimal schema has survived device testing.

### Device kernel

- [x] Define transport-neutral device commands.
- [x] Implement reverse-cloud Device Hub compatible with the Helper protocol.
- [x] Implement ADB transport for control, screenshot and media push.
- [x] Preserve heartbeat and reconnect-session safety.
- [x] Store only hashes of new device tokens.
- [ ] Build selective importer for the production legacy database.
- [ ] Add LAN Helper WebSocket client after real-device contract tests.

### Workflow engine

- [x] Add one active run per device.
- [x] Add progress steps, cancellation and terminal states.
- [x] Add a small deterministic TikTok browse workflow.
- [ ] Port TikTok like with state verification.
- [ ] Port comment only after delayed verification is characterized.
- [ ] Port upload as a separate state machine.
- [ ] Port follow only if it remains a product requirement.

### Media

- [x] Add media upload/catalog API.
- [x] Add ADB media push.
- [ ] Add Helper-mediated cloud media download.
- [ ] Add checksum confirmation on device.

### Dashboard

- [x] Build the new device-first responsive shell.
- [x] Add device selection and status refresh.
- [x] Add screen refresh and direct control pad.
- [x] Add text input and app launch.
- [x] Add quick workflow and activity views.
- [x] Add media upload/push UI.
- [ ] Add UI-tree inspector.
- [ ] Add artifact timeline and download.

### Security and operations

- [x] No default admin password in the new implementation.
- [x] No API key values returned by resource endpoints.
- [x] Add Docker and environment templates.
- [ ] Add production authentication before public cutover.
- [ ] Import or rotate existing device tokens.
- [ ] Add database backup command and restore drill.
- [ ] Add staging smoke test on the existing host.
- [ ] Switch `m.buonme.com` only after rollback validation.

### Verification

- [x] Unit tests for repository and token behavior.
- [x] API tests for health, devices, actions and workflow registry.
- [x] UI structural validation.
- [ ] Real LAN device control test.
- [ ] Real cloud reconnect test through Cloudflare.
- [ ] Media push + MediaStore visibility test.
- [ ] TikTok browse characterization run.

## 9. Cutover strategy

1. Run the refactor on a second port on `max.lan`.
2. Copy resource values securely; do not reuse the legacy source `.env`.
3. Import devices and issue token rotations where possible.
4. Connect one test Helper to the refactor WebSocket.
5. Validate direct control, screenshot, media and TikTok browse.
6. Back up the production DB immediately before cutover.
7. Point the existing Cloudflare route at the refactor port.
8. Keep legacy containers and data read-only for rollback.
9. Rotate external credentials once the new deployment is stable.

Running directly on the old domain is acceptable after these checks; a new
permanent domain is not required.
