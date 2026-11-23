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
    chat_box = st.container(height=300, border=True)
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

    # TẦNG 3: KHU VỰC ĐÍNH KÈM FILE & NHẬP CÂU HỎI (chỉ hiển thị khi đã đăng nhập)
    if st.session_state.get("logged_in", False):
        with st.expander("📎 Đính kèm file (CV / Excel)", expanded=False):
            uploaded_file = st.file_uploader(
                "Chọn file (.docx, .pdf, .xlsx)",
                type=["docx", "pdf", "xlsx"],
                label_visibility="collapsed",
                key=f"chat_file_uploader_{st.session_state.get('_chat_file_key', 0)}",
            )

        if uploaded_file is not None:
            st.caption(f"📄 File đính kèm: **{uploaded_file.name}**")
    else:
        uploaded_file = None

    # Form chứa cả ô nhập và nút Gửi cùng hàng. Nhấn Enter trong ô nhập cũng
    # gửi form (vì có nút submit trong form). clear_on_submit=True sẽ tự xóa
    # ô nhập sau khi gửi, không cần can thiệp session_state sau khi widget đã
    # được instantiate (tránh lỗi StreamlitWidgetAlreadyInstantiatedError).
    with st.form(key="chat_input_form", clear_on_submit=True, border=False):
        c_txt, c_btn = st.columns([4.5, 1.2], vertical_alignment="center")
        with c_txt:
            user_q = st.text_input(
                "Câu hỏi",
                placeholder="Nhập câu hỏi và bấm Enter...",
                label_visibility="collapsed",
                key="_chat_input_text",
            )
        with c_btn:
            submitted = st.form_submit_button(
                "Gửi", width="stretch", type="primary"
            )

    # ---------- XỬ LÝ KHI NGƯỜI DÙNG GỬI ----------
    if not submitted:
        return

    hist = list(st.session_state[cache_key])
    user_text = (user_q or "").strip()

    file_bytes = None
    filename = None
    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        filename = uploaded_file.name

    # Nếu không có text và không có file thì không gửi (bảo vệ lại)
    if not user_text and not file_bytes:
        return

    # Nội dung hiển thị: gắn text với file thành một request
    display_content = user_text
    if file_bytes:
        display_content = f"{user_text}\n📎 [Đính kèm file: {filename}]" if user_text else f"📎 [Đính kèm file: {filename}]"

    st.session_state[cache_key].append({"role": "user", "content": display_content})

    with chat_box:
        with st.chat_message("user"):
            st.markdown(display_content)

        with st.chat_message("assistant"):
            # --- Hiển thị tiến độ khi đang phân tích ---
            progress_container = st.empty()
            progress_container.markdown(
                "⏳ **Đang phân tích...** Đang gửi yêu cầu lên AI, vui lòng đợi trong giây lát."
            )
            prog_bar = st.progress(0)

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
                progress_container.empty()
                prog_bar.empty()
                answer = f"❌ Lỗi: {e}"
                used, p_used, status = False, None, "error"
                write_system_log(username or "guest", "Chat", f"Lỗi ({e})")

            # Xóa thanh tiến độ sau khi xong
            progress_container.empty()
            prog_bar.empty()

            # --- Stream câu trả lời từ AI ---
            full_answer = ""
            chunk_size = 20
            answer_placeholder = st.empty()
            for idx in range(0, len(answer), chunk_size):
                piece = answer[idx : idx + chunk_size]
                full_answer += piece
                answer_placeholder.markdown(full_answer + "▌")
                time.sleep(0.01)

            linked_final = linkify_profile_names(full_answer)
            answer_placeholder.markdown(linked_final, unsafe_allow_html=True)

            # --- Hiện kết quả đánh giá chi tiết (sinh động) ---
            if file_bytes:
                st.caption(f"📎 File đã xử lý: **{filename}**")

            if used and status == "updated" and p_used:
                st.success(
                    f"✅ Đã cập nhật hồ sơ **{p_used}** từ dữ liệu đính kèm."
                )
            elif used and status == "no_match":
                st.info(
                    "📄 Đã phân tích xong, nhưng không khớp với hồ sơ nào trong hệ thống."
                )
            elif used and status == "no_permission" and p_used:
                st.warning(
                    f"⚠️ Không có quyền ghi vào hồ sơ **{p_used}**."
                )
            elif status == "error":
                st.error("❌ Có lỗi xảy ra khi phân tích.")
            elif msg_status := _build_status_text(used, status, p_used):
                st.caption(msg_status)

    st.session_state[cache_key].append({
        "role": "assistant",
        "content": full_answer,
        "used_data": used,
        "profile_used": p_used,
        "tool_status": status,
    })
    # Nếu AI tìm thấy hồ sơ/CV của một người, tự động chuyển cửa sổ bên phải sang trang cá nhân đó
    if p_used:
        st.session_state.viewing_profile = p_used
        st.session_state.view_mode = "public_profile"

    # Reset trạng thái file sau khi gửi (tăng key để clear file_uploader)
    st.session_state["_chat_file_key"] = st.session_state.get("_chat_file_key", 0) + 1
    # Không gọi st.rerun() rõ ràng: Streamlit sẽ tự rerun sau khi form submit,
    # giúp tránh reload toàn bộ trang nhiều lần và giữ tốc độ phản hồi nhanh.


def render_chat_section(ctx: UserContext):
    """Điểm vào từ main.py: trích xuất thông tin cơ bản rồi giao cho fragment chạy riêng."""
    _render_chat_fragment(
        username=ctx.username,
        role=ctx.role,
        allowed_profiles=ctx.allowed_profiles,
        user_record=ctx.record,
    )
