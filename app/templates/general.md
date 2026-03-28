---
title: General Task Template
description: Template AI tổng quát cho các yêu cầu chưa có runner chuyên biệt.
platform: general
mode: ai
status: active
is_primary: false
implemented: true
risk_level: medium
sort_order: 200
fallback_behavior: Không có script chuyên biệt; dùng AI task thông thường.
default_vars: {"max_steps": 20}
ui_fields: []
capabilities: ["Bao bọc task AI tự do bằng guardrails cơ bản"]
limitations: ["Không có metadata UI chuyên sâu", "Không tối ưu cho nền tảng cụ thể"]
---
# General Task Template

## Task
{{task_description}}

## Instructions
Thực hiện task theo yêu cầu trên thiết bị Android.
Hãy hành động như một người dùng thực:
- Đợi vài giây giữa các hành động.
- Nếu gặp popup hoặc quảng cáo, đóng chúng trước.
- Nếu cần đăng nhập, thông báo và dừng lại.
- Nếu không thể hoàn thành task, giải thích lý do.

## Constraints
- Tối đa {{max_steps}} bước thực thi.
- Không cài đặt hoặc xóa ứng dụng trừ khi được yêu cầu.
- Không thay đổi cài đặt hệ thống.
