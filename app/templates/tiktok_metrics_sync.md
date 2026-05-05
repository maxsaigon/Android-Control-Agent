---
title: TikTok Metrics Sync
description: Đọc views/likes/comments/shares từ profile TikTok cho một assignment đã upload.
platform: tiktok
mode: script
status: beta
is_primary: false
implemented: true
risk_level: medium
sort_order: 120
fallback_behavior: Nếu sync thất bại, set metrics_status=needs_review và lưu artifact để operator kiểm tra.
default_vars: {"assignment_id": 0}
ui_fields: []
capabilities: ["Navigate to profile", "Read grid views", "Match post via locator signals", "Open post detail", "Read full metrics"]
limitations: ["Locator matching hiện dựa trên caption tokens/preview + grid hint, chưa scroll sâu beyond visible candidate window", "Cần device đã login TikTok"]
---
# TikTok Metrics Sync

Đọc số liệu hiệu suất (views, likes, comments, shares) từ TikTok profile cho một video assignment đã upload thành công.

## Luồng thực hiện

1. Mở TikTok, đảm bảo đang ở feed
2. Navigate về Profile tab
3. Mở Videos sub-tab trong profile
4. Đọc view counts từ video grid (quick scan)
5. Scan các candidate quanh `post_locator.grid_position_hint`, mở post và match theo caption tokens/preview
6. Đọc full metrics từ post detail (views, likes, comments, shares)
7. Back về profile grid
8. Lưu metrics vào database: latest state + snapshot history

## Điều kiện trước

- Assignment phải có `upload_status = UPLOADED`
- Device phải đang login TikTok account tương ứng
- `metrics_status` không được là `SYNCING` hoặc `DISABLED`

## Xử lý lỗi

- Nếu không navigate được đến profile → `metrics_status = NEEDS_REVIEW`
- Nếu không đọc được metrics → lưu artifact debug (screenshot + UI XML)
- Nếu grid trống → `metrics_status = NEEDS_REVIEW` + ghi chú "empty profile"
- Mọi lỗi đều lưu vào `metrics_error` trên assignment

## Tham số

- `assignment_id` (bắt buộc): ID của VideoAssignment cần sync metrics
