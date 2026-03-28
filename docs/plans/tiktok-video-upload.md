# TikTok Video Upload Automation — IN PROGRESS

> **Created**: 2026-03-23 | **Updated**: 2026-03-25
> **Status**: 🔄 IN PROGRESS — Device-backed state machine validated through post form; post completion verification still pending

## Bối cảnh

Mục tiêu của phase này không còn chỉ là "bấm đúng vài tọa độ" để upload video lên TikTok.
Mục tiêu thật là xây được một flow upload **quan sát được, debug được, recover được và đủ ổn định để chạy lặp lại**.

TikTok upload là flow khó vì:

- Mỗi màn hình có thể thay đổi theo version app, ngôn ngữ, account state, popup và device ratio.
- Nhiều thành phần UI không ổn định nếu chỉ dựa vào tọa độ cứng.
- Một số bước quan trọng như chọn video, nhập caption, bấm Post và verify upload thường fail âm thầm nếu không có bằng chứng màn hình.
- ADB đủ tốt cho việc quan sát và thu thập artifacts, nhưng thao tác production ổn định hơn khi có Accessibility backend.

## Nguyên tắc triển khai

### 1. ADB-first for observability
- Dùng ADB để chủ động:
  - chụp screenshot
  - dump UI XML
  - lấy foreground app/activity
  - screenrecord
  - pull artifacts về server để phân tích

### 2. Accessibility for reliability
- Ưu tiên Accessibility backend cho:
  - tap/swipe ổn định hơn
  - nhập text Unicode cho caption
  - đọc foreground app
  - lấy screen size / UI tree khi cần

### 3. State machine thay vì flow tuyến tính
- Flow upload sẽ được nâng cấp từ chuỗi bước cứng thành state machine có khả năng:
  - nhận diện đang ở màn hình nào
  - quyết định bước tiếp theo
  - recover khi lệch flow
  - fail kèm evidence thay vì fail mù

### 4. Verify sau action
- Mỗi action quan trọng phải có hậu kiểm:
  - bấm `Create` xong phải sang camera/upload screen
  - bấm `Next` xong phải sang đúng màn hình tiếp theo
  - nhập caption xong phải verify field có text
  - bấm `Post` xong phải có tín hiệu uploading / completion hợp lệ

## Phạm vi của phase

### In scope
- Hoàn thiện `tiktok_upload` script theo assignment/video metadata
- Tăng độ chính xác selector cho toàn bộ flow upload
- Tạo bộ debug artifacts cho từng lần chạy
- Thêm recovery, retry và xác minh màn hình
- Thêm calibration/fallback theo device
- Cập nhật trạng thái DB chỉ khi có tín hiệu thành công hợp lệ

### Out of scope
- Tối ưu nội dung caption bằng AI
- Proxy / antidetect network layer
- Multi-account scheduling chiến lược
- Public SaaS onboarding cho user cuối

## Hiện trạng codebase

### Đã có sẵn
- `tiktok_upload` flow cơ bản trong [app/services/script_runner.py](/Volumes/Mac%20Work/python/Android-Control/app/services/script_runner.py)
- Các action upload cơ bản trong [app/services/tiktok_controller.py](/Volumes/Mac%20Work/python/Android-Control/app/services/tiktok_controller.py)
- `ensure_on_feed()`, popup dismissal, recovery, text input fallback, UI dump
- Video metadata lấy từ DB (`Video`, `VideoAssignment`)

### Chưa đủ chắc
- Flow còn tuyến tính, chưa phải state machine thật
- `select_first_video()` vẫn phụ thuộc fallback coordinates mạnh
- `tap_next()` và `tap_post()` chưa có verify đủ sâu theo từng screen
- Sau `Post` đang chờ thời gian cố định, chưa verify completion đủ tin cậy
- Thiếu debug harness/artifacts chuẩn để phân tích nhanh mỗi lần fail

## Phát hiện thực tế trên device `192.168.1.45:5555`

### Flow thật của TikTok build hiện tại
- Không có bước `camera -> upload_gallery thumbnail` như giả định cũ.
- Flow quan sát được trên máy thật là:
  - `feed`
  - `camera_create`
  - `gallery_picker`
  - `video_editor`
  - `post_form`

### Các marker đã xác nhận bằng screenshot + XML
- `feed`
  - Có `For You`, `Create`, `Read or add comments`
- `camera_create`
  - Có `Add sound`, `15s`, `60s`, `POST`, `CREATE`
- `gallery_picker`
  - Có `Recents`, `Select multiple`, `Next`
- `video_editor`
  - Có `Your Story`, `Add sound`, `Next`
- `post_form`
  - Có `Add description...`, `Drafts`, `Post`, `Everyone can view this post`

### Pitfall đã loại bỏ
- Tile đầu tiên trong `Recents` không phải lúc nào cũng là video thật.
- Chọn "ô đầu tiên" có thể vào preview lỗi hoặc asset không phù hợp.
- Selector gallery phải ưu tiên tile có overlay thời lượng như `01:01`.

### Hậu `Post` trên build hiện tại
- Sau khi bấm `Post`, TikTok không đơn giản ở yên trên post form.
- Success path quan sát được:
  - `Post`
  - launcher popup `Add to Home screen / TikTok Camera`
  - dismiss popup
  - TikTok share sheet `Video posted! Everyone can view. Share:`
  - follow-up permission popup Facebook/email (có thể xuất hiện sau đó)
- Điều này có nghĩa Phase 6 không thể chỉ nhìn `foreground_app == TikTok` hay `sleep 15s`.

### Evidence paths
- Clean run dataset:
  - `/tmp/android-control/screenshots/tiktok_upload_debug/phase2_clean_run`
- Editor/post-form probes:
  - `/tmp/android-control/screenshots/tiktok_upload_debug/phase2_post_form_probe`
- State-machine smoke:
  - `/tmp/android-control/screenshots/tiktok_upload_debug/phase3_controller_smoke`

## Mục tiêu kỹ thuật

Sau phase này, `tiktok_upload` cần đạt:

1. Có thể tự chạy end-to-end trên 1 device debug ổn định.
2. Mỗi lần fail đều có đủ bằng chứng để sửa:
   - screenshot
   - UI dump
   - foreground app
   - step log
   - optional screen recording
3. Không còn phụ thuộc hoàn toàn vào tọa độ cứng cho các bước chính.
4. Có cơ chế calibration và fallback rõ ràng cho các phần UI không dump được.
5. `VideoAssignment.push_status` chỉ chuyển sang `UPLOADED` sau khi có tín hiệu thành công đáng tin cậy.

## Execution Plan

### Phase 0 — Device Readiness & Session Setup

**Goal**: Có 1 thiết bị debug ổn định để thu thập dữ liệu màn hình.

**Yêu cầu**
- ADB ổn định (`adb devices` thấy liên tục)
- TikTok đã login
- Màn hình luôn sáng, không auto-lock
- Có video mẫu trên device hoặc đã push sẵn
- Nếu có thể: Accessibility helper hoạt động song song với ADB

**Deliverable**
- Một session debug có thể:
  - chụp screenshot
  - dump UI
  - screenrecord
  - launch TikTok

**Tracking**
- [x] Device online qua ADB ổn định
- [x] TikTok login sẵn
- [x] Video test đã có mặt trên device
- [x] Helper accessibility sẵn sàng hoặc đã xác nhận chưa dùng

### Phase 1 — Debug Harness & Artifact Collection

**Goal**: Mỗi lần test upload đều sinh ra evidence đầy đủ.

**Implementation**
- Thêm debug helpers để lưu theo step:
  - screenshot
  - UI XML dump
  - foreground app/activity
  - timestamp
  - action name
- Thêm tùy chọn `screenrecord` cho toàn bộ run hoặc các step quan trọng
- Chuẩn hóa thư mục artifact theo `task_id` / `timestamp`

**Files dự kiến**
- `app/services/tiktok_controller.py`
- `app/services/script_runner.py`
- có thể thêm helper mới trong `app/services/`

**Deliverable**
- Một run upload thất bại vẫn để lại đầy đủ dữ liệu phân tích

**Tracking**
- [x] Có helper chụp screenshot theo step
- [x] Có helper dump UI theo step
- [x] Có helper lấy foreground app/activity
- [x] Có thể bật/tắt screenrecord cho upload run
- [x] Artifacts được lưu có cấu trúc, dễ pull và đối chiếu

### Phase 2 — Screen Inventory & Dataset

**Goal**: Lập bản đồ các màn hình thực tế trong flow upload.

**Màn hình cần map**
- Feed / For You
- Create / camera entry
- Upload gallery
- Gallery grid / video selection
- Edit / trim / preview
- Post form / caption form
- Uploading / processing / posting
- Success / redirect / profile / inbox
- Popup/overlay bất thường

**Deliverable**
- Một bộ dataset thực tế gồm screenshot + XML cho từng screen
- Ghi chú phần nào:
  - nhận diện được bằng XML
  - chỉ nhận diện được bằng screenshot / color / coord

**Tracking**
- [x] Feed dataset
- [x] Create/camera dataset
- [x] Gallery dataset
- [x] Edit/preview dataset
- [x] Post form dataset
- [ ] Uploading/completion dataset
- [ ] Popup/exception dataset

### Phase 3 — Screen Classifier & State Machine

**Goal**: Script biết mình đang ở đâu trước khi hành động.

**Implementation**
- Viết classifier cho các state:
  - `feed`
  - `create_camera`
  - `gallery`
  - `video_selected`
  - `edit_preview`
  - `post_form`
  - `uploading`
  - `completed`
  - `unknown`
- Chuyển `tiktok_upload` thành state machine:
  - detect current state
  - choose action
  - verify next state
  - recover nếu lệch flow

**Deliverable**
- Upload flow không còn phụ thuộc chuỗi action cứng "bấm rồi cầu may"

**Tracking**
- [x] Có hàm detect current upload screen
- [x] `tiktok_upload` dùng state transition rõ ràng
- [x] Có timeout per state
- [ ] Có recovery path cho state unknown

### Phase 4 — Selector Hardening & Device Calibration

**Goal**: Tăng độ chính xác thao tác, giảm fail do layout khác nhau.

**Implementation**
- Chuẩn hóa selector theo thứ tự ưu tiên:
  1. Accessibility/UI node
  2. XML text/content-desc/class pattern
  3. screenshot/color/pixel hint
  4. calibrated coordinate fallback
- Tách fallback theo:
  - screen ratio
  - resolution bucket
  - device profile nếu cần

**Điểm cần ưu tiên**
- `tap_create()`
- `camera -> gallery transition`
- `select_first_video()`
- `tap_next()`
- `fill_post_metadata()`
- `tap_post()`

**Deliverable**
- Bộ selector có xác suất thành công cao hơn trên device thật

**Tracking**
- [x] Create selector hardened
- [x] Gallery selector hardened
- [x] Video selection calibrated
- [x] Next selector hardened
- [x] Caption field selector hardened
- [x] Post selector hardened

### Phase 5 — Caption Input Reliability

**Goal**: Caption/title/hashtags vào đúng field, giữ được Unicode nếu có.

**Implementation**
- Ưu tiên Accessibility text input
- Fallback ADB theo nhiều strategy như code hiện có
- Thêm verify nội dung sau khi paste/type
- Xử lý trường hợp TikTok chỉ có 1 caption field thay vì tách title/description
- Xử lý newline/hashtag formatting an toàn

**Deliverable**
- `fill_post_metadata()` hoạt động đáng tin trên màn hình Post

**Tracking**
- [x] Focus đúng field caption
- [x] Type/paste thành công với ASCII
- [ ] Type/paste thành công với Unicode nếu helper khả dụng
- [x] Verify được text đã có trong field
- [x] Hashtag formatting ổn định

### Phase 6 — Post Verification & Completion Detection

**Goal**: Không đánh dấu upload thành công chỉ vì đã sleep đủ lâu.

**Implementation**
- Nhận diện các tín hiệu sau Post:
  - màn hình uploading / processing
  - tiến trình rời khỏi post form
  - redirect về profile/feed/inbox
  - thông báo thành công / error / retry
- Nếu không có tín hiệu rõ:
  - capture evidence
  - giữ trạng thái fail/pending phù hợp

**Deliverable**
- Logic completion detection đáng tin hơn fixed sleep

**Tracking**
- [ ] Có detector cho uploading state
- [x] Có detector cho completion state
- [ ] Có detector cho error state sau Post
- [x] DB chỉ update `UPLOADED` sau verify

### Phase 7 — Integration, Retry & Regression Safety

**Goal**: Gắn flow upload vào hệ thống task hiện tại mà vẫn debug được.

**Implementation**
- Chuẩn hóa step log cho upload
- Retry có chọn lọc cho lỗi transient
- Không phá các script TikTok khác
- Bổ sung test hoặc fixture parser ở mức có thể

**Deliverable**
- Flow upload chạy được qua task queue, có logs, có artifact, có status DB đúng

**Tracking**
- [ ] Step logs đầy đủ
- [ ] Retry hợp lý cho transient failures
- [ ] Không regression các script khác
- [ ] Có fixture/test tối thiểu cho screen detection hoặc metadata assembly

## Files dự kiến sẽ thay đổi

- `app/services/script_runner.py`
- `app/services/tiktok_controller.py`
- `app/services/backend_manager.py` hoặc helper liên quan nếu cần
- `app/models.py` nếu cần thêm metadata/debug linkage
- `tests/` cho fixture hoặc regression test

## Definition of Done

Phase này được xem là đủ tốt khi:

- Một video đã assign có thể được upload qua `tiktok_upload` trên device debug.
- Khi fail, artifacts cho phép xác định nguyên nhân trong một vòng phân tích.
- Không còn bước mù chỉ dựa vào `sleep`.
- `push_status` chỉ chuyển sang `UPLOADED` sau verify đáng tin.
- Có ít nhất một bộ device profile/dataset thực tế để tiếp tục scale sang device khác.

## Blockers hiện tại

- Chưa chạy live `Post` đến completion trên account thật, nên Phase 6 vẫn thiếu dữ liệu uploading/success/error
- Chưa có detector đủ chắc cho `unknown` state / recovery sau khi flow lệch bất thường
- Chưa có fixture/test tự động cho screen detection để chống regression khi TikTok đổi UI

## Việc chờ từ phía người dùng

Ở vòng review cuối, cần xác nhận:

- Có cho phép chạy 1 live post kiểm chứng completion detector hay không
- Có muốn ưu tiên hỗ trợ caption Unicode/Vietnamese đầy đủ trên account test này không
- Có cần thêm fallback/recovery cho các popup hoặc redirect bất thường trước khi scale sang device khác không

Ưu tiên tiếp theo sau review:

1. Phase 6: post-completion verification bằng live run có kiểm soát
2. Phase 7: retry/recovery cho unknown state
3. Fixture/test cho classifier và selector
