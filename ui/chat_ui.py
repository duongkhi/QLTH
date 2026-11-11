import streamlit as st

from config import UserContext
from chat_agent import chat_with_ai
from storage import write_system_log


def render_chat_caption(msg):
    if not msg.get("used_data"):
        st.caption("💬 Chat thường")
        return
    s, p = msg.get("tool_status"), msg.get("profile_used")
    if s == "ok":
        st.caption(f"📊 Đã tra cứu **{p}**")
    elif s == "no_data":
        st.caption(f"📭 Hồ sơ **{p}** chưa có dữ liệu")
    elif s == "not_found":
        st.caption(f"🚫 Không tìm thấy **{p}**")
    elif s == "ambiguous":
        st.caption(f"⚠️ Nhiều hồ sơ khớp: **{p}**")
    elif s == "list":
        st.caption("📋 Đã liệt kê hồ sơ")
    elif s == "search":
        st.caption("🔍 Đã tìm kiếm dữ liệu")
    else:
        st.caption("💬 Chat thường")


def render_chat_section(ctx: UserContext):
    st.subheader("💬 3. Hỏi đáp trực tiếp")
    st.caption("Ví dụ: *'Chào bạn'*, *'Hộ khẩu của tôi'*, "
               "*'Liệt kê người sinh trước 1975'*")

    if st.button("🗑️ Xóa lịch sử chat", key="btn_clear_chat"):
        st.session_state.chat_history = []
        st.rerun()

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_chat_caption(msg)

    user_q = st.chat_input("Nhập câu hỏi...", key="main_chat_input")
    if not user_q:
        return

    hist = list(st.session_state.chat_history)
    with st.chat_message("user"):
        st.markdown(user_q)
    st.session_state.chat_history.append(
        {"role": "user", "content": user_q})

    with st.chat_message("assistant"):
        with st.spinner("Đang suy nghĩ..."):
            try:
                answer, used, p_used, status = chat_with_ai(
                    user_q=user_q,
                    allowed=ctx.allowed_profiles,
                    username=ctx.username,
                    user_record=ctx.record,
                    chat_history=hist,
                )
                st.markdown(answer)
                render_chat_caption({
                    "used_data": used,
                    "profile_used": p_used,
                    "tool_status": status,
                })
            except Exception as e:
                answer = f"❌ Lỗi: {e}"
                used, p_used, status = False, None, None
                st.markdown(answer)
                write_system_log(ctx.username, "Chat", f"Lỗi ({e})")

    st.session_state.chat_history.append({
        "role": "assistant", "content": answer,
        "used_data": used, "profile_used": p_used, "tool_status": status,
    })
    write_system_log(ctx.username, "Chat",
                     f"OK (data={'yes' if used else 'no'}, status={status})")