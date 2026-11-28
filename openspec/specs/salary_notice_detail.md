# OpenSpec: Hien thi thong bao luong chi tiet khi tra cuu can bo (Salary Notice Detail)

## 1. Muc dich
Khi admin gõ tìm kiếm cán bộ trong tab Tong hop va tim thay duy nhat mot nguoi, he thong hien ra noi dung thong bao luong chi tiet (giong nhu noi dung duoc gui di qua email), phan biet theo 3 loai: Bien che / Hop dong / Khac.

## 2. Pham vi
- Trang Quan tri Luong (ui/salary_management.py), tab Tong hop.
- Ham _build_notice_detail: tao noi dung thong bao theo 3 loai nguon luong.
- Luu luu: Supabase key salary_profiles (trong bang app_data).

## 3. Cau truc du lieu
Moi user trong salary_profiles co truong:
- ho_va_ten, email, don_vi_cong_tac_phong
- nguon_luong: "Bien che" | "Hop dong" | "Khac" (nguon luan cua can bo)
- tien_phu_cap_luong, tien_phu_cap_ctp: tien phu cap cho loai Hop dong
- lich_su_bien_dong_luong: danh sach cac ban ghi luong theo thang/nam, moi ban ghi chua: nam, thang, he_so_luong, tien_luong, tong_cong, bac_luong, luong_cb, pc_ld, tien_phu_cap_luong, tien_phu_cap_ctp, he_so_vuot_khung, he_so_doc_hai_theo_vi_tri, he_so_doc_hai_tien, doc_hai_theo_luong, doc_hai_tien, truy_linh, bhiem_10_5, truy_thu, tien_tinh_thue, ghi_chu, ngay_hieu_luc, quyet_dinh_so, ...

## 4. Flow moi
### 4.1 Tab Tong hop - tra cuu can bo
1. Admin nhap ho ten can bo vao o tim kiem (salary_fullname_input) va nhan Enter.
2. He thong tim kiem chinh xac ho ten (bo dau, khoang trang, hoa/thuong).
3. Neu tim thay duy nhat 1 nguoi:
   - Hien thong tin: ho ten, @username, phong ban, nguon luong, thang/nam.
   - Hien noi dung thong bao luong chi tiet trong text_area (cao 420px), giong noi dung email se gui.
   - Dinh dang thong bao tu dong duoc nhan nguon tu truong nguon_luong (Bien che / Hop dong / Khac), khong can chon thu cong.
   - Noi dung thong bao duoc tao boi ham _build_notice_detail theo nguon luong:
     * Bien che: bang 13 muc (He so luong, He so phu cap, Vuot khung, He so vuot khung, Phan tram, Tien luong, He so doc hai theo luong, Doc hai theo luong, He so doc hai bang tien, Doc hai bang tien, Tu linh, Tru BHXH, Tru thu, Tong tien nhan).
     * Hop dong: bang 7 muc (He so luong, Tien phu cap luong, Tien phu cap CTP, Tien Luong = (1) x 2.340.000 + (2), Tru tu linh, Tru tien BHXH = 10,5% x 2.340.000 x (1), Tru thu, Tong tien nhan = (2)+(3)+(4)-(5)-(6)-(7)).
     * Khac: bang don gian (He so luong, Tien luong, Phu cap, Tong thuc linh).
   - Duoi noi dung thong bao la form Chinh sua bien dong luong (cac o nhap: nam, thang, he so, tien luong, tong cong, ... va nut Luu bien dong / Huy).
4. Neu tim thay nhieu nguoi trung ten -> hien selectbox de chon.
5. Neu khong tim thay -> hien canh bao.

### 4.2 Tab Thong bao luong (gui email)
- Giu nguyen chuc nang cu: tim kiem nguoi nhan, chon loai thong bao (Bien che/Hop dong/Khac), xem preview email, chon nhom nguoi nhan, gui email.

## 5. File anh huong
| File | Vai tro |
|------|---------|
| ui/salary_management.py | Them ham _fmt_num, _fmt_he_so, _build_notice_detail; sua phan hien thi chi luc trong tab Tong hop de hien thi thong bao luong chi tiet theo nguon luong |

## 6. Rang bao / Out of scope
- Khong tao bang moi tren Supabase.
- Khong gui email tu tab Tong hop (chi hien noi dung preview). Viec gui email o tab Thong bao luong.
- Neu khong co truong nguon_luong trong du lieu, mac dinh la "Bien che".
