# user_service.py
import re
import streamlit as st
from datetime import datetime
from supabase_adapter import load_json_from_db, save_json_to_db
from storage import get_all_existing_profiles, load_user_profile
from security import hash_password


# ---------- Migration ----------
def _migrate_user_record(uname, rec):
    if "role" not in rec:
        a = rec.get("allowed_profiles", [])
        rec["role"] = "admin" if "admin" in a else (
            "manager" if len(a) > 1 else "user")
    role = rec["role"]
    if "own_profile" not in rec:
        if role == "user":
            rec["own_profile"] = uname
        else:
            a = rec.get("allowed_profiles", [])
            rec["own_profile"] = uname if uname in a else None
    if role == "user" and not rec.get("own_profile"):
        rec["own_profile"] = uname
    if "allowed_tools" not in rec:
        rec["allowed_tools"] = []
    rec.pop("allowed_profiles", None)
    return rec


# ---------- Auth config ----------
def load_auth_config():
    cfg = load_json_from_db("auth_config")
    if not cfg or "users" not in cfg:
        if "DEFAULT_ADMIN_PW" not in st.secrets:
            raise RuntimeError("Thiếu st.secrets['DEFAULT_ADMIN_PW'] – phải cung cấp mật khẩu admin mặc định.")
        default_pw = st.secrets["DEFAULT_ADMIN_PW"]
        cfg = {"users": {
            "admin": {
                "password_hash": hash_password(default_pw),
                "own_profile": None,
                "role": "admin",
                "allowed_tools": ["workspace", "knowledge", "form_batch"],
            },
        }}
        save_json_to_db("auth_config", cfg)
    for u, r in cfg.get("users", {}).items():
        _migrate_user_record(u, r)
    return cfg


def save_auth_config(cfg):
    save_json_to_db("auth_config", cfg)


# ---------- Permission ----------
def get_own_profile(rec, username):
    return rec.get("own_profile")


def compute_allowed_profiles(rec):
    role = rec.get("role", "user")
    own = rec.get("own_profile")
    if role in ("admin", "manager"):
        p = set(get_all_existing_profiles())
        if own:
            p.add(own)
        return sorted(p)
    return [own] if own else []


# ---------- Validation ----------
def validate_username(u):
    if not u:
        return False, "Vui lòng nhập tên."
    if len(u) < 3:
        return False, "Tên phải ≥3 ký tự."
    if len(u) > 30:
        return False, "Tên ≤30 ký tự."
    if not re.match(r"^[a-zA-Z0-9_]+$", u):
        return False, "Chỉ chứa chữ, số, gạch dưới."
    return True, ""


# ---------- User CRUD ----------
def create_user(u, pw):
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": u,
        "role": "user",
        "allowed_tools": [],
    }
    save_auth_config(c)
    return True, "Đăng ký thành công! Hãy nạp dữ liệu ở mục Setting."


def admin_create_user(u, pw, role, own_prof=None, allowed_tools=None, salary_link=None):
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": own_prof if own_prof else (u if role == "user" else None),
        "role": role,
        "allowed_tools": allowed_tools or [],
        "salary_link": salary_link if salary_link else None,
    }
    save_auth_config(c)
    if salary_link:
        create_salary_entry_for_user(u, salary_link, ho_va_ten="", email="")
    if c["users"][u]["own_profile"] and load_user_profile(c["users"][u]["own_profile"]):
        from name_mapping import sync_name_mapping
        sync_name_mapping([c["users"][u]["own_profile"]])
    return True, f"Đã tạo user '{u}' (role '{role}')."


def admin_update_user(target, new_role, new_own, new_tools=None, salary_link=None):
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    rec = c["users"][target]
    rec["role"] = new_role
    rec["own_profile"] = new_own if new_own else (target if new_role == "user" else None)
    if new_tools is not None:
        rec["allowed_tools"] = new_tools
    if salary_link is not None:
        rec["salary_link"] = salary_link if salary_link else None
    save_auth_config(c)
    # Dong bo vao salary_profiles neu co salary_link
    if salary_link:
        sync_user_to_salary(target, c["users"][target])
    return True, f"Đã cập nhật phân quyền cho '{target}'."


def admin_reset_password(target, new_pw):
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    c["users"][target]["password_hash"] = hash_password(new_pw)
    save_auth_config(c)
    return True, f"Đã reset mật khẩu cho '{target}'."


def admin_delete_user(target, current):
    if target == current:
        return False, "Không thể xóa chính mình."
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    del c["users"][target]
    save_auth_config(c)
    return True, f"Đã xóa user '{target}'."


def update_user_password(u, new_pw):
    c = load_auth_config()
    if u not in c["users"]:
        return False
    c["users"][u]["password_hash"] = hash_password(new_pw)
    save_auth_config(c)
    return True


# ============================================================
# LUONG: tra cuu tu salary_profiles (key = username neu co user, nguoc lai fullname)
# ============================================================
def get_salary_profiles() -> dict:
    """Lay toan bo du lieu luong tu key 'salary_profiles' tren Supabase.
    Tra ve dict: {key: { ... lich_su_bien_dong_luong: [...] }}
    Key la username neu co user, nguoc lai la ho_va_ten."""
    return load_json_from_db("salary_profiles") or {}


def _normalize_key(s: str) -> str:
    """Bo dau, lower, khoang trang de so sanh key luong."""
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.lower().replace(" ", "").replace("_", "")


def _resolve_salary_key(profiles: dict, current_user: str, role: str, target_name: str,
                        user_record: dict | None = None):
    """Tim key trong salary_profiles tuong ung voi target_name.
    - Neu role admin/manager: tra ve key chinh xac target_name (neu co).
    - Neu role user: chi cho phep neu target_name khop voi current_user
      (so sanh theo username hoac ho_va_ten trong entry, hoac qua profile cua user,
       hoac qua salary_link neu co).
    Tra ve (key_duoc_chon, entry_hoac_None, loi_hoac_None)."""
    if target_name not in profiles:
        # Thu tim theo ho_va_ten trong entry neu target_name khong chinh xac key
        for k, v in profiles.items():
            if v.get("ho_va_ten", "").strip().lower() == target_name.strip().lower():
                target_name = k
                break
        else:
            return None, None, f"Khong tim thong tin luong cua '{target_name}'."

    if role in ("admin", "manager"):
        return target_name, profiles[target_name], None

    # User thuong: kiem tra xem target_name co phai chinh minh khong
    entry = profiles.get(target_name, {})
    entry_ho_ten = entry.get("ho_va_ten", "").strip()

    # So sanh theo username hoac ho_va_ten trong entry luong
    is_self = (
        _normalize_key(target_name) == _normalize_key(current_user)
        or _normalize_key(entry_ho_ten) == _normalize_key(current_user)
    )

    # Fallback 1: tra cuu profile cua user de lay ho_va_ten
    if not is_self:
        try:
            user_prof = load_user_profile(current_user) or {}
            user_ho_ten = user_prof.get("ho_va_ten", "").strip()
            if user_ho_ten and _normalize_key(user_ho_ten) == _normalize_key(entry_ho_ten):
                is_self = True
        except Exception:
            pass

    # Fallback 2: su dung salary_link neu co trong user record
    if not is_self and user_record:
        salary_link = user_record.get("salary_link")
        if salary_link:
            if _normalize_key(salary_link) == _normalize_key(target_name):
                is_self = True
            elif salary_link in profiles:
                # salary_link la key trong salary_profiles, kiem tra entry ho_va_ten
                link_ho_ten = profiles[salary_link].get("ho_va_ten", "").strip()
                if _normalize_key(link_ho_ten) == _normalize_key(target_name):
                    is_self = True
                    target_name = salary_link

    if not is_self:
        return target_name, None, "Ban chi duoc xem luong cua chinh minh."

    return target_name, entry, None


def tra_cuu_luong(ten_nguoi_can_xem: str, current_user: str, role: str,
                  user_record: dict | None = None) -> dict:
    """Tra cuu thong tin luong cua mot nguoi.
    Tra ve du lieu neu co quyen, nguoc lai tra ve {'error': ...}."""
    profiles = get_salary_profiles()
    key, entry, err = _resolve_salary_key(profiles, current_user, role, ten_nguoi_can_xem, user_record)
    if err:
        return {"error": err}
    return entry


def lay_luong_theo_thang(data_user: dict, nam: int, thang: int) -> dict | None:
    """Trich xuat luong cua mot thang tu lich_su_bien_dong_luong.
    Lay gan nhat truoc hoac bang thang (nam, thang). Neu khong co -> None."""
    lich_su = data_user.get("lich_su_bien_dong_luong", [])
    if not lich_su:
        return None

    hop_le = [b for b in lich_su
              if (b.get("nam", 0), b.get("thang", 0)) <= (nam, thang)]
    if not hop_le:
        return None

    return max(hop_le, key=lambda b: (b.get("nam", 0), b.get("thang", 0)))


def lay_ds_nhan_vien_co_luong() -> list[str]:
    """Tra ve danh sach ho ten cac nhan vien co luong (de hien thi dropdown/admin).
    Tra ve danh sach ho_va_ten (khong phai key) de hien thi thich thuc."""
    profiles = get_salary_profiles()
    ten_list = []
    for v in profiles.values():
        ten = v.get("ho_va_ten", "").strip()
        if ten:
            ten_list.append(ten)
    return sorted(set(ten_list))


def lay_ds_key_co_luong() -> list[str]:
    """Tra ve danh sach key (username hoac fullname) trong salary_profiles (dung cho admin)."""
    return sorted(get_salary_profiles().keys())


# ============================================================
# DONG BO user <-> salary_profiles
# ============================================================
def sync_user_to_salary(username: str, user_record: dict) -> bool:
    """Tao entry trong salary_profiles neu user duoc lien ket voi bang luong,
    va cap nhat ho_va_ten, email tu user_profile neu da thay doi.

    Tra ve True neu da tao/cap nhat thanh cong, False neu bo qua."""
    salary_link = user_record.get("salary_link")
    if not salary_link:
        return False  # User chua duoc lien ket voi bang luong nao

    profiles = get_salary_profiles()
    if salary_link not in profiles:
        # Tao entry trong khi chua co thong tin luong chi tiet
        profiles[salary_link] = {
            "ho_va_ten": user_record.get("own_profile", username),
            "email": user_record.get("email", ""),
            "don_vi_cong_tac": "",
            "ngay_nhan_luong_dau_tien": "",
            "cap_nhat_luc": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "lich_su_bien_dong_luong": [],
        }
    else:
        # Cap nhat ten/email neu user profile da thay doi
        entry = profiles[salary_link]
        entry["ho_va_ten"] = user_record.get("own_profile", username) or entry.get("ho_va_ten", "")
        entry["email"] = user_record.get("email", "") or entry.get("email", "")
        entry["cap_nhat_luc"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    return save_json_to_db("salary_profiles", profiles)


def create_salary_entry_for_user(username: str, salary_key: str, ho_va_ten: str = "", email: str = "") -> bool:
    """Tao entry trong salary_profiles cho user moi (dung khi admin tao user)."""
    profiles = get_salary_profiles()
    if salary_key in profiles:
        return True  # Da co, khong tao lai
    profiles[salary_key] = {
        "ho_va_ten": ho_va_ten or username,
        "email": email,
        "don_vi_cong_tac": "",
        "ngay_nhan_luong_dau_tien": "",
        "cap_nhat_luc": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "lich_su_bien_dong_luong": [],
    }
    return save_json_to_db("salary_profiles", profiles)
