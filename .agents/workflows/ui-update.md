---
description: Quy trình cập nhật UI/Dashboard cho Android Control System
---

# UI/Dashboard Update Workflow

## Bước 1: Đọc SKILL.md

Đọc file `.agents/skills/ui-dashboard/SKILL.md` để hiểu design system, coding standards, và architecture trước khi bắt đầu.
Đọc thêm `.agents/skills/karpathy-guidelines/SKILL.md` để chốt assumptions, non-goals, và verification trước khi sửa UI.

## Bước 2: Xem Component Patterns

Nếu cần tạo component mới, tham khảo `.agents/skills/ui-dashboard/resources/component_patterns.md` để lấy code snippets chuẩn.

## Bước 3: Xác định files cần sửa

Tùy thuộc vào thay đổi, sẽ cần sửa 1 hoặc nhiều files:
- **HTML only**: `app/static/index.html` (layout, structure thay đổi)
- **CSS only**: `app/static/style.css` (styling, animations)
- **JS only**: `app/static/app.js` (logic, API calls)
- **Backend + UI**: Thêm router/endpoint trong `app/routers/` + cập nhật JS

Trước khi implement, ghi ngắn:
- **Assumptions**
- **Non-goals**
- **Verify**

## Bước 4: Implement

Thực hiện thay đổi theo coding standards trong SKILL.md:
- Dùng CSS variables, không hardcode colors
- Unique IDs cho mọi interactive elements
- Error handling + toast cho API calls
- Responsive ở 3 breakpoints
- Chỉ chạm đúng lớp cần sửa: HTML/CSS/JS/Backend đã xác định ở bước 3
- Không redesign lan rộng nếu user chỉ yêu cầu chỉnh 1 panel hay 1 flow

## Bước 5: Validate

// turbo
Chạy script kiểm tra:
```sh
bash .agents/skills/ui-dashboard/scripts/validate_ui.sh
```

## Bước 6: Preview

Mở browser tại `http://localhost:8000/dashboard` để kiểm tra visual.
Server phải đang chạy (`uv run fastapi dev app/main.py`).

Checklist verify tối thiểu:
- Layout hiển thị đúng ở desktop và mobile width
- Flow mới không làm hỏng panel cũ liên quan
- Console không có lỗi mới
