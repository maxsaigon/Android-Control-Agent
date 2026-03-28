---
title: TikTok Like Videos
description: Script like TikTok với verify sau thao tác và hành vi like đa dạng.
platform: tiktok
mode: script
status: active
is_primary: false
implemented: true
risk_level: medium
sort_order: 40
fallback_behavior: Không dùng AI; runner verify trạng thái like sau khi thao tác.
default_vars: {"count": 10, "view_time_min": 5, "view_time_max": 15, "like_chance": 0.3}
ui_fields: [{"key":"count","type":"number","label":"Target likes","min":1,"max":30,"step":1},{"key":"view_time_min","type":"number","label":"View min (s)","min":1,"max":20,"step":1},{"key":"view_time_max","type":"number","label":"View max (s)","min":2,"max":40,"step":1},{"key":"like_chance","type":"number","label":"Like chance","min":0,"max":1,"step":0.1}]
capabilities: ["Double-tap hoặc tap heart", "Verify trạng thái like", "Pause tự nhiên sau like"]
limitations: ["Không comment", "Không follow", "Không share"]
---
# TikTok Like Videos

Runner này tập trung vào like có verify, không sinh comment.

## Nhiệm vụ
1. Mở TikTok và vào feed.
2. Xem mỗi video trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Quyết định like với xác suất {{like_chance}}.
4. Nếu like, runner sẽ verify trạng thái sau thao tác.
5. Swipe video tiếp theo cho đến khi đạt {{count}} like đã verify hoặc hết vòng lặp tự nhiên.

## Giới hạn
- Không comment.
- Không follow.
- Không mở link ngoài.
