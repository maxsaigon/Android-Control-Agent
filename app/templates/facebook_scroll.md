---
title: Facebook Scroll Feed
description: Script cuộn Facebook feed và có thể like post theo xác suất cấu hình.
platform: facebook
mode: script
status: active
is_primary: false
implemented: true
risk_level: low
sort_order: 70
fallback_behavior: Không dùng AI; runner chỉ scroll và có thể tap like post.
default_vars: {"count": 5, "view_time_min": 3, "view_time_max": 10, "like_chance": 0.2}
ui_fields: [{"key":"count","type":"number","label":"Posts","min":1,"max":30,"step":1},{"key":"view_time_min","type":"number","label":"Read min (s)","min":1,"max":20,"step":1},{"key":"view_time_max","type":"number","label":"Read max (s)","min":2,"max":30,"step":1},{"key":"like_chance","type":"number","label":"Like chance","min":0,"max":1,"step":0.1}]
capabilities: ["Mở Facebook", "Đọc feed theo thời gian ngẫu nhiên", "Tap like theo xác suất"]
limitations: ["Không đọc comment", "Không gửi reaction khác ngoài like", "Không share hoặc message"]
---
# Facebook Scroll Feed

Runner này chỉ xử lý scroll feed Facebook ở mức nhẹ.

## Nhiệm vụ
1. Mở Facebook.
2. Đọc mỗi post trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Có thể like với xác suất {{like_chance}}.
4. Scroll post tiếp theo.
5. Lặp lại {{count}} lần.

## Giới hạn
- Không đọc comment.
- Không gửi message.
- Không share bài viết.
