# ui/journal_admin_ui.py
# Trang Quản lý Danh mục Chất lượng Bài báo (Admin)
# Lưu trên Supabase bảng app_data dưới key "journal_quality_catalog"

import streamlit as st
import pandas as pd

from journal_service import (
    load_journal_catalog,
    save_journal_catalog,
    list_journals,
    upsert_journal_catalog,
    delete_journal,
    read_uploaded_file,
    INDEX_TYPES,
    QUARTILES,
    DOCUMENT_TYPES,
)
from storage import write_system_log


def render_journal_admin_page(ctx) -> None:
    """Trang Quản lý Danh mục Chất lượng Bài báo (chỉ Admin)."""
    st.title("📚 Quản lý Danh mục Chất lượng Bài báo")
    st.caption(
        "Quản lý kho danh mục tạp chí/chất lượng theo chuẩn Scopus/ISI/Trong nước. "
        "Dữ liệu lưu trên Supabase (key `journal_quality_catalog`)."
    )

    tab_upload, tab_list = st.tabs(["📥 Nhập danh mục (Upload)", "📋 Danh mục đã lưu"])

    with tab_upload:
        _render_upload_tab(ctx)
    with tab_list:
        _render_list_tab(ctx)


def _render_upload_tab(ctx) -> None:
    st.subheader("1. Tải lên file danh mục (.csv, .xlsx hoặc .docx)")
    st.info(
        "Hỗ trợ file xuất từ ScimagoJR, Scopus, hoặc văn bản danh mục (.docx có bảng). "
        "Các cột cần có: Tên tạp chí, ISSN/ISBN, DOI, Loại chỉ số (ISI/SCIE/Scopus/Trong nước), "
        "Q1-Q4, Năm."
    )

    uploaded = st.file_uploader(
        "Chọn file",
        type=["csv", "xlsx", "xls", "docx"],
        key="journal_uploader",
    )

    if uploaded:
        try:
            df = read_uploaded_file(uploaded)
            st.success(f"✅ Đã đọc {len(df)} dòng từ file `{uploaded.name}`.")
        except Exception as e:
            st.error(f"❌ Lỗi đọc file: {e}")
            return

        # Hiển thị preview + cho phép chỉnh sửa trước khi lưu
        st.subheader("2. Xem trước & Chỉnh sửa trước khi lưu")
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            width='stretch',
            key="journal_preview_editor",
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 Lưu vào kho danh mục", type="primary", key="btn_save_journal"):
                entries = edited.to_dict("records")
                add_cnt, upd_cnt = upsert_journal_catalog(entries)
                if add_cnt or upd_cnt:
                    write_system_log(
                        ctx.username,
                        f"Upsert danh mục tạp chí từ file {uploaded.name}",
                        f"+{add_cnt} mới, ~{upd_cnt} cập nhật",
                    )
                    st.success(
                        f"✅ Đã lưu: {add_cnt} mục mới, {upd_cnt} mục cập nhật (theo DOI/ISSN/Tên tạp chí)."
                    )
                    st.session_state.pop("journal_preview_editor", None)
                    st.rerun()
                else:
                    st.error("Không lưu được dữ liệu. Vui lòng thử lại.")
        with c2:
            if st.button("🔄 Tải lại file khác", key="btn_reload_journal"):
                st.session_state.pop("journal_preview_editor", None)
                st.rerun()


def _render_list_tab(ctx) -> None:
    st.subheader("3. Danh mục chất lượng đã lưu")
    rows = list_journals()
    if not rows:
        st.info("Chưa có mục nào trong kho danh mục.")
        return

    df = pd.DataFrame(rows)
    # Sắp xếp cột hiển thị
    show_cols = ["_id", "journal_name", "issn", "isbn", "doi", "index_type", "quartile", "year"]
    for c in show_cols:
        if c not in df.columns:
            df[c] = ""
    df = df[show_cols]

    st.data_editor(
        df,
        width='stretch',
        key="journal_list_editor",
        hide_index=True,
    )

    st.markdown("---")
    st.subheader("4. Xóa mục")
    del_id = st.text_input("Nhập `_id` (mã mục) cần xóa:", key="journal_del_id")
    if st.button("🗑️ Xóa mục này", key="btn_del_journal"):
        if not del_id.strip():
            st.warning("Vui lòng nhập `_id` cần xóa.")
        elif delete_journal(del_id.strip()):
            write_system_log(ctx.username, f"Xóa mục danh mục {del_id}", "OK")
            st.success(f"✅ Đã xóa mục `{del_id}`.")
            st.rerun()
        else:
            st.error("Không tìm thấy mục cần xóa.")
