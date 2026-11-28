# OpenSpec Change: Gán hồ sơ thuế bắt buộc cho người dùng

## Thay đổi đã thực hiện

### File: `ui/user_admin_ui.py`

**1. Thêm CSS cho ô chưa gán hồ sơ thuế (màu đỏ nhạt)**
- Class `.tax-missing`: viền đỏ, nền hồng nhạt, padding, border-radius.
- Class `.tax-required-msg`: chữ đỏ in đậm, thông báo bắt buộc gán.

**2. Form tạo user mới (expander "Tạo tài khoản mới")**
- Thêm selectbox "Chọn hồ sơ thuế hoặc tạo mới:" với các lựa chọn:
  - `(chưa gán)` — mặc định
  - Danh sách hồ sơ từ `salary_profiles` (hiển thị fullname @key)
  - `➕ Tạo hồ sơ thuế mới` — hiện ô nhập tên mới
- Nếu đã chọn "Chọn hồ sơ gán" ở trên, hệ thống tự động preselect fullname trùng khớp trong `salary_profiles`.
- Thêm biến `tax_missing`: `True` nếu chọn `(chưa gán)` hoặc chọn "Tạo mới" để trống tên.
- Hiển thị thông báo đỏ nếu `tax_missing` là `True`.
- Nút "Tạo tài khoản" bị `disabled` khi `tax_missing` hoặc thiếu tên đăng nhập/mật khẩu.
- Khi lưu: `tax_profile = new_u` (username), không phải fullname.

**3. Danh sách chỉnh sửa user (mỗi dòng user)**
- Biến `tax_missing_edit = not cur_tax_prof` (đánh dấu chưa gán nếu `tax_profile` rỗng).
- Selectbox "Chọn hồ sơ thuế:" được bọc trong `<div class="tax-missing">` nếu chưa gán.
- Thêm tùy chọn `➕ Tạo hồ sơ thuế mới` vào dropdown.
- Khi chọn "Tạo mới": hiện ô nhập tên, fallback là `uname` nếu để trống.
- Khi chọn hồ sơ có sẵn: luôn lưu `tax_profile = uname` (username của user đang sửa), không phải fullname.
- Hiển thị thông báo đỏ dưới selectbox nếu chưa gán.
- Hai nút "Lưu công cụ" và "Lưu phân quyền" bị `disabled` khi `tax_missing_edit` là `True`.

### File: `user_service.py`
- Không cần sửa. Hàm `admin_create_user` và `admin_update_user` đã hỗ trợ tham số `tax_profile` từ trước.

## Kết quả kiểm tra
- `python -m py_compile ui/user_admin_ui.py` → OK, không lỗi cú pháp.

## Lưu ý
- Trường `tax_profile` lưu vào `auth_config` trên Supabase (key `auth_config` trong bảng `app_data`).
- Giá trị lưu là username của user (key), không phải fullname hay key của bảng lương.
- Giao diện bắt buộc gán trước khi lưu, nhưng cấp dữ liệu Supabase không ép buộc (có thể `None`).
