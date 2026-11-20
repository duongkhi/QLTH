# ui/chat_ui.py
import streamlit as st
import time
from config import UserContext
from chat_agent import chat_with_ai
from storage import write_system_log
from ui.profile_ui import linkify_profile_names


def _build_status_text(used: bool, status: str | None, p_used: str | None) -> str | None:
    """Xây dựng văn bản trạng thái (chỉ hiện khi có dữ liệu thực sự)."""
    if not used or not status:
        return None
    if status == "ok" and p_used:
        return f"📊 Đã tra cứu hồ sơ **{p_used}**"
    if status == "no_data" and p_used:
        return f"📭 Hồ sơ **{p_used}** chưa có dữ liệu"
    if status == "not_found" and p_used:
        return f"🚫 Không tìm thấy **{p_used}**"
    if status == "list":
        return "📋 Đã liệt kê hồ sơ"
    if status == "search":
        return "🔍 Đã tìm kiếm dữ liệu"
    if status == "knowledge":
        return "📚 Đã tra cứu tri thức nội bộ"
    if status in ("data", "transaction"):
        return "📊 Đã truy xuất dữ liệu tài chính / lương"
    if status == "updated" and p_used:
        return f"✅ Đã cập nhật hồ sơ từ file **{p_used}**"
    if status == "no_permission" and p_used:
        return f"⚠️ Không có quyền ghi hồ sơ **{p_used}**"
    if status == "no_match":
        return "⚠️ File không khớp với hồ sơ nào trong hệ thống"
    if status == "admin_cmd":
        return "🛡️ Lệnh quản trị đã thực thi"
    if status == "error":
        return "❌ Có lỗi xảy ra"
    return None


@st.fragment
def _render_chat_fragment(username: str, role: str, allowed_profiles: list, user_record: dict):
    """Khung chat bên phải: bố cục 3 tầng tách biệt, không đè chữ."""
    # TẦNG 1: TIÊU ĐỀ & NÚT XÓA
    c_head, c_clr = st.columns([3, 1.4], vertical_alignment="center")
    with c_head:
        st.markdown("#### 💬 Trợ lý AI")
        st.caption(f"Chế độ: **{role.upper()}**")
    with c_clr:
        if st.button("🗑️ Xóa", key="btn_clear_chat", width="stretch"):
            cache_key = f"chat_hist_{username or 'guest'}"
            st.session_state[cache_key] = []
            st.session_state.pop("_chat_excel_download", None)
            st.rerun()

    cache_key = f"chat_hist_{username or 'guest'}"
    if cache_key not in st.session_state:
        st.session_state[cache_key] = []

    # TẦNG 2: KHUNG HIỂN THỊ TIN NHẮN (chiều cao vừa phải để không bị thanh nhập đè)
    chat_box = st.container(height=360, border=True)
    with chat_box:
        if not st.session_state[cache_key]:
            st.info("Xin chào! Bạn có thể hỏi thông tin về bất kỳ thành viên nào, đề tài hoặc quy chế.")
        for i, msg in enumerate(st.session_state[cache_key]):
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant":
                    linked_content = linkify_profile_names(msg["content"])
                    st.markdown(linked_content, unsafe_allow_html=True)
                    status_txt = _build_status_text(msg.get("used_data"), msg.get("tool_status"), msg.get("profile_used"))
                    if status_txt:
                        st.caption(status_txt)
                        if msg.get("tool_status") == "ok" and msg.get("profile_used"):
                            if st.button(f"👉 Xem chi tiết ({msg['profile_used']})", key=f"btn_goto_{msg['profile_used']}_{i}"):
                                st.session_state.viewing_profile = msg["profile_used"]
                                st.session_state.view_mode = "public_profile"
                                st.rerun()
                else:
                    st.markdown(msg["content"])

        dl_info = st.session_state.get("_chat_excel_download")
        if dl_info:
            st.download_button(
                label=f"📥 Tải {dl_info['filename']}",
                data=dl_info["bytes"],
                file_name=dl_info["filename"],
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key="btn_dl_chat_excel",
            )

    # TẦNG 3: KHU VỰC ĐÍNH KÈM FILE & NHẬP CÂU HỎI (tách khối độc lập phía dưới)
    with st.expander("📎 Đính kèm file (CV / Excel)", expanded=False):
        uploaded_file = st.file_uploader(
            "Chọn file (.docx, .pdf, .xlsx)",
            type=["docx", "pdf", "xlsx"],
            label_visibility="collapsed",
            key="chat_file_uploader",
        )

    if uploaded_file is not None:
        st.caption(f"📄 File đính kèm: **{uploaded_file.name}**")

    # Dùng st.form thay cho st.chat_input để không bao giờ bị ghim đè lên nội dung phía trên
    with st.form(key="chat_input_form", clear_on_submit=True, border=False):
        c_txt, c_btn = st.columns([4.5, 1.2], vertical_alignment="center")
        with c_txt:
            user_q = st.text_input(
                "Câu hỏi",
                placeholder="Nhập câu hỏi và bấm Enter...",
                label_visibility="collapsed",
            )
        with c_btn:
            submitted = st.form_submit_button("Gửi", width="stretch", type="primary")

    # ---------- XỬ LÝ KHI NGƯỜI DÙNG GỬI ----------
    if not submitted or not user_q or not user_q.strip():
        return

    hist = list(st.session_state[cache_key])
    user_text = user_q.strip()

    file_bytes = None
    filename = None
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

    st.session_state[cache_key].append({"role": "user", "content": user_text})

    with chat_box:
        with st.chat_message("user"):
            st.markdown(user_text)

        with st.chat_message("assistant"):
            status_placeholder = st.empty()
            status_placeholder.markdown("⏳ Đang xử lý...")

            try:
                answer, used, p_used, status = chat_with_ai(
                    user_q=user_text,
                    allowed_profiles=allowed_profiles,
                    username=username,
                    user_record=user_record,
                    chat_history=hist,
                    viewing_profile=st.session_state.get("viewing_profile"),
                    file_bytes=file_bytes,
                    filename=filename,
                )
            except Exception as e:
                answer = f"❌ Lỗi: {e}"
                used, p_used, status = False, None, "error"
                write_system_log(username or "guest", "Chat", f"Lỗi ({e})")

            full_answer = ""
            chunk_size = 20
            for idx in range(0, len(answer), chunk_size):
                piece = answer[idx : idx + chunk_size]
                full_answer += piece
                status_placeholder.markdown(full_answer + "▌")
                time.sleep(0.01)

            linked_final = linkify_profile_names(full_answer)
            status_placeholder.markdown(linked_final, unsafe_allow_html=True)

            if msg_status := _build_status_text(used, status, p_used):
                st.caption(msg_status)

    st.session_state[cache_key].append({
        "role": "assistant",
        "content": full_answer,
        "used_data": used,
        "profile_used": p_used,
        "tool_status": status,
    })
    st.rerun()


def render_chat_section(ctx: UserContext):
    """Điểm vào từ main.py: trích xuất thông tin cơ bản rồi giao cho fragment chạy riêng."""
    _render_chat_fragment(
        username=ctx.username,
        role=ctx.role,
        allowed_profiles=ctx.allowed_profiles,
        user_record=ctx.record,
    )
