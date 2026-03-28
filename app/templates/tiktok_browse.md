---
title: TikTok Browse
description: Script lướt feed TikTok và random like theo xác suất cấu hình.
platform: tiktok
mode: script
status: active
is_primary: false
implemented: true
risk_level: medium
sort_order: 20
fallback_behavior: Không dùng AI; runner chỉ browse feed và có thể like.
default_vars: {"count": 5, "view_time_min": 5, "view_time_max": 15, "like_chance": 0.3}
ui_fields: [{"key":"count","type":"number","label":"Videos","min":1,"max":30,"step":1},{"key":"view_time_min","type":"number","label":"View min (s)","min":1,"max":20,"step":1},{"key":"view_time_max","type":"number","label":"View max (s)","min":2,"max":40,"step":1},{"key":"like_chance","type":"number","label":"Like chance","min":0,"max":1,"step":0.1}]
capabilities: ["Mở feed TikTok", "Xem video với thời gian ngẫu nhiên", "Random like theo xác suất"]
limitations: ["Không comment", "Không follow", "Không mở profile có chủ đích"]
---
# TikTok Browse

Runner này dùng cho browsing tự nhiên, nhẹ, không sinh comment.

## Nhiệm vụ
1. Mở TikTok và đảm bảo đang ở feed.
2. Xem mỗi video trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Có thể like với xác suất {{like_chance}}.
4. Swipe lên video tiếp theo.
5. Lặp lại {{count}} lần.

## Giới hạn
- Không comment.
- Không follow.
- Không mở DM hay link ngoài.
