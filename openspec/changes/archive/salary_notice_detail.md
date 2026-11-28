# OpenSpec Change: Hien thi thong bao luong chi tiet khi tra cuu can bo

## Thay doi da thuc hien

### File: `ui/salary_management.py`

**1. Them 3 ham ho tro dinh dang va tao noi dung thong bao**
- `_fmt_num(val)`: dinh dang so nguyen co dau phay, tra ve "—" neu rong.
- `_fmt_he_so(val)`: dinh dang he so (2 chu so thap phan), tra ve "—" neu rong.
- `_build_notice_detail(ho_ten, thang, nam, nguon_luong, latest)`: tao noi dung thong bao luong chi tiet theo 3 loai:
  * `Bien che`: bang 13 muc giong mau anh dinh kem (He so luong, Phu cap, Vuot khung, He so vuot khung, Phan tram, Tien luong, Doc hai theo luong, Doc hai bang tien, Tu linh, Tru BHXH, Tru thu, Tong tien nhan).
  * `Hop dong`: bang rut gon (He so luong, Luong co ban, Phu cap, Tien luong, BH 10,5%, Tu linh, Tru thu, Tong thuc linh).
  * `Khac`: bang don gian (He so luong, Tien luong, Phu cap, Tong thuc linh).
  Cuoi cung co phan "Luan ly" va chu ky Phong Ke toan.

**2. Sua phan hien thi chi tiet trong tab Tong hop (tab_tong_hop)**
- Xoa hien thi thong tin luong thua (danh sach cac truong —).
- Thay bang hien thi thong bao luong chi tiet (text_area cao 420px) khi tim thay can bo.
- Lay `nguon_luong` tu `rec.get("nguon_luong")` hoac `latest.get("nguon_luong")` hoac `latest.get("loai")`, mac dinh "Bien che".
- Hien thi: ho ten, @username, phong ban, nguon luong, thang/nam.
- Duoi noi dung thong bao la form Chinh sua bien dong luong (cac o nhap: nam, thang, he so luong, tien luong, tong cong, he so vuot khung, doc hai, truy linh, BH, ... va nut Luu bien dong / Huy).
- Neu tim thay nhieu nguoi trung ten -> hien selectbox de chon, sau do hien thong bao luong cua nguoi duoc chon.

## Kiem tra
- `python -m py_compile ui/salary_management.py` -> OK, khong loi cu phap.

## Luu y
- Noi dung thong bao chi hien thi (preview), chua gui email tu tab Tong hop. Viec gui email duoc giu nguyen o tab Thong bao luong.
- Truong `nguon_luong` khong bat buoc; neu khong co, mac dinh la "Bien che".
