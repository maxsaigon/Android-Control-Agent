# Upload Pipeline Standardization — 🔄 IN PROGRESS

> **Created**: 2026-03-25 | **Updated**: 2026-03-25
> **Status**: 🔄 IN PROGRESS — Review + execution roadmap defined

## Mục tiêu

Chuẩn hóa một pipeline duy nhất từ webapp đến device cho upload video đa nền tảng:

- 1 video có thể được phân phối theo platform/account/device đúng rule
- mỗi assignment chạy như một job có trạng thái rõ ràng, quan sát được
- script runtime nhận đúng context (assignment, metadata, device_path)
- không còn phụ thuộc thao tác manual giữa các bước `assign -> push -> tạo task`

## Review hiện trạng

### Điểm mạnh đang có

- Có thư viện video + dedup theo hash trong `Video` (`file_hash`)
- Có `VideoAssignment` + `DeviceAccount` + flow `assign -> push`
- Có task queue, device lock và retry cơ bản
- TikTok upload script đã có state machine thực tế và post-completion signal

### Gaps kỹ thuật quan trọng

1. `template_vars` không đi xuyên qua task lifecycle
- `TaskCreate` nhận `template_vars`, nhưng model `Task` không lưu trường này.
- `task_queue -> task_engine` không truyền `template_vars` vào script runtime.
- Hệ quả: script chỉ chạy default params; upload theo `assignment_id` từ webapp không ổn định.

2. Chưa có orchestration endpoint cho assignment upload
- Hiện mới có `POST /api/videos/assignments/{id}/push`.
- Chưa có endpoint chuẩn kiểu `run upload for assignment`.
- `VideoAssignment.task_id` tồn tại nhưng chưa được gán trong luồng submit.

3. Ràng buộc dữ liệu quan trọng chưa được enforce ở DB
- Rule `UNIQUE(video_id, platform)` đang ở app logic, chưa thấy DB constraint thực.
- `DeviceAccount` cũng chưa có unique constraint `(device_id, platform)`.
- Rủi ro race condition khi concurrent requests.

4. `push_status` đang gộp nhiều ý nghĩa
- `pending/pushed/uploaded/failed` đang vừa là push state vừa là upload result.
- Thiếu phân tách giữa `push transport` và `platform publish`.

5. Webapp chưa có flow upload-centric theo assignment
- Video tab hiện mạnh ở `upload/assign/push`, nhưng chưa có CTA trực tiếp `Run upload`.
- Người vận hành phải đi qua Task form chung, dễ sai template/params.

6. Cloud/LAN chưa được chuẩn hóa ở khâu push
- Push hiện dựa subprocess ADB theo `ip:port`.
- Cần policy rõ cho cloud devices (nơi không có ADB trực tiếp).

## Kiến trúc chuẩn hóa đề xuất

Chuẩn hóa execution theo đơn vị `Assignment Upload Job` thay vì tạo `Task` rời:

`Video -> VideoAssignment -> UploadJob(platform-specific) -> TaskExecution -> Verification -> Finalize`

Nguyên tắc:

- Assignment là source of truth cho mục tiêu upload
- Task là execution record của một lần chạy assignment
- runtime script luôn nhận context tối thiểu:
  - `assignment_id`
  - `video_id`
  - `platform`
  - `device_id`
  - `device_path`
  - `metadata bundle` (title/tags/desc theo platform/account)

## Execution Plan

### Phase A — Contract & Data Integrity (ưu tiên cao)

1. Thêm DB constraints thực tế:
- `VideoAssignment`: unique `(video_id, platform)`
- `DeviceAccount`: unique `(device_id, platform)`

2. Chuẩn hóa task payload:
- thêm `template_vars` vào `Task` model (JSON/text)
- queue/engine phải truyền params xuống `ScriptRunner.run`

3. Tách status:
- `push_status`: `pending/pushed/push_failed`
- `upload_status`: `pending/running/uploaded/upload_failed/verify_failed`

Deliverable:
- Mọi run có thể reconstruct đầy đủ input context từ DB

### Phase B — Assignment-Centric Orchestration API

1. Thêm endpoint orchestration:
- `POST /api/videos/assignments/{id}/run-upload`
- optional: `POST /api/videos/assignments/run-batch`

2. Endpoint làm các bước chuẩn:
- validate assignment + device account + file
- auto push nếu chưa pushed (configurable)
- tạo task script đúng template theo platform
- set `assignment.task_id`

3. Bổ sung idempotency:
- tránh tạo 2 upload task cùng assignment khi job đang running

Deliverable:
- Webapp chỉ cần bấm 1 nút để chạy end-to-end cho assignment

### Phase C — Platform Script Contract

1. Chuẩn hóa interface cho upload scripts:
- `tiktok_upload`, `instagram_upload`, `facebook_upload`, `youtube_upload`
- cùng input contract (assignment/device_path/metadata)
- cùng output contract (completion signal + error code + evidence path)

2. Chuẩn hóa completion detector:
- mỗi platform có `wait_for_publish_completion()` riêng
- output normalized status codes để dashboard hiển thị nhất quán

Deliverable:
- Multi-platform upload có hành vi và logs đồng nhất

### Phase D — Webapp Flow & Ops

1. Video Library:
- thêm nút `Run Upload` ở assignment row
- thêm `Run All Pending` theo platform/device filter

2. Assignment matrix:
- hiển thị tách biệt `Push` và `Upload`
- hiển thị `last_task_id`, `last_error`, `last_run_at`

3. History:
- deep link từ assignment -> task logs -> debug artifacts

Deliverable:
- Vận hành upload không cần chuyển qua Task form chung

### Phase E — Scale & Governance

1. Account-aware scheduling:
- queue theo `(device, platform account)` thay vì chỉ device

2. Safety rails:
- daily limit per account/platform
- blackout windows
- cooldown giữa các publish jobs

3. Reliability:
- retry policy theo error class (`popup_blocking`, `network`, `platform_reject`)

Deliverable:
- Pipeline đủ ổn định để scale nhiều device và nhiều account

## Ưu tiên triển khai ngay (2 tuần)

Week 1:
- Phase A hoàn tất
- Phase B API `run-upload` cho TikTok

Week 2:
- Webapp `Run Upload` + status tách bạch
- đóng loop assignment->task->artifact hoàn chỉnh cho TikTok

Sau đó mới nhân bản contract sang Instagram/Facebook/YouTube.

## Definition of Done

- Có thể từ webapp bấm `Run Upload` cho assignment và chạy end-to-end không bước tay.
- Mọi assignment run đều có:
  - task_id
  - normalized upload status
  - artifact path
  - error code có cấu trúc
- Multi-platform scripts dùng chung contract input/output.
- Dashboard phản ánh đúng `push` vs `upload` và trạng thái run hiện tại.
