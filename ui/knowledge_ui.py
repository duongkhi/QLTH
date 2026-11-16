import os
import time
import streamlit as st
from knowledge_service import extract_chunk_from_pdf
from supabase_adapter import list_keys_with_prefix, load_json_from_db, delete_key_from_db, save_json_to_db

# Cấu hình giới hạn token
BUDGET_TOKEN = 1_000_000 
MAX_TOKEN_PER_RUN = BUDGET_TOKEN * 0.5  # 50%

def render_knowledge_ui(ctx):
    st.title("📚 Quản lý Tri thức Hệ thống")
    st.caption("Upload tài liệu PDF (Thông tư, Quy chế) để AI trích xuất quy định lưu vào Database.")

    # ==========================================
    # PHẦN 1: FORM UPLOAD
    # ==========================================
    st.subheader("Xử lý văn bản mới")
    st.info(f"💡 Hệ thống sẽ tự động xử lý ngầm. Sẽ tạm nghỉ 60s nếu dùng quá **{MAX_TOKEN_PER_RUN:,.0f}** token.")
    
    uploaded_files = st.file_uploader(
        "Tải lên các file PDF", 
        type=["pdf"], 
        accept_multiple_files=True,
        key="kb_uploads"
    )
    
    db_target = st.selectbox(
        "Lưu vào phân hệ nào?",
        ["finance_rules", "admin_rules", "other_rules"],
        format_func=lambda x: "Tài chính" if x=="finance_rules" else ("Hành chính" if x=="admin_rules" else "Khác"),
        key="kb_target_select"
    )

    if uploaded_files and st.button("🚀 Bắt đầu Phân tích", type="primary"):
        temp_dir = "./temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Lưu file ra đĩa tạm
        file_paths = []
        for f in uploaded_files:
            path = os.path.join(temp_dir, f.name)
            with open(path, "wb") as buffer:
                buffer.write(f.getbuffer())
            file_paths.append(path)

        # Gọi hàm xử lý tuần tự (sẽ block UI cho đến khi xong)
        _process_files_automatically(file_paths, db_target)
        st.rerun()

    st.markdown("---")

    # ==========================================
    # PHẦN 2: HIỂN THỊ DANH SÁCH ĐÃ CÓ
    # ==========================================
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
                if st.button(f"🗑️ Xóa văn bản này", key=f"del_{k}"):
                    delete_key_from_db(k)
                    st.rerun()

# ==========================================
# HÀM CHẠY VÒNG LẶP BLOCKING TỰ ĐỘNG
# ==========================================
def _process_files_automatically(file_paths, db_target):
    total_tokens_this_run = 0
    
    for path in file_paths:
        fname = os.path.basename(path)
        st.info(f"📄 Bắt đầu xử lý: **{fname}**")
        
        start_page = 0
        all_rules = []
        total_pages = 0
        
        file_progress = st.progress(0, text="Đang khởi tạo...")
        status_text = st.empty()
        
        while True:
            # Kiểm tra và tự động nghỉ nếu chạm ngưỡng
            if total_tokens_this_run >= MAX_TOKEN_PER_RUN:
                status_text.warning(f"⏸️ Đã dùng {total_tokens_this_run:,} tokens. Tạm nghỉ 60s để reset rate limit...")
                time.sleep(60)  # Chờ 60 giây
                total_tokens_this_run = 0 # Reset bộ đếm cho chu kỳ mới
                status_text.success("▶️ Tiếp tục chạy...")
                time.sleep(1)

            # Gọi API cho cụm 3 trang
            tokens, pages_done, rules, t_pages, msg = extract_chunk_from_pdf(
                path, start_page=start_page, max_pages_per_run=3
            )
            
            if msg not in ["OK", "Trang rỗng (bỏ qua)."]:
                st.error(f"Lỗi xử lý file {fname}: {msg}")
                break # Bỏ qua file này
                
            total_pages = t_pages
            total_tokens_this_run += tokens
            all_rules.extend(rules)
            start_page += pages_done
            
            # Cập nhật giao diện
            if total_pages > 0:
                pct = min(1.0, start_page / total_pages)
                file_progress.progress(pct, text=f"Đang xử lý... ({start_page}/{total_pages} trang, {total_tokens_this_run:,} tokens)")
            
            if start_page >= total_pages:
                file_progress.progress(1.0, text="✅ Đã trích xuất xong file này.")
                break
                
        # Lưu kết quả vào Supabase (sau khi xong toàn bộ file)
        if all_rules:
            safe_name = "".join([c if c.isalnum() else "_" for c in fname.replace(".pdf", "")]).lower()
            db_key = f"kb_{db_target.split('_')[0]}_{safe_name}"
            final_data = {"document_name": fname, "rules": all_rules}
            save_json_to_db(db_key, final_data)
            st.success(f"✅ Đã lưu {len(all_rules)} quy định từ {fname} vào Database.")
        else:
            st.warning(f"⚠️ Không tìm thấy quy định nào trong {fname}.")
            
        # Dọn dẹp file
        if os.path.exists(path):
            os.remove(path)
        
        st.markdown("---")
        
    st.success("🎉 Đã hoàn tất toàn bộ quá trình xử lý!")