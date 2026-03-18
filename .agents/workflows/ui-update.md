---
description: Quy trình cập nhật UI/Dashboard cho Android Control System
---

# UI/Dashboard Update Workflow

## Bước 1: Đọc SKILL.md

Đọc file `.agents/skills/ui-dashboard/SKILL.md` để hiểu design system, coding standards, và architecture trước khi bắt đầu.

## Bước 2: Xem Component Patterns

Nếu cần tạo component mới, tham khảo `.agents/skills/ui-dashboard/resources/component_patterns.md` để lấy code snippets chuẩn.

## Bước 3: Xác định files cần sửa

Tùy thuộc vào thay đổi, sẽ cần sửa 1 hoặc nhiều files:
- **HTML only**: `app/static/index.html` (layout, structure thay đổi)
- **CSS only**: `app/static/style.css` (styling, animations)
- **JS only**: `app/static/app.js` (logic, API calls)
- **Backend + UI**: Thêm router/endpoint trong `app/routers/` + cập nhật JS

## Bước 4: Implement

Thực hiện thay đổi theo coding standards trong SKILL.md:
- Dùng CSS variables, không hardcode colors
- Unique IDs cho mọi interactive elements
- Error handling + toast cho API calls
- Responsive ở 3 breakpoints

## Bước 5: Validate

// turbo
Chạy script kiểm tra:
```sh
bash .agents/skills/ui-dashboard/scripts/validate_ui.sh
```

## Bước 6: Preview

Mở browser tại `http://localhost:8000/dashboard` để kiểm tra visual.
Server phải đang chạy (`uv run fastapi dev app/main.py`).
