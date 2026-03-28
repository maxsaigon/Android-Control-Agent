---
title: YouTube Watch
description: Script mở YouTube, vào video/short đầu tiên rồi xem và swipe tuần tự.
platform: youtube
mode: script
status: active
is_primary: false
implemented: true
risk_level: low
sort_order: 90
fallback_behavior: Không dùng AI; runner chỉ mở video đầu tiên, xem và swipe.
default_vars: {"count": 3, "view_time_min": 10, "view_time_max": 30}
ui_fields: [{"key":"count","type":"number","label":"Videos","min":1,"max":20,"step":1},{"key":"view_time_min","type":"number","label":"Watch min (s)","min":3,"max":30,"step":1},{"key":"view_time_max","type":"number","label":"Watch max (s)","min":5,"max":60,"step":1}]
capabilities: ["Mở YouTube", "Tap video hoặc Shorts đầu tiên", "Xem và swipe tiếp"]
limitations: ["Không like", "Không đọc comment", "Không tìm kiếm thủ công"]
---
# YouTube Watch

Runner này xem YouTube theo flow đơn giản, không tương tác thêm.

## Nhiệm vụ
1. Mở YouTube.
2. Tap video hoặc Shorts đầu tiên.
3. Xem trong khoảng {{view_time_min}}-{{view_time_max}} giây.
4. Swipe nội dung tiếp theo.
5. Lặp lại {{count}} lần.

## Giới hạn
- Không like.
- Không mở comment.
- Không tìm kiếm theo từ khóa.
