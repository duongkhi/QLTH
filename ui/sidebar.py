# ui/sidebar.py
import streamlit as st
from config import UserContext


def render_sidebar(ctx: UserContext):
    with st.sidebar:
        st.markdown("## 🎓 Hệ Thống Hồ Sơ")

        # =========================================================
        # 1. TÀI KHOẢN (SIGN IN / SIGN OUT)
        # =========================================================
        if not st.session_state.logged_in:
            st.info("👀 Chế độ: **Khách (Public)**")
            if st.button("🔐 Sign In (Đăng nhập)", type="primary", width='stretch'):
                st.session_state.show_login_panel = not st.session_state.show_login_panel
                st.rerun()

            if st.session_state.show_login_panel:
                with st.container(border=True):
                    from ui.auth_ui import render_auth_screen
                    render_auth_screen()
            st.caption("💡 Mẹo: Bạn có thể hỏi Trợ lý AI bên phải để tìm và mở trang hồ sơ của bất kỳ thành viên nào.")
        else:
            role_badges = {
                "admin": "🛡️ Admin",
                "manager": "💼 Manager",
                "user": "👤 User Cá nhân",
            }
            st.success(f"**{ctx.username}** · {role_badges.get(ctx.role, ctx.role)}")

            # Nút về trang cá nhân của chính mình
            if ctx.own_profile:
                is_viewing_self = (
                    st.session_state.view_mode == "public_profile"
                    and st.session_state.viewing_profile == ctx.own_profile
                )
                if st.button(
                    "🏠 Trang cá nhân của tôi",
                    width='stretch',
                    type="primary" if is_viewing_self else "secondary",
                ):
                    st.session_state.viewing_profile = ctx.own_profile
                    st.session_state.view_mode = "public_profile"
                    st.rerun()

            c1, c2 = st.columns(2)
            with c1:
                if st.button(
                    "⚙️ Setting",
                    width='stretch',
                    type="primary" if st.session_state.view_mode == "settings" else "secondary",
                ):
                    st.session_state.view_mode = "settings"
                    st.rerun()
            with c2:
                if st.button("🚪 Sign Out", width='stretch'):
                    st.session_state.logged_in = False
                    st.session_state.username = ""
                    st.session_state["_prev_logged_user"] = ""
                    st.session_state.view_mode = "public_profile"
                    st.session_state.show_login_panel = False
                    st.rerun()

        # =========================================================
        # 2. ĐIỀU HƯỚNG NGHIỆP VỤ & QUẢN TRỊ (KHI ĐÃ SIGN IN)
        # =========================================================
        if st.session_state.logged_in:
            allowed_tools = ctx.record.get("allowed_tools", [])
            has_workspace = (ctx.role == "admin") or len(allowed_tools) > 0

            if has_workspace or ctx.role == "admin":
                st.markdown("---")
                st.markdown("### 🧭 Điều Hướng")

            if has_workspace:
                if st.button(
                    "💼 Nghiệp vụ (Tools)",
                    width='stretch',
                    type="primary" if st.session_state.view_mode == "workspace" else "secondary",
                ):
                    st.session_state.view_mode = "workspace"
                    st.rerun()

            if ctx.role == "admin":
                if st.button(
                    "🛡️ Quản lý User",
                    width='stretch',
                    type="primary" if st.session_state.view_mode == "user_admin" else "secondary",
                ):
                    st.session_state.view_mode = "user_admin"
                    st.rerun()

            # Nút truy cập trang Kỹ năng (Skill): tạo mới + quản trị (admin)
            st.markdown("---")
            if st.button(
                "🛠️ Kỹ năng (Skill)",
                width='stretch',
                type="primary" if st.session_state.view_mode == "skill" else "secondary",
            ):
                st.session_state.view_mode = "skill"
                st.rerun()

            if ctx.role == "admin":
                st.markdown("---")
                if st.button(
                    "📚 Quản lý Data",
                    width='stretch',
                    type="primary" if st.session_state.view_mode == "journal_admin" else "secondary",
                ):
                    st.session_state.view_mode = "journal_admin"
                    st.rerun()

    st.markdown("---")
    st.caption("Phiên bản: **v2.0.1** · Hệ Thống Hồ Sơ & AI Agent")