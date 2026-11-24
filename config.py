# config.py
import streamlit as st
from dataclasses import dataclass, field
from google.genai import types

MAX_CHARS = 25000
MAX_RETRIES = 2

MODELS_TO_TRY = [
    {"name": "gemini-3.8-flash", "thinking": types.ThinkingLevel.LOW},
    {"name": "gemini-3.5-flash-lite", "thinking": types.ThinkingLevel.MINIMAL},
]
CHAT_MODELS_TO_TRY = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

FORM_TEMPLATE_PREFIX = "_form_template_"
FORM_TEMPLATE_INDEX = "_form_template_index"
META_KEYS = {"auth_config", "name_mapping", FORM_TEMPLATE_INDEX, "ai_settings", "hermes_skills_registry", "journal_quality_catalog", "publications_index"}

# Danh sách công cụ nghiệp vụ có thể cấp quyền cho User / Manager
# PHẢI đồng bộ với các nút trong ui/sidebar.py (admin_buttons) và routing trong main.py
SYSTEM_TOOLS = {
    "workspace": "💰 Quản lý tài chính",
    "salary": "💰 Quản trị lương",
    "journal_admin": "📦 Sản phẩm khoa học",
    "data_management": "🗄️ Quản lý dữ liệu",
    "skill_admin": "🛠️ Quản trị Skill",
    "user_admin": "🛡️ Quản trị người dùng",
    "knowledge": "📚 Tra cứu Tri thức / Văn bản (Acknowledge)",
    "form_batch": "📝 Quản lý Thư viện Biểu mẫu",
}

DEFAULTS = {
    "logged_in": False,
    "username": "",
    "last_username": "",
    "chat_history": [],
    "finance_chat": [],
    "show_change_pw": False,
    "show_manage_users": False,
    "auth_mode": "login",
    "pending_toast": None,
    "pw_change_success": False,
    "upload_stage": None,
    "upload_extracted": None,
    "upload_detected_name": None,
    "upload_detected_dob": None,
    # --- Trạng thái điều hướng Version 2 ---
    "view_mode": "public_profile",   # public_profile | settings | workspace | user_admin
    "viewing_profile": "",           # Profile key đang xem ở chế độ Public (VD: VuDuong)
    "show_login_panel": False,       # Bật/tắt khung đăng nhập trên sidebar
}


@dataclass
class UserContext:
    username: str
    record: dict
    role: str
    own_profile: str | None
    allowed_profiles: list = field(default_factory=list)
    is_power: bool = False


def init_session_state():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v