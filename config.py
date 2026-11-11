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
META_KEYS = {"auth_config", "name_mapping", FORM_TEMPLATE_INDEX}

DEFAULTS = {
    "logged_in": False, "username": "", "last_username": "",
    "chat_history": [], "show_change_pw": False, "show_manage_users": False,
    "auth_mode": "login", "pending_toast": None, "pw_change_success": False,
    "upload_stage": None, "upload_extracted": None,
    "upload_detected_name": None, "upload_detected_dob": None,
    "active_module": "admin",
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