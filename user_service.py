# user_service.py
import re
import streamlit as st
from datetime import datetime
from supabase_adapter import load_json_from_db, save_json_to_db
from storage import get_all_existing_profiles, load_user_profile
from security import hash_password, _strip_diacritics


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
            }
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
        "salary_profile_id": u,
        "role": "user",
        "allowed_tools": [],
    }
    save_auth_config(c)
    return True, "Đăng ký thành công! Hãy nạp dữ liệu ở mục Setting."


def admin_create_user(u, pw, role, own_prof=None, allowed_tools=None, salary_profile_id=None):
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    # salary_profile_id luôn = username (key trong salary_profiles)
    sp_id = salary_profile_id if salary_profile_id else u
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": own_prof if own_prof else (u if role == "user" else None),
        "salary_profile_id": sp_id,
        "role": role,
        "allowed_tools": allowed_tools or [],
    }
    save_auth_config(c)
    if c["users"][u]["own_profile"] and load_user_profile(c["users"][u]["own_profile"]):
        from name_mapping import sync_name_mapping
        sync_name_mapping([c["users"][u]["own_profile"]])
    return True, f"Đã tạo user '{u}' (role '{role}')."


def admin_update_user(target, new_role, new_own, new_tools=None, salary_profile_id=None):
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    rec = c["users"][target]
    rec["role"] = new_role
    rec["own_profile"] = new_own if new_own else (target if new_role == "user" else None)
    # salary_profile_id luôn = username (target)
    rec["salary_profile_id"] = salary_profile_id if salary_profile_id else target
    if new_tools is not None:
        rec["allowed_tools"] = new_tools
    save_auth_config(c)
    # Dong bo vao salary_profiles (key = username)
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
       hoac qua salary_profile_id neu co).
    Tra ve (key_duoc_chon, entry_hoac_None, loi_hoac_None)."""
    if target_name not in profiles:
        # Thu tim theo ho_va_ten trong entry neu target_name khong chinh xac key
        target_norm = _strip_diacritics(target_name.strip().lower())
        for k, v in profiles.items():
            hv = v.get("ho_va_ten", "")
            if hv and _strip_diacritics(hv.strip().lower()) == target_norm:
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

    # Fallback 2: su dung salary_profile_id neu co trong user record
    if not is_self and user_record:
        spid = user_record.get("salary_profile_id")
        if spid:
            if _normalize_key(spid) == _normalize_key(target_name):
                is_self = True
            elif spid in profiles:
                # salary_profile_id la key trong salary_profiles, kiem tra entry ho_va_ten
                link_ho_ten = profiles[spid].get("ho_va_ten", "").strip()
                if _normalize_key(link_ho_ten) == _normalize_key(target_name):
                    is_self = True
                    target_name = spid

    if not is_self:
        return target_name, None, "Ban chi duoc xem luong cua chinh minh."

    return target_name, entry, None


def tra_cuu_luong(ten_nguoi_can_xem: str, current_user: str, role: str,
                  user_record: dict | None = None,
                  fields: list | None = None,
                  preset: str | None = None) -> dict:
    """Tra cuu thong tin luong cua mot nguoi.
    Tra ve du lieu neu co quyen, nguoc lai tra ve {'error': ...}.

    Tham so:
        ten_nguoi_can_xem: ten hoac key can tra cuu.
        current_user: ten user dang goi.
        role: vai tro cua user dang goi (admin/manager/user).
        user_record: record cua user dang goi (co the chua salary_profile_id).
        fields: danh sach can du lieu can tra cuu (neu preset la None).
        preset: "all" | "tao bang luong" | "bien dong luong" | "lan len luong gan nhat"
                Neu co preset se bo qua fields va tra ve theo preset.
    """
    profiles = get_salary_profiles()
    key, entry, err = _resolve_salary_key(profiles, current_user, role, ten_nguoi_can_xem, user_record)
    if err:
        return {"error": err}
    if not entry:
        return {"error": "Khong tim thay thong tin luong."}

    # Lay bien dong gan nhat
    lich_su = entry.get("lich_su_bien_dong_luong", [])
    latest = lich_su[-1] if lich_su else {}

    if preset:
        preset = str(preset).strip().lower()
        if preset == "all":
            return entry
        elif preset == "tao bang luong":
            return {
                "ho_va_ten": entry.get("ho_va_ten", ""),
                "don_vi_cong_tac_phong": entry.get("don_vi_cong_tac_phong", ""),
                "he_so_luong": latest.get("he_so_luong", ""),
                "tien_luong": latest.get("tien_luong", ""),
                "tong_cong": latest.get("tong_cong", ""),
                "nam": latest.get("nam", ""),
                "thang": latest.get("thang", ""),
            }
        elif preset == "bien dong luong":
            return {
                "ho_va_ten": entry.get("ho_va_ten", ""),
                "don_vi_cong_tac_phong": entry.get("don_vi_cong_tac_phong", ""),
                "lich_su_bien_dong_luong": lich_su,
            }
        elif preset == "lan len luong gan nhat":
            return {
                "ho_va_ten": entry.get("ho_va_ten", ""),
                "don_vi_cong_tac_phong": entry.get("don_vi_cong_tac_phong", ""),
                "latest": latest,
            }
        else:
            return {"error": f"Preset '{preset}' khong hop le."}

    if fields:
        result = {}
        for f in fields:
            if f == "lich_su_bien_dong_luong":
                result[f] = lich_su
            elif f == "latest_change":
                result[f] = latest
            elif f in entry:
                result[f] = entry[f]
            else:
                result[f] = latest.get(f, "")
        return result

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


def get_username_from_salary_key(key: str) -> str | None:
    """Tra ve username cua user lien ket voi key salary_profiles.

    - Neu user co salary_profile_id == key, tra ve username do.
    - Neu user co own_profile khop voi ho_va_ten trong entry salary_profiles, tra ve username do.
    - Tra ve None neu khong tim thay.
    """
    from storage import load_auth_config, load_user_profile

    auth_cfg = load_auth_config() or {}
    users = auth_cfg.get("users", {})

    # 1) Tim bang salary_profile_id (chuong trinh ưu tien)
    for uname, rec in users.items():
        if rec.get("salary_profile_id") == key:
            return uname

    # 2) Tim bang own_profile khop voi ho_va_ten trong entry salary_profiles
    profiles = get_salary_profiles()
    entry = profiles.get(key, {})
    entry_ho_ten = entry.get("ho_va_ten", "").strip()
    if entry_ho_ten:
        for uname, rec in users.items():
            own_prof = rec.get("own_profile") or uname
            prof = load_user_profile(own_prof) or {}
            hv = prof.get("ho_va_ten") or prof.get("ho_ten") or prof.get("full_name") or ""
            if hv.strip() == entry_ho_ten:
                return uname

    return None


# ============================================================
# DONG BO user <-> salary_profiles
# ============================================================
def sync_user_to_salary(username: str, user_record: dict) -> bool:
    """Dong bo user vao salary_profiles.
    - Key = username (luon).
    - Cap nhat ho_va_ten, don_vi_cong_tac_phong/vien/tong (lay tu user_profile, tach khoang ',').
    - Chi dong bo email neu entry chua co email.
    - Giu nguyen lich_su_bien_dong_luong.
    Tra ve True neu da tao/cap nhat thanh cong, False neu bo qua.
    """
    profiles = get_salary_profiles()

    # Lay don_vi_cong_tac tu ho so ca nhan (load_user_profile), neu khong co lay tu auth_config
    profile_key = user_record.get("own_profile", username) or username
    prof_data = load_user_profile(profile_key) or {}
    don_vi_raw = prof_data.get("don_vi_cong_tac", "") or user_record.get("don_vi_cong_tac", "") or ""
    don_vi_phong = ""
    don_vi_vien = ""
    don_vi_tong = ""
    if don_vi_raw:
        parts = [p.strip() for p in str(don_vi_raw).split(",")]
        don_vi_phong = parts[0] if len(parts) > 0 else ""
        don_vi_vien = parts[1] if len(parts) > 1 else ""
        don_vi_tong = parts[2] if len(parts) > 2 else ""

    ho_va_ten = user_record.get("own_profile", username) or username
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    if username not in profiles:
        # Tao entry moi
        user_email = user_record.get("email", "") or ""
        new_entry = {
            "ho_va_ten": ho_va_ten,
            "don_vi_cong_tac_phong": don_vi_phong,
            "don_vi_cong_tac_vien": don_vi_vien,
            "don_vi_cong_tac_tong": don_vi_tong,
            "cap_nhat_luc": now_str,
            "lich_su_bien_dong_luong": [],
        }
        if user_email:
            new_entry["email"] = user_email
        profiles[username] = new_entry
    else:
        # Cap nhat entry ton tai
        entry = profiles[username]
        entry["ho_va_ten"] = ho_va_ten
        entry["don_vi_cong_tac_phong"] = don_vi_phong
        entry["don_vi_cong_tac_vien"] = don_vi_vien
        entry["don_vi_cong_tac_tong"] = don_vi_tong
        entry["cap_nhat_luc"] = now_str
        # Chi dong bo email neu entry chua co email
        user_email = user_record.get("email", "") or ""
        if user_email and not entry.get("email"):
            entry["email"] = user_email

    return save_json_to_db("salary_profiles", profiles)
