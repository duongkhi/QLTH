# OpenSpec: Gán hồ sơ thuế cho người dùng (Tax Profile Assignment)

## 1. Mục đích
Đảm bảo mọi tài khoản người dùng trên hệ thống đều có liên kết tới một hồ sơ thuế (key trong `salary_profiles`), và admin có thể tạo mới hồ sơ thuế trực tiếp từ trang quản trị nếu chưa có hồ sơ tương ứng.

## 2. Phạm vi
- Trang `Quản trị Người Dùng & Phân Quyền` (`ui/user_admin_ui.py`)
- Hàm tạo user mới (`admin_create_user` trong `user_service.py`)
- Hàm cập nhật user (`admin_update_user` trong `user_service.py`)
- Lưu trữ: Supabase bảng `app_data`, key `auth_config`, trường `tax_profile` và `salary_profile_id` của từng user.

## 3. Cấu trúc dữ liệu lưu trữ
Mỗi user trong `auth_config.users[tên_đăng_nhập]` có các trường:
| Trường | Ý nghĩa |
|--------|---------|
| `tax_profile` | Key của hồ sơ thuế (đồng bộ với salary_profile_id) |
| `salary_profile_id` | **Mới**: Key chính của hồ sơ thuée/lương được gán cho user |

Hai trường này luôn được giữ đồng bộ (cùng giá trị) khi lưu từ giao diện admin.

## 4. Flow hiện tại (trước khi thay đổi)
1. Admin vào trang Quản trị Người Dùng.
2. Để tạo user mới: form có chọn "Liên kết bảng lương" nhưng **không có trường chọn hồ sơ thuế**. Hàm `admin_create_user` được gọi với `tax_profile=None` → user mới luôn bị bỏ trống `tax_profile`.
3. Để chỉnh sửa user cũ: có dropdown "Chọn hồ sơ thuế", nhưng khi lưu, giá trị được chuyển đổi qua `get_username_from_salary_key()` trước khi lưu. Nếu key không khớp (ví dụ user chưa được đồng bộ bảng lương), hàm trả về `None` → `tax_profile` bị xóa/trống dù admin vừa chọn.
4. Không có ràng buộc bắt buộc gán → nhiều user bị trống `tax_profile`, admin không dễ phát hiện.

## 4. Flow mới (sau khi thay đổi)
### 4.1 Tạo user mới
1. Admin mở expander "Tạo tài khoản mới".
2. Nhập "Tên đăng nhập" và "Mật khẩu" (bắt buộc).
3. Chọn "Vai trò" (bắt buộc).
4. Chọn "Chọn hồ sơ gán" (tùy chọn, có thể để trống).
5. Chọn "Liên kết bảng lương" (tùy chọn).
6. Chọn "Hồ sơ thuế": MẶC ĐỊNH LÀ "➕ Tạo hồ sơ thuế mới".
   - Danh sách hồ sơ có sẵn từ `salary_profiles` (hiển thị fullname @key).
   - `➕ Tạo hồ sơ thuế mới` (mặc định được chọn, nằm trên cùng) → hiện ô nhập tên mới.
7. Khi nhấn "Tạo tài khoản":
   - Nếu tên đăng nhập, mật khẩu, vai trò hoặc tên hồ sơ thuế mới chưa điền → nút disable, hiện thông báo cần điền đầy đủ.
   - Nếu đã điền đầy đủ → lưu `salary_profile_id = giá trị đã chọn` và `tax_profile = cùng giá trị` vào `auth_config`.
8. Có nút "❌ Hủy" để đóng form không tạo.

### 4.2 Chỉnh sửa user cũ
1. Admin vào danh sách tài khoản (user admin bị loại khỏi danh sách).
2. Cột "Chọn hồ sơ thuế" hiển thị dropdown:
   - BỎ "(chưa gán)" đi. Chỉ giữ "➕ Tạo hồ sơ thuế mới" + danh sách có sẵn.
   - Nếu `salary_profile_id`/`tax_profile` đã có giá trị → preselect đúng giá trị đó (không cần phải có trong salary_profiles).
   - Vẫn giữ lựa chọn "➕ Tạo hồ sơ thuế mới" để phòng trường hợp nhầm.
3. Nút **Lưu công cụ** đã được XÓA BỎ.
4. Chỉ có một nút **"Lưu hồ sơ"** để đồng bộ tất cả (quyền, hồ sơ cá nhân, hồ sơ thuế).
5. Khi lưu: đồng bộ `salary_profile_id` và `tax_profile` vào `auth_config`.
6. Refresh trang → giá trị đã lưu vẫn hiển thị đúng, không bị reset.

### 4.3 Role admin
- Không bắt buộc gán hồ sơ thuế khi tạo/sửa user admin.
- User admin bị loại khỏi danh sách quản trị (chỉ quản lý user và manager).

## 5. Cách lưu trữ
- Bảng `app_data` trên Supabase, key `auth_config`.
- Cấu trúc: `auth_config.users[tên_đăng_nhập].salary_profile_id = key_cua_ho_so_thue` và `tax_profile = cùng giá trị`.
- Trường này không bắt buộc ở mức cơ sở dữ liệu (có thể `None`).
- Giao diện admin không còn bắt buộc phải chọn hồ sơ thuế trước khi lưu (đã bỏ "(chưa gán)" khỏi dropdown). Nếu muốn tạo hồ sơ thuế, chọn "➕ Tạo hồ sơ thuế mới" và nhập tên.

## 6. File ảnh hưởng
|| File | Vai trò ||
||------|---------||
|| `ui/user_admin_ui.py` | Giao diện tạo/chỉnh sửa user, dropdown hồ sơ thuế (mặc định "Tạo mới"), nút "Lưu hồ sơ" đồng bộ tất cả ||
|| `user_service.py` | `admin_create_user`, `admin_update_user` — thêm tham số `salary_profile_id`, lưu đồng bộ với `tax_profile` ||

## 7. Ràng buộc / Out of scope
- Không tạo bảng mới trên Supabase.
- Không tự động tạo entry trong `salary_profiles` khi chọn "Tạo hồ sơ thuế mới" (chỉ lưu tên vào `salary_profile_id` của user, entry salary phải được tạo riêng qua quản trị lương).
- Trường hồ sơ thuế không bắt buộc ở cấp giao diện admin (đã bỏ "(chưa gán)").
- Trường hồ sơ thuế không ép buộc bắt buộc ở cấp dữ liệu Supabase.
