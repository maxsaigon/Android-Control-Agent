# Upload Pipeline Standardization (TikTok-first)

> Created: 2026-03-25  
> Updated: 2026-03-28 06:35 (ICT)  
> Owner: Platform Core + TikTok Agent  
> Scope now: TikTok upload workflow end-to-end (PC -> device -> TikTok)  

## Goal

Chuẩn hóa một pipeline upload chạy trơn tru từ webapp, với `VideoAssignment` là source of truth:

`Videos tab -> Assignment -> Run Upload -> Push/Task/Script -> Upload verify -> Persist status/artifacts`

Không cần thao tác thủ công qua Task form ở Dashboard cho luồng upload TikTok.

---

## Current Status

### Phase A — Data contract & integrity
Status: ✅ Done

- [x] Persist + propagate `template_vars` in Task lifecycle.
- [x] Add `upload_status` lifecycle (`pending -> queued -> running -> uploaded/upload_failed`).
- [x] Add DB constraints:
- [x] `VideoAssignment(video_id, platform)` unique.
- [x] `DeviceAccount(device_id, platform)` unique.
- [x] Startup additive migration for legacy DB fields.

### Phase B — Assignment-centric orchestration API
Status: ✅ Done

- [x] `POST /api/videos/assignments/{id}/run-upload`.
- [x] `POST /api/videos/assignments/run-batch`.
- [x] Atomic idempotency guard for concurrent run-upload calls.
- [x] Device file binding via `device_path` + `device_filename` in `template_vars`.

### Phase C — TikTok runtime hardening
Status: ✅ Done (for current device/app build)

- [x] Upload state classifier robust for editor variants (`Your Story + Next` without `Add sound`).
- [x] Create/gallery entry hardened with fallback paths.
- [x] Metadata input hardened:
- [x] deterministic caption target selection,
- [x] token-based verification,
- [x] Unicode-first path via Accessibility (ADB fallback).
- [x] Post submit hardened:
- [x] bottom CTA preference,
- [x] one retry when post form remains,
- [x] completion detector accepts `completed_main_nav` (Inbox/Home/Profile redirect).

### Phase D — Runtime verification on production-like env
Status: ✅ Done

Validated on `m.buonme.com` mapped to Docker app on `max.lan`.

- [x] Task `#23` completed (`Video successfully uploaded to TikTok`).
- [x] Assignment `id=3` now `upload_status=uploaded`, `push_status=uploaded`.
- [x] Metadata snapshot confirms Vietnamese Unicode caption/tags entered on post form.
- [x] Artifacts captured under:
`/home/max/android-control/screenshots/tiktok_upload_debug/20260325T113103Z_192.168.1.45_5555`

---

## Remaining Risks (TikTok)

- [ ] First attempt often hits ADB connection timeout (~35s) then succeeds on retry.
- [ ] Gallery filename match still falls back to first tile in current TikTok gallery UI.
- [ ] Post-completion confirmation currently inferred by navigation state (main nav redirect), not by TikTok post URL/id.

---

## Next Phases — Videos Tab Orchestration (No Dashboard Task Form)

### Phase E — Videos Tab as upload control plane
Status: ✅ Done

- [x] Add assignment-row actions in Videos tab:
- [x] `Run Upload` (single),
- [x] `Run Selected`,
- [x] `Run All Ready (TikTok-visible filter scope)`.
- [x] Show per-assignment runtime fields directly in Videos tab:
- [x] `upload_status`, `task_id`, `last_error`, `last_run_at`, `uploaded_at`.
- [x] Deep link to task logs from assignment row.
- [x] Deep link to upload artifacts from assignment row.

### Phase F — Distribution workflow in Videos tab
Status: 🔄 In Progress

- [x] Add `Distribution Board` in Videos tab with focus mode per selected video.
- [x] List device/account target context inside assignment matrix and detail modal.
- [x] Allow one-click orchestration:
- [x] `Assign -> Push (if needed) -> Run Upload` in one flow per target.
- [x] Add bulk assign by rules for TikTok targets (`Auto-Assign TikTok` for unassigned visible videos).
- [ ] Add dedicated video-detail coverage matrix when one video maps to many future platforms.

### Phase G — Safe rerun policy
Status: ✅ Done (TikTok-first)

- [x] `Rerun failed only` with cooldown + dedupe guard.
- [x] Error-class aware rerun hints (`connectivity`, `gallery_select`, `post_verify`).
- [x] Manual confirm gate before rerun when same assignment failed repeatedly.

### Phase H — UX/UI Optimization for Videos Tab
Status: 🔄 In Progress

- [x] Information architecture:
- [x] split UI into `Video Library` (asset-level) + `Distribution Board` (assignment-level).
- [x] add summary cards for `videos / assignments / uploaded / needs review`.
- [x] keep one focused context panel for selected video (`Distribution Board` focus state).
- [x] Assignment table UX:
- [x] semantic status chips + inline error line for `last_error`.
- [x] inline quick actions: `Run`, `Push`, `Open Logs`, `Detail`.
- [x] sticky columns for large tables.
- [x] direct artifact button in table row.
- [x] Bulk action UX:
- [x] row selection + bulk bar (`Push selected`, `Run selected`, `Run all ready`, `Clear`).
- [x] show scope summary before execute (`visible assignments`, selected count).
- [x] Visibility/feedback:
- [x] empty states per filter condition.
- [x] toast + auto-refresh after task websocket events.
- [x] skeleton loading for table and side panels.
- [x] row-level live progress indicator inside assignment table.
- [x] Assignment detail drawer/modal:
- [x] quick review of pipeline state, metadata, timeline, task jump.
- [x] embed recent task steps + artifact links inline.
- [x] Responsive behavior baseline:
- [x] desktop matrix + mobile stacked controls supported by CSS.
- [ ] optimize mobile action sheet for assignment actions.

### Deployment — Ubuntu server
Status: ✅ Done

- [x] Synced updated backend/frontend code to `max@max.lan:~/android-control`.
- [x] Rebuilt and restarted `android-control-app-1` via Docker Compose.
- [x] Verified authenticated runtime on [m.buonme.com](https://m.buonme.com):
- [x] `/dashboard` returns updated Videos UI.
- [x] `/api/videos/assignments?platform=tiktok` returns new fields (`artifact_manifest_url`, `error_hint_label`, rerun fields).
- [x] `/debug-media/.../manifest.json` serves artifact files behind authenticated session.

---

## Definition of Done (Current milestone)

- [x] Từ webapp, bấm `Run Upload` cho assignment và chạy end-to-end TikTok.
- [x] Metadata (title/desc/tags) được nhập đúng trong post form.
- [x] Assignment phản ánh đúng `uploaded` khi flow hoàn tất.
- [x] Có artifact/debug trail để audit từng run.

## Definition of Done (Next milestone: Videos tab orchestration)

- [x] Operator không cần dùng Dashboard task form cho upload TikTok cơ bản.
- [x] Toàn bộ phân phối TikTok cốt lõi có thể điều phối từ Videos tab.
- [x] Có batch controls + trạng thái + rerun policy hoàn chỉnh ngay trong Videos UI.
- [ ] Videos tab đạt UX baseline:
- [x] thao tác run/push/log tối đa 2 click từ assignment row.
- [x] thời gian nhận biết lỗi (`last_error` + hint) giảm mạnh ngay trên matrix/detail.
- [x] artifact jump tối đa 2 click từ assignment row.
- [x] không cần chuyển tab để theo dõi tiến trình từng assignment cơ bản.
