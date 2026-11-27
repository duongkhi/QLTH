# ui/sidebar.py
# Sidebar bên trái: tài khoản, công cụ quản trị, chat box, dark mode toggle.
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
            f"<div style='text-align:center; margin-bottom:8px;'>"
            f"<img src='data:image/png;base64,{avatar_b64}' "
            f"class='avatar' /></div>",
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
        st.markdown(
            f"<div style='text-align:center; margin-bottom:8px;'>"
            f"<div class='avatar-initials'>{initials}</div></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<div class='sb-account-name'>{display_name}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div class='sb-account-role'>{role.upper()}</div>",
        unsafe_allow_html=True,
    )


def _render_account_card(ctx: UserContext):
    """Render khung tài khoản (avatar + tên + vai trò) dạng card."""
    is_logged_in = st.session_state.get("logged_in", False)

    st.markdown('<div class="sb-account-card">', unsafe_allow_html=True)

    if not is_logged_in:
        _render_avatar(None, "guest", None)
    else:
        profile_key = ctx.own_profile or None
        _render_avatar(st.session_state.get("username", ""), ctx.role, profile_key)

    st.markdown("</div>", unsafe_allow_html=True)


def _render_auth_actions():
    """Hiển thị các hành động khi chưa đăng nhập."""
    if st.button("🔐 Đăng nhập", type="primary", key="btn_sidebar_login", width='stretch'):
        st.session_state.show_login_panel = not st.session_state.get("show_login_panel", False)
        st.rerun()

    if st.session_state.get("show_login_panel", False):
        with st.container(border=True):
            from ui.auth_ui import render_auth_screen
            render_auth_screen()


def _render_logged_in_actions(ctx: UserContext):
    """Hiển thị các hành động sau khi đăng nhập (Setting, Đăng xuất)."""
    if st.button("⚙️ Setting Hồ Sơ", key="btn_sidebar_setting", width='stretch'):
        st.session_state.view_mode = "settings"
        st.rerun()

    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)

    if st.button("🚪 Đăng xuất", key="btn_sidebar_logout", width='stretch'):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state["_prev_logged_user"] = ""
        st.session_state.view_mode = "public_profile"
        st.session_state.show_login_panel = False
        clear_local_session()
        st.rerun()


def _render_admin_tools(ctx: UserContext):
    """Hiển thị nhóm công cụ quản trị (admin/manager)."""
    st.markdown('<div class="sb-section-title">🛠️ Công cụ quản trị</div>', unsafe_allow_html=True)

    admin_buttons = [
        ("💰 Quản lý tài chính", "workspace"),
        ("💰 Quản trị lương", "salary"),
        ("📦 Sản phẩm khoa học", "journal_admin"),
        ("🗄️ Quản lý dữ liệu", "data_management"),
        ("🛠️ Quản trị Skill", "skill_admin"),
    ]

    # Nút Quản trị người dùng chỉ hiển thị cho Admin
    if ctx.role == "admin":
        admin_buttons.insert(0, ("🛡️ Quản trị người dùng", "user_admin"))

    for label, mode in admin_buttons:
        if st.button(label, key=f"nav_{mode}", width='stretch'):
            st.session_state.view_mode = mode
            st.session_state.pop("_run_skill_name", None)
            st.session_state.pop("_run_skill_description", None)
            st.rerun()


def _render_theme_toggle():
    """Nút bật/tắt chế độ sáng/tối."""
    _dm = st.session_state.get("dark_mode", False)
    _icon = "🌙" if not _dm else "☀️"
    _label = "Bật chế độ tối" if not _dm else "Bật chế độ sáng"
    if st.button(f"{_icon} {_label}", key="btn_theme_toggle", width='stretch'):
        st.session_state.dark_mode = not _dm
        st.rerun()


def _render_collapse_toggle(is_collapsed: bool):
    """Nút thu gọn / mở sidebar (phiên bản Streamlit button)."""
    icon = "›" if is_collapsed else "‹"
    label = "Mở menu" if is_collapsed else "Thu gọn menu"
    if st.button(f"{icon} {label}", key="btn_sidebar_collapse", width='stretch'):
        st.session_state.sidebar_collapsed = not is_collapsed
        st.rerun()


def render_sidebar(ctx: UserContext):
    """Render nội dung sidebar."""
    is_logged_in = st.session_state.get("logged_in", False)
    is_collapsed = bool(st.session_state.get("sidebar_collapsed", False))

    # Wrapper sidebar (.sb-container) để áp class collapsed
    collapsed_class = " sb-collapsed" if is_collapsed else " sb-open"
    st.markdown(
        f'<div class="sb-container{collapsed_class}">',
        unsafe_allow_html=True,
    )

    # Khi sidebar bị thu gọn: chỉ để lại nút mở lại, ẩn toàn bộ nội dung khác
    if is_collapsed:
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        _render_collapse_toggle(is_collapsed)
        st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
        st.caption("Phiên bản: **v2.0.1** · Hệ Thống Hồ Sơ & AI Agent")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    # =========================================================
    # 1. TÀI KHOẢN
    # =========================================================
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown('<div class="sb-section-title">👤 Tài khoản</div>', unsafe_allow_html=True)
    _render_account_card(ctx)

    if not is_logged_in:
        _render_auth_actions()
    else:
        _render_logged_in_actions(ctx)

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

    # =========================================================
    # 2. CÔNG CỦ QUẢN TRỊ (chỉ admin / manager)
    # =========================================================
    if is_logged_in and ctx.role in ("admin", "manager"):
        st.markdown('<div class="sb-section">', unsafe_allow_html=True)
        _render_admin_tools(ctx)
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

    # =========================================================
    # 3. CHẾ ĐỘ HIỂN THỊ (dark/light)
    # =========================================================
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown('<div class="sb-section-title">🎨 Giao diện</div>', unsafe_allow_html=True)
    _render_theme_toggle()
    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown('<hr class="sb-divider">', unsafe_allow_html=True)

    # =========================================================
    # 4. CHAT BOX
    # =========================================================
    st.markdown('<div class="sb-section">', unsafe_allow_html=True)
    st.markdown('<div class="sb-section-title">💬 Trợ lý AI</div>', unsafe_allow_html=True)
    render_chat_section(ctx)
    st.markdown('</div>', unsafe_allow_html=True)

    # =========================================================
    # 5. Nút thu gọn / mở (Streamlit button)
    # =========================================================
    _render_collapse_toggle(is_collapsed)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    st.caption("Phiên bản: **v2.0.1** · Hệ Thống Hồ Sơ & AI Agent")

    st.markdown("</div>", unsafe_allow_html=True)
