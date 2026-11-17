import streamlit as st
from config import UserContext
from chat_agent import chat_with_ai, load_chat_history, save_chat_history
from storage import write_system_log

def render_chat_caption(msg):
    if not msg.get("used_data"):
        st.caption("💬 Chat thường")
        return
    s, p = msg.get("tool_status"), msg.get("profile_used")
    if s == "ok": st.caption(f"📊 Đã tra cứu **{p}**")
    elif s == "no_data": st.caption(f"📭 Hồ sơ **{p}** chưa có dữ liệu")
    elif s == "not_found": st.caption(f"🚫 Không tìm thấy **{p}**")
    elif s == "list": st.caption("📋 Đã liệt kê hồ sơ")
    elif s == "search": st.caption("🔍 Đã tìm kiếm dữ liệu")
    elif s == "knowledge": st.caption("📚 Đã tra cứu tri thức nội bộ")
    elif s in ("data", "transaction"): st.caption("📊 Đã truy xuất dữ liệu tài chính")
    else: st.caption("💬 Chat thường")

def render_chat_section(ctx: UserContext):
    st.markdown("---")
    st.subheader("💬 Trợ lý AI Hợp nhất")
    st.caption(f"*(Trợ lý đang hoạt động ở chế độ: **{ctx.role.upper()}**)*")

    # Tải lịch sử chat từ Supabase (chỉ tải 1 lần khi mở app)
    cache_key = f"chat_hist_{ctx.username}"
    if cache_key not in st.session_state:
        with st.spinner("Đang tải lịch sử chat..."):
            st.session_state[cache_key] = load_chat_history(ctx.username)

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🗑️ Xóa lịch sử", key="btn_clear_chat", use_container_width=True):
            st.session_state[cache_key] = []
            save_chat_history(ctx.username, [])
            st.rerun()

    # Render khung chat
    chat_container = st.container(height=500) 
    with chat_container:
        for msg in st.session_state[cache_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg["role"] == "assistant":
                    render_chat_caption(msg)

    # Ô nhập chat
    user_q = st.chat_input("Nhập câu hỏi...", key="main_chat_input")
    if not user_q:
        return

    # Xử lý khi user gửi tin nhắn
    hist = list(st.session_state[cache_key])
    st.session_state[cache_key].append({"role": "user", "content": user_q})

    with st.spinner("Đang suy nghĩ..."):
        try:
            answer, used, p_used, status = chat_with_ai(
                user_q=user_q,
                allowed_profiles=ctx.allowed_profiles,
                username=ctx.username,
                user_record=ctx.record,
                chat_history=hist,
            )
        except Exception as e:
            answer = f"❌ Lỗi: {e}"
            used, p_used, status = False, None, None
            write_system_log(ctx.username, "Chat", f"Lỗi ({e})")

    # Cập nhật UI và lưu vào Database
    new_msg = {
        "role": "assistant", "content": answer,
        "used_data": used, "profile_used": p_used, "tool_status": status
    }
    st.session_state[cache_key].append(new_msg)
    
    # Lưu lịch sử lên Supabase (chỉ lưu, không cần chờ)
    save_chat_history(ctx.username, st.session_state[cache_key])
    
    st.rerun()