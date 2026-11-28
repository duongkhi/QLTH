# OpenSpec Change: Lay don_vi_cong_tac tu ho so ca nhan (khong phai auth_config)

## Thay doi da thuc hien

### File: `user_service.py`

**1. Ham `sync_user_to_salary` - Lay `don_vi_cong_tac` tu ho so ca nhan**
- Truoc: lay `don_vi_cong_tac` tu `user_record` (auth_config), khong co gia tri
- Sau: load `load_user_profile(profile_key)` lay `don_vi_cong_tac` tu ho so ca nhan (key rieng), neu khong co moi lay tu auth_config

**Nguyen ly:** Ho so `BuiNhung` (61 truong) khong co `don_vi_cong_tac` trong auth_config, ma co the co trong ho so ca nhan. Truoc day ham khong lay duoc gia tri nay, nen `salary_profiles` khong co don vi cong tac phong. Sau sua doi, ham se load ho so ca nhan truoc de lay gia tri.

## Kiem tra
- `python -m py_compile user_service.py` -> OK, khong loi cu phap.
