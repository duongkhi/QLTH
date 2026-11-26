import os
import time
import streamlit as st
import pymupdf
from knowledge_service import extract_chunk_from_pdf
from supabase_adapter import list_keys_with_prefix, load_json_from_db, delete_key_from_db, save_json_to_db

BUDGET_TOKEN = 1_000_000
MAX_TOKEN_PER_RUN = BUDGET_TOKEN * 0.5  # 50%


def _has_any_text(pdf_bytes: bytes, sample_pages: int = 3) -> bool:
    """Kiểm tra PDF có BẤT KỲ text nào không (kể cả text ẩn/invisible)."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        total = min(len(doc), sample_pages)
        if total == 0:
            doc.close()
            return False

        # Cách 1: Đọc text thường
        normal_chars = sum(len(doc[i].get_text("text").strip()) for i in range(total))
        if normal_chars > 50:
            doc.close()
            return True

        # Cách 2: Fallback đọc rawdict (bắt text ẩn)
        raw_chars = 0
        for i in range(total):
            rawdict = doc[i].get_text("rawdict")
            for block in rawdict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        raw_chars += len(span.get("text", "").strip())
        doc.close()
        return raw_chars > 50
    except Exception:
        return False


def _render_ocr_guide_if_needed(uploaded_files):
    """Chỉ cảnh báo khi file thực sự không có text layer (ảnh scan thuần)."""
    if not uploaded_files:
        return

    scanned_files = []
    for f in uploaded_files:
        try:
            if not _has_any_text(f.getvalue()):
                scanned_files.append(f.name)
        except Exception:
            pass

    if not scanned_files:
        return

    st.warning(
        f"⚠️ **{len(scanned_files)} file không có lớp text nào** "
        f"(ảnh scan thuần, AI sẽ đọc rất chậm — có thể mất 5-10 phút/trang): "
        f"`{'`, `'.join(scanned_files)}`"
    )

    st.markdown(
        """
        ### 📄 Chuyển PDF scan → PDF có text (miễn phí, 2-3 phút)
        1. Nhấn nút bên dưới mở công cụ OCR.
        2. Upload file PDF.
        3. Chọn ngôn ngữ **Vietnamese**.
        4. Nhấn **OCR** → tải file kết quả về.
        5. Upload lại file mới (AI xử lý trong ~30 giây).
        """
    )

    c1, c2 = st.columns(2)
    with c1:
        st.link_button(
            "🌐 iLovePDF OCR (file lớn OK)",
            "https://www.ilovepdf.com/ocr-pdf",
            width='stretch',
            type="primary",
        )
    with c2:
        st.link_button(
            "📂 Google Drive (miễn phí, <2MB)",
            "https://drive.google.com",
            width='stretch',
        )

    st.caption(
        "💡 **Gợi ý:** Google Drive miễn phí và không giới hạn, nhưng chỉ nhận file **< 2MB**. "
        "File lớn → dùng iLovePDF."
    )


def render_knowledge_ui(ctx):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.title("📚 Quản lý Tri thức Hệ thống")
    st.caption("Upload tài liệu PDF (Thông tư, Quy chế) để AI trích xuất quy định lưu vào Database.")

    if "kb_queue" not in st.session_state:
        st.session_state.kb_queue = []
    if "kb_tokens_used" not in st.session_state:
        st.session_state.kb_tokens_used = 0
    if "kb_target_key" not in st.session_state:
        st.session_state.kb_target_key = "finance_rules"

    # PHẦN 1: HIỂN THỊ HÀNG ĐỢI (NẾU CÓ)
    if st.session_state.kb_queue:
        st.warning(
            f"⏸️ **Đang tạm dừng:** Còn **{len(st.session_state.kb_queue)} file** chưa xử lý "
            f"do đã chạm giới hạn {MAX_TOKEN_PER_RUN:,.0f} token của phiên này."
        )
        st.info(f"Đã sử dụng: **{st.session_state.kb_tokens_used:,}** token.")

        if st.button("▶️ Tiếp tục xử lý các file còn lại", type="primary", width='stretch'):
            _process_queue(st.session_state.kb_target_key)
            st.rerun()

        if st.button("🗑️ Hủy bỏ hàng đợi", width='stretch'):
            st.session_state.kb_queue = []
            st.session_state.kb_tokens_used = 0
            st.rerun()
        st.markdown("---")

    # PHẦN 2: FORM UPLOAD
    if not st.session_state.kb_queue:
        st.subheader("Xử lý văn bản mới")
        st.info(f"💡 Giới hạn an toàn: Chỉ sử dụng tối đa **{MAX_TOKEN_PER_RUN:,.0f}** token (50% budget) cho mỗi phiên.")

        uploaded_files = st.file_uploader(
            "Tải lên các file PDF",
            type=["pdf"],
            accept_multiple_files=True,
            key="kb_uploads",
        )

        # Gọi hàm kiểm tra & hiển thị hướng dẫn OCR
        _render_ocr_guide_if_needed(uploaded_files)

        db_target = st.selectbox(
            "Lưu vào phân hệ nào?",
            ["finance_rules", "admin_rules", "other_rules"],
            format_func=lambda x: "Tài chính" if x == "finance_rules" else ("Hành chính" if x == "admin_rules" else "Khác"),
            key="kb_target_select",
        )

        if uploaded_files and st.button("🚀 Bắt đầu Phân tích AI", type="primary"):
            temp_dir = "./temp_uploads"
            os.makedirs(temp_dir, exist_ok=True)

            new_paths = []
            for f in uploaded_files:
                path = os.path.join(temp_dir, f.name)
                with open(path, "wb") as buffer:
                    buffer.write(f.getbuffer())
                new_paths.append(path)

            st.session_state.kb_queue = new_paths
            st.session_state.kb_target_key = db_target
            st.session_state.kb_tokens_used = 0

            _process_queue(db_target)
            st.rerun()

    st.markdown("---")

    # PHẦN 3: DANH SÁCH TRI THỨC ĐÃ CÓ
    st.subheader("Các văn bản đã lưu trên Supabase")
    kb_keys = [k for k in list_keys_with_prefix("kb_")]

    if not kb_keys:
        st.info("Chưa có văn bản nào được xử lý.")
    else:
        for k in kb_keys:
            data = load_json_from_db(k)
            name = data.get("document_name", k)
            n_rules = len(data.get("rules", []))
            with st.expander(f"📄 {name} — {n_rules} quy định"):
                st.json(data.get("rules", [])[:3])
                st.caption("...")
                if st.button(f"🗑️ Xóa văn bản này", key=f"del_{k}"):
                    delete_key_from_db(k)
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


def _process_queue(db_target):
    queue = st.session_state.kb_queue
    if not queue:
        return

    overall_progress = st.progress(0, text="Đang chuẩn bị...")
    file_status = st.empty()
    log_area = st.container()

    current_idx = 0

    while queue and st.session_state.kb_tokens_used < MAX_TOKEN_PER_RUN:
        path = queue[0]
        current_idx += 1
        fname = os.path.basename(path)

        file_status.info(f"📄 Đang xử lý: **{fname}**")

        safe_name = "".join([c if c.isalnum() else "_" for c in fname.replace(".pdf", "")]).lower()
        db_key = f"kb_{db_target.split('_')[0]}_{safe_name}"

        file_progress = st.progress(0)
        status_txt = st.empty()

        start_page = 0
        all_rules = []
        total_pages = 0

        while True:
            if st.session_state.kb_tokens_used >= MAX_TOKEN_PER_RUN:
                status_txt.warning(f"⏸️ Đã dùng {st.session_state.kb_tokens_used:,} tokens. Tạm nghỉ 60s...")
                time.sleep(60)
                st.session_state.kb_tokens_used = 0
                status_txt.success("▶️ Tiếp tục...")
                time.sleep(1)

            tokens_used, pages_done, rules, total_pages, msg = extract_chunk_from_pdf(
                path, start_page=start_page, max_pages_per_run=10
            )

            if msg not in ["OK", "Trang rỗng (bỏ qua)."]:
                st.error(f"Lỗi xử lý file {fname}: {msg}")
                break

            st.session_state.kb_tokens_used += tokens_used
            all_rules.extend(rules)
            start_page += pages_done

            if total_pages > 0:
                pct = min(1.0, start_page / total_pages)
                file_progress.progress(pct, text=f"Đang xử lý... ({start_page}/{total_pages} trang)")

            if start_page >= total_pages:
                file_progress.progress(1.0, text="✅ Đã trích xuất xong file này.")
                break

        if all_rules:
            final_data = {"document_name": fname, "rules": all_rules}
            save_json_to_db(db_key, final_data)
            log_area.success(f"✅ Đã lưu {len(all_rules)} quy định từ {fname} vào Database.")
        else:
            log_area.warning(f"⚠️ Không tìm thấy quy định nào trong {fname}.")

        if os.path.exists(path):
            os.remove(path)

        queue.pop(0)
        overall_progress.progress(min(1.0, st.session_state.kb_tokens_used / MAX_TOKEN_PER_RUN),
                                  text=f"Đã dùng {st.session_state.kb_tokens_used:,} / {MAX_TOKEN_PER_RUN:,.0f} tokens")

    st.session_state.kb_queue = queue

    if not queue:
        log_area.success(f"🎉 Đã xử lý xong toàn bộ! Tổng token sử dụng: {st.session_state.kb_tokens_used:,}")
        st.session_state.kb_tokens_used = 0
    else:
        log_area.warning(
            f"⏸️ Đã đạt giới hạn 50% token. Còn lại {len(queue)} file chưa xử lý. "
            f"Vui lòng bấm 'Tiếp tục' ở trên."
        )
