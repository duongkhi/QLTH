"""
supabase_adapter.py
Adapter key-value trên Supabase, table `app_data`.

Public API:
  - get_supabase_client()  / get_client()   → Client
  - load_json_from_db(key)                  → dict
  - save_json_to_db(key, data)              → bool
  - delete_key_from_db(key)                 → bool
  - list_all_keys()                         → list[str]
  - list_keys_with_prefix(prefix)           → list[str]
  - exists_key(key)                         → bool
  - load_many(keys)                         → dict[key, data]
  - filter_profiles_in_db(op, field, value) → list[{'key', 'data'}]
"""
import logging
import os
from typing import Any

import streamlit as st
from supabase import Client, create_client

logger = logging.getLogger(__name__)

TABLE = "app_data"


# ============================================================
# CLIENT
# ============================================================
@st.cache_resource(show_spinner=False)
def get_supabase_client() -> Client:
    """
    Singleton Supabase client.
    Thứ tự đọc config: st.secrets → env vars.
    """
    url = key = None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        pass

    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "Thiếu SUPABASE_URL / SUPABASE_KEY. "
            "Thêm vào .streamlit/secrets.toml hoặc biến môi trường."
        )
    return create_client(url, key)


# Alias tương thích với form_templates.py
get_client = get_supabase_client


# ============================================================
# ERROR HELPER
# ============================================================
def _notify(prefix: str, e: Exception) -> None:
    """Log lỗi. Chỉ hiện st.error nếu đang chạy trong Streamlit."""
    logger.error("%s: %s", prefix, e, exc_info=True)
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is not None:
            st.error(f"{prefix}: {e}")
    except Exception:
        pass


# ============================================================
# CRUD key-value
# ============================================================
def load_json_from_db(key: str) -> dict:
    if not key:
        return {}
    try:
        resp = (
            get_supabase_client()
            .table(TABLE)
            .select("data")
            .eq("key", key)
            .execute()
        )
        return resp.data[0]["data"] if resp.data else {}
    except Exception as e:
        _notify(f"Lỗi đọc Supabase key='{key}'", e)
        return {}


def save_json_to_db(key: str, data: dict) -> bool:
    if not key:
        return False
    try:
        (
            get_supabase_client()
            .table(TABLE)
            .upsert({"key": key, "data": data})
            .execute()
        )
        return True
    except Exception as e:
        _notify(f"Lỗi ghi Supabase key='{key}'", e)
        return False


def delete_key_from_db(key: str) -> bool:
    if not key:
        return False
    try:
        (
            get_supabase_client()
            .table(TABLE)
            .delete()
            .eq("key", key)
            .execute()
        )
        return True
    except Exception as e:
        _notify(f"Lỗi xóa Supabase key='{key}'", e)
        return False


def list_all_keys() -> list:
    try:
        resp = get_supabase_client().table(TABLE).select("key").execute()
        return [r["key"] for r in (resp.data or [])]
    except Exception as e:
        _notify("Lỗi list keys", e)
        return []


def list_keys_with_prefix(prefix: str) -> list:
    """Liệt kê key bắt đầu bằng prefix (dùng LIKE 'prefix%')."""
    if not prefix:
        return list_all_keys()
    try:
        resp = (
            get_supabase_client()
            .table(TABLE)
            .select("key")
            .like("key", f"{prefix}%")
            .execute()
        )
        return [r["key"] for r in (resp.data or [])]
    except Exception as e:
        _notify(f"Lỗi list keys prefix='{prefix}'", e)
        return []


def exists_key(key: str) -> bool:
    if not key:
        return False
    try:
        resp = (
            get_supabase_client()
            .table(TABLE)
            .select("key")
            .eq("key", key)
            .limit(1)
            .execute()
        )
        return bool(resp.data)
    except Exception:
        return False


def load_many(keys: list) -> dict:
    """Load nhiều key trong 1 query. Trả về {key: data}."""
    if not keys:
        return {}
    try:
        resp = (
            get_supabase_client()
            .table(TABLE)
            .select("key, data")
            .in_("key", list(keys))
            .execute()
        )
        return {r["key"]: r["data"] for r in (resp.data or [])}
    except Exception as e:
        _notify("Lỗi load_many", e)
        return {}


# ============================================================
# DYNAMIC FILTER (chat search)
# ============================================================
_ALLOWED_OPS = {
    "eq", "neq", "gt", "gte", "lt", "lte",
    "like", "ilike",
}


def filter_profiles_in_db(operator: str, field: str, value: Any) -> list:
    """
    Truy vấn động trên bảng app_data.

    Args:
        operator: 'eq'|'neq'|'gt'|'gte'|'lt'|'lte'|'like'|'ilike'|'in'|'cs'|'cd'
                  (whitelist — toán tử khác trả [] để tránh injection)
        field:    JSON path, vd 'data->>ngay_sinh'
        value:    str | number | list

    Returns:
        list[{'key': str, 'data': dict}]  — [] nếu lỗi/rỗng.
    """
    if not operator or not field:
        return []
    op = operator.lower().strip()

    try:
        client = get_supabase_client()
        query = client.table(TABLE).select("key, data")

        if op == "in":
            vals = value if isinstance(value, (list, tuple)) else [value]
            query = query.in_(field, list(vals))
        elif op in ("cs", "contains"):
            query = query.contains(field, value)
        elif op in ("cd", "contained_by"):
            query = query.contained_by(field, value)
        elif op in _ALLOWED_OPS:
            query = getattr(query, op)(field, value)
        else:
            _notify("Toán tử không hỗ trợ", ValueError(op))
            return []

        resp = query.execute()
        return resp.data or []
    except Exception as e:
        _notify(f"Lỗi filter {op} {field}={value!r}", e)
        return []