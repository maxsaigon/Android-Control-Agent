---
title: Instagram Scroll Feed
description: Script cuộn feed Instagram cơ bản, không like/comment/follow.
platform: instagram
mode: script
status: active
is_primary: false
implemented: true
risk_level: low
sort_order: 80
fallback_behavior: Không dùng AI; runner chỉ mở app, xem và scroll.
default_vars: {"count": 5, "view_time_min": 3, "view_time_max": 8}
ui_fields: [{"key":"count","type":"number","label":"Items","min":1,"max":30,"step":1,"help":"Số item feed cần xem."},{"key":"view_time_min","type":"number","label":"View min (s)","min":1,"max":20,"step":1},{"key":"view_time_max","type":"number","label":"View max (s)","min":2,"max":30,"step":1}]
capabilities: ["Mở Instagram", "Xem item theo thời gian ngẫu nhiên", "Scroll feed tuần tự"]
limitations: ["Không like", "Không comment", "Không follow"]
---
# Instagram Scroll Feed

Runner này chỉ thực hiện cuộn feed Instagram.

## Nhiệm vụ
1. Mở Instagram.
2. Xem mỗi item trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Scroll sang item tiếp theo.
4. Lặp lại {{count}} lần.

## Giới hạn
- Không like.
- Không comment.
- Không follow.
- Không mở DM hay link ngoài.
