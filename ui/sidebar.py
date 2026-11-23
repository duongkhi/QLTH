# ui/sidebar.py
# Sidebar bên trái: avatar/tài khoản, quản lý skill, chat box.
# Có nút thu gọn / mở sidebar. Chiếm khoảng 30% chiều rộng màn hình.
import streamlit as st
from config import UserContext
from ui.local_session import clear_local_session
from skill_manager import (
    get_user_skill_tree,
    add_skill_to_user_tree,
    generate_skill_from_request,
    create_skill,
)
from ui.chat_ui import render_chat_section


def _render_avatar(username: str | None, role: str):
    """Hiển thị mini avatar (hoặc default guest)."""
    if username:
        role_icon = {"admin": "🛡️", "manager": "💼", "user": "👤"}.get(role, "👤")
        st.markdown(
            f"<div style='text-align:center; font-size:28px; margin-bottom:4px;'>{role_icon}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='text-align:center; font-weight:600; font-size:14px;'>{username}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='text-align:center; font-size:11px; opacity:0.7;'>{role.upper()}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='text-align:center; font-size:28px; margin-bottom:4px;'>👤</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='text-align:center; font-weight:600; font-size:14px;'>Khách</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='text-align:center; font-size:11px; opacity:0.7;'>GUEST</div>",
            unsafe_allow_html=True,
        )


def render_sidebar(ctx: UserContext):
    """Render nội dung sidebar."""
    st.markdown("---")

    # =========================================================
    # 1. AVATAR & TÀI KHOẢN
    # =========================================================
    if not st.session_state.get("logged_in", False):
        _render_avatar(None, "guest")
        if st.button("🔐 Đăng nhập", type="primary", width='stretch'):
            st.session_state.show_login_panel = not st.session_state.get("show_login_panel", False)
            st.rerun()
        if st.session_state.get("show_login_panel", False):
            with st.container(border=True):
                from ui.auth_ui import render_auth_screen
                render_auth_screen()
    else:
        _render_avatar(ctx.username, ctx.role)
        if st.button("🚪 Đăng xuất", width='stretch'):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state["_prev_logged_user"] = ""
            st.session_state.view_mode = "public_profile"
            st.session_state.show_login_panel = False
            clear_local_session()
            st.rerun()

    st.markdown("---")

    # =========================================================
    # 2. CÔNG CỦ QUẢN TRỊ (chỉ admin / manager)
    # =========================================================
    if st.session_state.get("logged_in", False) and ctx.role in ("admin", "manager"):
        st.markdown("### 🛠️ Công cụ quản trị")

        admin_buttons = [
            ("💰 Công cụ tài chính", "workspace"),
            ("📦 Sản phẩm khoa học", "journal_admin"),
            ("🗄️ Quản lý dữ liệu", "data_management"),
            ("🛠️ Quản trị Skill", "skill_admin"),
        ]

        # Nút Quản trị người dùng chỉ hiển thị cho Admin (bảo mật cao nhất)
        if ctx.role == "admin":
            admin_buttons.insert(0, ("🛡️ Quản trị người dùng", "user_admin"))

        # Hiển thị các nút theo 2 cột một hàng
        for i in range(0, len(admin_buttons), 2):
            c1, c2 = st.columns(2)
            label1, mode1 = admin_buttons[i]
            with c1:
                if st.button(label1, key=f"nav_{mode1}", width='stretch'):
                    st.session_state.view_mode = mode1
                    st.session_state.pop("_run_skill_name", None)
                    st.session_state.pop("_run_skill_description", None)
                    st.rerun()
            if i + 1 < len(admin_buttons):
                label2, mode2 = admin_buttons[i + 1]
                with c2:
                    if st.button(label2, key=f"nav_{mode2}", width='stretch'):
                        st.session_state.view_mode = mode2
                        st.session_state.pop("_run_skill_name", None)
                        st.session_state.pop("_run_skill_description", None)
                        st.rerun()

    st.markdown("---")

    # =========================================================
    # 4. CHAT BOX (đặt trong sidebar)
    # =========================================================
    render_chat_section(ctx)

    st.markdown("---")
    st.caption("Phiên bản: **v2.0.1** · Hệ Thống Hồ Sơ & AI Agent")
