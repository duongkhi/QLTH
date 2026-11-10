import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def load_json_from_db(key: str) -> dict:
    try:
        resp = get_supabase_client().table("app_data").select("data").eq("key", key).execute()
        return resp.data[0]["data"] if resp.data else {}
    except Exception as e:
        st.error(f"Lỗi đọc Supabase: {e}")
        return {}

def save_json_to_db(key: str, data: dict) -> bool:
    try:
        get_supabase_client().table("app_data").upsert({"key": key, "data": data}).execute()
        return True
    except Exception as e:
        st.error(f"Lỗi ghi Supabase: {e}")
        return False

def delete_key_from_db(key: str) -> bool:
    try:
        get_supabase_client().table("app_data").delete().eq("key", key).execute()
        return True
    except Exception as e:
        st.error(f"Lỗi xóa Supabase: {e}")
        return False

def list_all_keys() -> list:
    try:
        resp = get_supabase_client().table("app_data").select("key").execute()
        return [r["key"] for r in resp.data]
    except Exception as e:
        st.error(f"Lỗi list keys: {e}")
        return []