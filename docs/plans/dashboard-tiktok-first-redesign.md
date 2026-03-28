# Dashboard TikTok-First Redesign

> Created: 2026-03-28  
> Updated: 2026-03-28 08:05 (ICT)  
> Owner: UI Dashboard + Platform Core  
> Scope: biến tab `Dashboard` thành cockpit TikTok-first, chuẩn hóa metadata template, và đồng bộ UI với runtime thật

## Goal

Đổi tab `Dashboard` từ một admin panel đa nền tảng thành khu điều phối chính cho vận hành TikTok, trong đó:

- `tiktok_comment` là template mặc định và nổi bật nhất
- Dashboard hiển thị rõ pipeline hybrid, fallback, risk, và trạng thái verify
- Template metadata trở thành source of truth cho composer và template library
- Nội dung markdown của template phản ánh logic runtime thật, không còn mô tả aspirational

---

## Product Direction

### Primary UX

- `Dashboard` ưu tiên `TikTok Comment Videos`
- `Live Run Rail` phải đọc được các phase chính của comment flow:
  - `info`
  - `read_comments`
  - `ai_comment`
  - `type`
  - `verify`
  - `comment_retry`
  - `comment_failed`

### Secondary UX

- TikTok secondary templates vẫn hiện rõ:
  - Browse
  - Warm-up
  - Like
  - Follow
- Facebook / Instagram / YouTube được giữ lại nhưng ở nhóm phụ

### Data model direction

- Dashboard composer không hardcode từng action-card riêng lẻ
- UI phải được dựng từ metadata trả về bởi `/api/templates`
- `tiktok_comment` dùng `count` làm biến canonical, vẫn support `max_comments` để backward-compatible

---

## Phase Tracking

### Phase A — Template metadata foundation
Status: ✅ Done

- [x] Mở rộng `TemplateManager` để parse YAML frontmatter.
- [x] Bổ sung metadata schema cho `/api/templates`:
  - `platform`
  - `mode`
  - `status`
  - `is_primary`
  - `implemented`
  - `default_vars`
  - `ui_fields`
  - `capabilities`
  - `limitations`
  - `risk_level`
  - `fallback_behavior`
- [x] Giữ `render()` dùng phần body markdown sau frontmatter.
- [x] Thêm alias `count <-> max_comments` cho `tiktok_comment`.

### Phase B — Template parity audit
Status: ✅ Done

- [x] Viết lại `tiktok_comment.md` theo pipeline runtime thật:
  - `video_info`
  - `read_comments`
  - DeepSeek text-only primary
  - GPT-4o screenshot fallback
  - pool fallback cuối cùng
  - send + verify bắt buộc
- [x] Bỏ thông điệp “screenshot-first” khỏi template chính.
- [x] Audit và chỉnh lại copy của:
  - `tiktok_browse`
  - `tiktok_warmup`
  - `tiktok_like`
  - `tiktok_follow`
  - `facebook_scroll`
  - `youtube_watch`
- [x] Thêm `instagram_scroll.md` để metadata/UI không còn mồ côi.
- [x] Đánh dấu `tiktok_edit_profile` là planned / not implemented.

### Phase C — Dashboard overview contract
Status: ✅ Done

- [x] Thêm `GET /api/dashboard/overview`.
- [x] Gom device snapshot, queue snapshot, recent failure counts, running by template/mode.
- [x] Trả `primary_template` và `top_templates` để UI dựng hero/composer/library.
- [x] Giữ nguyên `POST /api/tasks` và `POST /api/tasks/batch`.

### Phase D — Dashboard IA redesign
Status: ✅ Done

- [x] Redesign phần riêng của tab `Dashboard`.
- [x] Thêm `hero` + `System Snapshot`.
- [x] Thêm `Primary Run Composer` mặc định vào `tiktok_comment`.
- [x] Thêm `Live Run Rail`.
- [x] Thêm `Template Library` theo nhóm:
  - Primary
  - Secondary TikTok
  - Other Platforms
  - Planned
- [x] Thêm `Recent Outcomes`.
- [x] Chuyển từ action-card cũ sang metadata-driven composer.

### Phase E — Composer behavior alignment
Status: ✅ Done

- [x] Composer đọc field từ `ui_fields`.
- [x] `tiktok_comment` có field trực tiếp cho:
  - `count`
  - `view_time_min`
  - `view_time_max`
  - `like_after_comment`
  - `use_ai`
- [x] Tách execution area cho:
  - device
  - batch
  - cost estimate
- [x] Submit flow gửi đúng:
  - `template=tiktok_comment`
  - `execution_mode=script`
  - `template_vars.count`
  - `template_vars.use_ai`
  - watch min/max
  - `like_after_comment`

### Phase F — Verification and follow-up
Status: 🔄 In Progress

- [x] JS syntax check bằng `node --check`.
- [x] Python compile check cho các file backend chính.
- [x] Manual assertion cho `TemplateManager` metadata/rendering.
- [ ] Full browser smoke test với server runtime đầy đủ dependency.
- [ ] E2E submit thử `tiktok_comment` từ Dashboard mới trên môi trường app chạy thật.
- [ ] Rà thêm visual polish khi có feedback thực tế từ thao tác operator.

---

## Current Risks

- Môi trường local hiện chưa đủ package runtime để chạy full app smoke test ngay trong turn này.
- `/api/dashboard/overview` hiện dựa nhiều vào metadata tĩnh hơn là telemetry thật vì local DB đang rỗng.
- Composer mới đã metadata-driven, nhưng các template planned/beta cần tiếp tục được review nếu sau này được đưa lên luồng primary.

---

## Definition of Done

- [x] Dashboard mặc định vào `tiktok_comment`.
- [x] UI không còn bắt user đi qua `Custom AI` để chạy hybrid comment flow.
- [x] Template library và detail panel phản ánh metadata thực.
- [x] Nội dung `tiktok_comment` khớp pipeline runtime thật.
- [x] Các template chính không còn mô tả vượt quá khả năng runner hiện tại.
- [ ] Đã chạy smoke test end-to-end trên môi trường server/dashboard đầy đủ dependency.
