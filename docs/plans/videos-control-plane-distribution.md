# Videos Control Plane Distribution

> Created: 2026-03-28  
> Updated: 2026-03-28 07:32 (ICT)  
> Owner: Platform Core + UI Dashboard  
> Scope: biến tab `Videos` thành control plane cho phân phối nội dung theo `video -> platform -> device/account target`

## Goal

Sau khi TikTok upload workflow đã chạy ổn định, bước tiếp theo là chuẩn hóa kiến trúc phân phối:

`Video asset -> target coverage -> assignment state -> upload execution -> artifact/review`

Mục tiêu là để tab `Videos` trở thành nơi điều phối chính, thay vì chỉ là thư viện file + danh sách assignment rời rạc.

---

## Architecture Direction

### Source of truth

- `Video` là content asset gốc.
- `DeviceAccount(device_id, platform)` định nghĩa target khả dụng.
- `VideoAssignment(video_id, device_id, platform)` là distribution unit thực tế.

### Core rule

- Một video có thể được assign tới nhiều device trên cùng một platform.
- Ràng buộc đúng là:
`UNIQUE(video_id, device_id, platform)`

Điều này thay thế rule cũ `UNIQUE(video_id, platform)` vốn không phù hợp với bài toán control plane nhiều target.

---

## Phase Tracking

### Phase A — Assignment model realignment
Status: ✅ Done

- [x] Đổi uniqueness của `VideoAssignment` sang `video_id + device_id + platform`.
- [x] Thêm migration logic để bỏ legacy unique index `video_id + platform` khi có thể.
- [x] Sửa `assign_video()` để duplicate check theo target thật.
- [x] Sửa `auto_assign()` để tạo missing targets thay vì round-robin một assignment duy nhất.
- [x] Verify migration behavior trên server Ubuntu data thật.

### Phase B — Distribution summary contract
Status: ✅ Done (foundation)

- [x] Enrich `GET /api/videos` với `platform_summary`.
- [x] Expose `missing_target_devices`, `assigned_targets`, `uploaded_targets`, `failed_targets`.
- [x] Giữ tương thích với TikTok-first upload orchestration hiện có.
- [ ] Add explicit distribution overview endpoint nếu data từ `GET /api/videos` bắt đầu quá nặng.

### Phase C — Video focus coverage UX
Status: 🔄 In Progress

- [x] Focus panel hiển thị coverage line theo TikTok targets.
- [x] Render target cards cho assigned targets.
- [x] Render missing-target cards với quick assign action.
- [x] Video cards hiển thị progress theo platform coverage thay vì assignment đầu tiên.
- [ ] Tách riêng target grid thành component/view ổn định cho nhiều platform hơn.

### Phase D — Multi-target operations
Status: ⏳ Next

- [ ] Chọn toàn bộ targets của 1 video rồi push/run từ focus panel.
- [ ] Filter assignment matrix theo `focused video + failed only + ready only`.
- [ ] Bulk rerun failed targets theo từng video.
- [ ] Add “run remaining targets” action cho từng video.

### Phase E — Cross-platform readiness
Status: ⏳ Planned

- [ ] Mở `platform_summary` cho YouTube / Instagram / Facebook ở mức control-plane data.
- [ ] Không build upload runtime mới ngay; chỉ chuẩn hóa target coverage + assignment lifecycle.
- [ ] Xác định platform capability flags: `has_account`, `has_script`, `can_assign`, `can_run`.

### Phase F — Ops / Review
Status: ⏳ Planned

- [ ] Add distribution history slice theo `video_id`.
- [ ] Add per-video rollout summary (`targets total`, `uploaded`, `failed`, `missing`).
- [ ] Add operator notes / manual-review markers khi cần.

### Phase G — Deployment verification
Status: ✅ Done

- [x] Sync updated control-plane files to `max.lan`.
- [x] Rebuild and restart Docker app.
- [x] Verify DB unique index on production-like env:
`uq_videoassignment_video_device_platform`.
- [x] Verify `GET /api/videos` returns `platform_summary` and `tiktok_assignments`.

---

## Current Risks

- SQLite legacy env có thể vẫn mang auto unique index cũ trên `(video_id, platform)` nếu DB được tạo từ schema rất cũ; trường hợp đó cần table rebuild thay vì drop index.
- `GET /api/videos` đang được enrich mạnh hơn; nếu số video/assignment tăng lớn sẽ cần endpoint summary chuyên biệt.
- UI hiện mới tối ưu sâu cho TikTok targets; phần cross-platform hiện vẫn ở mức data-contract direction.

---

## Definition of Done

- [x] Một video có thể có nhiều TikTok targets theo device/account.
- [x] `Auto-Assign TikTok` tạo đủ missing assignments thay vì chọn một device duy nhất.
- [x] Focus panel hiển thị rõ assigned targets và missing targets.
- [x] Operator có thể hiểu rollout status của một video mà không cần ghép thông tin thủ công từ nhiều nơi.
