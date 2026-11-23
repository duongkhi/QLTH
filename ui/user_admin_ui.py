# ui/user_admin_ui.py
import streamlit as st
from config import UserContext, SYSTEM_TOOLS
from user_service import (
    load_auth_config, admin_create_user, admin_update_user,
    admin_reset_password, admin_delete_user, validate_username,
)
from storage import get_all_existing_profiles, load_json_from_db, save_json_to_db, load_user_profile, save_user_profile
from security import hash_password
from profile_service import sync_publications_index


def render_user_admin_page(ctx: UserContext):
    """Quản trị người dùng & phân quyền. Chỉ Admin được truy cập."""
    # =========================================================
    # BẢO MẬT: Chỉ Admin mới được vào trang này
    # =========================================================
    if not st.session_state.get("logged_in", False):
        st.error("🚫 Bạn chưa đăng nhập. Vui lòng đăng nhập để tiếp tục.")
        return
    if ctx.role != "admin":
        st.error("🚫 Chỉ quản trị viên (Admin) mới có quyền truy cập trang Quản trị Người Dùng.")
        return
    if not ctx.username:
        st.error("🚫 Không xác định được tài khoản đang đăng nhập.")
        return

    st.title("🛡️ Quản Trị Người Dùng & Phân Quyền")
    st.caption("Admin mặc định có toàn bộ công cụ; Manager và User được tùy chỉnh thêm/bớt từng công cụ")

    # Giới hạn chiều rộng selectbox gán hồ sơ, không bị extend full cột
    st.markdown(
        """
        <style>
        div[data-testid="stSelectbox"] > div[data-baseweb="select"] {
            max-width: 340px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
            with c4:
                # Chọn hồ sơ bằng box (button) username, không phải rổ chọn
                prof_search_new = st.text_input(
                    "🔍 Tìm hồ sơ",
                    key="new_user_prof_search",
                    label_visibility="collapsed",
                    placeholder="Tìm tên hồ sơ...",
                )
                if prof_search_new:
                    filtered_new = [p for p in all_profiles if prof_search_new.lower() in p.lower()][:5]
                else:
                    filtered_new = all_profiles[:5]

                if filtered_new:
                    n_cols = min(len(filtered_new), 5)
                    cols_new = st.columns(n_cols)
                    for idx, p in enumerate(filtered_new):
                        with cols_new[idx]:
                            if st.button(
                                p,
                                key=f"new_prof_box_{p}",
                                use_container_width=False,
                                help=f"Gán hồ sơ {p}",
                            ):
                                st.session_state["new_user_selected_prof"] = p
                                st.rerun()

                selected_prof_new = st.session_state.get("new_user_selected_prof", "")
                if selected_prof_new:
                    st.caption(f"✅ Đã chọn: {selected_prof_new}")
                else:
                    st.caption("⚪ Chưa chọn hồ sơ (sẽ tự động theo username)")

                # Giá trị ẩn gửi đi khi submit form
                new_p = selected_prof_new if selected_prof_new else None
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
    c_stat, c_search = st.columns([3, 2])
    with c_stat:
        st.subheader(f"📋 Danh sách tài khoản ({len(users)})")
    with c_search:
        search_q = st.text_input(
            "🔍 Tìm tên người dùng",
            value=st.session_state.get("user_admin_search", ""),
            placeholder="Nhập tên hoặc username...",
            key="user_admin_search_input",
            label_visibility="collapsed",
        )
    st.session_state["user_admin_search"] = search_q

    search_lower = (search_q or "").strip().lower()
    filtered_users = {}
    if search_lower:
        for uname, urec in users.items():
            prof_data = load_user_profile(urec.get("own_profile") or uname) or {}
            disp = (
                prof_data.get("ho_va_ten")
                or prof_data.get("ho_ten")
                or prof_data.get("full_name")
                or uname
            )
            if search_lower in uname.lower() or search_lower in disp.lower():
                filtered_users[uname] = urec
    else:
        filtered_users = users

    if not filtered_users:
        st.info("Không tìm thấy tài khoản nào khớp với từ khóa tìm kiếm.")
    else:
        st.caption(f"Tìm thấy {len(filtered_users)} tài khoản")

    for uname, urec in filtered_users.items():
        profile_key = urec.get("own_profile") or uname
        prof_data = load_user_profile(profile_key) or {}

        avatar_b64 = prof_data.get("_avatar_b64")
        display_name = (
            prof_data.get("ho_va_ten")
            or prof_data.get("ho_ten")
            or prof_data.get("full_name")
            or uname
        )

        with st.container(border=True):
            # --- Hàng đầu: avatar + tên link sát nhau ---
            role_icon_map = {"admin": "🛡️", "manager": "💼", "user": "👤"}
            role_color_map = {"admin": "#1f2937", "manager": "#1d4ed8", "user": "#8b5cf6"}
            user_role = urec.get("role", "user")
            default_icon = role_icon_map.get(user_role, "👤")
            default_color = role_color_map.get(user_role, "#8b5cf6")

            c_av, c_name = st.columns([0.9, 4.2], vertical_alignment="center")
            with c_av:
                if avatar_b64:
                    st.markdown(
                        f'<img src="data:image/png;base64,{avatar_b64}" '
                        'style="width:72px;height:72px;border-radius:50%;object-fit:cover;" />',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="width:72px;height:72px;border-radius:50%;'
                        f'background:#f3f4f6;display:flex;align-items:center;justify-content:center;'
                        f'font-size:34px;color:{default_color};">{default_icon}</div>',
                        unsafe_allow_html=True,
                    )
            with c_name:
                if st.button(
                    f"{display_name}",
                    key=f"goto_profile_{uname}",
                    help=f"Xem trang công khai của {display_name}",
                ):
                    st.session_state.viewing_profile = profile_key
                    st.session_state.view_mode = "public_profile"
                    st.rerun()
                st.caption(f"@{uname} · {user_role.upper()}")

            st.markdown("---")

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
            with c2:
                prof_search_edit = st.text_input(
                    "🔍 Tìm hồ sơ",
                    key=f"prof_search_edit_{uname}",
                    label_visibility="collapsed",
                    placeholder="Tìm tên hồ sơ...",
                )
                if prof_search_edit:
                    filtered_edit = [p for p in all_profiles if prof_search_edit.lower() in p.lower()][:5]
                else:
                    filtered_edit = all_profiles[:5]
                # Thêm tùy chọn bỏ gán
                prof_opts_edit = ["(Không gán)"] + filtered_edit

                # Hiển thị các box username (tối đa 5), click vào chọn
                if prof_opts_edit:
                    n_cols = min(len(prof_opts_edit), 5)
                    cols_edit = st.columns(n_cols)
                    for idx, p in enumerate(prof_opts_edit):
                        with cols_edit[idx]:
                            if st.button(
                                p,
                                key=f"edit_prof_box_{uname}_{p}",
                                use_container_width=False,
                                help=f"Gán hồ sơ {p} cho {uname}",
                            ):
                                st.session_state[f"edit_prof_selected_{uname}"] = p
                                st.rerun()

                selected_prof_edit = st.session_state.get(f"edit_prof_selected_{uname}", cur_prof)
                if selected_prof_edit != cur_prof:
                    st.caption(f"✅ Đã chọn: {selected_prof_edit}")
                new_prof = selected_prof_edit

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
                if st.button("💾 Lưu phân quyền", key=f"adm_save_{uname}", type="primary", width='stretch'):
                    prof_to_save = None if new_prof == "(Không gán)" else new_prof
                    tools_to_save = list(SYSTEM_TOOLS.keys()) if is_admin_role else new_tools
                    ok, msg = admin_update_user(uname, new_role, prof_to_save, tools_to_save)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            with b2:
                with st.popover("🔑 Đổi mật khẩu", width='stretch'):
                    rp = st.text_input("Mật khẩu mới:", type="password", key=f"rp_in_{uname}")
                    if st.button("Xác nhận đổi", key=f"rp_btn_{uname}"):
                        if len(rp) >= 4:
                            admin_reset_password(uname, rp)
                            st.success("Đã đổi mật khẩu!")
                        else:
                            st.error("Tối thiểu 4 ký tự.")
            with b3:
                if uname != ctx.username:
                    if st.button("🗑️ Xóa", key=f"adm_del_{uname}", width='stretch'):
                        ok, msg = admin_delete_user(uname, ctx.username)
                        if ok:
                            st.rerun()
                        else:
                            st.error(msg)

            # --- Expander chỉnh sửa thông tin hồ sơ trực tiếp (chỉ Admin) ---
            with st.expander(f"✏️ Chỉnh sửa thông tin hồ sơ của {uname}", expanded=False):
                edit_fields = [
                    ("ho_va_ten", "Họ và tên"),
                    ("chuc_vu", "Chức vụ"),
                    ("don_vi_cong_tac", "Đơn vị công tác"),
                    ("email", "Email"),
                    ("so_dien_thoai", "Số điện thoại"),
                    ("hoc_ham", "Học hàm"),
                    ("hoc_vi", "Học vị"),
                    ("ngay_sinh", "Ngày sinh"),
                ]
                with st.form(f"form_edit_profile_{uname}"):
                    new_values = {}
                    cols = st.columns(2)
                    for idx, (field, label) in enumerate(edit_fields):
                        with cols[idx % 2]:
                            cur_val = prof_data.get(field, "") or ""
                            new_values[field] = st.text_input(
                                label,
                                value=str(cur_val),
                                key=f"edit_{uname}_{field}",
                            )
                    if st.form_submit_button("💾 Lưu thông tin hồ sơ", type="primary", width='stretch'):
                        for field, val in new_values.items():
                            prof_data[field] = val.strip() if val else ""
                        pub = set(prof_data.get("_public_fields", []))
                        for field in new_values:
                            pub.add(field)
                        prof_data["_public_fields"] = list(pub)
                        ok = save_user_profile(profile_key, prof_data)
                        if ok:
                            st.success(f"✅ Đã cập nhật hồ sơ của {uname}!")
                            st.rerun()
                        else:
                            st.error("❌ Không lưu được thông tin hồ sơ.")