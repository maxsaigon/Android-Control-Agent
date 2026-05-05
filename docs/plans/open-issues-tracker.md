# Open Issues Tracker

> Created: 2026-04-02  
> Updated: 2026-04-02 10:28 (ICT)  
> Owner: Platform Core + TikTok Agent  
> Purpose: gom toàn bộ vấn đề còn mở vào một nơi duy nhất để debug có thứ tự, tránh chồng chéo giữa các nhánh fix và audit production.

## Operating Rules

- Mỗi vấn đề chỉ có **một** issue card trong file này.
- Khi có bug mới, phải kiểm tra file này trước để:
  - cập nhật vào issue đang mở nếu cùng root cause
  - hoặc tạo issue mới nếu là root cause khác
- Khi issue đã fix xong và có verification đủ mạnh, chuyển xuống `Recently Resolved`.
- Mọi deploy/fix liên quan production nên tham chiếu `Issue ID` trong commit note, audit note, hoặc log nội bộ.

---

## Snapshot

| ID | Severity | Area | Status | Short Summary |
|----|----------|------|--------|---------------|
| I-001 | P0 | TikTok Comment Runtime | 🔄 IN PROGRESS | `tiktok_comment` đã có run production thành công thật, nhưng vẫn cần nâng độ ổn định và success rate để đạt target count đều hơn |
| I-002 | P1 | Helper / Accessibility | 🔄 IN PROGRESS | Accessibility service vẫn có lúc degrade/rớt giữa comment flow |
| I-003 | P2 | Verification / Anti-spam | 🔄 MONITORING | Report task và `Comment history` hiện đã khớp ở các run mới, nhưng chưa có delayed verification/hard guarantee ở tầng history |
| I-004 | P1 | Video API / DB Schema | 🔄 IN PROGRESS | `GET /api/videos` đang fail trên production vì schema drift `video.description` |
| I-005 | P2 | Dashboard E2E | 🔄 IN PROGRESS | Browser smoke đã có, nhưng submit flow với device thật từ dashboard mới vẫn chưa được đóng hoàn toàn |

---

## I-001 — TikTok Comment Runtime Cần Ổn Định Hóa

Status: 🔄 IN PROGRESS  
Severity: P0  
Owner: TikTok Agent  
Last Confirmed: task `#24` ngày 2026-04-02

### Problem
- `tiktok_comment` đã có success thật trên production, nhưng chưa đủ ổn định để kỳ vọng đều đặn đạt target `count`.
- Vấn đề trọng tâm hiện tại không còn là “report success giả”, mà là:
  - success rate giữa các session còn biến thiên
  - số comment thực tế thường thấp hơn target `count`
  - helper degradation vẫn chen vào các run thành công

### Evidence
- Task `#21`: fail do `send_ready_ok` không lên, retry trước đây còn bị giữ text cũ trong field.
- Task `#22`: chỉ có 1 comment attempt thật; primary và retry đều có text đúng trong field nhưng detector cũ không thấy nút send dù recorder cho thấy nút hồng đang sáng.
- Recorder frame thật của task `#22` xác nhận nút send visible ở khoảng `(966, 1311)`.
- Task `#23`: `Commented on 1/5 ... verified: 1, failed: 0` và đã khớp `Comment history`.
- Task `#24`: `Commented on 3/5 ... verified: 3, failed: 0`; 3 comment trong task log khớp đúng 3 comment mới xuất hiện trong `Comment history`.

### What Has Been Fixed Already
- Không còn blind send khi chưa detect active target.
- Retry path bắt buộc clear input trước khi gõ lại.
- Retry/text ngắn dùng strict verification.
- Timeout path giữ partial step logs để audit không bị trắng.
- Skip LIVE sessions cho template `tiktok_comment`.
- Chống duplicate-video trong cùng session bằng video fingerprint.
- Detector send button đã chuyển từ raw screencap bytes sang PNG screenshot + connected-component detection.
- Detector send mới đã qua production thực tế:
  - task `#23` bắt send ở `fallback_right`
  - `send_ready_ok`, `send_tap_ok`, `posted_ok` đều pass
- Task reporting hiện đã khớp với `Comment history` ở các run mới nhất.

### What Is Still Open
- Cần nâng tỷ lệ đạt target `count` trong cùng một session.
- Cần hiểu rõ vì sao có session chỉ đạt `1/5` trong khi session khác đạt `3/5`.
- Cần giữ success ổn định ngay cả khi helper degraded trước/during typing.

### Next Actions
1. Theo dõi thêm 3-5 task production liên tiếp trên `192.168.1.45:5555`.
2. Với mỗi task, ghi lại:
   - target count
   - verified count
   - số cycle comment thật
   - số cycle bị skip
   - có/không có `helper_warn`
3. Gom pattern để tách:
   - issue runtime thật
   - session tự nhiên ít cơ hội comment
   - issue helper/control-plane

### Exit Criteria
- Có ít nhất 3 task production liên tiếp mà:
  - report task khớp `Comment history`
  - không có false positive `verified`
  - success rate đạt mức chấp nhận được so với target `count`

---

## I-002 — Helper Accessibility Service Không Ổn Định

Status: 🔄 IN PROGRESS  
Severity: P1  
Owner: Platform Core + Android Helper  
Last Confirmed: task `#24`

### Problem
- Helper Accessibility vẫn có thể rớt giữa lúc comment flow đang chạy.
- Khi helper degrade giữa typing/send, runtime phải recovery, làm:
  - mất thời gian
  - tăng số retry
  - làm khó tách lỗi send thật với lỗi backend/control-plane

### Evidence
- Log có chuỗi `Device error: Service not running`.
- Task `#21` và các task trước đó từng gặp `helper degraded before typing` / `during typing`.
- Task `#23` và `#24` vẫn còn `helper_warn` ở cả before/during typing, dù task vẫn thành công.

### What Has Been Fixed Already
- Có nhánh `recover_helper_service()` để re-enable accessibility, restart helper service, và kéo foreground quay lại TikTok.
- `helper_warn` / `helper_recover` đã được log vào step log.
- Không còn abort ngay nếu helper degraded nhưng text vẫn verify được.

### What Is Still Open
- Chưa có root cause cuối cùng ở phía helper APK hoặc Android OS vì sao service rớt.
- Chưa có health gate chủ động để phát hiện device đang ở trạng thái “helper yếu” trước khi bước vào cycle comment.

### Next Actions
1. Thêm health check nhẹ trước mỗi comment attempt:
   - ping helper
   - kiểm tra `get_ui_tree`
   - kiểm tra foreground app/readiness
2. Thu thập log/version/device-state từ helper khi service recover.
3. Nếu vẫn tái diễn:
   - audit helper APK lifecycle
   - xem lại foreground service / battery optimization / accessibility rebind

### Exit Criteria
- 5+ task comment liên tiếp không có `helper_warn` / `helper_recover`.

---

## I-003 — Verification / History Alignment Tiếp Tục Theo Dõi

Status: 🔄 MONITORING  
Severity: P2  
Owner: TikTok Agent  
Last Confirmed: task `#24` ngày 2026-04-02

### Problem
- Trước đây đã có false positive giữa report và `Comment history`.
- Hiện tại các run mới đã khớp, nhưng chưa có lớp guarantee ở tầng history-level persistence.

### Evidence
- Case trước đó: task báo `Commented on 2/5 ... verified: 2`, nhưng `Comment history` không có comment thành công.
- User xác nhận có 2 comment hiện trong history nhưng nằm cùng 1 video, làm lộ thêm sai lệch về semantics “success theo comment” vs “success theo unique video”.
- Task `#23`: report `1/5 verified` khớp `Comment history`.
- Task `#24`: report `3/5 verified` khớp với 3 comment mới trong `Comment history`.

### What Has Been Fixed Already
- Bỏ nhánh `LIKELY OK`.
- `verify_comment_posted()` giờ chỉ pass khi thấy comment mới visible và không nằm trong baseline comments trước khi gửi.
- Đã thêm chặn duplicate-video bằng fingerprint.
- Production runs mới nhất không còn cho thấy mismatch giữa report và history.

### What Is Still Open
- Chưa có delayed verification layer để kiểm tra lại sau vài giây/phút hoặc đối chiếu trực tiếp với `Comment history`.
- Chưa có semantic tách riêng:
  - `visible_post_ok`
  - `history_persisted_ok`

### Next Actions
1. Thêm verification 2 tầng cho `tiktok_comment`:
   - tầng 1: visible comment trên panel
   - tầng 2: delayed re-check hoặc audit riêng theo history
2. Bổ sung telemetry field để phân biệt rõ:
   - posted_to_ui
   - persisted_in_history
3. Không dùng `verified_actions` như KPI cuối nếu chưa có tín hiệu history-level đủ mạnh.

### Exit Criteria
- Metric/reporting của task phản ánh đúng nghĩa:
  - success ở UI
  - success bền vững trong history

---

## I-004 — Production Schema Drift Ở `/api/videos`

Status: 🔄 IN PROGRESS  
Severity: P1  
Owner: Platform Core  
Last Confirmed: 2026-03-31

### Problem
- `GET /api/videos` đang fail trên production do DB schema không khớp model hiện tại.

### Evidence
- Error:
  - `sqlite3.OperationalError: no such column: video.description`
- Endpoint hiện fail trong lúc dashboard/task flows khác vẫn chạy.

### Impact
- Tab Videos và các flow phụ thuộc video listing có thể bị hỏng hoặc trả 500.
- Đây là drift production, không phải bug logic frontend đơn thuần.

### Next Actions
1. Audit schema hiện tại của bảng `video` trên production.
2. So sánh với model hiện tại trong code.
3. Viết migration hoặc compatibility fallback có chủ đích.
4. Thêm smoke check riêng cho `/api/videos`.

### Exit Criteria
- `/api/videos` và các endpoint liên quan pass trên production data hiện tại.

---

## I-005 — Dashboard Submit E2E Với Device Thật Chưa Đóng

Status: 🔄 IN PROGRESS  
Severity: P2  
Owner: UI Dashboard + Platform Core  
Last Confirmed: 2026-04-02

### Problem
- Dashboard mới đã có public Playwright smoke và render ổn định, nhưng flow submit với device thật chưa được đóng như một phase hoàn chỉnh sau tất cả các lần redeploy/comment hardening.

### What Has Been Fixed Already
- Public domain smoke đã chặn stale JS/cache mismatch.
- Dashboard composer, template library, overview API, và login flow đã pass.

### What Is Still Open
- Chưa có một E2E chuẩn hóa từ UI:
  - chọn template
  - submit task
  - task chạy trên device thật
  - đối chiếu status về UI/operator flow

### Next Actions
1. Viết một browser-driven smoke có đăng nhập và submit task an toàn trên device test.
2. Chỉ dùng template/task non-destructive hoặc count thấp để giảm rủi ro.
3. Gắn check này vào phase sau khi comment runtime ổn định hơn.

### Exit Criteria
- Có browser E2E pass từ dashboard submit đến task state update trên server/device thật.

---

## Recently Resolved

Các mục dưới đây **không còn là issue mở**, chỉ giữ để tránh reopen nhầm:

### R-001 — HTML Mới nhưng JS Public Cũ
- Fixed bằng asset version động + public-domain Playwright smoke.

### R-002 — Mất History / Device Data Sau Deploy
- Fixed bằng restore DB production + thêm pre-deploy DB backup vào `max-lan-smoke.sh`.

### R-003 — Quét LAN Trả `Unexpected token 'I'`
- Fixed bằng error handling JSON-safe ở UI và API scan LAN.

### R-004 — `tiktok_comment` Comment Vào LIVE
- Fixed bằng `is_live_session()` + skip live trước và sau khi mở comment panel.

### R-005 — Duplicate Comment Trên Cùng Video
- Fixed bằng video fingerprint + verified feed advance sau mỗi swipe.

### R-006 — Retry Verify Pass Nhầm Khi Field Còn Text Cũ
- Fixed bằng `clear_comment_input()` + strict verify cho retry/text ngắn.

### R-007 — Timeout Task Làm Mất Step Log
- Fixed bằng persist partial `history` trong `task_queue`.
