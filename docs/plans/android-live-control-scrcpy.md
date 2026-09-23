# Android Live Control: scrcpy + Tango

Implemented 2026-09-23. Hardware verification pending: no device was attached
to the local ADB server. No latency/FPS claims have been measured.

## Architecture

- Cloud / Helper devices keep MediaProjection + LiveKit video and DeviceHub input.
- Existing ADB TCP/IP devices use `/ws/adb/{device_id}`. FastAPI starts a Node/Tango
  worker for each authenticated session. The worker pushes official scrcpy-server
  3.3.3 through the existing ADB server and forwards encoded H.264 to a WebCodecs
  canvas. FastAPI does not decode/re-encode video.
- Touch down/move/up/cancel uses current video dimensions, including rotation.
  Back/Home/Recents and Unicode clipboard paste are supported. Audio is disabled.
- The worker has no public listener, shell endpoint or file-management endpoint.

This integration uses the existing `ip_address:adb_port` registry. USB-only serial
registration is not added: the registry and watchdog currently expect TCP/IP.
Do not represent USB devices as cloud records with port 0.

## Local setup

Requires Node 22+ and a working ADB binary:

```sh
cd gateway/scrcpy
npm ci
npm run setup
npm run build
npm test
```

`setup` downloads scrcpy-server 3.3.3 from Genymobile and verifies SHA-256
`7e70323ba7f259649dd4acce97ac4fefbae8102b2c6d91e2e7be613fd5354be0`.
Update/test the server and protocol client together. `package-lock.json` pins JS
dependencies. Generated assets and vendor binaries are not tracked by Git.

Configure the runtime `.env` (default `/tmp/android-control/.env`, not automatically
the repository `.env`):

```dotenv
SCRCPY_ENABLED=true
SCRCPY_NODE_PATH=node
SCRCPY_ADB_HOST=127.0.0.1
SCRCPY_ADB_PORT=5037
SCRCPY_SESSION_SECONDS=1800
ADB_PATH=adb
```

On this Mac, native ADB is at
`/opt/homebrew/share/android-commandlinetools/platform-tools/adb` and Node at
`/opt/homebrew/bin/node`. The default `/etc/platform-tools/adb` has an incompatible
CPU architecture. Use the full native paths in settings when needed.

Start the configured ADB server, connect an authorized device using the existing
Connect flow, restart FastAPI after changing settings, then open **Live Control**.
Use HTTPS or localhost and an H.264 WebCodecs browser. There is no WASM fallback.
Closing the modal stops its worker; close/reopen to reconnect after interruption.

## Deployment and reservations

The Dockerfile builds the player and downloads the verified server in a Node build
stage. The runtime includes Node and gateway dependencies. Set `SCRCPY_ENABLED=true`
explicitly. The ADB server must be running with the device already connected; the
gateway does not start/kill shared ADB daemons or scan networks.

FastAPI and Node are colocated. ADB may be on a private gateway specified by host
and port. Existing device-management commands must use the same ADB server. Never
publish port 5037 to the Internet. Reverse proxies must forward WebSocket Upgrade,
Host and Origin headers and support the chosen session duration.

Use one FastAPI worker, consistent with the current in-memory TaskQueue. Multiple
API processes require a distributed reservation before enabling this feature.
The session holds the existing device lock until the worker exits: automation
queues behind it and a second viewer is rejected. This is a single-controller
session, not simultaneous view-only fan-out.

## Access and lifecycle

- Requires a signed dashboard session and matching Origin.
- Active device-token owners can access their ADB device. Unassigned legacy ADB
  records are limited to `HELPER_OWNER_USERNAME` because they lack an owner column.
- Permissions/state are rechecked every 10 seconds. Deletion, revocation for a
  non-operator owner, or connection changes terminate the session.
- Startup has a 20-second deadline; sessions have a configurable lifetime.
- Bounded queues and timeouts disconnect slow clients rather than accumulating
  unlimited video. An unchanged screen may remain idle.
- Disconnect/failure cancels relay tasks and terminates the worker before unlock.

Cloud control now polls Helper stream status and displays permission rejection,
capture errors and stopped capture. Failed starts return HTTP 409. Android's
MediaProjection permission dialog remains required.

## Verification

Implementation checks on 2026-09-23: Python suite `106 passed, 1 skipped,
9 subtests passed`; JavaScript protocol suite `3 passed`; player bundle and JS
syntax checks passed. A browser smoke test displayed a synthetic H.264 frame and
confirmed tap/drag, Home, Vietnamese text messages and player cleanup against a
local test WebSocket. This test did not communicate with an Android device.
Docker image build was not run because the local Docker daemon was unavailable.

Automated tests cover auth/origin, ownership/revocation, transport selection,
disabled configuration, message bounds, Unicode, binary framing, rotation and
letterbox mapping, reservation conflicts and process cleanup. Cloud tests cover
ownership, missing configuration, disconnected devices, rejected starts and status.

Hardware acceptance still required:

1. Test tap, continuous drag, long press, Back/Home/Recents on a real ADB phone.
2. Paste Vietnamese text, rotate twice and verify coordinate mapping.
3. Disconnect/reconnect and confirm closing releases the device for automation.
4. Approve/reject MediaProjection on a cloud phone and test stop/reconnect.
5. Measure startup/input latency, CPU and bandwidth on LAN/Internet with 1 and
   several devices. ADB targets max dimension 1280, 30 FPS and 2 Mbps; these are
   settings, not observed performance.

## Upstream licenses

- [Genymobile scrcpy](https://github.com/Genymobile/scrcpy): Apache-2.0.
- [Tango](https://github.com/yume-chan/ya-webadb): MIT; dependencies retain licenses.
- [Pinned release](https://github.com/Genymobile/scrcpy/releases/tag/v3.3.3).
- [Client documentation](https://tangoadb.dev/scrcpy/).

No GPL/AGPL ws-scrcpy-web or Webscreen code is included.
