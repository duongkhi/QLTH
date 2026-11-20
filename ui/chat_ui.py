# ui/chat_ui.py
import streamlit as st
from config import UserContext
from chat_agent import chat_with_ai, load_chat_history, save_chat_history
from storage import write_system_log, load_user_profile
from ui.profile_ui import linkify_profile_names


def render_chat_caption(msg, i):
    s, p = msg.get("tool_status"), msg.get("profile_used")

    if p and s in ("ok", "no_data"):
        if st.button(f"👉 Bấm vào đây để xem chi tiết ({p})", key=f"btn_goto_{p}_{i}"):
            st.session_state.viewing_profile = p
            st.session_state.view_mode = "public_profile"
            st.rerun()

    if not msg.get("used_data"):
        st.caption("💬 Chat thường")
        return
    if s == "ok":
        st.caption(f"📊 Đã tra cứu hồ sơ **{p}**")
    elif s == "no_data":
        st.caption(f"📭 Hồ sơ **{p}** chưa có dữ liệu")
    elif s == "not_found":
        st.caption(f"🚫 Không tìm thấy **{p}**")
    elif s == "list":
        st.caption("📋 Đã liệt kê hồ sơ")
    elif s == "search":
        st.caption("🔍 Đã tìm kiếm dữ liệu")
    elif s == "knowledge":
        st.caption("📚 Đã tra cứu tri thức nội bộ")
    elif s in ("data", "transaction"):
        st.caption("📊 Đã truy xuất dữ liệu tài chính / lương")
    else:
        st.caption("💬 Chat thường")


@st.fragment
def _render_chat_fragment(username: str, role: str, allowed_profiles: list, user_record: dict):
    """Khung chat bên phải: chỉ rerun fragment này khi nhắn tin, không load lại toàn bộ trang."""
    c_head, c_clr = st.columns([3.5, 1.5])
    with c_head:
        st.markdown("#### 💬 Trợ lý AI")
        st.caption(f"Chế độ: **{role.upper()}**")
    with c_clr:
        if st.button("🗑️ Xóa", key="btn_clear_chat", width='stretch'):
            cache_key = f"chat_hist_{username or 'guest'}"
            st.session_state[cache_key] = []
            st.session_state.pop("_chat_excel_download", None)
            if username:
                save_chat_history(username, [])
            st.rerun()

    cache_key = f"chat_hist_{username or 'guest'}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = load_chat_history(username) if username else []

    chat_box = st.container(height=450, border=False)
    with chat_box:
        if not st.session_state[cache_key]:
            st.info("Xin chào! Bạn có thể hỏi thông tin về bất kỳ thành viên nào, đề tài hoặc quy chế.")
        for i, msg in enumerate(st.session_state[cache_key]):
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    linked_content = linkify_profile_names(msg["content"])
                    st.markdown(linked_content, unsafe_allow_html=True)
                    render_chat_caption(msg, i)
                else:
                    st.markdown(msg["content"])

        dl_info = st.session_state.get("_chat_excel_download")
        if dl_info:
            st.download_button(
                label=f"📥 Tải {dl_info['filename']}",
                data=dl_info["bytes"],
                file_name=dl_info["filename"],
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width='stretch',
                key="btn_dl_chat_excel",
            )

    with st.form("right_sidebar_chat_form", clear_on_submit=True):
        c_in, c_btn = st.columns([4, 1.3])
        user_q = c_in.text_input(
            "Câu hỏi",
            placeholder="Nhập câu hỏi (VD: Tìm thông tin Vũ Dương)...",
            label_visibility="collapsed",
        )
        submitted = c_btn.form_submit_button("Gửi", type="primary", width='stretch')

    if not submitted or not user_q.strip():
        return

    hist = list(st.session_state[cache_key])
    st.session_state[cache_key].append({"role": "user", "content": user_q.strip()})

    with st.spinner("Đang trả lời..."):
        try:
            answer, used, p_used, status = chat_with_ai(
                user_q=user_q.strip(),
                allowed_profiles=allowed_profiles,
                username=username,
                user_record=user_record,
                chat_history=hist,
                viewing_profile=st.session_state.get("viewing_profile"),
            )
        except Exception as e:
            answer = f"❌ Lỗi: {e}"
            used, p_used, status = False, None, None
            write_system_log(username or "guest", "Chat", f"Lỗi ({e})")

    new_msg = {
        "role": "assistant",
        "content": answer,
        "used_data": used,
        "profile_used": p_used,
        "tool_status": status,
    }
    st.session_state[cache_key].append(new_msg)
    if username:
        save_chat_history(username, st.session_state[cache_key])

    st.rerun()


def render_chat_section(ctx: UserContext):
    """Điểm vào từ main.py: trích xuất thông tin cơ bản rồi giao cho fragment chạy riêng."""
    _render_chat_fragment(
        username=ctx.username,
        role=ctx.role,
        allowed_profiles=ctx.allowed_profiles,
        user_record=ctx.record,
    )