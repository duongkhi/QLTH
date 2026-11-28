# OpenSpec Change: Bo droplist chon dinh dang bang luong

## Thay doi da thuc hien

### File: `ui/salary_management.py`

**1. Xoa droplist "Định dạng" trong tab Tong hop**
- Xoa block chon dinh dang bang luong (Bien che / Hop dong / Khac) o phan hien thi chi tiet can bo.
- Xoa bien `loai_luong` (khong con can thiet).

**2. Dinh dang tu dong tu nguon luong**
- Loai thong bao (Bien che / Hop dong / Khac) duoc tu dong xac dinh tu truong `nguon_luong` cua user hoac `loai` cua ban ghi luong gan nhat.
- Khong can chon thu cong.

## Kiem tra
- `python -m py_compile ui/salary_management.py` -> OK, khong loi cu phap.
