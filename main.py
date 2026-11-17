import streamlit as st

from config import init_session_state, UserContext
from user_service import (
    load_auth_config, compute_allowed_profiles, get_own_profile,
)
from ui.auth_ui import render_auth_screen
from ui.sidebar import render_sidebar
from ui.admin_module import render_admin_module
from ui.finance_module import render_finance_module
from ui.knowledge_ui import render_knowledge_ui
from ui.chat_ui import render_chat_section
from ui.profile_ui import render_profile_page


st.set_page_config(page_title="AI Agent Hệ Thống",
                   page_icon="🔒", layout="wide")

st.markdown("""<style>
    html, body, [class*="css"] { font-size: 18px; }
    h1 { font-size: 2.4rem !important; }
    h2 { font-size: 1.9rem !important; }
    h3 { font-size: 1.4rem !important; }
    p, li, label, .stMarkdown p { font-size: 1.1rem !important; line-height: 1.6; }
    input, textarea, select, button { font-size: 1.05rem !important; }
    [data-testid="stChatMessage"] p { font-size: 1.15rem !important; line-height: 1.6; }
    hr { margin: 2rem 0 !important; }
</style>""", unsafe_allow_html=True)

init_session_state()

if not st.session_state.logged_in:
    render_auth_screen()
    st.stop()

# --- Đã đăng nhập ---
if st.session_state.get("pending_toast"):
    st.toast(st.session_state.pending_toast, icon="🎉")
    st.session_state.pending_toast = None

user_record = load_auth_config()["users"].get(st.session_state.username, {})
role_key = user_record.get("role", "user")
own_profile = get_own_profile(user_record, st.session_state.username)
allowed_profiles = compute_allowed_profiles(user_record)
is_power = role_key in ("admin", "manager")

# ĐÃ SỬA: Không ép user thường vào "admin" nữa, để mặc định là "profile"
if "active_module" not in st.session_state:
    st.session_state.active_module = "profile"
    
# Nếu là user thường mà lại đang đứng ở các module của Admin/Manager thì đẩy về profile
if not is_power and st.session_state.active_module not in ("profile", "admin"):
    st.session_state.active_module = "profile"

ctx = UserContext(
    username=st.session_state.username,
    record=user_record,
    role=role_key,
    own_profile=own_profile,
    allowed_profiles=allowed_profiles,
    is_power=is_power,
)

# Render Sidebar
render_sidebar(ctx)

# ==========================================
# ĐIỀU HƯỚNG MODULE (ROUTING)
# ==========================================
# ĐÃ SỬA: Dùng đúng st.session_state.active_module
active_mod = st.session_state.active_module

if active_mod == "profile":
    # Mặc định render trang cá nhân của chính mình
    render_profile_page(ctx, ctx.username) 
elif active_mod == "admin":
    render_admin_module(ctx)
elif active_mod == "finance":
    render_finance_module(ctx)
elif active_mod == "knowledge":
    render_knowledge_ui(ctx)

# ==========================================
# CHAT TOÀN CẦU (Luôn nằm dưới cùng)
# ==========================================
render_chat_section(ctx)