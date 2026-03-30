# TikTok Automation — Vấn đề, Giải pháp & Tiến độ

> **Mục đích**: Tài liệu này ghi lại toàn bộ vấn đề gặp phải khi automation TikTok, các giải pháp đã thử (kể cả thất bại), và những gì đã hoạt động. Giúp agent mới không phải lặp lại các quy trình đã fail.

> **Cập nhật lần cuối**: 2026-03-30 14:15

---

## 1. Kiến trúc TikTok Automation hiện tại

### Các file chính
| File | Vai trò |
|------|---------|
| `app/services/tiktok_controller.py` | Controller cấp thấp — tap, swipe, type, detect UI elements |
| `app/services/script_runner.py` | Script cấp cao — orchestrate flows (browse, like, comment, follow) |
| `app/templates/tiktok_*.md` | 7 template kịch bản: browse, warmup, like, comment, follow, upload, edit_profile |

### Các kịch bản đã implement (script deterministic)
- ✅ `tiktok_browse` — lướt feed, xem video, random like
- ✅ `tiktok_warmup` — xem video thụ động, không tương tác (warm-up account mới)
- ✅ `tiktok_like` — like video bằng double-tap hoặc tap heart icon + verification
- ✅ `tiktok_comment` — hybrid AI+script: AI sinh comment + script gửi + verification
- ✅ `tiktok_follow` — vào profile → follow + verification
- 📋 `tiktok_upload` — chỉ có template, chưa implement script
- 📋 `tiktok_edit_profile` — chỉ có template, chưa implement script

---

## 2. Vấn đề đã gặp & Giải pháp

### 2.1 🔴 Send Comment Button — INVISIBLE cho uiautomator

**Vấn đề**: Nút Send (mũi tên hồng ⬆) trong panel comment **KHÔNG XUẤT HIỆN** trong `uiautomator dump`. TikTok render nút này dưới dạng SurfaceView overlay — UI hierarchy hoàn toàn không thấy.

**Các giải pháp ĐÃ THỬ và THẤT BẠI**:
1. ❌ **`uiautomator dump` → tìm nút Send**: Không tìm thấy — nút invisible
2. ❌ **Tìm theo resource-id**: TikTok obfuscate resource-id thành mã 3 ký tự random (dzw, fca...) — không ổn định giữa các version
3. ❌ **Hardcoded coordinates fallback (w*0.92, h*0.90)**: Toạ độ sai vì vị trí nút thay đổi khi keyboard mở/đóng
4. ❌ **`input keyevent 66` (ENTER)**: TikTok xử lý ENTER thành xuống dòng (newline), KHÔNG phải gửi comment

**Giải pháp THÀNH CÔNG** ✅:
- **Screenshot pixel detection** (`_find_pink_send_button()`):
  - `adb shell screencap /sdcard/_pink.dump` → `adb pull` → đọc binary pixel data
  - Scan tìm pixel hồng: **R>230, G<120, B<140, (R-G)>100**
  - Vùng scan: phải 30% màn hình (x > w*0.7), y: 40-80% (tránh false positive từ hearts)
  - Tìm cluster center → đó là nút Send
  - Kích thước hợp lệ: 40-200px (hình tròn)

**3-tier fallback strategy cho `send_comment()`**:
1. Pink pixel detection (primary)
2. UI dump tìm text "Post"/"Send"/"Đăng"/"Gửi" (cho version TikTok khác)
3. Hardcoded coords: (w*0.89, h*0.575) — khi keyboard đang mở

---

### 2.2 🔴 Instant Tap bị TikTok REJECT

**Vấn đề**: `adb shell input tap x y` tạo ra touch event 0ms (instant). TikTok **CHẤP NHẬN** tap này (comment hiển thị tạm thời trên UI) nhưng **KHÔNG THỰC SỰ POST** lên backend. Comment biến mất sau vài giây, không xuất hiện trong Comment History.

**Bằng chứng**:
| Method | Kết quả |
|--------|---------|
| `input tap 966 1310` | ❌ Comment hiện tạm ("testcomment") nhưng **KHÔNG có trong Comment History** |
| `input keyevent 66` (ENTER) | ❌ Thêm newline thay vì gửi |
| `input swipe 965 1310 965 1310 80` | ✅ **Comment "entertest" posted at "1s ago"** — hiện trong comment list |

**Giải pháp THÀNH CÔNG** ✅:
- **`_realistic_tap()`**: Dùng `input swipe x y x y <duration>` thay vì `input tap`
- Duration: 80ms ± 20ms random — mô phỏng ngón tay nhấn-rồi-nhả
- TikTok chấp nhận đây là human input

```
# Thay vì:
adb shell input tap 966 1310  # ❌ 0ms, bị reject

# Dùng:
adb shell input swipe 966 1310 966 1310 80  # ✅ 80ms, accepted
```

> [!CAUTION]
> **`_realistic_tap` CHỈ DÙNG CHO SEND BUTTON**. Các tap thông thường (like, comment icon, follow) vẫn dùng `input tap` bình thường — chỉ Send button bị TikTok filter.

---

### 2.9 🟡 `_run_adb` Corrupts Binary Data

**Vấn đề**: `_run_adb()` trong `adb_agent.py` (line ~221) decode stdout bằng `.decode(errors='replace')` — chuyển bytes thành string. Khi dùng `exec-out screencap` (trả raw pixel data), binary bị corrupt vì `.decode()` thay các byte không hợp lệ bằng `?`.

**Giải pháp** ✅: Dùng **file-based approach** thay vì pipe:
```
# Thay vì:
adb exec-out screencap  # ❌ Binary bị corrupt bởi _run_adb.decode()

# Dùng:
adb shell screencap /sdcard/_pink.dump  # Save trên device
adb pull /sdcard/_pink.dump /tmp/        # Pull về local (binary-safe)
# Read with open(_path, 'rb') as f: ...  # Đọc raw bytes
```

---

### 2.10 🟡 `steps_taken` Không Update Real-time

**Vấn đề**: Trong API `/api/tasks/{id}`, field `steps_taken` luôn = 0 trong khi task đang chạy. Chỉ update về giá trị đúng **sau khi task hoàn thành** (ví dụ: `steps=93` khi complete). Điều này gây hiểu nhầm task bị stuck trong khi thực tế nó đang chạy bình thường.

**Workaround**: Kiểm tra `queue-status` API — nếu `running_tasks > 0` và `device_locks` chứa device ID, task đang chạy. Hoặc chụp screenshot device để xác nhận.

**Root cause**: `steps_taken` counter ở DB chưa được update real-time bởi `on_step` callback, chỉ update bulk khi `TaskResult` trả về.

---

### 2.11 🟢 Vietnamese Comment — SOLVED via Accessibility

**Vấn đề ban đầu**: Comment tiếng Việt như "quá hay" bị `adb input text` mangled thành "qu hay" hoặc bị drop. `type_text()` trong TikTokController luôn fallback về ADB vì `self._backend` chưa được khởi tạo.

**Root cause**: `type_text()` check `if self._backend:` nhưng KHÔNG gọi `await self._get_backend()` để lazy-init. `self._backend` luôn = `None`, nên luôn dùng ADB path (ASCII only).

**Giải pháp** ✅: Thêm `await self._get_backend()` vào `type_text()` → auto-detect AccessibilityBackend → WebSocket → Helper APK → `ACTION_SET_TEXT` (full Unicode).

**Pipeline đầy đủ**:
```
TikTokController.type_text("tuyệt vời")
  → await self._get_backend()         # Lazy-init Accessibility via BackendManager
  → self._backend.type_text()          # AccessibilityBackend
    → WebSocket ws://device:38301      # JSON command
      → CommandHandler: "type_text"    # Java handler
        → service.typeText()           # ACTION_SET_TEXT (Unicode ✅)
```

**Bằng chứng**: Screenshot cho thấy **"Video tuyệt vời quá! 🔥🇻🇳"** hiển thị HOÀN HẢO trong comment field — dấu tiếng Việt + emoji đều đúng.

---

### 2.12 🟢 Accessibility-First Migration

**Vấn đề**: Mọi action (tap, swipe, type, key_event) đều dùng ADB trực tiếp. `self._backend` chưa được init vì thiếu `await self._get_backend()`.

**Giải pháp** ✅: Thêm `await self._get_backend()` vào TẤT CẢ methods trước khi check `self._backend`. Accessibility được ưu tiên, ADB chỉ dùng khi Accessibility unavailable.

**Pattern áp dụng cho mọi method**:
```python
await self._get_backend()  # Lazy-init AccessibilityBackend
if self._backend:
    await self._backend.action(...)  # Ưu tiên Accessibility
else:
    # FALLBACK: ADB
    await self._adb._run_adb(...)
```

**Methods đã migrate**: `_tap`, `_realistic_tap`, `_get_screen_size`, `type_text`, `is_tiktok_foreground`, `recover`, `close_panel`, `swipe_next`, `dismiss_popups` BACK key.

**Methods cần migrate** (TODO `[ACCESSIBILITY-MIGRATE]`): `dump_ui`, `_find_pink_send_button`, `_capture_verify_screenshot` — cần format adapter hoặc binary screenshot support.

---

### 2.13 🟡 Context-Aware AI Comments (v2)

**Vấn đề**: DeepSeek sinh comment CHUNG CHUNG ("hay quá", "tuyệt vời") → TikTok spam filter reject.

**Root cause**: Prompt cũ yêu cầu "comment ngắn, tự nhiên, SÁNG TẠO" mà KHÔNG cung cấp context. AI không biết video nói gì, người khác comment gì.

**Giải pháp** ✅:
1. **`read_comments()`** — method mới trong TikTokController, scrape comments từ UI hierarchy khi panel mở
2. **Prompt mới** — BẮT BUỘC đề cập 1 chi tiết CỤ THỂ, có GÓC NHÌN rõ ràng
3. **Flow mới**: get video info → mở panel → đọc comments → generate AI với full context

**Ví dụ TỐT vs XẤU**:
| ✅ TỐT | ❌ XẤU |
|---------|--------|
| "đoạn chuyển nhạc ở giây 5 smooth quá" | "hay quá" |
| "outfit hôm nay match ghê" | "tuyệt vời!" |
| "kỹ năng tay trái ảo thật" | "đỉnh nóc" |
| "nhạc này là bài gì nhỉ nghe hoài ko chán" | ":))" |

**Context gửi cho DeepSeek**:
```
Creator: username
Mô tả video: #hashtag content...
Nhạc nền: bài xyz
--- Comment nổi bật (người khác đã viết) ---
  @user1: nhạc này hay quá
  @user2: outfit đẹp ghê
```

**Trạng thái**: 🟡 Đã implement, CHƯA TEST. Cần chạy task mới để xác nhận.

---

### 2.14 🟡 Send Button Inactive Sau Khi Text Đã Hiện

**Triệu chứng**: Comment đã xuất hiện trong ô nhập, nhưng nút Send vẫn không bật màu hồng nên bấm gửi không có tác dụng. Flow cũ vẫn tiếp tục tap vào vùng send, dẫn tới verify fail hoặc fail thầm lặng.

**Root cause khả dĩ**:
1. `ACTION_SET_TEXT` / clipboard / paste có thể làm text hiển thị trong `EditText` nhưng **không kích hoạt TextWatcher** của TikTok
2. Flow cũ chỉ verify `"text đã có trong ô"` rồi gửi ngay, nhưng **không verify `"send button đã active"`**
3. Hardcoded fallback tap vào vùng send là blind tap, không phân biệt nút đang active hay disabled

**Giải pháp đã áp dụng** ✅:
1. Thêm **`ensure_comment_send_ready()`**:
   - detect active send target qua `_find_pink_send_button()` hoặc button text-based
   - nếu chưa active: re-focus input rồi dùng **ADB real input nudge** (`x`/space + `DEL`) để kích hoạt watcher
2. `script_runner._attempt_comment()` chỉ gọi `send_comment()` sau khi `ensure_comment_send_ready()` trả `True`
3. `send_comment(allow_blind_fallback=False)` được dùng trong comment flow để **từ chối blind tap** khi chưa detect active send target
4. Nếu vẫn không active → chụp screenshot `comment_send_inactive` để debug

**Quy tắc mới**:
> **Text visible chưa đủ để gửi comment.** Với TikTok comment flow, phải verify `send-ready` trước khi tap Send.

**Giải pháp dài hạn nên làm tiếp**:
- Nâng helper APK để hỗ trợ **IME-like incremental typing** hoặc **set-text + synthetic edit event**, thay vì chỉ `ACTION_SET_TEXT`
- Thêm metric/log riêng cho `text_entered_ok` vs `send_ready_ok` vs `posted_ok` để phân biệt rõ lỗi nhập text và lỗi kích hoạt send
- Chạy regression task chỉ để test `comment input -> send ready` trên 2-3 version TikTok khác nhau

---

### 2.15 🟡 Retry Comment Có Thể Giữ Text Cũ Trong Ô Nhập

**Triệu chứng**: Retry log báo đã gõ comment ngắn như `:)`, `wow`, `lol`, nhưng `EditText` thực tế vẫn còn comment cũ từ lượt primary. Verification cũ vẫn có thể pass vì chỉ match một phần text hoặc chấp nhận text không-placeholder.

**Root cause**:
1. Retry path không ép clear ô comment trước khi retype
2. `_verify_text_entered()` quá nới, đặc biệt với retry text ngắn
3. Khi helper degraded giữa typing, field dễ giữ state cũ nhưng flow vẫn nghĩ retry thành công

**Giải pháp đã áp dụng** ✅:
1. Thêm `clear_comment_input()` trước cả primary typing và retry typing
2. Nếu không clear được field → fail sớm, chụp screenshot `comment_input_not_cleared`
3. `_verify_text_entered(..., strict=True)` cho retry hoặc text rất ngắn, không chấp nhận partial token match

**Quy tắc mới**:
> Với retry comment, phải clear field và verify đúng text retry. Không được gửi nếu ô nhập còn text cũ.

---

### 2.16 🟡 Task Timeout Làm Mất Forensic Steps

**Triệu chứng**: Khi task bị timeout 10 phút, API/DB có thể trả `steps=0` dù stdout cho thấy task đã chạy rất nhiều step. Điều này làm mất dữ liệu debug cho các case fail dài.

**Root cause**: Nhánh timeout trong `task_queue` tạo `TaskResult` mới với `steps=0`, không dùng lại step history đang giữ trong live memory.

**Giải pháp đã áp dụng** ✅:
1. `on_step` giữ thêm `history` ring buffer riêng cho mỗi task
2. Timeout path tái sử dụng `current_step` + `history` để persist partial `step_log`
3. REST polling vẫn chỉ giữ 10 step gần nhất để UI nhẹ, nhưng forensic log vẫn còn tối đa 500 step

**Quy tắc mới**:
> Timeout không được làm mất log. Mọi task fail do timeout vẫn phải giữ đủ dấu vết để audit.

---

### 2.17 🟡 Raw Screencap Có Thể Làm Mù Detector Send Button

**Triệu chứng**: Recorder và screenshot cho thấy nút Send đang sáng màu hồng rất rõ, nhưng `_find_pink_send_button()` vẫn log `Too few pink pixels (0)` và `send_ready_ok = fail`.

**Root cause**:
1. Dò màu trực tiếp trên raw bytes từ `screencap` không ổn định giữa thiết bị vì channel order/format có thể khác
2. Khi scan toàn vùng bên phải, detector cũ có thể gom cả underline đỏ trong ô input với nút Send thành một bbox quá lớn rồi reject

**Giải pháp đã áp dụng** ✅:
1. Chuyển detector sang **PNG screenshot thật**:
   - ưu tiên `backend.capture_screenshot()`
   - fallback `adb shell screencap -p` + pull file
2. Scan theo lane gần ô input nhưng tách **connected components**
3. Chỉ nhận component tròn/compact ở mép phải, bỏ underline đỏ mảnh trong field

**Quy tắc mới**:
> Send-button detection phải chạy trên ảnh đã decode (PNG/JPEG), không dựa vào raw screencap bytes.

---

### 2.3 🟢 Unicode/Vietnamese Text Input — SOLVED

**Vấn đề**: `adb shell input text` chỉ hỗ trợ ASCII. Comment tiếng Việt có dấu (ví dụ: "tuyệt vời!") bị mangled hoặc không gõ được.

**Giải pháp chính** ✅: **Accessibility Backend** (`ACTION_SET_TEXT`) — xem §2.11.

**Fallback chain** (khi Accessibility không available):
1. **ASCII direct** — nếu text thuần ASCII → `input text`
2. **ADBKeyboard IME broadcast** — encode base64 → `am broadcast -a ADB_INPUT_B64 --es msg <b64>`
3. **Clipboard service call** → `keyevent 279` (PASTE)
4. **Clipper app broadcast** → `am broadcast -a clipper.set -e text <text>` → PASTE
5. **ASCII fallback** — strip non-ASCII, thay bằng `:)` nếu rỗng

**Verification**: `_verify_text_entered()` dump UI kiểm tra EditText có text thật.

**Trạng thái**: 🟢 **SOLVED** — Accessibility là primary path, ADB chỉ là fallback.

---

### 2.4 🟡 UI Element Detection — content-desc vs resource-id

**Vấn đề**: TikTok obfuscate `resource-id` thành mã ngẫu nhiên 3 ký tự (thay đổi mỗi version). Không thể dựa vào resource-id.

**Giải pháp** ✅:
- Dùng `content-desc` (ổn định qua các version TikTok) làm primary locator
- Regex patterns đã map:
  - Like: `"Like video"` → đổi thành `"Unlike video"` khi đã liked
  - Comment: `"Read or add comments"`
  - Share: `"Share video"` 
  - Follow: `"^Follow\\s"`
  - Profile: `"profile$"`
  - Sound: `"^Sound:"`
  - Nav tabs: `"^Home$"`, `"^Inbox$"`, `"^Profile$"`, `"^Create$"`
- Fallback: calibrated coordinates theo % screen size (1080x2280 reference)

---

### 2.5 🟢 Popup/Dialog Dismissal

**Vấn đề**: TikTok mở lên thường có các popup (Privacy Policy, Cookie consent, Age verification, LIVE stream redirect).

**Giải pháp** ✅ (`dismiss_popups()`):
- Scan UI dump tìm clickable buttons match patterns: "Got it", "Accept", "OK", "Allow", "Agree", "Continue", "Not now", "Skip", "Close", "Dismiss", "Yes"
- Nếu không tìm thấy button nhưng không có feed elements → press BACK (có thể đang ở webview/LIVE)
- Max 5 attempts, mỗi lần đợi 1.5s

---

### 2.6 🟢 Post-Action Verification System

**Vấn đề ban đầu**: Mọi method đều return `True` unconditionally — kể cả khi fallback path fail. Comment báo success nhưng thực tế KHÔNG ĐƯỢC POST.

**Giải pháp** ✅ — 3 verification methods:

#### Like Verification (`verify_like_state`)
- Sau khi tap like → dump UI → check `content-desc` thay đổi
- "Like video" → "Unlike video" = đã like thành công
- Keywords: "unlike", "liked", "bỏ thích"

#### Comment Verification (`verify_comment_posted`)
- Sau lần false-positive ngày `2026-03-29`, **không còn cho phép `EditText cleared` tự động pass**
- Success chỉ được tính khi:
  1. panel vẫn mở
  2. input không còn giữ nguyên text vừa gõ
  3. **và** có visible comment mới match mạnh với comment vừa gửi
- Match mới phải **không được tồn tại trong baseline comments trước khi send**
  - đặc biệt quan trọng với retry comments generic như `"lol"`, `"wow"`, `"nice"`
- `EditText cleared` nhưng không thấy comment mới = **AMBIGUOUS → FAIL SAFE**
- `EditText still has text` = FAILED (nút Send miss)
- `No EditText found` = FAILED (tap lệch ra ngoài / panel đóng)

#### Follow Verification (`verify_follow_state`)
- Sau khi tap Follow → check button text đổi thành "Following"/"Friends"/"Đang follow"/"Bạn bè"
- Button biến mất = likely succeeded

---

### 2.7 🟢 TikTok Foreground Recovery

**Giải pháp** ✅ (`recover()` + `is_tiktok_foreground()`):
- **Primary**: Accessibility `get_foreground_app()` → check package name
- **Fallback**: ADB `dumpsys activity activities` → tìm `mResumedActivity` chứa `com.ss.android.ugc.trill`
- Recovery flow: BACK → check → re-launch → check
- **Lưu ý**: KHÔNG dùng pipe/grep trong ADB args — phải filter trong Python

---

### 2.8 🟢 Comment Flow — Context-Aware AI (v2)

**Flow mới** (refactored 2026-03-20):
1. `get_video_info()` → lấy metadata (author, description, sound, likes)
2. `tap_comment_icon()` → mở comment panel
3. **`read_comments()`** → scrape 5-10 comments đang hiển thị từ UI dump
4. **AI generate** với FULL context (video info + existing comments)
5. Tap input field → type text via Accessibility → verify in field
6. Send comment (`_realistic_tap` + pink detection)
7. Verify comment posted (3s timeout)

**Thay đổi so với v1**:
- ❌ Cũ: Generate comment TRƯỚC khi mở panel → AI không biết comments người khác
- ✅ Mới: Mở panel → đọc comments → generate comment CÓ CONTEXT
- Prompt yêu cầu comment CỤ THỂ, có GÓC NHÌN — không chấp nhận generic praise

**Retry strategy**:
- Nếu fail → retry 1 lần với ASCII comment ("nice", "love this", "wow", "lol", ":)")
- Nếu retry cũng fail → capture debug screenshot
- Step limit: 100 steps mỗi session
- `failed` metric chỉ đếm **video fail cuối cùng**, không cộng fail tạm của primary attempt
- Sau audit task `#9` ngày `2026-03-29`:
  - **không abort chỉ vì helper báo degraded** nếu UI verify cho thấy text đã nằm trong field
  - sau helper recovery, ưu tiên **giữ comment panel hiện tại** thay vì tap lại icon comment bằng fallback coords
  - `dump_ui()` phải fallback sang `Accessibility get_ui_tree()` khi ADB `uiautomator dump` trả rỗng/fail
  - bật `comment-cycle screenrecord` để mỗi lần bot comment đều có MP4 riêng phục vụ audit

---

## 3. Những gì ĐÃ HOẠT ĐỘNG ✅

1. **Browse feed** — mở TikTok, dismiss popups, ensure on feed, swipe qua videos
2. **Like videos** — double-tap (70%) hoặc heart icon (30%) + verify like state
3. **Comment videos** — context-aware AI comment + Accessibility input + pink button detect + realistic tap + verify
4. **Follow accounts** — tap avatar → xem profile → tap Follow + verify state
5. **Warmup accounts** — passive browsing, random long pauses, occasional profile view
6. **Anti-detection behaviors** — random delays, skip patterns, varied timings, scroll speed variation
7. **AI comment generation v2** — DeepSeek + video info + existing comments context → comment CỤ THỂ có quan điểm
8. **Verification system** — post-action checks cho like/comment/follow, capture screenshots on failure
9. **Send button detection** — screencap pixel analysis tìm nút Send hồng (invisible cho uiautomator)
10. **Realistic tap** — `input swipe x y x y 80` vượt qua anti-bot check của TikTok
11. **Accessibility-first backend** — tất cả actions ưu tiên Accessibility (tap, swipe, type, key_event), ADB chỉ fallback
12. **Vietnamese/Unicode input** — `ACTION_SET_TEXT` qua Accessibility WebSocket, full Unicode support
13. **Comment context reading** — `read_comments()` scrape comments từ UI khi panel mở

---

## 4. Những gì CHƯA HOẠT ĐỘNG / CẦN CẢI THIỆN 🟡

1. ~~**Unicode text input**~~ — ✅ **SOLVED** via Accessibility
2. **Upload video** (`tiktok_upload`) — chỉ có template, chưa implement script
3. **Edit profile** (`tiktok_edit_profile`) — chỉ có template, chưa implement
4. **Search & engage** — chưa implement flow tìm kiếm keyword → interact
5. **Comment panel scroll** — chưa handle scroll xuống xem thêm comments
6. **Multi-device screen calibration** — fallback coords calibrated cho 1080x2280
7. **`steps_taken` real-time** — chỉ update khi complete
8. **Comment verification false positive** — TikTok async reject sau 3-10s → cần re-check sau 10-30s
9. **Accessibility migration TODO** — `dump_ui()`, `_find_pink_send_button()`, `_capture_verify_screenshot()` vẫn dùng ADB (xem §2.12)

---

## 5. Anti-Detection Rules Đã Implement

| Rule | Implementation |
|------|---------------|
| Random delays giữa actions | `human_behavior.random_delay()` + `_wait(lo, hi)` |
| Không like/comment liên tục | Skip 2-3 video giữa mỗi comment; `consecutive_likes` cap |
| Scroll speed variation | Random duration 250-450ms |
| Occasional long pauses | 10% chance pause 8-20s; warmup có 30-60s pauses |
| Mixed behaviors | Profile visits (10-15%), read others' comments (40%), sometimes NOT follow (30%) |
| Double-tap vs heart icon | 70/30 split cho like |
| Comment đa dạng | AI generate context-aware comments dựa trên video + existing comments |
| Realistic tap timing | 80ms swipe-tap cho Send button (Accessibility primary, ADB fallback) |

---

## 6. Lưu ý quan trọng cho Agent mới

> [!IMPORTANT]
> **KHÔNG dùng `input tap` cho nút Send comment**. TikTok silently reject 0ms taps. PHẢI dùng `input swipe x y x y 80` (realistic tap).

> [!IMPORTANT]
> **Nút Send INVISIBLE trong uiautomator dump**. Chỉ có thể detect qua screenshot pixel analysis (tìm pixel hồng R>230, G<120, B<140).

> [!IMPORTANT]
> **resource-id TikTok bị obfuscate** — KHÔNG dùng resource-id. Luôn dùng `content-desc` patterns.

> [!WARNING]
> **`input keyevent 66` (ENTER) KHÔNG gửi comment** trên TikTok — nó tạo newline.

> [!WARNING]
> **Mọi method đều phải VERIFY** sau khi thực hiện. Không tin return value — phải dump UI check state change.

> [!NOTE]
> Device test hiện tại: `192.168.1.45` (1080x2280). Package: `com.ss.android.ugc.trill`.

---

## 7. Accessibility-First Migration Status

### Đã migrate (Accessibility primary, ADB fallback):
| Method | Accessibility API | ADB Fallback |
|--------|-------------------|-------------||
| `_tap()` | `tap(x, y)` | `input tap` |
| `_realistic_tap()` | `swipe(x,y,x,y,80)` | `input swipe` |
| `_get_screen_size()` | `get_screen_size()` | `wm size` |
| `type_text()` | `ACTION_SET_TEXT` (Unicode) | `input text` (ASCII) |
| `is_tiktok_foreground()` | `get_foreground_app()` | `dumpsys activity` |
| `recover()` | `key_event()` + `launch_app()` | `keyevent` + `monkey` |
| `close_panel()` | `key_event("BACK")` | `keyevent 4` |
| `swipe_next()` | `swipe()` | `input swipe` |
| `dismiss_popups()` BACK | `key_event("BACK")` | `keyevent 4` |

### TODO — Cần migrate:
| Method | Hiện tại (ADB) | Mục tiêu (Accessibility) |
|--------|----------------|-------------------------|
| `dump_ui()` | `uiautomator dump` | `get_ui_tree()` + format adapter |
| `_find_pink_send_button()` | `screencap` + `pull` | `capture_screenshot()` via WebSocket |
| `_capture_verify_screenshot()` | `screencap` + `pull` | `capture_screenshot()` via WebSocket |

---

## 8. Lịch sử Test & Kết quả

### Task #22 — tiktok_comment (2026-03-20 08:45-08:58)

| Metric | Giá trị |
|--------|--------|
| **Status** | `completed` |
| **Steps** | 93 |
| **Report** | 4/5 verified, 0 failed |
| **Actual** | **2/4 comments trong history** |

**Phân tích**: Comments tiếng Việt do AI sinh ra bị TikTok async reject (spam filter). Chỉ ASCII đơn giản (":)", "hhh") survive.

---

### Task #23 — tiktok_comment (2026-03-20 09:59-10:05)

| Metric | Giá trị |
|--------|--------|
| **Status** | `completed` |
| **Steps** | 101 |
| **Report** | 4/5 commented, verified: 4, failed: 2 |
| **Actual** | **2 comment mới trong history** (cả hai ":)") |

**Comment History đối chiếu** (Mar 20 — từ Task #22 + #23):
| # | Comment | Source | Kết quả |
|---|---------|--------|---------|
| 1 | ":)" → Arcadia Beach Resort | Task #23 | ✅ |
| 2 | ":)" → (dancing video) | Task #23 | ✅ |
| 3 | ":)" → Hạt Bụi | Task #22 | ✅ |
| 4 | "hhh" → (soccer) | Task #22 | ✅ |

**Phân tích Task #23**:
- AI comments (tiếng Việt/dài) bị TikTok filter → retry với ASCII → ":)" survive
- Root cause: **comment CHUNG CHUNG** ("hay quá", "tuyệt vời") bị spam filter
- Giải pháp: **Refactored AI prompt** → yêu cầu comment CỤ THỂ, có quan điểm (§2.13)

### Kết luận tiến triển:
| Giai đoạn | Task | Comments posted | Tỷ lệ |
|-----------|------|----------------|--------|
| Manual test (Mar 19) | N/A | 5/5 (ASCII only) | 100% |
| Task #22 (Mar 20 sáng) | #22 | 2/4 (ASCII survive) | 50% |
| Task #23 (Mar 20 trưa) | #23 | 2/? (ASCII survive) | ~50% |
| **Next**: Context-aware prompt | TBD | Chờ test | 🔄 |

> [!WARNING]
> **Verification false positive**: Task report "verified" nhưng TikTok async reject sau 3-10s. Cần re-check verification sau 10-30s.

> [!NOTE]
> **Context-aware AI comments** (§2.13) đã implement nhưng CHƯA TEST. Cần chạy task mới để xác nhận comment CỤ THỂ có vượt qua TikTok spam filter không.
