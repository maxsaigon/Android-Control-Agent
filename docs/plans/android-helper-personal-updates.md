# Android Helper 1.4.0 — personal pairing and managed updates

Implemented 2026-09-23. The first APK must be installed once; older Helpers do not implement the update command.

## First installation

1. Deploy the matching backend and published APK/metadata together, following the repository's existing deploy procedure. Database startup creates `helperupdatejob` and `helperupdatepolicy` tables without altering existing device bindings.
2. Install Helper 1.4.0 (versionCode 8) over the existing app. The certificate matches the previously published 1.3.1 APK. Keep this signing key for later releases; do not uninstall the app to upgrade.
3. Existing devices retain their token and installation ID. New devices request approval automatically; compare the last six characters of the request ID on the Helper and dashboard, then accept once. There is no username/password field on the Helper.
4. Enable Accessibility if needed. On the Helper, tap **Allow updates / Continue installation**, grant permission to install updates and allow notifications. Android may still ask to confirm individual installations.
5. In Dashboard → Thiết bị → Cập nhật Android Helper, choose a canary device and run **Cập nhật máy thử**. A matching installed version still requires a successful health check. Only then enable automatic updates if desired.

`HELPER_OWNER_USERNAME` defaults to `admin`. Set it to an existing dashboard account if the personal owner uses another name. Legacy clients that send username continue to work. Dashboard authentication remains in place.

## Release and rollout

- Increase `versionCode` for each changed APK, then run `android-helper/build-and-publish.sh`. Build metadata is embedded in the APK; the publisher reads it rather than inventing a publish-time build SHA/time.
- Publishing writes the immutable versioned APK, latest alias and metadata atomically per file, with metadata last. The publisher rejects a different APK with an already published versionCode.
- The server checks every 10 seconds. Automatic updates are off until enabled after a verified canary. When enabled, a newer published release creates a canary-first rollout for registered devices.
- Rollout is serial: no next device until the preceding device reports the expected version and passes its health check. A failed canary stops the rest. Offline devices remain queued.
- Cloud updates require the new `helper_update` capability. Download uses HTTPS on the configured server, rejects redirects, checks size/hash/package/version and the current signing certificate before committing a PackageInstaller session.
- ADB devices use `adb install -r` with an extended install timeout. Installed version and bound Accessibility service are checked. Existing Accessibility settings for other apps are preserved.
- Update jobs pin artifact metadata, so another publish cannot change an in-flight rollout. Keep old immutable APKs available while any job references them.

## Coordination and recovery

Task execution, manual input, stream startup and updates share the device lock. Workflows wait while a persistent update reservation exists. Live streams must be closed before a cloud update starts.

Job states include queued, waiting_device, waiting_idle, downloading, installing, waiting_user_action, verifying, succeeded, failed, needs_bootstrap and cancelled. States and maintenance reservations survive server restart. The installer command is not automatically replayed when its outcome is uncertain.

After 15 minutes without verified recovery, the job fails and the reservation remains. A late healthy reconnect clears it. An explicit installer failure can safely release it. Retry checks for an outstanding installation before accepting another attempt. **Dừng các máy đang chờ** cancels work that has not started and disables automatic rollout; it does not interrupt committed installations.

Android can return a pending-user-action result even when silent installation was requested. Helper posts a notification and provides a continuation button. Confirm/cancel a pending installer on the device before retrying. Cloud-only devices whose Helper cannot run need local repair; ADB remains the recovery path when available. No uninstall/downgrade rollback is attempted automatically.

The coordinator assumes the existing single-process server deployment: device WebSockets and task locks are process-local. Multiple API workers require a shared coordinator before enabling rollouts.

## API

All update-management endpoints require the configured owner's dashboard session:

- `GET /api/helper/updates`: policy and last 100 jobs.
- `POST /api/helper/updates/rollout`: `{"device_ids": [canary_id, ...]}`.
- `PUT /api/helper/updates/policy`: `{"automatic": true, "canary_device_id": 1}`; requires a successful canary job.
- `POST /api/helper/updates/{job_id}/retry`: retry failure/bootstrap or verify a manual repair.
- `POST /api/helper/updates/rollouts/{rollout_id}/stop`: stop unstarted work.

## Validation before physical installation

- Release Gradle build, R8 and vital lint passed.
- APK signature verified; certificate SHA-256 matches 1.3.1: `6c67d4a04db2eb2bbcd2a328e5b425c659ee5f8101ae98d23f8e141e4e7c874b`.
- Tests cover passwordless enrollment/owner approval, canary sequencing, failed/uncertain installs, restart, late recovery, task/manual/stream exclusion, old-helper bootstrap, artifact verification, ADB installation, automatic rollout, owner API access and immutable publishing.
- Physical-device installation, OEM background behavior and PackageInstaller confirmation flows still need the first canary test. No device was installed or updated during implementation.
