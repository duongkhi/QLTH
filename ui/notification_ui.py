# ui/notification_ui.py
# Trang Gửi thông báo (khung cơ bản, có thể bổ sung logic gửi thực tế sau).
import streamlit as st
from config import UserContext


def render_notification_page(ctx: UserContext):
    """Gửi thông báo đến người dùng trong hệ thống."""
    st.title("📢 Gửi thông báo")
    st.caption("Gửi thông báo đến người dùng trong hệ thống.")

    target = st.selectbox(
        "Chọn đối tượng nhận:",
        ["Toàn bộ nhân viên", "Theo nhóm", "Cá nhân"],
    )

    if target == "Theo nhóm":
        st.text_input("Nhập tên nhóm:", key="notif_group")
    elif target == "Cá nhân":
        st.text_input("Nhập tên đăng nhập người nhận:", key="notif_person")

    message = st.text_area("Nội dung thông báo:", height=180)

    if st.button("📨 Gửi thông báo", type="primary", width='stretch'):
        if not message.strip():
            st.error("Vui lòng nhập nội dung thông báo.")
        else:
            st.success("✅ Đã gửi thông báo (chức năng đang phát triển).")
