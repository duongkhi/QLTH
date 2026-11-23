# ui/journal_admin_ui.py
# Trang Quản lý sản phẩm khoa học (Admin)
# Lưu trên Supabase bảng app_data dưới các key tương ứng.

import streamlit as st
import pandas as pd

from journal_service import (
    load_journal_catalog,
    save_journal_catalog,
    list_journals,
    upsert_journal_catalog,
    delete_journal,
    read_uploaded_file,
    reclassify_existing_catalog,
    INDEX_TYPES,
    QUARTILES,
    DOCUMENT_TYPES,
)
from storage import write_system_log
from supabase_adapter import list_all_keys, load_json_from_db, save_json_to_db


def render_journal_admin_page(ctx) -> None:
    """Trang Quản lý sản phẩm khoa học (chỉ Admin)."""
    st.title("🎓 Quản lý sản phẩm khoa học")
    st.caption(
        "Quản lý các sản phẩm khoa học: công bố, văn bằng, sách, giải thưởng. "
        "Dữ liệu lưu trên Supabase."
    )

    tab_pub, tab_degree, tab_book, tab_award = st.tabs([
        "📄 Công bố khoa học",
        "🎓 Văn bằng SHTT",
        "📚 Sách và giáo trình",
        "🏆 Các giải thưởng khác",
    ])

    with tab_pub:
        _render_publication_tab(ctx)
    with tab_degree:
        _render_degree_tab(ctx)
    with tab_book:
        _render_book_tab(ctx)
    with tab_award:
        _render_award_tab(ctx)


def _render_publication_tab(ctx) -> None:
    """Tab Công bố khoa học: thống kê bài báo + quản lý danh mục chất lượng."""
    # ========================================================
    # MỤC 1: THỐNG KÊ BÀI BÁO (có bảng, tìm kiếm thông minh)
    # ========================================================
    st.subheader("1. Thống kê bài báo khoa học")

    index = load_json_from_db("publications_index") or {}

    # Nếu publications_index trống, đọc bài báo từ tất cả hồ sơ có trường bai_bao_cong_bo
    if not index:
        from storage import get_all_existing_profiles, load_user_profile
        all_profiles = get_all_existing_profiles()
        fallback_rows = []
        for pk in all_profiles:
            prof = load_user_profile(pk) or {}
            pubs = prof.get("bai_bao_cong_bo", [])
            if not isinstance(pubs, list):
                continue
            for p in pubs:
                if not isinstance(p, dict):
                    continue
                fallback_rows.append({
                    "Mã": f"{pk}|{p.get('ten_cong_trinh','')}|{p.get('nam_cong_bo','')}",
                    "Tên bài báo": p.get("ten_cong_trinh", ""),
                    "Tác giả": p.get("tac_gia", "") or "",
                    "Tạp chí": p.get("noi_cong_bo", ""),
                    "Năm": p.get("nam_cong_bo", ""),
                    "Loại chỉ số": p.get("phan_loai", ""),
                    "Chất lượng": p.get("phan_loai", ""),
                    "DOI": p.get("doi", ""),
                    "ISSN": p.get("issn", ""),
                })
        if fallback_rows:
            index = {r["Mã"]: r for r in fallback_rows}

    if not index:
        st.info("Chưa có bài báo nào trong hệ thống.")
    else:
        rows = []
        for pub_key, pub in index.items():
            if not isinstance(pub, dict):
                continue
            rows.append({
                "Mã": pub_key,
                "Tên bài báo": pub.get("title", ""),
                "Tác giả": pub.get("authors", ""),
                "Tạp chí": pub.get("source_title", ""),
                "Năm": pub.get("year", ""),
                "Loại chỉ số": pub.get("index_type", ""),
                "Chất lượng": pub.get("quartile", ""),
                "DOI": pub.get("doi", ""),
                "ISSN": pub.get("issn", ""),
            })

        df = pd.DataFrame(rows)

        # Tìm kiếm thông minh trong tất cả các trường
        search_q = st.text_input(
            "🔍 Tìm kiếm bài báo (tên, tác giả, tạp chí, chất lượng, DOI, ISSN...)",
            key="pub_search",
            placeholder="Nhập từ khóa tìm kiếm...",
        )
        if search_q:
            sq = search_q.strip().lower()
            mask = (
                df["Tên bài báo"].astype(str).str.lower().str.contains(sq, na=False)
                | df["Tác giả"].astype(str).str.lower().str.contains(sq, na=False)
                | df["Tạp chí"].astype(str).str.lower().str.contains(sq, na=False)
                | df["Năm"].astype(str).str.lower().str.contains(sq, na=False)
                | df["Loại chỉ số"].astype(str).str.lower().str.contains(sq, na=False)
                | df["Chất lượng"].astype(str).str.lower().str.contains(sq, na=False)
                | df["DOI"].astype(str).str.lower().str.contains(sq, na=False)
                | df["ISSN"].astype(str).str.lower().str.contains(sq, na=False)
            )
            df = df[mask]

        # Sắp xếp theo năm giảm dần
        df["_sort_year"] = pd.to_numeric(df["Năm"], errors="coerce").fillna(0)
        df = df.sort_values("_sort_year", ascending=False).drop(columns=["_sort_year"])

        st.data_editor(
            df,
            width='stretch',
            hide_index=True,
            key="pub_stat_editor",
            column_config={
                "Mã": st.column_config.TextColumn("Mã", disabled=True),
                "Tên bài báo": st.column_config.TextColumn("Tên bài báo"),
                "Tác giả": st.column_config.TextColumn("Tác giả"),
                "Tạp chí": st.column_config.TextColumn("Tạp chí"),
                "Năm": st.column_config.TextColumn("Năm"),
                "Loại chỉ số": st.column_config.TextColumn("Loại chỉ số"),
                "Chất lượng": st.column_config.TextColumn("Chất lượng"),
                "DOI": st.column_config.TextColumn("DOI"),
                "ISSN": st.column_config.TextColumn("ISSN"),
            },
        )

    st.markdown("---")

    # ========================================================
    # MỤC 2: DANH MỤC CHẤT LƯỢNG (không bảng, chỉ tìm kiếm tạp chí)
    # ========================================================
    st.subheader("2. Danh mục chất lượng")

    # Danh sách tên tài liệu đã tải lên (lưu trong Supabase)
    uploaded_files = load_json_from_db("uploaded_catalog_files") or []
    if not isinstance(uploaded_files, list):
        uploaded_files = []

    # Tên hiển thị tùy chỉnh cho các catalog key (lưu trong Supabase)
    catalog_display_names = load_json_from_db("catalog_display_names") or {}
    if not isinstance(catalog_display_names, dict):
        catalog_display_names = {}

    st.markdown("**Tên tài liệu đã tải lên:**")
    if uploaded_files:
        for fname in uploaded_files:
            st.caption(f"• {fname}")
    else:
        st.info("Chưa có tài liệu nào được tải lên.")

    st.markdown("---")

    # Quản lý tên hiển thị cho các catalog đã tồn tại trên Supabase
    all_keys = list_all_keys()
    catalog_keys = sorted([
        k for k in all_keys
        if k.startswith("journal_quality_catalog_")
    ])

    with st.expander("🏷️ Đặt tên hiển thị cho các danh mục đã có (tùy chọn)", expanded=False):
        st.caption("Ví dụ: gán tên 'Scimago 2025' cho key `journal_quality_catalog_Scinago_2025_01`...")
        for ck in catalog_keys:
            data = load_json_from_db(ck) or {}
            current_name = catalog_display_names.get(ck, ck)
            col_n1, col_n2 = st.columns([3, 2])
            with col_n1:
                st.caption(f"`{ck}` — {len(data)} mục")
            with col_n2:
                new_name = st.text_input(
                    "Tên hiển thị",
                    value=current_name,
                    key=f"disp_name_{ck}",
                    label_visibility="collapsed",
                    placeholder="Nhập tên...",
                )
                if st.button("💾 Lưu tên", key=f"save_disp_{ck}"):
                    catalog_display_names[ck] = new_name.strip() or ck
                    save_json_to_db("catalog_display_names", catalog_display_names)
                    st.success(f"✅ Đã đặt tên '{new_name.strip()}' cho {ck}")
                    st.rerun()

    st.markdown("---")

    # Lấy danh sách các key catalog từ Supabase để chọn tìm kiếm
    if catalog_keys:
        selected_catalog = st.selectbox(
            "Chọn danh mục để tìm kiếm tạp chí:",
            options=catalog_keys,
            key="cat_selector",
            format_func=lambda k: catalog_display_names.get(k, k),
        )
    else:
        selected_catalog = None

    # Tìm kiếm tạp chí trong danh mục đã chọn
    st.markdown("### Tìm kiếm tạp chí trong danh mục chất lượng")
    search_journal = st.text_input(
        "🔍 Nhập tên tạp chí",
        key="cat_search_journal",
        placeholder="Ví dụ: Nature, IEEE, ...",
    )

    if search_journal and selected_catalog:
        catalog = load_json_from_db(selected_catalog) or {}
        sq = search_journal.strip().lower()
        results = []
        for key, entry in catalog.items():
            name = str(entry.get("journal_name", "")).lower()
            source = str(entry.get("source_title", "")).lower()
            if sq in name or sq in source:
                results.append({
                    "ID": key,
                    "Tên tạp chí": entry.get("journal_name", ""),
                    "Nguồn": entry.get("source_title", ""),
                    "ISSN": entry.get("issn", ""),
                    "ISBN": entry.get("isbn", ""),
                    "DOI": entry.get("doi", ""),
                    "Loại chỉ số": entry.get("index_type", ""),
                    "Chất lượng": entry.get("quartile", ""),
                    "Năm": entry.get("year", ""),
                })

        if results:
            res_df = pd.DataFrame(results)
            st.data_editor(
                res_df,
                width='stretch',
                hide_index=True,
                key="cat_search_result_editor",
                column_config={
                    "ID": st.column_config.TextColumn("ID", disabled=True),
                    "Tên tạp chí": st.column_config.TextColumn("Tên tạp chí"),
                    "Nguồn": st.column_config.TextColumn("Nguồn"),
                    "ISSN": st.column_config.TextColumn("ISSN"),
                    "ISBN": st.column_config.TextColumn("ISBN"),
                    "DOI": st.column_config.TextColumn("DOI"),
                    "Loại chỉ số": st.column_config.TextColumn("Loại chỉ số"),
                    "Chất lượng": st.column_config.TextColumn("Chất lượng"),
                    "Năm": st.column_config.TextColumn("Năm"),
                },
            )
        else:
            st.warning("Không tìm thấy tạp chí nào khớp.")
    elif search_journal and not selected_catalog:
        st.info("Vui lòng chọn một danh mục chất lượng để tìm kiếm.")

    st.markdown("---")

    # Nút tải lên danh mục chất lượng (nằm trong phần 2)
    st.markdown("### Tải lên danh mục chất lượng mới")
    uploaded_cat = st.file_uploader(
        "Chọn file danh mục (.csv, .xlsx hoặc .docx)",
        type=["csv", "xlsx", "xls", "docx"],
        key="catalog_uploader",
    )
    if uploaded_cat:
        try:
            df_cat = read_uploaded_file(uploaded_cat)
            total_rows = len(df_cat)
            st.success(f"✅ Đã đọc {total_rows} dòng từ file `{uploaded_cat.name}`.")
        except Exception as e:
            st.error(f"❌ Lỗi đọc file: {e}")
            return

        # Preview chỉ hiển thị 100 dòng đầu để tránh bảng quá lớn không render
        preview_rows = min(total_rows, 100)
        st.caption(f"👀 Xem trước {preview_rows} dòng đầu (tổng {total_rows} dòng). Toàn bộ dữ liệu sẽ được lưu khi nhấn nút dưới đây.")
        edited_preview = st.data_editor(
            df_cat.head(preview_rows),
            num_rows="dynamic",
            width='stretch',
            key="catalog_preview_editor",
        )

        if st.button("💾 Lưu danh mục chất lượng", type="primary", key="btn_save_catalog"):
            # Lưu toàn bộ df_cat (không chỉ preview)
            entries = df_cat.to_dict("records")
            add_cnt, upd_cnt = upsert_journal_catalog(entries)
            write_system_log(
                ctx.username,
                f"Upsert danh mục chất lượng từ file {uploaded_cat.name}",
                f"+{add_cnt} mới, ~{upd_cnt} cập nhật",
            )
            # Lưu tên file đã upload vào Supabase để hiển thị lại lần sau
            fname = uploaded_cat.name
            if fname not in uploaded_files:
                uploaded_files.append(fname)
                save_json_to_db("uploaded_catalog_files", uploaded_files)
            st.success(f"✅ Đã lưu: {add_cnt} mục mới, {upd_cnt} mục cập nhật.")
            st.session_state.pop("catalog_preview_editor", None)
            st.rerun()


def _render_degree_tab(ctx) -> None:
    """Tab Văn bằng SHTT (đang phát triển)."""
    st.info("🚧 Chức năng quản lý Văn bằng SHTT đang phát triển.")


def _render_book_tab(ctx) -> None:
    """Tab Sách và giáo trình (đang phát triển)."""
    st.info("🚧 Chức năng quản lý Sách và giáo trình đang phát triển.")


def _render_award_tab(ctx) -> None:
    """Tab Các giải thưởng khác (đang phát triển)."""
    st.info("🚧 Chức năng quản lý Các giải thưởng khác đang phát triển.")
