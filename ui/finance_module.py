import streamlit as st

from config import UserContext


def render_finance_module(ctx: UserContext):
    st.title("💰 Quản Lý Tài Chính")
    st.caption("Phân hệ quản lý thu chi, ngân sách và báo cáo.")

    st.info("🚧 Phân hệ này đang trong quá trình phát triển.")
    st.write(f"Chào mừng **{ctx.username}** đến với không gian làm việc mới.")

    col1, col2 = st.columns(2)
    with col1:
        st.metric(label="Tổng thu tháng này", value="0 VNĐ", delta="0%")
    with col2:
        st.metric(label="Tổng chi tháng này", value="0 VNĐ", delta="0%")

    st.markdown("---")
    st.subheader("📝 Ghi nhận giao dịch mới")
    with st.form("finance_form"):
        c1, c2 = st.columns(2)
        with c1:
            st.date_input("Ngày giao dịch")
            st.number_input("Số tiền (VNĐ)", min_value=0, step=1000)
        with c2:
            st.selectbox("Loại giao dịch", ["Thu nhập", "Chi phí"])
            st.text_input("Mô tả / Lý do")
        if st.form_submit_button("Lưu giao dịch"):
            st.success("✅ Đã ghi nhận (demo).")