# user_service.py
import re
import streamlit as st
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


def admin_create_user(u, pw, role, own_prof=None, allowed_tools=None):
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": own_prof if own_prof else (u if role == "user" else None),
        "role": role,
        "allowed_tools": allowed_tools or [],
    }
    save_auth_config(c)
    if c["users"][u]["own_profile"] and load_user_profile(c["users"][u]["own_profile"]):
        from name_mapping import sync_name_mapping
        sync_name_mapping([c["users"][u]["own_profile"]])
    return True, f"Đã tạo user '{u}' (role '{role}')."


def admin_update_user(target, new_role, new_own, new_tools=None):
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    rec = c["users"][target]
    rec["role"] = new_role
    rec["own_profile"] = new_own if new_own else (target if new_role == "user" else None)
    if new_tools is not None:
        rec["allowed_tools"] = new_tools
    save_auth_config(c)
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