# OpenSpec: Dong bo don vi cong tac va email vao salary_profiles

## 1. Muc dich
Khi admin luu ho so (tao moi hoac chinh sua) tren trang Quan tri Nguoi Dung, he thong dong bo thong tin don vi cong tac va email tu ho so cua user sang bang luong (salary_profiles) tren Supabase.

## 2. Pham vi
- Ham `sync_user_to_salary` trong `user_service.py`
- Duoc goi tu `admin_create_user` va `admin_update_user`
- Duoc goi tu expander "Chinh sua thong tin ho so" trong `ui/user_admin_ui.py`
- Luu luu: Supabase key `salary_profiles` (trong bang `app_data`)

## 3. Cau truc don vi cong tac
Truong `don_vi_cong_tac` luu trong ho so ca nhan (key rieng tren Supabase, khong phai auth_config), co dang "phong, vien, tong" (cach boi dau phay).
- Phan [0] = phong (co the khac nhau giua cac user)
- Phan [1] = vien (giong nhau tat ca user: "Vien Vat ly")
- Phan [2] = tong (giong nhau tat ca user: "Vien Han lam Khoa hoc va Cong nghe Viet Nam")

He thong luu 3 truong rieng liet vao `salary_profiles`:
- `don_vi_cong_tac_phong`: phong
- `don_vi_cong_tac_vien`: vien
- `don_vi_cong_tac_tong`: tong

Hai truong `[1]` va `[2]` dung de dien bieu tuu dong khi xuat ra.

## 4. Nguon lay don_vi_cong_tac
Hàm `sync_user_to_salary` lay `don_vi_cong_tac` theo thu tu uu tien:
1. Tu ho so ca nhan (load_user_profile, key rieng cua user)
2. Neu khong co, lay tu auth_config (user_record)

Nguyen ly: truoc day ham chi lay tu auth_config (khong co gia tri), nen cac user nhom Bui Nhung khong co don vi cong tac phong. Sau sua doi, ham se load ho so ca nhan truoc de lay gia tri `don_vi_cong_tac`.

## 5. Dong bo email
- Neu entry trong `salary_profiles` chua co email -> dong bo email tu user_record sang.
- Neu entry da co email -> khong ghi de (giu nguyen email cu).
- Xoa logic `entry.pop("email", None)` cu (khong xoa email cu).

## 6. File anh huong
|| File | Vai tro ||
||------|---------||
|| `user_service.py` | Ham `sync_user_to_salary`: luu 3 truong don vi cong tac, dong bo email co dieu kien ||

## 7. Rang bao / Out of scope
- Khong tao bang moi tren Supabase.
- Khong gui email tu trang quan tri nguoi dung.
- Truong email trong `salary_profiles` khong bat buoc (co the None).
