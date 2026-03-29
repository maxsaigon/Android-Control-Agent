# TikTok Comment Hardening

Status: 🔄 IN PROGRESS

## Goal
- Ngăn lỗi "text đã vào ô nhưng nút Send không active" tái diễn.
- Chuẩn hóa quản lý Android helper APK để biết chính xác device đang chạy bản nào.
- Thêm regression gate để deploy không bỏ sót helper build hoặc route `/set`.

## Workstreams

### 1. Helper Release Management
Status: ✅ COMPLETE
- Đổi artifact APK sang format versioned `android-control-helper-v<version>+<code>.apk`
- Giữ alias ổn định `android-control-helper-latest.apk` cho install/deploy
- Sinh `helper-release.json` để `/set`, `/download/helper.apk`, deploy smoke và ADB helper install cùng dùng chung một source metadata
- Hiển thị `version`, `build_sha`, `build_time_utc`, `artifact_name` trên `/set`
- Bơm helper build metadata vào app UI/log/device info/cloud heartbeat

### 2. Comment Action Telemetry
Status: ✅ COMPLETE
- Tách checkpoint cho `text_entered_ok`, `send_ready_ok`, `send_tap_ok`, `posted_ok`
- Giữ rule: không tap send nếu chưa detect active target
- Lưu các checkpoint này vào task step log để xác định đúng điểm hỏng khi production fail

### 3. Regression Gates
Status: ✅ COMPLETE
- Unit regression cho `_attempt_comment` để chặn blind send khi nút Send chưa active
- Public-domain smoke kiểm tra thêm `/set`, `/api/helper/release`, và `/download/helper.apk`
- Internal deploy smoke kiểm tra helper release metadata + download headers

## Release Process
1. Build helper: `cd android-helper && ./build-and-publish.sh`
2. Verify file xuất hiện trong `app/static/downloads/`
3. Commit + push branch hiện tại lên `origin`
4. Deploy bằng `./deploy/max-lan-smoke.sh`
5. Smoke phải pass cả Dashboard public lẫn helper download public

## Notes
- Không cần migration DB cho phase này; helper version được track qua metadata file, log, cloud hub metadata và device info runtime.
- `DeviceManager.ensure_helper_apk()` giờ resolve helper từ release metadata thay vì hardcode `/app/ac-helper.apk`.
