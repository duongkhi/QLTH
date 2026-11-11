import os
import time
from supabase_adapter import (
    load_json_from_db, save_json_to_db, delete_key_from_db,
    list_all_keys, filter_profiles_in_db,
)
from config import META_KEYS, FORM_TEMPLATE_PREFIX

DATA_DIR = "./database"
LOG_FILE = os.path.join(DATA_DIR, "system_logs.txt")

__all__ = [
    "load_json_from_db", "save_json_to_db", "delete_key_from_db",
    "list_all_keys", "filter_profiles_in_db",
    "load_user_profile", "save_user_profile",
    "load_name_mapping", "save_name_mapping",
    "get_all_existing_profiles", "write_system_log",
]


def load_user_profile(name):
    if not name:
        return {}
    return load_json_from_db(name) or {}


def save_user_profile(name, data):
    if not name:
        return
    save_json_to_db(name, data)


def load_name_mapping():
    return load_json_from_db("name_mapping") or {}


def save_name_mapping(m):
    save_json_to_db("name_mapping", m)


def get_all_existing_profiles():
    return sorted(
        k for k in list_all_keys()
        if k not in META_KEYS
        and not k.startswith("_")
        and not k.startswith(FORM_TEMPLATE_PREFIX)
    )


def write_system_log(user, action, status):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {user} | {action} | {status}\n")
    except Exception:
        pass