# OpenSpec Change: Cap nhat mau thong bao luong Hop dong

## Thay doi da thuc hien

### File: `ui/salary_management.py`

**1. Cap nhat ham `_build_notice_detail` cho loai "Hop dong"**
- Bo "bang rut gon" cu, thay bang "bang 7 muc giong mau thuc te":
  - (1) He so luong
  - (2) Tien phu cap luong (moi them)
  - (3) Tien phu cap CTP (moi them)
  - (4) Tien Luong = (1) x 2.340.000 + (2)
  - (5) Tru tu linh
  - (6) Tru tien BHXH = 10,5% x 2.340.000 x (1)
  - (7) Tru thu
  - Tong so tien duoc nhan: (2)+(3)+(4)-(5)-(6)-(7)
- Them 2 bien moi: `tien_phu_cap_luong`, `tien_phu_cap_ctp` lay tu `latest.get(...)`

**2. Cap nhat spec `openspec/specs/salary_notice_detail.md`**
- Cap nhat cau truc du lieu: them 2 truong tien_phu_cap_luong, tien_phu_cap_ctp
- Cap nhat mo tap Hop dong: bang 7 muc giong mau thuc te

## Kiem tra
- `python -m py_compile ui/salary_management.py` -> OK, khong loi cu phap.
