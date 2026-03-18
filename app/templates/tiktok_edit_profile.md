# TikTok Edit Profile

Bạn đang chỉnh sửa profile TikTok. Thao tác cẩn thận, kiểm tra kỹ trước khi lưu.

## Nhiệm vụ
1. Mở app TikTok
2. Nhấn tab "Profile" (icon người, góc phải dưới)
3. Nhấn nút "Edit profile" / "Sửa hồ sơ"
4. Thực hiện các thay đổi theo config bên dưới
5. Nhấn "Save" / "Lưu"
6. Xác nhận thay đổi đã được lưu

## Thông tin cần thay đổi
- **Tên hiển thị**: {{display_name}}
- **Bio**: {{bio}}
- **Avatar**: {{avatar_path}}

## Quy tắc
- Chỉ thay đổi các field có giá trị (không rỗng)
- Nếu display_name rỗng → KHÔNG thay đổi tên
- Nếu bio rỗng → KHÔNG thay đổi bio
- Nếu avatar_path rỗng → KHÔNG thay đổi avatar
- Đợi 2-3 giây giữa mỗi field khi chỉnh sửa
- Clear field cũ trước khi gõ giá trị mới (select all → delete → type)
- Kiểm tra lại giá trị đã gõ trước khi lưu

## Thay đổi Avatar (nếu có)
1. Nhấn vào avatar hiện tại
2. Chọn "Chọn từ thư viện" / "Choose from library"
3. Chọn ảnh từ gallery
4. Crop/chỉnh nếu cần → xác nhận
5. Đợi upload hoàn tất

## An toàn
- KHÔNG thay đổi username (khác với display name)
- KHÔNG liên kết thêm tài khoản (Instagram, YouTube...)
- KHÔNG thay đổi email/số điện thoại
- KHÔNG thay đổi privacy settings
- Nếu gặp xác minh danh tính → DỪNG và báo cáo
