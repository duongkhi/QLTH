# ui/sidebar.py
# Sidebar bên trái: avatar/tài khoản, quản lý skill, chat box.
# Có nút thu gọn / mở sidebar. Chiếm khoảng 30% chiều rộng màn hình.
import streamlit as st
from config import UserContext
from ui.local_session import clear_local_session
from storage import load_user_profile
from skill_manager import (
    get_user_skill_tree,
    add_skill_to_user_tree,
    generate_skill_from_request,
    create_skill,
)
from ui.chat_ui import render_chat_section


def _render_avatar(username: str | None, role: str, profile_key: str | None = None):
    """Hiển thị avatar (ảnh nếu có, ngược lại initials) + username + role."""
    avatar_b64 = None
    display_name = username or "Khách"

    if profile_key:
        try:
            prof = load_user_profile(profile_key) or {}
            avatar_b64 = prof.get("_avatar_b64")
            disp = (
                prof.get("ho_va_ten")
                or prof.get("ho_ten")
                or prof.get("full_name")
                or username
            )
            if disp:
                display_name = disp
        except Exception:
            pass

    if avatar_b64:
        st.markdown(
            f"<div style='text-align:center; margin-bottom:4px;'>"
            f"<img src='data:image/png;base64,{avatar_b64}' "
            f"style='width:120px;height:120px;border-radius:50%;object-fit:cover;'"
            f"border:3px solid #3b82f6;' /></div>",
            unsafe_allow_html=True,
        )
    else:
        parts = [p for p in str(display_name).strip().split() if p]
        if len(parts) >= 2:
            initials = (parts[0][0] + parts[-1][0]).upper()
        elif parts:
            initials = parts[0][:2].upper()
        else:
            initials = "CV"
        role_color = {"admin": "#1f2937", "manager": "#1d4ed8", "user": "#8b5cf6"}.get(role, "#8b5cf6")
        st.markdown(
            f"<div style='text-align:center; margin-bottom:4px;'>"
            f"<div style='width:120px;height:120px;border-radius:50%;'"
            f"background:linear-gradient(135deg,#2563eb,#7c3aed);'"
            f"display:flex;align-items:center;justify-content:center;'"
            f"color:#fff;font-size:42px;font-weight:700;'"
            f"border:3px solid rgba(255,255,255,0.3);'>{initials}</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<div style='text-align:center; font-weight:600; font-size:14px;'>{display_name}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='text-align:center; font-size:11px; opacity:0.7;'>{role.upper()}</div>",
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
        _render_avatar(ctx.username, ctx.role, ctx.own_profile)
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        if st.button("⚙️ Setting Hồ Sơ", key="btn_sidebar_setting", width='stretch'):
            st.session_state.view_mode = "settings"
            st.rerun()
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
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
