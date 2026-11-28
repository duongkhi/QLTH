# ui/user_admin_ui.py
import streamlit as st
from config import UserContext, SYSTEM_TOOLS
from user_service import (
    load_auth_config, admin_create_user, admin_update_user,
    admin_reset_password, admin_delete_user, validate_username,
    lay_ds_key_co_luong, get_username_from_salary_key,
)
from storage import get_all_existing_profiles, load_json_from_db, save_json_to_db, load_user_profile, save_user_profile
from security import hash_password
from profile_service import sync_publications_index


def render_user_admin_page(ctx: UserContext):
    """Quản trị người dùng & phân quyền. Chỉ Admin được truy cập."""
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

    st.markdown(
        """
        <style>
        div[data-testid="stButton"] button[kind="primary"][disabled] {
            background-color: #2563eb !important; border-color: #2563eb !important;
            color: #ffffff !important; opacity: 1 !important;
        }
        div[data-testid="stButton"] button[kind="secondary"] {
            background-color: #f3f4f6 !important; border-color: #d1d5db !important;
            color: #374151 !important; opacity: 1 !important;
        }
        div[data-testid="stButton"] button[kind="secondary"]:hover {
            background-color: #e5e7eb !important; border-color: #9ca3af !important;
        }
        div[data-testid="stSelectbox"] > div[data-baseweb="select"] { max-width: 340px !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    auth_data = load_auth_config()
    users = auth_data.get("users", {})
    all_profiles = sorted(k for k in users.keys() if k != "salary_profiles")
    catalog_display_names = load_json_from_db("catalog_display_names") or {}
    if not isinstance(catalog_display_names, dict):
        catalog_display_names = {}

    def _prof_label(profile_key: str) -> str:
        return catalog_display_names.get(profile_key, profile_key)

    # --- Tạo user mới ---
    with st.expander("➕ Tạo tài khoản mới", expanded=False):
        prof_opts_new = ["(Không gán)"] + all_profiles
        selected_prof_new = st.selectbox(
            "Chọn hồ sơ gán (gõ tên để tìm):", options=prof_opts_new, index=0,
            key="new_user_select_prof",
            format_func=lambda k: "(Không gán)" if k == "(Không gán)" else _prof_label(k),
        )
        if selected_prof_new and selected_prof_new != "(Không gán)":
            st.caption(f"✅ Đã chọn: {selected_prof_new}")
        else:
            st.caption("⚪ Chưa chọn hồ sơ (sẽ tự động theo username)")

        salary_keys = lay_ds_key_co_luong()
        salary_data = load_json_from_db("salary_profiles") or {}
        salary_opts = ["(Không liên kết)"]
        salary_label_map = {}
        for sk in salary_keys:
            sp = salary_data.get(sk, {})
            ten = sp.get("ho_va_ten", sk)
            label = f"{ten} (@{sk})"
            salary_opts.append(label)
            salary_label_map[label] = sk
        selected_salary_label = st.selectbox(
            "Liên kết hồ sơ lương (chọn fullname trong salary_profiles):",
            options=salary_opts, index=0, key="new_user_select_salary",
        )
        selected_salary_link = salary_label_map.get(selected_salary_label) if selected_salary_label != "(Không liên kết)" else None

        st.markdown("---")

        with st.form("form_admin_create_user"):
            c1, c2, c3 = st.columns(3)
            new_u = c1.text_input("Tên đăng nhập *")
            new_pw = c2.text_input("Mật khẩu *", type="password")
            new_r = c3.selectbox("Vai trò:", ["user", "manager", "admin"])
            new_t = c1.multiselect(
                "Cấp quyền Tool (bỏ qua nếu là Admin):",
                options=list(SYSTEM_TOOLS.keys()), format_func=lambda k: SYSTEM_TOOLS[k],
            )
            missing_fields = []
            if not new_u: missing_fields.append("Tên đăng nhập")
            if not new_pw: missing_fields.append("Mật khẩu")
            if len(new_pw) > 0 and len(new_pw) < 4: missing_fields.append("Mật khẩu ≥ 4 ký tự")
            if missing_fields:
                st.markdown('<div style="color:#dc2626;font-weight:bold;font-size:0.9rem;margin-top:4px;">⚠️ Cần điền đầy đủ: ' + ", ".join(missing_fields) + "</div>", unsafe_allow_html=True)
            btn_disabled = bool(missing_fields)
            if st.form_submit_button("✅ Tạo tài khoản", type="primary", disabled=btn_disabled):
                ok, msg = validate_username(new_u)
                if not ok:
                    st.error(msg)
                elif len(new_pw) < 4:
                    st.error("Mật khẩu phải ≥ 4 ký tự.")
                else:
                    prof_val = None if selected_prof_new == "(Không gán)" else selected_prof_new
                    tools_val = list(SYSTEM_TOOLS.keys()) if new_r == "admin" else new_t
                    # salary_profile_id luôn = username
                    ok2, msg2 = admin_create_user(
                        new_u, new_pw, new_r, prof_val, tools_val,
                        salary_profile_id=new_u,
                    )
                    if ok2:
                        st.success(msg2); st.rerun()
                    else:
                        st.error(msg2)
            if st.form_submit_button("❌ Hủy", type="secondary"): st.rerun()

    st.markdown("---")
    c_stat, c_search = st.columns([3, 2])
    with c_stat:
        st.subheader(f"📋 Danh sách tài khoản ({len(users)})")
    with c_search:
        search_q = st.text_input(
            "🔍 Tìm tên người dùng",
            value=st.session_state.get("user_admin_search", ""),
            placeholder="Nhập tên hoặc username...", key="user_admin_search_input",
            label_visibility="collapsed",
        )
    st.session_state["user_admin_search"] = search_q
    search_lower = (search_q or "").strip().lower()
    filtered_users = {}
    if search_lower:
        for uname, urec in users.items():
            if urec.get("role") == "admin": continue
            prof_data = load_user_profile(urec.get("own_profile") or uname) or {}
            disp = prof_data.get("ho_va_ten") or prof_data.get("ho_ten") or prof_data.get("full_name") or uname
            if search_lower in uname.lower() or search_lower in disp.lower():
                filtered_users[uname] = urec
    else:
        filtered_users = {k: v for k, v in users.items() if v.get("role") != "admin"}
    if not filtered_users:
        st.info("Không tìm thấy tài khoản nào khớp với từ khóa tìm kiếm.")
    else:
        st.caption(f"Tìm thấy {len(filtered_users)} tài khoản")

    for uname, urec in filtered_users.items():
        profile_key = urec.get("own_profile") or uname
        prof_data = load_user_profile(profile_key) or {}
        avatar_b64 = prof_data.get("_avatar_b64")
        display_name = prof_data.get("ho_va_ten") or prof_data.get("ho_ten") or prof_data.get("full_name") or uname
        st.markdown('<div class="card">', unsafe_allow_html=True)
        role_icon_map = {"admin": "🛡️", "manager": "💼", "user": "👤"}
        role_color_map = {"admin": "#1f2937", "manager": "#1d4ed8", "user": "#8b5cf6"}
        user_role = urec.get("role", "user")
        default_icon = role_icon_map.get(user_role, "👤")
        default_color = role_color_map.get(user_role, "#8b5cf6")
        c_av, c_name = st.columns([0.9, 4.2], vertical_alignment="center")
        with c_av:
            if avatar_b64:
                st.markdown(f'<img src="data:image/png;base64,{avatar_b64}" style="width:72px;height:72px;border-radius:50%;object-fit:cover;" />', unsafe_allow_html=True)
            else:
                st.markdown(f'<div style="width:72px;height:72px;border-radius:50%;background:#f3f4f6;display:flex;align-items:center;justify-content:center;font-size:34px;color:{default_color};\">{default_icon}</div>', unsafe_allow_html=True)
        with c_name:
            if st.button(f"{display_name}", key=f"goto_profile_{uname}", help=f"Xem trang công khai của {display_name}"):
                st.session_state.viewing_profile = profile_key; st.session_state.view_mode = "public_profile"; st.rerun()
            st.caption(f"@{uname} · {user_role.upper()}")
        st.markdown("---")

        c1, c2, c3 = st.columns([1.4, 3, 3])
        cur_role = urec.get("role", "user")
        roles = ["user", "manager", "admin"]
        new_role = c1.selectbox("Vai trò:", options=roles, index=roles.index(cur_role) if cur_role in roles else 0, key=f"adm_role_{uname}")
        cur_prof = urec.get("own_profile") or ""
        with c2:
            prof_opts_edit = ["(Không gán)"] + all_profiles
            default_index = 0 if not cur_prof or cur_prof not in prof_opts_edit else prof_opts_edit.index(cur_prof)
            selected_prof_edit = st.selectbox("Chọn hồ sơ cá nhân:", options=prof_opts_edit, index=default_index, key=f"edit_prof_select_{uname}", format_func=lambda k: "(Không gán)" if k == "(Không gán)" else _prof_label(k))
            new_prof = selected_prof_edit if selected_prof_edit != "(Không gán)" else ""
            if new_prof: st.caption(f"✅ Đã gán: {new_prof}")
            else: st.caption("⚪ Chưa gán hồ sơ cá nhân")
        with c3:
            # salary_profile_id luon = username
            st.caption(f"🔑 Hồ sơ lương: @{uname}")

        st.markdown("**Quyền quản trị:**")
        is_admin_role = (new_role == "admin")
        cur_tools = list(SYSTEM_TOOLS.keys()) if is_admin_role else [t for t in urec.get("allowed_tools", []) if t in SYSTEM_TOOLS]
        granted = [t for t in cur_tools if t in SYSTEM_TOOLS]
        if granted:
            n_col = 3; rows = (len(granted) + n_col - 1) // n_col
            for r in range(rows):
                cols = st.columns(n_col)
                for c in range(n_col):
                    idx = r * n_col + c
                    if idx >= len(granted): break
                    tool_key = granted[idx]; tool_label = SYSTEM_TOOLS[tool_key]
                    with cols[c]:
                        st.button(tool_label, key=f"view_tool_{uname}_{tool_key}", type="primary", disabled=True, width='stretch', help=tool_label)
        else:
            st.caption("(Chưa có tool nào)")
        st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
        with st.popover("✏️ Sửa quyền", width='stretch'):
            st.markdown(f"**Chỉnh sửa quyền quản trị cho {display_name} (@{uname})**")
            st.caption("Màu xanh = đang cấp quyền · Màu trắng = chưa cấp quyền · Nhấn vào công cụ để Bật/Tắt")
            temp_key = f"temp_tools_{uname}"
            if temp_key not in st.session_state: st.session_state[temp_key] = list(cur_tools)
            tool_items = list(SYSTEM_TOOLS.items())
            n_col = 3; rows = (len(tool_items) + n_col - 1) // n_col
            for r in range(rows):
                cols = st.columns(n_col)
                for c in range(n_col):
                    idx = r * n_col + c
                    if idx >= len(tool_items): break
                    tool_key, tool_label = tool_items[idx]
                    with cols[c]:
                        is_selected = tool_key in st.session_state[temp_key]
                        btn_type = "primary" if is_selected else "secondary"
                        if st.button(tool_label, key=f"tool_toggle_{uname}_{tool_key}", type=btn_type, width='stretch', help=f"Bật/tắt {tool_label}"):
                            if is_selected: st.session_state[temp_key].remove(tool_key)
                            else: st.session_state[temp_key].append(tool_key)
                            st.rerun()

        with st.expander(f"✏️ Chỉnh sửa thông tin hồ sơ của {uname}", expanded=False):
            edit_fields = [
                ("ho_va_ten", "Họ và tên"), ("chuc_vu", "Chức vụ"),
                ("don_vi_cong_tac", "Đơn vị công tác"),
                ("don_vi_cong_tac_con", "Đơn vị con (trung tâm/phòng ban)"),
                ("email", "Email"), ("so_dien_thoai", "Số điện thoại"),
                ("hoc_ham", "Học hàm"), ("hoc_vi", "Học vị"), ("ngay_sinh", "Ngày sinh"),
                ("mat_khau_moi", "Mật khẩu mới"),
            ]
            edit_cols = st.columns(2)
            edit_values = {}
            dvc_options = [
                "Trung tâm Vật lý Hạt nhân", "Trung tâm Vật lý kỹ thuật", "Trung tâm Vật lý lý thuyết",
                "Trung tâm Vật lý tính toán", "Trung tâm Điện tử học lượng tử", "Phòng tự động hóa",
                "Trung tâm Vật lý ứng dụng và Thiết bị khoa học", "Phòng quản lý tổng hợp",
            ]
            for idx, (field, label) in enumerate(edit_fields):
                with edit_cols[idx % 2]:
                    cur_val = prof_data.get(field, "") or ""
                    if field == "don_vi_cong_tac_con":
                        edit_values[field] = st.selectbox(label, options=[""] + dvc_options, index=(dvc_options.index(cur_val) + 1) if cur_val in dvc_options else 0, key=f"edit_{uname}_{field}")
                    elif field == "mat_khau_moi":
                        edit_values[field] = st.text_input(label, type="password", value="", key=f"edit_{uname}_{field}")
                    else:
                        edit_values[field] = st.text_input(label, value=str(cur_val), key=f"edit_{uname}_{field}")

        st.markdown("---")
        save_cols = st.columns([2, 2, 1])
        with save_cols[0]:
            if st.button("💾 Lưu hồ sơ", key=f"adm_save_{uname}", type="primary", width='stretch'):
                tools_to_save = list(SYSTEM_TOOLS.keys()) if is_admin_role else st.session_state.get(f"temp_tools_{uname}", cur_tools)
                prof_to_save = None if new_prof == "(Không gán)" else new_prof
                ok, msg = admin_update_user(uname, new_role, prof_to_save, tools_to_save, None, salary_profile_id=uname)
                if ok:
                    prof_updates = {}
                    for field, val in edit_values.items():
                        if field == "mat_khau_moi":
                            if val: admin_reset_password(uname, val)
                        elif val: prof_updates[field] = val.strip()
                    if prof_updates:
                        for field, val in prof_updates.items(): prof_data[field] = val
                        pub = set(prof_data.get("_public_fields", []))
                        for field in prof_updates: pub.add(field)
                        prof_data["_public_fields"] = list(pub)
                        save_user_profile(profile_key, prof_data)
                        try:
                            from user_service import sync_user_to_salary
                            cfg = load_auth_config(); urec2 = cfg.get("users", {}).get(uname, {})
                            sync_user_to_salary(uname, urec2)
                        except Exception: pass
                    st.success(msg); st.rerun()
                else:
                    st.error(msg)
        with save_cols[2]:
            if st.button("🗑️ Xóa", key=f"adm_del_{uname}", width='stretch'):
                ok, msg = admin_delete_user(uname, ctx.username)
                if ok: st.rerun()
                else: st.error(msg)
        st.markdown('</div>', unsafe_allow_html=True)
