import streamlit as st

from user_service import (
    load_auth_config,  create_user,
    validate_username, compute_allowed_profiles,
)
from security import verify_password           
from name_mapping import sync_name_mapping
from storage import write_system_log


def render_auth_screen():
    st.title("🔒 Đăng Nhập Hệ Thống")
    st.write("Vui lòng xác thực tài khoản để làm việc.")
    auth_config = load_auth_config()

    c1, c2 = st.columns(2)
    with c1:
        if st.button(
            "🔑 Đăng nhập", use_container_width=True,
            type="primary" if st.session_state.auth_mode == "login" else "secondary",
            key="sw_login",
        ):
            st.session_state.auth_mode = "login"
            st.rerun()
    with c2:
        if st.button(
            "📝 Đăng ký", use_container_width=True,
            type="primary" if st.session_state.auth_mode == "register" else "secondary",
            key="sw_register",
        ):
            st.session_state.auth_mode = "register"
            st.rerun()

    st.markdown("---")

    if st.session_state.auth_mode == "login":
        _render_login(auth_config)
    else:
        _render_register()


def _render_login(auth_config):
    default_u = st.session_state.get("last_username", "")
    with st.form("login_form"):
        u = st.text_input("Tên đăng nhập", value=default_u, key="login_u")
        p = st.text_input("Mật khẩu", type="password", key="login_p")
        if st.form_submit_button("Đăng nhập", use_container_width=True):
            rec = auth_config["users"].get(u)
            if rec and verify_password(p, rec["password_hash"]):
                st.session_state.update({
                    "logged_in": True, "username": u,
                    "last_username": u, "chat_history": [],
                    "auth_mode": "login", "active_module": "admin",
                })
                sync_name_mapping(compute_allowed_profiles(rec))
                write_system_log(u, "Đăng nhập", "OK")
                st.rerun()
            else:
                st.session_state.last_username = u
                write_system_log(u or "Ẩn danh", "Login failed", "Thất bại")
                st.error("Sai tài khoản hoặc mật khẩu!")


def _render_register():
    st.subheader("📝 Đăng ký tài khoản")
    with st.form("register_form"):
        nu = st.text_input("Tên đăng nhập", key="reg_u",
                           placeholder="3-30 ký tự, chữ/số/gạch dưới")
        npw = st.text_input("Mật khẩu", type="password", key="reg_p",
                            placeholder="≥6 ký tự")
        npw2 = st.text_input("Nhập lại mật khẩu", type="password", key="reg_p2")
        if st.form_submit_button("Đăng ký", use_container_width=True):
            ok_u, msg_u = validate_username(nu)
            if not ok_u:
                st.error(msg_u)
                return
            if not npw or len(npw) < 6:
                st.error("Mật khẩu ≥6 ký tự.")
                return
            if npw != npw2:
                st.error("Mật khẩu nhập lại không khớp.")
                return
            ok, msg = create_user(nu, npw)
            if ok:
                st.session_state.update({
                    "logged_in": True, "username": nu,
                    "last_username": nu, "chat_history": [],
                    "auth_mode": "login", "active_module": "admin",
                    "pending_toast": f"🎉 Chào mừng {nu}!",
                })
                write_system_log(nu, "Đăng ký", "OK")
                st.rerun()
            else:
                st.error(msg)