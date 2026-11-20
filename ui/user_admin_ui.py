# ui/user_admin_ui.py
import streamlit as st
from config import UserContext, SYSTEM_TOOLS
from user_service import (
    load_auth_config, admin_create_user, admin_update_user,
    admin_reset_password, admin_delete_user, validate_username,
)
from storage import get_all_existing_profiles


def render_user_admin_page(ctx: UserContext):
    st.title("🛡️ Quản Trị Người Dùng & Phân Quyền")
    st.caption("Admin mặc định có toàn bộ công cụ; Manager và User được tùy chỉnh thêm/bớt từng công cụ")

    auth_data = load_auth_config()
    users = auth_data.get("users", {})
    all_profiles = get_all_existing_profiles()

    # --- Tạo user mới ---
    with st.expander("➕ Tạo tài khoản mới", expanded=False):
        with st.form("form_admin_create_user"):
            c1, c2, c3 = st.columns(3)
            new_u = c1.text_input("Tên đăng nhập *")
            new_pw = c2.text_input("Mật khẩu *", type="password")
            new_r = c3.selectbox("Vai trò:", ["user", "manager", "admin"])
            c4, c5 = st.columns(2)
            new_p = c4.selectbox("Gán hồ sơ cá nhân:", ["(Tự động theo username)"] + all_profiles)
            new_t = c5.multiselect(
                "Cấp quyền Tool (bỏ qua nếu là Admin):",
                options=list(SYSTEM_TOOLS.keys()),
                format_func=lambda k: SYSTEM_TOOLS[k],
            )
            if st.form_submit_button("✅ Tạo tài khoản", type="primary"):
                ok, msg = validate_username(new_u)
                if not ok:
                    st.error(msg)
                elif len(new_pw) < 4:
                    st.error("Mật khẩu phải ≥ 4 ký tự.")
                else:
                    prof_val = None if new_p == "(Tự động theo username)" else new_p
                    tools_val = list(SYSTEM_TOOLS.keys()) if new_r == "admin" else new_t
                    ok2, msg2 = admin_create_user(new_u, new_pw, new_r, prof_val, tools_val)
                    if ok2:
                        st.success(msg2)
                        st.rerun()
                    else:
                        st.error(msg2)

    st.markdown("---")
    st.subheader(f"📋 Danh sách tài khoản ({len(users)})")

    for uname, urec in users.items():
        with st.container(border=True):
            st.markdown(f"#### 👤 `{uname}`")
            c1, c2, c3 = st.columns([1.4, 1.8, 3])

            cur_role = urec.get("role", "user")
            roles = ["user", "manager", "admin"]
            new_role = c1.selectbox(
                "Vai trò:",
                options=roles,
                index=roles.index(cur_role) if cur_role in roles else 0,
                key=f"adm_role_{uname}",
            )

            cur_prof = urec.get("own_profile") or ""
            prof_opts = ["(Không gán)"] + all_profiles
            new_prof = c2.selectbox(
                "Hồ sơ gắn kết:",
                options=prof_opts,
                index=prof_opts.index(cur_prof) if cur_prof in prof_opts else 0,
                key=f"adm_prof_{uname}",
            )

            # Nếu chọn role == 'admin' -> mặc định active hết và khóa chỉnh sửa
            # Nếu là 'manager' hoặc 'user' -> mở khóa để add/remove tự do
            is_admin_role = (new_role == "admin")
            cur_tools = list(SYSTEM_TOOLS.keys()) if is_admin_role else [
                t for t in urec.get("allowed_tools", []) if t in SYSTEM_TOOLS
            ]

            new_tools = c3.multiselect(
                "Tool nghiệp vụ được cấp:",
                options=list(SYSTEM_TOOLS.keys()),
                default=cur_tools,
                format_func=lambda k: SYSTEM_TOOLS[k],
                key=f"adm_tools_{uname}_{new_role}",
                disabled=is_admin_role,
                help="Admin mặc định kích hoạt toàn bộ công cụ. Manager và User có thể thêm/bớt tùy ý.",
            )

            b1, b2, b3 = st.columns([2, 2, 1])
            with b1:
                if st.button("💾 Lưu phân quyền", key=f"adm_save_{uname}", type="primary", use_container_width=True):
                    prof_to_save = None if new_prof == "(Không gán)" else new_prof
                    tools_to_save = list(SYSTEM_TOOLS.keys()) if is_admin_role else new_tools
                    ok, msg = admin_update_user(uname, new_role, prof_to_save, tools_to_save)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            with b2:
                with st.popover("🔑 Đổi mật khẩu", use_container_width=True):
                    rp = st.text_input("Mật khẩu mới:", type="password", key=f"rp_in_{uname}")
                    if st.button("Xác nhận đổi", key=f"rp_btn_{uname}"):
                        if len(rp) >= 4:
                            admin_reset_password(uname, rp)
                            st.success("Đã đổi mật khẩu!")
                        else:
                            st.error("Tối thiểu 4 ký tự.")
            with b3:
                if uname != ctx.username:
                    if st.button("🗑️ Xóa", key=f"adm_del_{uname}", use_container_width=True):
                        ok, msg = admin_delete_user(uname, ctx.username)
                        if ok:
                            st.rerun()
                        else:
                            st.error(msg)