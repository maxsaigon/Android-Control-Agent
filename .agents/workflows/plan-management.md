---
description: Quy tắc lưu trữ và quản lý kế hoạch — đọc trước khi bắt đầu bất kì task nào
---

# Plan Management

## Quy tắc bắt buộc

1. **LUÔN đọc `docs/plans/_index.md` trước khi bắt đầu bất kì task nào** để biết:
   - Tasks nào đã hoàn thành (✅ COMPLETE)
   - Tasks nào đang làm (🔄 IN PROGRESS)
   - Tasks nào đã lên kế hoạch (📋 PLANNED)

2. **Mọi kế hoạch mới phải được lưu trong `docs/plans/`**:
   - Đặt tên file theo nội dung chính (ví dụ: `cloud-device-integration.md`)
   - Bắt đầu file với: `# Tên Plan — STATUS`
   - Phải có `Assumptions`, `Non-goals`, `Implementation Plan`, `Verification`
   - Cập nhật `_index.md` khi thêm/sửa plan

3. **Status format**:
   - ✅ COMPLETE — Đã hoàn thành
   - 🔄 IN PROGRESS — Đang thực hiện
   - 📋 PLANNED — Chưa bắt đầu
   - ❌ CANCELLED — Đã huỷ

4. **KHÔNG được xoá plan cũ** — chỉ update status

5. **Khi user nhắc đến phase/plan cũ**, tìm trong `docs/plans/` trước khi đoán

6. **Implementation Plan phải kiểm chứng được**:
   - Không viết bước mơ hồ kiểu "fix bug", "update UI", "improve logic"
   - Mỗi bước nên theo format: `1. [Step] → verify: [check cụ thể]`

7. **Nếu plan dựa trên giả định chưa xác minh**, ghi rõ trong `Assumptions`
   - Nếu ambiguity làm thay đổi thiết kế hoặc phạm vi sửa file, dừng và làm rõ trước khi code
