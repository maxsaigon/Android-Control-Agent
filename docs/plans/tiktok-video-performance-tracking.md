# TikTok Video Performance Tracking — 📋 PLANNED

> **Created**: 2026-04-04 | **Updated**: 2026-04-04  
> **Status**: 📋 PLANNED — Chưa implement, đang chốt hướng kiến trúc và UX

---

## Mục tiêu

Bổ sung khả năng **theo dõi views và tương tác** của các video đã upload lên TikTok, và tích hợp trực tiếp vào tab `VIDEOS` để operator không phải chuyển qua nơi khác để:

- biết video nào đã lên bài thành công
- biết bài nào đang có hiệu suất tốt / kém
- biết assignment nào chưa sync được số liệu
- review lại từng target `device/account` khi crawl metrics fail

Scope của phase này là **TikTok-first** và bám vào control-plane hiện có:

`Video asset -> VideoAssignment(target) -> Upload result -> Metrics sync -> Review`

---

## Nguyên tắc thiết kế

### 1. Theo dõi theo `assignment`, không theo `video` thuần

Một `Video` có thể được upload lên nhiều TikTok account khác nhau qua nhiều `VideoAssignment`.

Vì vậy:

- `Video` = content asset gốc
- `VideoAssignment(video_id, device_id, platform)` = một bài post thực tế trên một target cụ thể
- metrics phải gắn với `VideoAssignment`

Nếu gắn metrics trực tiếp vào `Video`, dữ liệu sẽ sai ngay khi cùng một asset được đăng lên nhiều account.

### 2. Tách upload pipeline và metrics pipeline

Upload thành công không đồng nghĩa phải sync metrics ngay trong cùng một task.

Nên tách:

- `tiktok_upload` = chịu trách nhiệm post
- `tiktok_metrics_sync` = chịu trách nhiệm vào profile/post để đọc số liệu

Điều này giúp:

- không kéo dài upload runtime
- retry metrics độc lập với upload
- dễ batch sync và schedule lại

### 3. Reuse Distribution Board hiện có

Tab `VIDEOS` đã có:

- `Video Library`
- `Distribution Board`
- `Assignment Detail`

Tracking metrics nên được gắn vào các vùng này, không tạo tab mới.

### 4. Artifact-first khi sync fail

TikTok UI không ổn định. Mọi lần sync metrics fail phải để lại:

- screenshot
- UI XML
- thời điểm sync
- device/account
- error reason

để operator review nhanh từ `Assignment Detail`.

### 5. Capture post fingerprint ngay khi upload

Ngay trong `_tiktok_upload()`, sau khi post thành công, phải capture thông tin nhận diện bài post:

- caption text đã nhập (hash 50 ký tự đầu)
- upload timestamp (ISO8601)
- account name (từ `DeviceAccount`)

Lưu vào `VideoAssignment.post_locator` JSON field → giúp metrics sync tìm đúng post sau này.

Đây là **improvement nhỏ nhưng rất quan trọng** — nếu không capture lúc upload, metrics sync sẽ phải đoán blind.

---

## Hiện trạng codebase liên quan

### Đã có sẵn

- `Video`, `VideoAssignment`, `DeviceAccount` trong `app/models.py`
- `GET /api/videos` và `GET /api/videos/assignments` trong `app/routers/videos.py`
- Tab `VIDEOS` và `Distribution Board` trong `app/static/index.html`
- Render logic video/assignment trong `app/static/app.js`
- Upload artifact summary qua `upload_artifacts_service`
- `TikTokController.get_video_info()` đã đọc được `likes/comments/shares` trên feed (nhưng KHÔNG có `views` — TikTok không hiện views trên feed cho video của người khác)
- `capture_debug_snapshot()` — full artifact capture (screenshot + XML + metadata)
- `tap_avatar()` — tap creator avatar on feed
- Scheduler service (`app/services/scheduler.py`) — có thể reuse cho scheduled sync

### Chưa có — Controller primitives gap

> **⚠️ Đây là bottleneck lớn nhất.** Controller hiện tại không có bất kỳ method nào để navigate vào profile tab, mở video grid, hay đọc metrics từ profile.

| Primitive cần build | Mô tả |
|---------------------|-------|
| `navigate_to_profile_tab()` | Tap "Profile" bottom tab |
| `ensure_on_profile()` | Verify + recover nếu không ở profile screen |
| `navigate_to_videos_tab()` | Tap "Videos" sub-tab trong profile |
| `read_profile_grid_metrics()` | Parse grid tiles → list of `{position, views_text, thumbnail_rect}` |
| `open_profile_video_at_position()` | Tap grid item tại index N |
| `read_post_detail_metrics()` | Parse post detail → `{views, likes, comments, shares, bookmarks}` |
| `navigate_back_from_post_detail()` | Press BACK safely, verify profile grid |
| `match_post_by_fingerprint()` | So khớp metadata để tìm đúng post |

**Ước tính**: ~400-600 LOC mới trong controller, chưa tính edge cases (popup, LIVE on profile, private video, empty profile, etc.)

### Chưa có — Backend / Data

- model lưu metrics hiện tại / lịch sử metrics
- API sync metrics cho assignment
- UI hiển thị performance trong `VIDEOS`

---

## Source Of Truth Đề xuất

### Entity chính

#### `Video`
- asset gốc
- title/tags/description/thumbnail
- **Không lưu metrics** — chỉ aggregate read-only trong API response

#### `VideoAssignment`
- target distribution unit
- giữ upload state hiện tại
- nên được enrich để giữ **latest metrics state**

#### `VideoAssignmentMetricSnapshot` (new)
- lưu từng lần sync metrics
- làm history/trend
- phục vụ chart hoặc review theo thời gian

---

## Data Model Đề xuất

### A. Mở rộng `VideoAssignment`

Thêm các field sau:

- `metrics_status` (`MetricsStatus` enum)
  - `pending` — chưa sync lần nào
  - `syncing` — task sync đang chạy (real-time UI status)
  - `synced` — sync thành công
  - `needs_review` — sync fail, cần operator kiểm tra
  - `sync_failed` — sync fail, đã retry hết
  - `disabled` — operator tắt tracking cho assignment này
- `metrics_last_synced_at`
- `metrics_error`
- `post_locator` — JSON field, schema cố định:
  ```json
  {
    "caption_fingerprint": "sha1_of_caption_first_50_chars",
    "upload_timestamp": "2026-04-04T10:30:00Z",
    "grid_position_hint": 0,
    "account_name": "@username"
  }
  ```
- `latest_views`
- `latest_likes`
- `latest_comments`
- `latest_shares`

Ghi chú:

- `post_url` không ổn định từ mobile app → dùng `post_locator` JSON làm chuẩn.
- `post_locator` là fingerprint để tìm lại đúng bài trong profile grid hoặc detail screen.
- `bookmarks` **không** track ở Phase 1 — thêm sau khi flow ổn định.

### B. Bảng mới `VideoAssignmentMetricSnapshot`

Đề xuất cột (đã loại bỏ redundant columns — `video_id`, `device_id`, `platform` đã có qua `assignment_id`):

- `id`
- `assignment_id` (FK → `VideoAssignment`)
- `views`
- `likes`
- `comments`
- `shares`
- `collected_at`
- `source`
  - `grid` — lấy từ profile grid tile
  - `post_detail` — lấy từ post detail screen
  - `manual` — operator nhập thủ công
- `raw_payload` — JSON dump toàn bộ data đọc được
- `artifact_dir` — path đến debug artifacts
- `error` — error message nếu sync partial

### C. Không lưu history trong JSON blob của assignment

`VideoAssignment` chỉ nên giữ latest state.
Lịch sử phải ở bảng snapshot riêng để:

- query nhanh
- filter/order chuẩn
- không phình row assignment

### D. Data retention policy

- Giữ tối đa **100 snapshots / assignment**
- Auto-purge oldest khi vượt → giữ DB gọn
- Phase đầu chưa cần purge (volume thấp)

---

## Luồng nghiệp vụ mục tiêu

### Flow 1 — Sau upload thành công

Khi `tiktok_upload` thành công:

1. `VideoAssignment.upload_status -> uploaded`
2. set `metrics_status -> pending`
3. capture `post_locator` fingerprint vào `VideoAssignment`:
   - `caption_fingerprint`: SHA1 của 50 ký tự đầu caption
   - `upload_timestamp`: thời điểm post
   - `account_name`: từ `DeviceAccount`
   - `grid_position_hint`: 0 (mới nhất)

> **Implementation note**: Thêm ~15 LOC vào cuối `_tiktok_upload()` (sau line 1977 trong `script_runner.py`) để capture fingerprint. Không ảnh hưởng upload flow.

### Flow 2 — Sync metrics thủ công

Operator bấm `Sync Metrics` trên assignment:

1. server tạo task `tiktok_metrics_sync`
2. set `metrics_status -> syncing`
3. task mở TikTok trên đúng device
4. verify account login state trước khi tiếp tục
5. đi vào profile account đang login
6. mở tab `Videos`
7. tìm đúng post đã upload (dùng `post_locator` fingerprint)
8. đọc views + interactions
9. update latest metrics trên `VideoAssignment`
10. insert 1 row vào `VideoAssignmentMetricSnapshot`
11. set `metrics_status -> synced`
12. nếu fail thì lưu artifact + `metrics_error` + set `metrics_status -> needs_review`

### Flow 3 — Batch sync từ Distribution Board

Operator chọn nhiều assignment trong `Distribution Board`:

1. filter theo `platform=tiktok`
2. chọn các row `upload_status=uploaded`
3. bấm `Sync Metrics`
4. hệ thống queue nhiều task sync
5. UI hiển thị trạng thái đang sync / fail / synced

**Rate limiting**: Max 3 sync task / device / hour để tránh TikTok flag hành vi bất thường.

### Flow 4 — Scheduled sync

Sau khi luồng thủ công ổn định, có thể thêm:

- sync lần 1 sau upload 15-30 phút
- sync định kỳ mỗi 6h hoặc 12h cho các bài mới
- dừng sync khi bài quá cũ hoặc operator disable tracking

Phase này chưa bắt buộc.

### Flow 5 — Manual metrics input (fallback)

Khi crawl fail, operator có thể nhập metrics thủ công:

1. mở Assignment Detail Modal
2. click "Enter Metrics Manually"
3. nhập views / likes / comments / shares
4. hệ thống lưu snapshot với `source=manual`
5. update latest metrics trên assignment

Quan trọng vì Phase 1 sẽ có tỷ lệ sync fail cao do controller primitives chưa mature.

---

## Tìm đúng bài post: chiến lược nhận diện

Đây là phần rủi ro nhất của feature.

### Candidate signals

- `assignment.post_locator.caption_fingerprint`
- `assignment.post_locator.upload_timestamp`
- `assignment.post_locator.account_name`
- `video.thumbnail`
- `post_locator.grid_position_hint`

### Hướng nhận diện đề xuất

#### Layer 1 — Profile grid candidate

Từ profile tab:

- vào tab `Videos`
- đọc các tile đang visible
- ưu tiên tile gần nhất / mới nhất (dùng `grid_position_hint`)
- nếu grid có số views, lấy luôn `views`

#### Layer 2 — Open candidate post

Mở từng candidate:

- đọc caption
- đọc likes/comments/shares
- so khớp `caption_fingerprint` với `post_locator` đã lưu

#### Layer 3 — Thumbnail similarity fallback

Nếu text không đủ ổn định:

- reuse thumbnail của `Video`
- so khớp ảnh tile/grid ở mức heuristic

#### Layer 4 — Manual review fallback

Nếu vẫn không tìm được:

- set `metrics_status=needs_review`
- lưu artifact
- operator review từ modal detail

---

## API Contract Đề xuất

### Endpoint mới

#### `POST /api/videos/assignments/{assignment_id}/sync-metrics`
- tạo task sync cho 1 assignment
- set `metrics_status=syncing` atomically (giống QUEUED pattern của upload)
- chỉ cho phép khi:
  - `platform=tiktok`
  - `upload_status=uploaded`
  - `metrics_status` not in (`syncing`, `disabled`)

#### `POST /api/videos/assignments/sync-metrics-batch`
- batch sync nhiều assignment
- rate limit: max 3 / device / hour

#### `POST /api/videos/assignments/{assignment_id}/cancel-sync`
- cancel sync task đang chạy hoặc stuck
- reset `metrics_status` về `pending` hoặc `sync_failed`
- pattern tương tự cooldown logic của upload pipeline

#### `POST /api/videos/assignments/{assignment_id}/metrics`
- manual metrics input — operator nhập thủ công
- body: `{ "views": 1200, "likes": 45, "comments": 3, "shares": 2 }`
- tạo snapshot với `source=manual`
- update latest metrics trên assignment

#### `GET /api/videos/assignments/{assignment_id}/metrics`
- trả latest metrics + history snapshots (paginated)

#### `GET /api/videos/metrics-summary`
- **Thêm từ Phase A** — SQL aggregated summary
- aggregation ở frontend sẽ chậm ngay khi >50 videos × multiple assignments
- trả về: total tracked posts, total views, pending sync count, needs review count

### Enrich response hiện có

#### `GET /api/videos`
Cho mỗi video, thêm aggregate TikTok metrics (computed from assignments, NOT stored on Video):

- `tiktok_total_views`
- `tiktok_total_likes`
- `tiktok_total_comments`
- `tiktok_total_shares`
- `tiktok_metrics_synced_targets`
- `tiktok_metrics_pending_targets`

#### `GET /api/videos/assignments`
Cho mỗi assignment, thêm:

- `metrics_status`
- `metrics_last_synced_at`
- `metrics_error`
- `latest_views`
- `latest_likes`
- `latest_comments`
- `latest_shares`

---

## UI Integration Trong Tab `VIDEOS`

### 1. Video Ops Summary

Thêm các card mới:

- `Tracked Posts`
- `Total Views`
- `Pending Sync`
- `Needs Review`

### 2. Video Library cards

Mỗi card video hiển thị aggregate TikTok performance:

- `12.4K views`
- `430 likes`
- `18 comments`

Nếu chưa sync đủ target:

- hiển thị badge `metrics pending`

### 3. Distribution Focus

Mỗi target card trong focus panel hiển thị:

- latest views
- likes/comments/shares
- last synced time
- nút `Sync Metrics`

Nếu fail:

- badge `needs review`
- nút mở artifact/detail

### 4. Assignment Matrix

Thêm:

- cột `Performance`
- filter `metrics_status`
- batch action `Sync Metrics`

### 5. Assignment Detail Modal

Thêm block `Performance`:

- current metrics
- last synced time
- sync error
- link artifact sync gần nhất
- snapshot history
- nút "Enter Metrics Manually" (fallback khi crawl fail)

### 6. Không tạo tab mới

Lý do:

- operator đã quen luồng `video -> assignment -> review`
- metrics là phần tiếp theo của upload lifecycle
- giữ `VIDEOS` là control plane thống nhất

---

## Automation / Runtime Direction

### Template mới

Thêm template:

- `app/templates/tiktok_metrics_sync.md`

### Script runner

Thêm handler:

- `script_runner.py` -> `_tiktok_metrics_sync(...)`

> **Note**: `script_runner.py` đã ~2116 lines (~86KB). Nếu metrics sync handler >200 LOC, xem xét extract thành `app/services/tiktok_metrics_runner.py` nhưng giữ registry ở `script_runner.py`.

### TikTok controller

Cần bổ sung các primitive mới (~400-600 LOC):

| # | Method | Mô tả | Complexity |
|---|--------|-------|------------|
| 1 | `navigate_to_profile_tab()` | Tap "Profile" bottom tab | Low |
| 2 | `ensure_on_profile()` | Verify + recover nếu không ở profile | Medium |
| 3 | `navigate_to_videos_tab()` | Tap "Videos" sub-tab trong profile | Low |
| 4 | `read_profile_grid_metrics()` | Parse grid tiles → `[{position, views_text, thumbnail_rect}]` | High |
| 5 | `open_profile_video_at_position()` | Tap grid item tại index N | Medium |
| 6 | `read_post_detail_metrics()` | Parse post detail → `{views, likes, comments, shares}` | High |
| 7 | `navigate_back_from_post_detail()` | Press BACK safely, verify profile grid | Medium |
| 8 | `match_post_by_fingerprint()` | So khớp metadata để tìm đúng post | High |

Edge cases cần handle:
- Popup/dialog trên profile screen
- LIVE stream banner trên profile
- Private/deleted video trong grid
- Empty profile (chưa có video)
- "Photos" / "Reposts" tab hiện thay vì "Videos"
- Grid layout 3 columns vs 2 columns tùy version
- Pinned videos ở đầu grid

### Artifact storage

Tạo namespace mới:

- `tiktok_metrics_debug/<session>/...`

Pattern giữ giống `tiktok_upload_debug` để dễ review.

---

## Phased Execution Plan

### Phase A — Schema & Read Model
Status: 📋 Planned | Estimate: 2-3h | Dependency: None

- [ ] Thêm `MetricsStatus` enum (pending/syncing/synced/needs_review/sync_failed/disabled)
- [ ] Thêm fields latest metrics + `post_locator` vào `VideoAssignment`
- [ ] Thêm bảng `VideoAssignmentMetricSnapshot`
- [ ] Migration cho SQLite hiện có
- [ ] Enrich API responses với metrics placeholder
- [ ] Thêm `GET /api/videos/metrics-summary` endpoint (SQL aggregated)

### Phase B — UI Skeleton In `VIDEOS`
Status: 📋 Planned | Estimate: 3-4h | Dependency: Phase A

- [ ] Thêm summary cards cho metrics
- [ ] Thêm performance block trong video card / focus panel / assignment modal
- [ ] Thêm filter `metrics_status`
- [ ] Thêm "Enter Metrics Manually" button trong assignment detail
- [ ] Chưa crawl thật; dùng placeholder state để validate UX

### Phase C1 — Controller Primitives (Profile Navigation)
Status: 📋 Planned | Estimate: 8-12h | Dependency: None (có thể song song Phase A/B)

> **Critical path** — phần khó nhất, cần test trên thiết bị thật.

- [ ] Build `navigate_to_profile_tab()` + `ensure_on_profile()`
- [ ] Build `navigate_to_videos_tab()`
- [ ] Build `read_profile_grid_metrics()`
- [ ] Build `open_profile_video_at_position()`
- [ ] Build `read_post_detail_metrics()`
- [ ] Build `navigate_back_from_post_detail()`
- [ ] Build `match_post_by_fingerprint()`
- [ ] Test trên device thật — handle edge cases (popups, layout variance, empty profile)

### Phase C2 — Single Assignment Metrics Sync (Integration)
Status: 📋 Planned | Estimate: 4-6h | Dependency: Phase A + C1

- [ ] Tạo template `tiktok_metrics_sync`
- [ ] Thêm runner `_tiktok_metrics_sync` (wire controller primitives)
- [ ] Thêm API endpoint `POST .../sync-metrics`
- [ ] Thêm API endpoint `POST .../cancel-sync`
- [ ] Thêm API endpoint `POST .../metrics` (manual input)
- [ ] Capture `post_locator` trong `_tiktok_upload()` (thêm ~15 LOC)
- [ ] Lưu latest metrics + snapshot + artifact
- [ ] Retry policy: 2 retries, mỗi lần cách 5 phút

### Phase D — Batch Sync & Review Workflow
Status: 📋 Planned | Estimate: 3-4h | Dependency: Phase C2

- [ ] Batch sync từ Distribution Board
- [ ] Bulk action cho selected assignments
- [ ] Rate limiting: max 3 sync / device / hour
- [ ] Error hint + review link khi locate post thất bại

### Phase E — Scheduled Sync
Status: 📋 Planned | Estimate: 4-6h | Dependency: Phase D + Scheduler

- [ ] Auto schedule sync sau upload (15-30 phút)
- [ ] Re-sync theo chu kỳ cho bài mới (mỗi 6-12h)
- [ ] Rule dừng theo tuổi bài post / trạng thái operator
- [ ] Integrate với `TaskScheduler` hiện có (`app/services/scheduler.py`)

### Phase F — Trend / Historical UX
Status: 📋 Planned | Estimate: 4-6h | Dependency: Phase C2

- [ ] Snapshot history trong modal detail
- [ ] Trend line mini-chart (Chart.js hoặc inline SVG)
- [ ] Sort theo views hoặc engagement trong `VIDEOS`
- [ ] Data retention: auto-purge oldest snapshots khi >100/assignment

---

## Rủi ro chính

### 1. Khó locate đúng post trong profile grid

Đây là rủi ro lớn nhất. Nếu không có locator tốt, metrics có thể bị gán nhầm assignment.

**Mitigation**: Capture `post_locator` fingerprint ngay lúc upload, dùng multi-signal matching (caption + timestamp + grid position).

### 2. UI TikTok thay đổi theo build / locale

Selector cần dựa vào nhiều signal:

- text
- content-desc
- layout heuristics
- fallback artifact review

### 3. Metrics nằm ở nhiều lớp UI khác nhau

- views có thể hiện ở profile grid
- likes/comments/shares có thể chỉ rõ khi mở post detail

Collector phải chấp nhận dữ liệu đến từ nhiều source.

### 4. Cùng asset đăng nhiều lần trên cùng account

Nếu operator repost một video tương tự, chỉ caption/title có thể không đủ để định danh.
Khi đó phải dựa thêm:

- upload time
- thumbnail
- post order

### 5. Không được làm chậm flow upload hiện tại

Metrics sync phải là pipeline phụ, không được kéo `tiktok_upload` thành flow dài và khó recover hơn.

Thêm `post_locator` capture chỉ ~15 LOC ở cuối flow, không ảnh hưởng upload logic.

### 6. Account bị logout / bị ban giữa sync

TikTok hay force-logout account trên device. Sync flow đi vào profile nhưng đã bị logout → profile screen khác hẳn expected.

**Mitigation**: Check account login state trước khi sync. Nếu bị logout → set `metrics_status=needs_review`, lưu artifact, skip.

### 7. Rate limiting khi sync nhiều assignment cùng device

Batch sync 10 assignment trên cùng device = mở 10 lần profile + 10 lần post detail. TikTok có thể flag hành vi bất thường.

**Mitigation**: Max 3 sync / device / hour. Thêm random delay 30-120s giữa các sync trên cùng device.

### 8. SQLite concurrent write khi batch sync

Nhiều task sync chạy song song, cùng write vào `VideoAssignment` + `VideoAssignmentMetricSnapshot`. SQLite single-writer lock có thể gây timeout.

**Mitigation**: Verify WAL mode đã enable. Hoặc serialize writes qua queue nếu conflict xảy ra.

### 9. Profile grid layout không ổn định

- Profile grid có thể có pinned videos, hiển thị khác
- "Photos" tab vs "Videos" tab vs "Reposts" tab
- Layout grid 3 columns vs 2 columns tùy version

**Mitigation**: Detect grid structure dynamically bằng UI dump, không hardcode positions. Fallback manual review khi detect fail.

---

## Definition Of Done Cho Phase Đầu (A + B + C1 + C2)

Phase đầu được coi là đạt khi:

- [ ] Tab `VIDEOS` hiển thị performance state trên từng TikTok assignment
- [ ] Operator có thể bấm `Sync Metrics` cho 1 assignment đã upload
- [ ] Hệ thống đọc được tối thiểu `views`, `likes`, `comments`, `shares` cho một bài post thật
- [ ] Latest metrics được lưu trên `VideoAssignment`
- [ ] Mỗi lần sync đều lưu 1 snapshot history
- [ ] Nếu sync fail, operator có thể mở artifact để review
- [ ] Operator có thể nhập metrics thủ công khi crawl fail
- [ ] `post_locator` được capture tự động khi upload thành công
- [ ] Không ảnh hưởng upload flow hiện tại

---

## Quyết định kiến trúc — ĐÃ CHỐT

| # | Câu hỏi | Quyết định |
|---|---------|------------|
| 1 | `post_url` vs `post_locator`? | **`post_locator` JSON** — `post_url` không lấy được ổn định từ mobile app. Schema: `{caption_fingerprint, upload_timestamp, grid_position_hint, account_name}` |
| 2 | Aggregate metrics ở cấp `Video`? | **Có, read-only** — aggregate trong API response (computed), KHÔNG lưu field riêng trên `Video` table |
| 3 | Bookmarks ở Phase 1? | **Không** — chỉ 4 chỉ số: `views`, `likes`, `comments`, `shares`. Bookmarks thêm sau khi flow ổn định |
| 4 | Auto-sync sau upload ở Phase 1? | **Không** — Phase 1 chỉ manual sync. Auto-sync ở Phase E khi biết tỷ lệ fail thật |
| 5 | Retry policy cho metrics sync? | **2 retries, mỗi lần cách 5 phút** trước khi set `sync_failed` |
| 6 | Data retention cho snapshots? | **Max 100 snapshots / assignment**, auto-purge oldest khi vượt |
| 7 | Tách metrics runner riêng? | **Xem xét khi >200 LOC** — extract `tiktok_metrics_runner.py`, giữ registry ở `script_runner.py` |

Khuyến nghị tổng:

- Phase 1 chỉ làm `manual sync` + `manual input fallback`
- source of truth = `VideoAssignment`
- history = bảng snapshot riêng
- metrics core = `views/likes/comments/shares`
- `post_locator` capture ngay trong upload flow
