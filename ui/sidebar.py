# ui/sidebar.py
# Sidebar thu gọn: chỉ có icon quản lý skill, đăng nhập, đăng xuất, avatar.
# Các thao tác nghiệp vụ khác được điều khiển qua chat.
import streamlit as st
from config import UserContext
from skill_manager import (
    get_user_skill_tree,
    add_skill_to_user_tree,
    generate_skill_from_request,
    create_skill,
)


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
    with st.sidebar:
        st.markdown("## 🎓 Hệ Thống Hồ Sơ")
        st.markdown("---")

        # =========================================================
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
                st.rerun()

        st.markdown("---")

        # =========================================================
        # 2. QUẢN LÝ SKILL (chỉ khi đã đăng nhập)
        # =========================================================
        if st.session_state.get("logged_in", False):
            st.markdown("### 🛠️ Kỹ năng (Skill)")

            # Nút tạo skill mới bằng AI
            if st.button("✨ Tạo Skill mới", width='stretch'):
                st.session_state["_show_create_skill"] = True
                st.rerun()

            # Form tạo skill (hiện khi bấm nút trên)
            if st.session_state.get("_show_create_skill", False):
                with st.form("form_create_skill_sidebar", clear_on_submit=True):
                    user_request = st.text_area(
                        "Yêu cầu tạo Skill (tiếng Việt)",
                        placeholder="Ví dụ: Tính tổng lương tháng của toàn bộ nhân sự và xuất bảng tóm tắt.",
                        height=80,
                        key="sidebar_skill_req",
                    )
                    c1, c2 = st.columns(2)
                    with c1:
                        create_submit = st.form_submit_button("🤖 Tạo bằng AI", width='stretch')
                    with c2:
                        cancel_create = st.form_submit_button("❌ Hủy", width='stretch')
                if cancel_create:
                    st.session_state["_show_create_skill"] = False
                    st.rerun()
                if create_submit:
                    if not user_request or not user_request.strip():
                        st.warning("Vui lòng nhập yêu cầu tạo Skill.")
                    else:
                        with st.spinner("🤖 Đang gọi AI sinh Skill..."):
                            result = generate_skill_from_request(user_request.strip())
                        if not result:
                            st.error("Không thể sinh Skill. Vui lòng kiểm tra API key.")
                        else:
                            ok = create_skill(
                                skill_name=result.get("skill_name", "skill_moi_tao"),
                                creator=ctx.username,
                                description=result.get("description", ""),
                                code=result.get("code", ""),
                                allowed_users=[ctx.username],
                            )
                            if ok:
                                add_skill_to_user_tree(ctx.username, result["skill_name"], "Khác")
                                st.success(f"✅ Đã tạo Skill '{result['skill_name']}'!")
                                st.session_state["_show_create_skill"] = False
                                st.rerun()
                            else:
                                st.error("Tên Skill đã tồn tại hoặc không hợp lệ.")

            st.markdown("---")

            # =========================================================
            # 3. CÂY THƯ MỤC SKILL (dropdown nhóm)
            # =========================================================
            skill_tree = get_user_skill_tree(ctx.username)
            if skill_tree:
                st.markdown("#### 📂 Danh sách Skill của bạn")
                for group in skill_tree:
                    folder = group["folder"]
                    skills = group["skills"]
                    with st.expander(f"📁 {folder} ({len(skills)})", expanded=False):
                        for skill in skills:
                            c1, c2 = st.columns([4, 1])
                            with c1:
                                if st.button(
                                    f"⚙️ {skill['name']}",
                                    key=f"run_skill_{ctx.username}_{skill['name']}",
                                    width='stretch',
                                    help=skill["description"],
                                ):
                                    st.session_state["_run_skill_name"] = skill["name"]
                                    st.session_state["_run_skill_description"] = skill["description"]
                                    st.session_state.view_mode = "skill_run"
                                    st.rerun()
                            with c2:
                                if st.button("🗑️", key=f"del_skill_{ctx.username}_{skill['name']}", width='stretch'):
                                    from skill_manager import remove_skill_from_user_tree
                                    remove_skill_from_user_tree(ctx.username, skill["name"])
                                    st.rerun()
            else:
                st.caption("Bạn chưa có Skill nào. Hãy bấm 'Tạo Skill mới' để bắt đầu.")

    st.markdown("---")
    st.caption("Phiên bản: **v2.0.1** · Hệ Thống Hồ Sơ & AI Agent")