# main.py
import sys
import asyncio

if sys.platform.startswith("win"):
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
from ui.salary_management import render_salary_management_page
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

# CSS Design System & Responsive
_css_path = "static/style.css"
try:
    with open(_css_path, "r", encoding="utf-8") as _f:
        _css = _f.read()
    st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)
except FileNotFoundError:
    pass

# Áp dụng theme attribute (light/dark) lên document element
_dark = bool(st.session_state.get("dark_mode", False))
st.markdown(
    f"""
    <script>
    (function() {{
        var root = document.documentElement;
        root.setAttribute("data-theme", { "dark" if _dark else "light" });
    }})();
    </script>
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
            clear_local_session()

# Đăng ký Skill mặc định khi khởi động
ensure_statistics_skill()
ensure_quan_ly_lich_lam_viec_skill()

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
# 2. XÂY DỰNG USER CONTEXT & TỰ ĐỘNG VỀ TRANG PHÙ HỢP
# =========================================================
is_logged_in = st.session_state.get("logged_in", False)
username = st.session_state.get("username", "") if is_logged_in else ""

try:
    _auth_cfg = load_auth_config()
except Exception:
    _auth_cfg = {"users": {}}
user_record = _auth_cfg.get("users", {}).get(username, {}) if is_logged_in else {}
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
        st.session_state.view_mode = "user_admin"
    else:
        st.session_state.viewing_profile = ctx.own_profile or ""
        st.session_state.view_mode = "public_profile"
elif not is_logged_in and prev_user:
    st.session_state["_prev_logged_user"] = ""

# Khởi tạo hồ sơ mặc định nếu chưa có
if not st.session_state.get("viewing_profile"):
    if "all_profiles_cache" not in st.session_state:
        try:
            st.session_state["all_profiles_cache"] = get_all_existing_profiles()
        except Exception:
            st.session_state["all_profiles_cache"] = []
    all_p = st.session_state["all_profiles_cache"]
    st.session_state.viewing_profile = ctx.own_profile or (all_p[0] if all_p else "")

# =========================================================
# 3. BỐ CỘT: SIDEBAR + KHUNG CHÍNH (responsive theo màn hình)
# =========================================================
try:
    _screen_w = st.session_state.get("_screen_width", 1000)
except Exception:
    _screen_w = 1000

# Nếu sidebar bị thu gọn thì cột sidebar rất nhỏ
_is_collapsed = bool(st.session_state.get("sidebar_collapsed", False))
if _screen_w < 768:
    sb_ratio, main_ratio = 0.01, 0.99
elif _is_collapsed:
    sb_ratio, main_ratio = 0.04, 0.96
else:
    sb_ratio, main_ratio = 0.25, 0.75

col_sb, col_main = st.columns([sb_ratio, main_ratio], gap="small")

with col_sb:
    if _screen_w >= 768:
        render_sidebar(ctx)
    else:
        st.button("\u2630 Menu", key="btn_mobile_menu", width='stretch')
        st.caption("Chieu rong man hinh it hon 768px — sidebar duoc an de xem dung man chinh.")

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
            help="Nhập tham số cho skill dưới dạng JSON, ví dụ: {\\\\\\\\\\\\\"from_year\\\\\\\\\\\\\\\": 2020, \\\\\\\\\\\\\\\"to_year\\\\\\\\\\\\\\\": 2025}",
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
# 4. KHUNG CHÍNH BÊN PHẢI - HIỂN THỊ NỘI DUNG THEO TASK
# =========================================================
with col_main:
    # Scroll về đầu trang khi chuyển mục/trang
    st.markdown(
        """
        <script>
        window.scrollTo(0, 0);
        </script>
        """,
        unsafe_allow_html=True,
    )
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
    elif mode == "salary":
        if ctx.role in ("admin", "manager"):
            render_salary_management_page(ctx)
        else:
            st.error("🚫 Chỉ Admin/Quản lý mới có quyền truy cập trang này.")
