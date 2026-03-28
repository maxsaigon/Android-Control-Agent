---
title: TikTok Warm-up
description: Script xem feed TikTok thụ động với thời gian dài hơn, không tương tác chủ động.
platform: tiktok
mode: script
status: active
is_primary: false
implemented: true
risk_level: low
sort_order: 30
fallback_behavior: Không dùng AI; runner chỉ xem feed, đôi khi pause lâu hoặc vào profile ngắn.
default_vars: {"count": 8, "view_time_min": 10, "view_time_max": 30, "session_count": 3}
ui_fields: [{"key":"count","type":"number","label":"Videos","min":1,"max":30,"step":1},{"key":"session_count","type":"number","label":"Planned sessions","min":1,"max":10,"step":1,"help":"Giá trị tham chiếu cho kế hoạch vận hành; runner hiện không tự tách nhiều session."},{"key":"view_time_min","type":"number","label":"View min (s)","min":5,"max":45,"step":1},{"key":"view_time_max","type":"number","label":"View max (s)","min":10,"max":90,"step":1}]
capabilities: ["Xem feed thụ động", "Pause dài tự nhiên", "Đôi khi mở profile ngắn rồi quay lại"]
limitations: ["Không comment", "Không follow", "Không tự chia session dù có trường session_count"]
---
# TikTok Warm-up

Runner này dành cho warm-up nhẹ, ưu tiên footprint xem tự nhiên hơn là tương tác.

## Nhiệm vụ
1. Mở TikTok và vào feed.
2. Xem mỗi video trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Thỉnh thoảng dừng lâu hơn hoặc mở profile ngắn rồi quay lại.
4. Swipe sang video tiếp theo.
5. Lặp lại {{count}} lần.

## Giới hạn
- Không comment.
- Không follow.
- Không đổi cài đặt tài khoản.
