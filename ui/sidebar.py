# ui/sidebar.py
import re
import streamlit as st

from config import UserContext
from storage import write_system_log, load_name_mapping, save_name_mapping, load_user_profile
from user_service import (
    load_auth_config, save_auth_config, update_user_password, validate_username,
    admin_create_user, admin_update_user, admin_reset_password, admin_delete_user,
)
from name_mapping import sync_name_mapping
from supabase_adapter import load_json_from_db, save_json_to_db, get_ai_settings, save_ai_settings


def render_sidebar(ctx: UserContext):
    role_display = {
        "admin": "👑 Quản trị",
        "manager": "📋 Quản lý tổng hợp",
        "user": "👤 Người dùng",
    }.get(ctx.role, "👤 Người dùng")

    profile_display = ctx.own_profile if ctx.own_profile else "(chưa có)"

    with st.sidebar:
        # ---------- THẺ THÔNG TIN USER ----------
        st.markdown(f"""
        <div style="padding:16px;
                    background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
                    border-radius:12px;color:white;margin-bottom:16px;">
            <div style="font-size:1.4rem;font-weight:bold;">👤 {ctx.username}</div>
            <div style="font-size:1rem;margin-top:6px;opacity:.95;">{role_display}</div>
            <div style="font-size:.9rem;margin-top:4px;opacity:.85;">Profile: {profile_display}</div>
        </div>
        """, unsafe_allow_html=True)

        # ---------- NÚT TRANG CÁ NHÂN (Ưu tiên) ----------
        if st.button("👤 Trang Cá Nhân", use_container_width=True, type="primary" if st.session_state.get("active_module") == "profile" else "secondary"):
            st.session_state.active_module = "profile"
            st.rerun()

        # ---------- ĐIỀU HƯỚNG PHÂN HỆ (Chỉ Admin/Manager) ----------
        if ctx.is_power:
            st.markdown("---")
            st.markdown("**🧭 Phân hệ làm việc**")
            
            # Danh sách module bao gồm cả profile
            modules = ["profile", "admin", "finance", "knowledge"]
            current_idx = modules.index(st.session_state.active_module) if st.session_state.active_module in modules else 0
            
            module_choice = st.radio(
                "Chọn phân hệ:",
                modules,
                format_func=lambda x: (
                    "👤 0. Trang cá nhân" if x == "profile"
                    else ("📄 1. Quản lý Hành chính" if x == "admin"
                    else ("💰 2. Quản lý Tài chính" if x == "finance" else "📚 3. Quản lý Pháp lý"))
                ),
                index=current_idx,
                label_visibility="collapsed",
                key="module_switcher",
            )
            if module_choice != st.session_state.active_module:
                st.session_state.active_module = module_choice
                st.rerun()

        # ---------- QUẢN LÝ USER & CẤU HÌNH AI (Admin) ----------
        if ctx.role == "admin":
            st.markdown("---")
            _render_manage_users(ctx)
            st.markdown("---")
            _render_ai_config(ctx) 

        # ---------- ÁNH XẠ TÊN ----------
        if ctx.role == "admin":
            st.markdown("---")
            _render_name_mapping(ctx)

        # ---------- ĐĂNG XUẤT ----------
        st.markdown("---")
        if st.button("🚪 Đăng xuất", use_container_width=True, key="btn_logout"):
            write_system_log(ctx.username, "Đăng xuất", "OK")
            # Xóa sạch session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()


# ==========================================
# CÁC HÀM QUẢN LÝ (Giữ nguyên)
# ==========================================
def _render_ai_config(ctx: UserContext):
    with st.expander("⚙️ Cấu hình Bộ não AI (Global)", expanded=False):
        st.caption("Tùy chỉnh System Prompt chung cho toàn hệ thống.")
        current_ai = get_ai_settings()
        
        with st.form("ai_settings_form"):
            new_prompt = st.text_area(
                "System Prompt (Tính cách AI)", 
                value=current_ai.get("chat_system_prompt", ""),
                height=120
            )
            if st.form_submit_button("💾 Lưu Cấu hình AI", use_container_width=True):
                save_ai_settings({"chat_system_prompt": new_prompt})
                st.success("✅ Đã cập nhật bộ não của AI!")
                st.rerun()

    with st.expander("📚 Nhập nhanh Tri thức (Text)", expanded=False):
        st.caption("Chỉ dùng cho các quy định ngắn. Với văn bản PDF dài, hãy dùng module 'Quản lý Pháp lý'.")
        MODULE_OPTIONS = {"admin": "📄 Quản lý Hành chính", "finance": "💰 Quản lý Tài chính"}
        
        module_choice = st.selectbox(
            "Chọn phân hệ:", 
            list(MODULE_OPTIONS.keys()),
            format_func=lambda x: MODULE_OPTIONS[x],
            key="ai_config_module_select"
        )
        
        kb_key = f"{module_choice}_rules"
        current_kb = load_json_from_db(kb_key)
        kb_text = current_kb.get("content", "")
        
        with st.form("kb_settings_form"):
            new_kb = st.text_area(
                "Nội dung tri thức (Knowledge Base)", 
                value=kb_text,
                height=200,
                placeholder="VD: Quy định nghỉ phép: 12 ngày/năm..."
            )
            if st.form_submit_button("💾 Lưu Tri thức", use_container_width=True):
                save_json_to_db(kb_key, {"content": new_kb})
                st.success(f"✅ Đã lưu tri thức cho phân hệ {MODULE_OPTIONS[module_choice]}!")
                st.rerun()


def _render_manage_users(ctx: UserContext):
    if st.button(
        "👥 Quản lý user" if not st.session_state.get("show_manage_users")
        else "✖️ Đóng quản lý user",
        use_container_width=True, key="btn_toggle_manage", type="primary",
    ):
        st.session_state.show_manage_users = not st.session_state.get("show_manage_users", False)
        st.rerun()

    if not st.session_state.get("show_manage_users"):
        return

    cfg_now = load_auth_config()
    users_now = cfg_now["users"]

    with st.expander("➕ Thêm user mới", expanded=False):
        with st.form("admin_add_user", clear_on_submit=True):
            nu = st.text_input("Tên đăng nhập", key="add_u", placeholder="3-30 ký tự")
            npw = st.text_input("Mật khẩu", type="password", key="add_p", placeholder="≥6 ký tự")
            npw2 = st.text_input("Nhập lại mật khẩu", type="password", key="add_p2")
            role_choice = st.selectbox(
                "Role", ["user", "manager", "admin"],
                format_func=lambda x: {"user": "👤 Người dùng", "manager": "📋 Quản lý", "admin": "👑 Quản trị"}[x],
                key="add_role",
            )
            if st.form_submit_button("Tạo user", use_container_width=True):
                ok_u, msg_u = validate_username(nu)
                if not ok_u: st.error(msg_u)
                elif not npw or len(npw) < 6: st.error("Mật khẩu ≥6 ký tự.")
                elif npw != npw2: st.error("Mật khẩu nhập lại không khớp.")
                else:
                    ok, msg = admin_create_user(nu, npw, role_choice)
                    if ok:
                        write_system_log(ctx.username, f"Tạo user '{nu}'", "OK")
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else: st.error(msg)

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
                format_func=lambda x: {"user": "👤 Người dùng", "manager": "📋 Quản lý", "admin": "👑 Quản trị"}[x],
                key=f"r_{uname}", disabled=is_self,
            )
            
            new_perms = []
            if new_role == "manager":
                ALL_PERMS = ["hr", "finance", "project", "legal"]
                cur_perms = urec.get("permissions", ALL_PERMS)
                new_perms = st.multiselect(
                    "Quyền hạn của Manager:",
                    options=ALL_PERMS,
                    default=cur_perms,
                    format_func=lambda x: {
                        "hr": "👤 Nhân sự", "finance": "💰 Tài chính",
                        "project": "📁 Đề tài", "legal": "📚 Pháp lý"
                    }.get(x, x)
                )
                
            new_own = st.text_input(
                "Profile riêng", value=urec.get("own_profile") or "",
                key=f"o_{uname}", disabled=is_self,
                help="Role 'user' luôn dùng username làm profile.",
            )
            if st.form_submit_button("💾 Lưu", use_container_width=True):
                if is_self and new_role != cur_role:
                    st.error("Không thể tự đổi role.")
                else:
                    cfg = load_auth_config()
                    cfg["users"][uname]["permissions"] = new_perms
                    save_auth_config(cfg)
                    
                    eff_role = cur_role if is_self else new_role
                    eff_own = uname if eff_role == "user" else new_own.strip()
                    if eff_own and not re.match(r"^[a-zA-Z0-9_]+$", eff_own):
                        st.error("Profile chỉ chứa chữ, số, gạch dưới.")
                    else:
                        ok, msg = admin_update_user(uname, eff_role, eff_own)
                        if ok:
                            write_system_log(ctx.username, f"Sửa user '{uname}'", "OK")
                            st.success(msg)
                            st.rerun()
                        else: st.error(msg)

        with st.form(f"reset_{uname}"):
            new_pw = st.text_input("Mật khẩu mới", type="password", key=f"np_{uname}")
            if st.form_submit_button("🔑 Reset mật khẩu", use_container_width=True):
                if not new_pw or len(new_pw) < 6: st.error("Mật khẩu ≥6 ký tự.")
                else:
                    ok, msg = admin_reset_password(uname, new_pw)
                    if ok:
                        write_system_log(ctx.username, f"Reset pass '{uname}'", "OK")
                        st.success(msg)
                    else: st.error(msg)

        if not is_self:
            if st.button("🗑️ Xóa user", key=f"d_{uname}", use_container_width=True):
                ok, msg = admin_delete_user(uname, ctx.username)
                if ok:
                    write_system_log(ctx.username, f"Xóa user '{uname}'", "OK")
                    st.success(msg)
                    st.rerun()
                else: st.error(msg)
        else:
            st.caption("_(không thể xóa chính mình)_")


def _render_name_mapping(ctx: UserContext):
    with st.expander("🗂️ Ánh xạ tên → hồ sơ"):
        mp = load_name_mapping()
        vis = {k: v for k, v in mp.items() if k in ctx.allowed_profiles}
        if vis:
            for k, v in sorted(vis.items()):
                st.markdown(f"**`{k}`** — {v.get('display_name', '(chưa có)')}")
                if v.get("aliases"): st.caption(f"Alias: {', '.join(v['aliases'])}")
        else: st.info("Chưa có ánh xạ.")

        if ctx.role == "admin":
            st.markdown("**Thêm/sửa alias:**")
            with st.form("alias_form", clear_on_submit=True):
                tk = st.selectbox("Hồ sơ", ctx.allowed_profiles, key="al_tgt")
                dn = st.text_input("Display name", value=mp.get(tk, {}).get("display_name", ""), key="al_dn")
                na = st.text_input("Alias mới", key="al_new", placeholder="vd: 'Vũ Dương'")
                if st.form_submit_button("Lưu", use_container_width=True):
                    mp.setdefault(tk, {"display_name": "", "aliases": []})
                    if dn: mp[tk]["display_name"] = dn.strip()
                    if na and na.strip() not in mp[tk]["aliases"]: mp[tk]["aliases"].append(na.strip())
                    save_name_mapping(mp)
                    st.success(f"✅ Đã lưu cho `{tk}`.")
                    st.rerun()