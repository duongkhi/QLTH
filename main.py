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
from ui.skill_ui import render_skill_page
from skill_manager import ensure_statistics_skill, ensure_quan_ly_lich_lam_viec_skill, run_skill
from ui.journal_admin_ui import render_journal_admin_page
from ui.admin_dashboard import render_admin_dashboard
from ui.notification_ui import render_notification_page
from ui.local_session import load_local_session, clear_local_session
from name_mapping import sync_name_mapping

st.set_page_config(
    page_title="Hệ Thống Hồ Sơ & AI Agent",
    page_icon="🎓",
    layout="wide",
)

# CSS cố định: font size responsive theo từng màn hình, layout sidebar/chính
st.markdown(
    """
    <style>
    :root {
        --base-font: 16px;
    }
    html, body, [class*="css"] {
        font-size: var(--base-font) !important;
    }
    .stMarkdown p, .stMarkdown li {
        font-size: 1rem !important;
        line-height: 1.6 !important;
    }
    .stTextInput input {
        font-size: 1rem !important;
        padding: 8px 10px !important;
    }
    .stButton button {
        font-size: 0.95rem !important;
        padding: 7px 12px !important;
    }
    .stCaption, .stCaption p {
        font-size: 0.85rem !important;
    }
    .stFileUpload > div > button {
        font-size: 0.9rem !important;
    }
    /* Khoảng trắng phía trên để tránh bị che bởi thanh Streamlit khi deploy/rerun */
    .block-container {
        padding-top: 2rem !important;
        padding-bottom: 1rem !important;
        max-width: none !important;
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
    /* Responsive font size theo màn hình */
    @media (max-width: 768px) {
        html, body, [class*="css"] {
            font-size: 14px !important;
        }
        .stButton button {
            font-size: 0.85rem !important;
            padding: 6px 10px !important;
        }
        .stMarkdown p, .stMarkdown li {
            font-size: 0.95rem !important;
        }
    }
    @media (min-width: 1200px) {
        html, body, [class*="css"] {
            font-size: 18px !important;
        }
        .stButton button {
            font-size: 1rem !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

init_session_state()

# =========================================================
# TỰ ĐỘNG KHÔI PHỤC PHIÊN ĐĂNG NHẬP TỪ MÁY CỦA BẠN
# (nếu trước đó đã chọn "Ghi nhớ đăng nhập" và chưa hết hạn)
# =========================================================
if not st.session_state.get("logged_in", False):
    ls = load_local_session()
    if ls:
        try:
            auth_config = load_auth_config()
            rec = auth_config.get("users", {}).get(ls["username"])
            if rec and rec.get("password_hash") == ls["password_hash"]:
                st.session_state.update({
                    "logged_in": True,
                    "username": ls["username"],
                    "last_username": ls["username"],
                    "chat_history": [],
                    "auth_mode": "login",
                    "active_module": "admin",
                })
                sync_name_mapping(compute_allowed_profiles(rec))
        except Exception:
            # Nếu Supabase/lỗi mạng, bỏ qua tự động đăng nhập;
            # người dùng vẫn có thể đăng nhập thủ công bình thường.
            clear_local_session()

# Đăng ký Skill mặc định khi khởi động
ensure_statistics_skill()
ensure_quan_ly_lich_lam_viec_skill()

if st.session_state.get("pending_toast"):
    st.toast(st.session_state.pending_toast, icon="🎉")
    st.session_state.pending_toast = None

# Trạng thái thu gọn/mở sidebar (đã bỏ)

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
# 2. XÂY DỰNG USER CONTEXT & TỰ ĐỘNG VỀ TRANG PHÙ HỢP
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
    if ctx.role == "admin":
        # Admin mặc định vào trang Quản trị người dùng
        st.session_state.view_mode = "user_admin"
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
# 3. BỐ CỘT: SIDEBAR (30%) + KHUNG CHÍNH (70%)
# =========================================================
sb_ratio = 0.20
main_ratio = 0.80

col_sb, col_main = st.columns([sb_ratio, main_ratio], gap="small")

with col_sb:
    render_sidebar(ctx)

# Lưu last_view_mode cho admin (để khôi phục khi đăng nhập lại)
if is_logged_in and ctx.role == "admin":
    current_mode = st.session_state.get("view_mode", "admin_dashboard")
    st.session_state[f"last_view_mode_{username}"] = current_mode

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
            help="Nhập tham số cho skill dưới dạng JSON, ví dụ: {\\\"from_year\\\": 2020, \\\"to_year\\\": 2025}",
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


# =========================================================
# 4. KHUNG CHÍNH BÊN PHẢI (70%) - HIỂN THỊ NỘI DUNG THEO TASK
# =========================================================
with col_main:
    mode = st.session_state.get(
        "view_mode", "admin_dashboard" if ctx.role == "admin" else "public_profile"
    )

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
    elif mode == "admin_dashboard":
        if ctx.role == "admin":
            render_admin_dashboard(ctx)
        else:
            st.error("🚫 Chỉ quản trị viên mới có quyền truy cập trang này.")
    elif mode == "data_management":
        if ctx.role == "admin":
            st.title("🗄️ Quản lý dữ liệu")
            st.info("Chức năng quản lý dữ liệu đang phát triển.")
        else:
            st.error("🚫 Chỉ quản trị viên mới có quyền truy cập trang này.")
    elif mode == "notification":
        if ctx.role == "admin":
            render_notification_page(ctx)
        else:
            st.error("🚫 Chỉ quản trị viên mới có quyền truy cập trang này.")
    elif mode == "skill_admin":
        if ctx.role == "admin":
            render_skill_page(ctx)
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


