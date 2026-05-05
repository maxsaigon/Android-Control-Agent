# Workflow Karpathy Alignment — ✅ COMPLETE
**Created**: 2026-04-28
**Last Updated**: 2026-04-28

## Mục tiêu
Đồng bộ workflow và skill docs với `karpathy-guidelines` để mọi agent phải chốt assumptions, non-goals, write scope, và verification trước khi sửa code.

## Assumptions
- `.agents/workflows/` là nơi định nghĩa process chuẩn cho agents trong repo này.
- Việc áp dụng guideline vào workflow docs là đủ cho yêu cầu hiện tại; chưa cần refactor toàn bộ từng skill chuyên biệt.

## Non-goals
- Không thay đổi application code trong `app/`
- Không thay đổi runtime scripts hay behavior của các agent platform
- Không rewrite toàn bộ mọi `SKILL.md`; chỉ chạm phần điều phối chung và 2 skill đại diện đang chi phối phạm vi rộng

## Implementation Plan
1. Review workflow docs hiện tại → verify: xác định được chỗ đang thiếu assumptions, scope boundary, verify criteria.
2. Cập nhật workflow chuẩn và workflow phụ → verify: mỗi workflow chính đều nhắc `karpathy-guidelines` và yêu cầu task brief/verifiable checks.
3. Nối workflow với rules/skill layer → verify: `RULES.md` và các skill đại diện có guardrails ngắn gọn, không tạo mâu thuẫn ownership/process.

## Verification
- `git diff` cho thấy cập nhật tập trung ở `.agents/workflows/`, `.agents/RULES.md`, và skill docs liên quan.
- Đọc lại tài liệu xác nhận đã có các mục `Assumptions`, `Non-goals`, `Verify` và nguyên tắc surgical changes.
