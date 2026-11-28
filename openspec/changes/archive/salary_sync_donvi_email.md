# OpenSpec Change: Dong bo don vi cong tac va email vao salary_profiles

## Thay doi da thuc hien

### File: `user_service.py`

**1. Ham `sync_user_to_salary` - Luu 3 truong don vi cong tac**
- Truoc: chi luu `don_vi_cong_tac_phong` (phan [0])
- Sau: luu them `don_vi_cong_tac_vien` (phan [1]) va `don_vi_cong_tac_tong` (phan [2])
- Phan [1] va [2] giong nhau tat ca user (Vien Vat ly, Vien Han lam Khoa hoc va Cong nghe Viet Nam)
- Dung de dien bieu tuu dong khi xuat ra

**2. Ham `sync_user_to_salary` - Dong bo email co dieu kien**
- Truoc: `entry.pop("email", None)` (xoa email neu co)
- Sau: chi set email neu entry chua co email; neu da co email thi giu nguyen, khong ghi de

## Kiem tra
- `python -m py_compile user_service.py` -> OK, khong loi cu phap.
