---
title: TikTok Follow Accounts
description: Script follow từ feed TikTok với bước vào profile và verify trạng thái follow.
platform: tiktok
mode: script
status: active
is_primary: false
implemented: true
risk_level: high
sort_order: 50
fallback_behavior: Không dùng AI; runner quyết định follow theo xác suất và verify sau thao tác.
default_vars: {"count": 5, "view_time_min": 5, "view_time_max": 12, "follow_chance": 0.3}
ui_fields: [{"key":"count","type":"number","label":"Target follows","min":1,"max":15,"step":1},{"key":"view_time_min","type":"number","label":"View min (s)","min":1,"max":20,"step":1},{"key":"view_time_max","type":"number","label":"View max (s)","min":2,"max":40,"step":1},{"key":"follow_chance","type":"number","label":"Follow chance","min":0,"max":1,"step":0.1}]
capabilities: ["Tap avatar vào profile", "Đôi khi xem video trên profile", "Verify follow state"]
limitations: ["Chỉ follow từ feed", "Không hỗ trợ search/suggested flow", "Không comment trên profile"]
---
# TikTok Follow Accounts

Runner này follow từ feed hiện tại, không dùng search hay suggested list.

## Nhiệm vụ
1. Mở TikTok và vào feed.
2. Xem mỗi video trong khoảng {{view_time_min}}-{{view_time_max}} giây.
3. Sau khi đã skip đủ vài video, có thể vào profile tác giả với xác suất {{follow_chance}}.
4. Trên profile, có thể xem ngắn 1 video rồi mới quyết định follow.
5. Nếu follow, runner sẽ verify trạng thái.
6. Quay lại feed và tiếp tục cho đến khi đạt {{count}} follow đã verify hoặc hết vòng lặp tự nhiên.

## Giới hạn
- Không search theo keyword.
- Không follow suggested list.
- Không gửi tin nhắn và không comment trên profile.
