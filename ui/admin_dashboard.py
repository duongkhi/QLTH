# ui/admin_dashboard.py
# Bảng điều khiển cho Admin khi vừa đăng nhập: hiển thị 4 tác vụ chính.
import streamlit as st
from config import UserContext


def render_admin_dashboard(ctx: UserContext):
    """Trang tổng quan quản trị: hiện 4 nút tác vụ, bấm vào mới vào trang chi tiết."""
    st.title("🛡️ Bảng điều khiển Quản trị")
    st.caption("Chào quản trị viên. Hãy chọn một tác vụ bên dưới để thực hiện.")

    tasks = [
        {
            "key": "user_admin",
            "icon": "👥",
            "title": "Quản trị người dùng",
            "desc": "Tạo tài khoản, phân quyền, đổi mật khẩu, xóa tài khoản.",
        },
        {
            "key": "data_management",
            "icon": "🗄️",
            "title": "Quản lý dữ liệu",
            "desc": "Xem và quản lý hồ sơ, tài chính, đề tài trong hệ thống.",
        },
        {
            "key": "notification",
            "icon": "📢",
            "title": "Gửi thông báo",
            "desc": "Gửi thông báo đến toàn bộ, nhóm hoặc cá nhân.",
        },
        {
            "key": "skill_admin",
            "icon": "⚙️",
            "title": "Quản trị kỹ năng (Skill)",
            "desc": "Duyệt mã, xóa, cấp quyền dùng skill cho người khác.",
        },
    ]

    cols = st.columns(2)
    for i, task in enumerate(tasks):
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f"### {task['icon']} {task['title']}")
                st.caption(task["desc"])
                if st.button(
                    f"Vào {task['title']}",
                    key=f"goto_{task['key']}",
                    width='stretch',
                    type="primary",
                ):
                    st.session_state.view_mode = task["key"]
                    st.rerun()
