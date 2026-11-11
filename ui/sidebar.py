import re
import streamlit as st

from config import UserContext
from storage import write_system_log
from user_service import (
    load_auth_config, update_user_password, validate_username,
    admin_create_user, admin_update_user,
    admin_reset_password, admin_delete_user,
)
from storage import load_name_mapping, save_name_mapping
from name_mapping import sync_name_mapping


def render_sidebar(ctx: UserContext):
    role_display = {
        "admin": "👑 Quản trị",
        "manager": "📋 Quản lý tổng hợp",
        "user": "👤 Người dùng",
    }.get(ctx.role, "👤 Người dùng")

    profile_display = ctx.own_profile if ctx.own_profile else "(chưa có)"

    with st.sidebar:
        st.markdown(f"""
        <div style="padding:16px;
                    background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
                    border-radius:12px;color:white;margin-bottom:16px;">
            <div style="font-size:1.4rem;font-weight:bold;">👤 {ctx.username}</div>
            <div style="font-size:1rem;margin-top:6px;opacity:.95;">{role_display}</div>
            <div style="font-size:.9rem;margin-top:4px;opacity:.85;">Profile: {profile_display}</div>
        </div>
        """, unsafe_allow_html=True)

        # ---------- Module switcher ----------
        if ctx.is_power:
            st.markdown("**🧭 Phân hệ làm việc**")
            module_choice = st.radio(
                "Chọn phân hệ:",
                ["admin", "finance"],
                format_func=lambda x: (
                    "📄 1. Quản lý Hành chính" if x == "admin"
                    else "💰 2. Quản lý Tài chính"),
                index=0 if st.session_state.active_module == "admin" else 1,
                label_visibility="collapsed",
                key="module_switcher",
            )
            if module_choice != st.session_state.active_module:
                st.session_state.active_module = module_choice
                st.rerun()
            st.markdown("---")

        # ---------- Manage users ----------
        if ctx.role == "admin":
            _render_manage_users(ctx)
            st.markdown("---")

        # ---------- Change password ----------
        _render_change_password(ctx)

        # ---------- Name mapping ----------
        _render_name_mapping(ctx)

        st.markdown("---")
        if st.button("🚪 Đăng xuất", use_container_width=True, key="btn_logout"):
            write_system_log(ctx.username, "Đăng xuất", "OK")
            for k in ("logged_in", "username", "chat_history",
                      "show_change_pw", "show_manage_users",
                      "upload_stage", "upload_extracted",
                      "upload_detected_name", "upload_detected_dob"):
                if k in st.session_state:
                    if k == "logged_in":
                        st.session_state[k] = False
                    elif k == "chat_history":
                        st.session_state[k] = []
                    else:
                        st.session_state[k] = ""
            st.rerun()


def _render_manage_users(ctx: UserContext):
    if st.button(
        "👥 Quản lý user" if not st.session_state.show_manage_users
        else "✖️ Đóng quản lý user",
        use_container_width=True, key="btn_toggle_manage", type="primary",
    ):
        st.session_state.show_manage_users = not st.session_state.show_manage_users
        st.rerun()

    if not st.session_state.show_manage_users:
        return

    cfg_now = load_auth_config()
    users_now = cfg_now["users"]

    with st.expander("➕ Thêm user mới", expanded=False):
        with st.form("admin_add_user", clear_on_submit=True):
            nu = st.text_input("Tên đăng nhập", key="add_u",
                               placeholder="3-30 ký tự, chữ/số/gạch dưới")
            npw = st.text_input("Mật khẩu", type="password", key="add_p",
                                placeholder="≥6 ký tự")
            npw2 = st.text_input("Nhập lại mật khẩu", type="password", key="add_p2")
            role_choice = st.selectbox(
                "Role", ["user", "manager", "admin"],
                format_func=lambda x: {
                    "user": "👤 Người dùng",
                    "manager": "📋 Quản lý tổng hợp",
                    "admin": "👑 Quản trị",
                }[x],
                key="add_role",
            )
            if st.form_submit_button("Tạo user", use_container_width=True):
                ok_u, msg_u = validate_username(nu)
                if not ok_u:
                    st.error(msg_u)
                elif not npw or len(npw) < 6:
                    st.error("Mật khẩu ≥6 ký tự.")
                elif npw != npw2:
                    st.error("Mật khẩu nhập lại không khớp.")
                else:
                    ok, msg = admin_create_user(nu, npw, role_choice)
                    if ok:
                        write_system_log(ctx.username,
                                         f"Tạo user '{nu}'", "OK")
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else:
                        st.error(msg)

    st.markdown("**📋 Danh sách user:**")
    for uname, urec in sorted(users_now.items()):
        _render_user_row(ctx, uname, urec)


def _render_user_row(ctx: UserContext, uname, urec):
    is_self = uname == ctx.username
    cur_role = urec.get("role", "user")
    icon = {"admin": "👑", "manager": "📋", "user": "👤"}.get(cur_role, "👤")
    label = f"{icon} {uname}" + (" _(bạn)_" if is_self else "")

    with st.expander(label, expanded=False):
        prof = urec.get("own_profile") or "(chưa gán)"
        st.caption(f"Role: `{cur_role}` | Profile: `{prof}`")

        with st.form(f"edit_{uname}"):
            new_role = st.selectbox(
                "Role", ["user", "manager", "admin"],
                index=["user", "manager", "admin"].index(cur_role),
                format_func=lambda x: {
                    "user": "👤 Người dùng",
                    "manager": "📋 Quản lý tổng hợp",
                    "admin": "👑 Quản trị",
                }[x],
                key=f"r_{uname}", disabled=is_self,
            )
            new_own = st.text_input(
                "Profile riêng", value=urec.get("own_profile") or "",
                key=f"o_{uname}", disabled=is_self,
                help=("Chỉ dùng cho manager/admin. "
                      "Role 'user' luôn dùng username làm profile."),
            )
            if st.form_submit_button("💾 Lưu", use_container_width=True):
                if is_self and new_role != cur_role:
                    st.error("Không thể tự đổi role.")
                else:
                    eff_role = cur_role if is_self else new_role
                    eff_own = uname if eff_role == "user" else new_own.strip()
                    if eff_own and not re.match(r"^[a-zA-Z0-9_]+$", eff_own):
                        st.error("Profile chỉ chứa chữ, số, gạch dưới.")
                    else:
                        ok, msg = admin_update_user(uname, eff_role, eff_own)
                        if ok:
                            write_system_log(
                                ctx.username, f"Sửa user '{uname}'", "OK")
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with st.form(f"reset_{uname}"):
            new_pw = st.text_input("Mật khẩu mới", type="password",
                                   key=f"np_{uname}")
            if st.form_submit_button("🔑 Reset mật khẩu",
                                     use_container_width=True):
                if not new_pw or len(new_pw) < 6:
                    st.error("Mật khẩu ≥6 ký tự.")
                else:
                    ok, msg = admin_reset_password(uname, new_pw)
                    if ok:
                        write_system_log(ctx.username,
                                         f"Reset pass '{uname}'", "OK")
                        st.success(msg)
                    else:
                        st.error(msg)

        if not is_self:
            if st.button("🗑️ Xóa user", key=f"d_{uname}",
                         use_container_width=True):
                ok, msg = admin_delete_user(uname, ctx.username)
                if ok:
                    write_system_log(ctx.username,
                                     f"Xóa user '{uname}'", "OK")
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.caption("_(không thể xóa chính mình)_")


def _render_change_password(ctx: UserContext):
    if st.button(
        "🔑 Đổi mật khẩu" if not st.session_state.show_change_pw
        else "✖️ Hủy đổi mật khẩu",
        use_container_width=True, key="btn_toggle_pw",
    ):
        st.session_state.show_change_pw = not st.session_state.show_change_pw
        st.rerun()

    if st.session_state.show_change_pw:
        with st.form("change_pw_form"):
            new_pw = st.text_input("Mật khẩu mới", type="password", key="cp_new")
            confirm = st.text_input("Nhập lại mật khẩu mới",
                                    type="password", key="cp_conf")
            if st.form_submit_button("Xác nhận", use_container_width=True):
                if not new_pw or not confirm:
                    st.error("Điền đầy đủ cả 2 ô.")
                elif new_pw != confirm:
                    st.error("Mật khẩu nhập lại không khớp.")
                elif len(new_pw) < 6:
                    st.error("Mật khẩu ≥6 ký tự.")
                else:
                    if update_user_password(ctx.username, new_pw):
                        write_system_log(ctx.username, "Đổi mật khẩu", "OK")
                        st.session_state.pw_change_success = True
                        st.session_state.show_change_pw = False
                        st.rerun()
                    else:
                        st.error("Không tìm thấy user.")

    if st.session_state.get("pw_change_success"):
        st.success("✅ Đã đổi mật khẩu!")
        st.session_state.pw_change_success = False


def _render_name_mapping(ctx: UserContext):
    with st.expander("🗂️ Ánh xạ tên → hồ sơ"):
        mp = load_name_mapping()
        vis = {k: v for k, v in mp.items() if k in ctx.allowed_profiles}
        if vis:
            for k, v in sorted(vis.items()):
                st.markdown(f"**`{k}`** — {v.get('display_name', '(chưa có)')}")
                if v.get("aliases"):
                    st.caption(f"Alias: {', '.join(v['aliases'])}")
        else:
            st.info("Chưa có ánh xạ.")

        if ctx.role == "admin":
            st.markdown("**Thêm/sửa alias:**")
            with st.form("alias_form", clear_on_submit=True):
                tk = st.selectbox("Hồ sơ", ctx.allowed_profiles, key="al_tgt")
                dn = st.text_input(
                    "Display name",
                    value=mp.get(tk, {}).get("display_name", ""),
                    key="al_dn",
                )
                na = st.text_input("Alias mới", key="al_new",
                                   placeholder="vd: 'Vũ Dương', 'anh Dương'")
                if st.form_submit_button("Lưu", use_container_width=True):
                    mp.setdefault(tk, {"display_name": "", "aliases": []})
                    if dn:
                        mp[tk]["display_name"] = dn.strip()
                    if na and na.strip() not in mp[tk]["aliases"]:
                        mp[tk]["aliases"].append(na.strip())
                    save_name_mapping(mp)
                    st.success(f"✅ Đã lưu cho `{tk}`.")
                    st.rerun()