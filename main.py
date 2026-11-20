# main.py
import sys
import asyncio

if sys.platform.startswith("win"):
    # Bỏ qua thông báo ConnectionResetError [WinError 10054] vô hại khi trình duyệt đóng/reload kết nối
    def _ignore_win_conn_reset(loop, context):
        exc = context.get("exception")
        if isinstance(exc, ConnectionResetError):
            return
        loop.default_exception_handler(context)

    try:
        asyncio.get_event_loop().set_exception_handler(_ignore_win_conn_reset)
    except RuntimeError:
        pass

import streamlit as st

from config import init_session_state, UserContext
from user_service import load_auth_config, compute_allowed_profiles, get_own_profile
from storage import get_all_existing_profiles
from ui.sidebar import render_sidebar
from ui.profile_ui import render_public_profile, render_settings_page
from ui.workspace_ui import render_workspace_module
from ui.user_admin_ui import render_user_admin_page
from ui.chat_ui import render_chat_section
from ui.skill_ui import render_skill_page
from skill_manager import ensure_statistics_skill, run_skill
from ui.journal_admin_ui import render_journal_admin_page

st.set_page_config(
    page_title="Hệ Thống Hồ Sơ & AI Agent",
    page_icon="🎓",
    layout="wide",
)

# CSS cố định Chatbox bên phải luôn nổi và làm đẹp link hồ sơ
st.markdown("""<style>
    html, body, [class*="css"] { font-size: 20px !important; }
    .stMarkdown p, .stMarkdown li { font-size: 1.15rem !important; line-height: 1.7 !important; }
    .stTextInput input { font-size: 18px !important; padding: 10px 12px !important; }
    .stButton button { font-size: 17px !important; padding: 8px 14px !important; }
    .stCaption, .stCaption p { font-size: 15px !important; }
    .stFileUpload > div > button { font-size: 16px !important; }
    div[data-testid="stHorizontalBlock"] > div:nth-child(2) {
        position: sticky;
        top: 3.5rem;
        align-self: flex-start;
    }
    a.profile-link {
        color: #1a73e8;
        font-weight: 600;
        text-decoration: none;
        border-bottom: 1px dashed #1a73e8;
    }
    a.profile-link:hover {
        color: #0d47a1;
        border-bottom: 1px solid #0d47a1;
    }
</style>""", unsafe_allow_html=True)

init_session_state()

# Đăng ký Skill thống kê bài báo mặc định (nếu chưa có)
ensure_statistics_skill()

if st.session_state.get("pending_toast"):
    st.toast(st.session_state.pending_toast, icon="🎉")
    st.session_state.pending_toast = None

# =========================================================
# 1. XỬ LÝ LINK CHUYỂN TRANG HỒ SƠ (?profile=...)
# =========================================================
qp_profile = st.query_params.get("profile")
if qp_profile:
    st.session_state.viewing_profile = qp_profile
    st.session_state.view_mode = "public_profile"
    st.query_params.clear()
    st.rerun()

# =========================================================
# 2. XÂY DỰNG USER CONTEXT & TỰ ĐỘNG VỀ TRANG CÁ NHÂN KHI SIGN IN
# =========================================================
is_logged_in = st.session_state.get("logged_in", False)
username = st.session_state.get("username", "") if is_logged_in else ""
user_record = load_auth_config()["users"].get(username, {}) if is_logged_in else {}
role_key = user_record.get("role", "guest")

ctx = UserContext(
    username=username,
    record=user_record,
    role=role_key,
    own_profile=get_own_profile(user_record, username) if is_logged_in else None,
    allowed_profiles=compute_allowed_profiles(user_record) if is_logged_in else [],
    is_power=(role_key in ("admin", "manager")),
)

# Phát hiện sự kiện vừa Sign In -> Tự động đưa về trang phù hợp
prev_user = st.session_state.get("_prev_logged_user", "")
if is_logged_in and username != prev_user:
    st.session_state["_prev_logged_user"] = username
    # Admin mở trang làm việc gần nhất, user thường mở trang cá nhân
    if ctx.role == "admin":
        last_mode = st.session_state.get(f"last_view_mode_{username}", "workspace")
        st.session_state.view_mode = last_mode
    else:
        st.session_state.viewing_profile = ctx.own_profile or ""
        st.session_state.view_mode = "public_profile"
elif not is_logged_in and prev_user:
    st.session_state["_prev_logged_user"] = ""

# Khởi tạo hồ sơ mặc định nếu chưa có
if not st.session_state.get("viewing_profile"):
    if "all_profiles_cache" not in st.session_state:
        st.session_state["all_profiles_cache"] = get_all_existing_profiles()
    all_p = st.session_state["all_profiles_cache"]
    st.session_state.viewing_profile = ctx.own_profile or (all_p[0] if all_p else "")

# =========================================================
# 3. CONTROL BÊN TRÁI (SIDEBAR)
# =========================================================
render_sidebar(ctx)

# Lưu last_view_mode cho admin (để khôi phục khi đăng nhập lại)
if is_logged_in and ctx.role == "admin":
    current_mode = st.session_state.get("view_mode", "public_profile")
    st.session_state[f"last_view_mode_{username}"] = current_mode

# =========================================================
# 4. KHUNG CHÍNH (GIỮA) + CHATBOX CỐ ĐỊNH (BÊN PHẢI)
# =========================================================
col_main, col_chat = st.columns([7.2, 2.8], gap="medium")

with col_main:
    mode = st.session_state.get("view_mode", "public_profile")

    if not is_logged_in and mode != "public_profile":
        mode = "public_profile"
        st.session_state.view_mode = "public_profile"

    if mode == "public_profile":
        render_public_profile(ctx, st.session_state.viewing_profile)
    elif mode == "settings":
        render_settings_page(ctx)
    elif mode == "workspace":
        allowed_tools = user_record.get("allowed_tools", [])
        if ctx.role == "admin" or allowed_tools:
            render_workspace_module(ctx, allowed_tools)
        else:
            st.warning("⚠️ Bạn chưa được cấp quyền truy cập công cụ nghiệp vụ.")
    elif mode == "user_admin":
        if ctx.role == "admin":
            render_user_admin_page(ctx)
        else:
            st.error("🚫 Chỉ quản trị viên mới có quyền truy cập trang này.")
    elif mode == "skill":
        render_skill_page(ctx)
    elif mode == "skill_run":
        _render_skill_run_page(ctx)
    elif mode == "journal_admin":
        if ctx.role == "admin":
            render_journal_admin_page(ctx)
        else:
            st.error("🚫 Chỉ quản trị viên mới có quyền truy cập trang này.")

with col_chat:
    with st.container(height=680, border=True):
        render_chat_section(ctx)


# ============================================================
# TRANG CHẠY SKILL TỪ SIDEBAR
# ============================================================
def _render_skill_run_page(ctx: UserContext):
    """Hiển thị form nhập tham số và chạy skill được chọn từ sidebar."""
    skill_name = st.session_state.get("_run_skill_name", "")
    skill_desc = st.session_state.get("_run_skill_description", "")

    if not skill_name:
        st.error("Không tìm thấy skill để chạy.")
        if st.button("⬅️ Quay lại"):
            st.session_state.view_mode = "public_profile"
            st.rerun()
        return

    st.title(f"⚙️ Chạy Skill: {skill_name}")
    if skill_desc:
        st.caption(skill_desc)

    st.markdown("---")

    # Form nhập tham số (JSON)
    with st.form("form_run_skill"):
        args_text = st.text_area(
            "Tham số (JSON)",
            value="{}",
            height=150,
            help="Nhập tham số cho skill dưới dạng JSON, ví dụ: {\"from_year\": 2020, \"to_year\": 2025}",
        )
        c1, c2 = st.columns(2)
        with c1:
            run_submit = st.form_submit_button("🚀 Chạy Skill", type="primary", width='stretch')
        with c2:
            back_submit = st.form_submit_button("⬅️ Quay lại", width='stretch')

    if back_submit:
        st.session_state.view_mode = "public_profile"
        st.session_state.pop("_run_skill_name", None)
        st.session_state.pop("_run_skill_description", None)
        st.rerun()

    if run_submit:
        try:
            import json as _json
            args = _json.loads(args_text) if args_text.strip() else {}
        except Exception as e:
            st.error(f"❌ JSON không hợp lệ: {e}")
            return

        with st.spinner("⏳ Đang chạy skill..."):
            result = run_skill(
                skill_name=skill_name,
                args=args,
                username=ctx.username,
                allowed_profiles=ctx.allowed_profiles,
            )

        if "error" in result:
            st.error(f"❌ {result['error']}")
        else:
            st.success("✅ Đã chạy skill thành công!")

            # Nếu có file Excel để tải xuống
            if "_excel_bytes" in result:
                st.download_button(
                    label="📥 Tải file Excel",
                    data=result.pop("_excel_bytes"),
                    file_name=f"{result.get('download_token', 'skill_result')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.document",
                    width='stretch',
                )

            # Hiển thị kết quả
            st.json(result)