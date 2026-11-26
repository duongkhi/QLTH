# Trang Quản lý sản phẩm khoa học (Admin)
# Lưu trên Supabase bảng app_data dưới các key tương ứng.

import streamlit as st
import pandas as pd
import json
import re

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
from ai_client import generate_gemini_text_real
from docx_utils import extract_profile_document
from security import _strip_diacritics


def render_journal_admin_page(ctx) -> None:
    """Trang Quản lý sản phẩm khoa học (chỉ Admin)."""
    st.markdown('<div class="card">', unsafe_allow_html=True)
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
    st.markdown('</div>', unsafe_allow_html=True)


def _render_publication_tab(ctx) -> None:
    """Tab Công bố khoa học: thống kê bài báo + quản lý danh mục chất lượng."""
    # ========================================================
    # MỤC 1: THỐNG KÊ BÀI BÁO (có bảng, tìm kiếm thông minh)
    # ========================================================
    st.subheader("1. Thống kê bài báo khoa học")

    # Đọc bài báo từ bai_bao_cong_bo của tất cả hồ sơ
    from storage import get_all_existing_profiles, load_user_profile
    all_profiles = get_all_existing_profiles()

    # Gom nhóm bài báo theo (ten_cong_trinh, nam_cong_bo) để xử lý nhiều tác giả cùng bài
    pub_groups = {}  # key: (ten_cong_trinh, nam_cong_bo) -> list of (profile_key, prof_data, entry)
    for pk in all_profiles:
        prof = load_user_profile(pk) or {}
        if not isinstance(prof, dict):
            continue
        pubs = prof.get("bai_bao_cong_bo", [])
        if not isinstance(pubs, list):
            continue
        for p in pubs:
            if not isinstance(p, dict):
                continue
            ten_cong_trinh = str(p.get("ten_cong_trinh", "")).strip()
            if not ten_cong_trinh:
                continue
            nam_cong_bo = str(p.get("nam_cong_bo", "")).strip()
            group_key = (ten_cong_trinh, nam_cong_bo)
            if group_key not in pub_groups:
                pub_groups[group_key] = []
            pub_groups[group_key].append((pk, prof, p))

    # Xây dựng danh sách hiển thị: chọn 1 tác giả đại diện cho mỗi bài báo
    rows = []
    for (ten_cong_trinh, nam_cong_bo), entries in pub_groups.items():
        # Lấy thông tin tạp chí và phân loại từ entry đầu tiên
        first_entry = entries[0][2]
        noi_cong_bo = str(first_entry.get("noi_cong_bo", "")).strip()
        phan_loai = str(first_entry.get("phan_loai", "")).strip()

        # Chọn tác giả đại diện theo quy tắc:
        # 1. Có tên full name trên hệ thống (ho_va_ten)
        # 2. Ưu tiên tác giả liên hệ (tac_gia_lien_he = true)
        # 3. Rồi tác giả chính (tac_gia_dau = true)
        # 4. Nếu cả hai đều không phải → ưu tiên tên ABC
        candidates = []
        for pk, prof, p in entries:
            full_name = str(prof.get("ho_va_ten", "") or prof.get("ho_ten", "") or prof.get("full_name", "") or "").strip()
            if not full_name:
                continue  # bỏ qua nếu không có tên trên hệ thống
            is_lien_he = bool(p.get("tac_gia_lien_he", False))
            is_chinh = bool(p.get("tac_gia_dau", False))
            candidates.append({
                "full_name": full_name,
                "is_lien_he": is_lien_he,
                "is_chinh": is_chinh,
            })

        if candidates:
            # Sắp xếp: liên hệ trước, rồi chính, rồi tên ABC
            candidates.sort(key=lambda c: (
                0 if c["is_lien_he"] else (1 if c["is_chinh"] else 2),
                c["full_name"].lower(),
            ))
            tac_gia_hien_thi = candidates[0]["full_name"]
        else:
            tac_gia_hien_thi = ""

        rows.append({
            "Tên bài báo": ten_cong_trinh,
            "Tên tạp chí": noi_cong_bo,
            "Năm xuất bản": nam_cong_bo,
            "Tác giả": tac_gia_hien_thi,
            "Phân loại chất lượng": phan_loai,
        })

    if not rows:
        st.info("Chưa có bài báo nào trong hệ thống.")
    else:
        df = pd.DataFrame(rows)

        # Tìm kiếm thông minh trong tất cả các trường
        search_q = st.text_input(
            "🔍 Tìm kiếm bài báo (tên, tạp chí, tác giả, phân loại, năm...)",
            key="pub_search",
            placeholder="Nhập từ khóa tìm kiếm...",
        )
        if search_q:
            sq = _strip_diacritics(search_q.strip().lower())
            mask = (
                df["Tên bài báo"].astype(str).apply(lambda x: _strip_diacritics(x.lower())).str.contains(sq, na=False)
                | df["Tên tạp chí"].astype(str).apply(lambda x: _strip_diacritics(x.lower())).str.contains(sq, na=False)
                | df["Tác giả"].astype(str).apply(lambda x: _strip_diacritics(x.lower())).str.contains(sq, na=False)
                | df["Năm xuất bản"].astype(str).apply(lambda x: _strip_diacritics(x.lower())).str.contains(sq, na=False)
                | df["Phân loại chất lượng"].astype(str).apply(lambda x: _strip_diacritics(x.lower())).str.contains(sq, na=False)
            )
            df = df[mask]

        # Sắp xếp theo năm giảm dần
        df["_sort_year"] = pd.to_numeric(df["Năm xuất bản"], errors="coerce").fillna(0)
        df = df.sort_values("_sort_year", ascending=False).drop(columns=["_sort_year"])

        st.data_editor(
            df,
            width='stretch',
            hide_index=True,
            key="pub_stat_editor",
            column_config={
                "Tên bài báo": st.column_config.TextColumn("Tên bài báo"),
                "Tên tạp chí": st.column_config.TextColumn("Tên tạp chí"),
                "Năm xuất bản": st.column_config.TextColumn("Năm xuất bản"),
                "Tác giả": st.column_config.TextColumn("Tác giả"),
                "Phân loại chất lượng": st.column_config.TextColumn("Phân loại chất lượng"),
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

    st.markdown("**Tên tài liệu đã tải lên:**")
    if uploaded_files:
        for fname in uploaded_files:
            st.caption(f"• {fname}")
    else:
        st.info("Chưa có tài liệu nào được tải lên.")

    st.markdown("---")

    # Lấy danh sách các key catalog từ Supabase
    all_keys = list_all_keys()
    catalog_keys = sorted([
        k for k in all_keys
        if k.startswith("journal_quality_catalog_")
    ])

    # Tìm kiếm tạp chí trên TẤT CẢ các danh mục
    st.markdown("### Tìm kiếm tạp chí trong tất cả danh mục chất lượng")
    search_journal = st.text_input(
        "🔍 Nhập tên tạp chí",
        key="cat_search_journal",
        placeholder="Ví dụ: Nature, IEEE, ...",
    )

    if search_journal and catalog_keys:
        sq = _strip_diacritics(search_journal.strip().lower())
        all_results = []
        for ck in catalog_keys:
            catalog = load_json_from_db(ck) or {}
            for key, entry in catalog.items():
                name = _strip_diacritics(str(entry.get("journal_name", "")).lower())
                source = _strip_diacritics(str(entry.get("source_title", "")).lower())
                if sq in name or sq in source:
                    all_results.append({
                        "Nguồn danh mục": ck,
                        "Tên tạp chí": entry.get("journal_name", ""),
                        "ISSN": entry.get("issn", ""),
                        "ISBN": entry.get("isbn", ""),
                        "DOI": entry.get("doi", ""),
                        "Loại chỉ số": entry.get("index_type", ""),
                        "Chất lượng": entry.get("quartile", ""),
                        "Năm": entry.get("year", ""),
                    })

        if all_results:
            res_df = pd.DataFrame(all_results)
            st.data_editor(
                res_df,
                width='stretch',
                hide_index=True,
                key="cat_search_result_editor",
                column_config={
                    "Nguồn danh mục": st.column_config.TextColumn("Nguồn danh mục"),
                    "Tên tạp chí": st.column_config.TextColumn("Tên tạp chí"),
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
    elif search_journal and not catalog_keys:
        st.info("Chưa có danh mục chất lượng nào trong hệ thống.")

    st.markdown("---")

    # Nút tải lên danh mục chất lượng (nằm trong phần 2)
    st.markdown("### Tải lên danh mục chất lượng mới")
    uploaded_cat = st.file_uploader(
        "Chọn file danh mục (.csv, .xlsx, .docx, .pdf)",
        type=["csv", "xlsx", "xls", "docx", "pdf"],
        key="catalog_uploader",
    )

    if uploaded_cat:
        # Ô tên danh mục (tự động từ tên file, cho phép sửa)
        default_name = uploaded_cat.name.rsplit(".", 1)[0] if "." in uploaded_cat.name else uploaded_cat.name
        cat_name = st.text_input(
            "Tên danh mục",
            value=default_name,
            key="catalog_name_input",
            placeholder="Nhập tên danh mục...",
        )
        cat_name = cat_name.strip() or default_name
        cat_slug = "".join(c if c.isalnum() or c == "_" else "_" for c in cat_name)

        try:
            # Xác định loại file và phân tích
            name_lower = uploaded_cat.name.lower()
            if name_lower.endswith((".csv", ".xlsx", ".xls")):
                # Phân tích trực tiếp, không cần Gemini
                df_cat = read_uploaded_file(uploaded_cat)
                source_info = f"File {uploaded_cat.name}"
            elif name_lower.endswith((".pdf", ".docx")):
                # Dùng Gemini để trích xuất JSON
                raw_bytes = uploaded_cat.getvalue()
                raw_text = extract_profile_document(raw_bytes, uploaded_cat.name)

                if not raw_text or len(raw_text.strip()) < 10:
                    st.error("❌ File không có nội dung văn bản hoặc nội dung quá ít.")
                    return

                prompt = (
                    "Trích xuất toàn bộ danh sách tạp chí/chất lượng từ file dưới dạng JSON mảng.\n"
                    "Mỗi phần tử là một dict có các key sau:\n"
                    "- journal_name: tên tạp chí\n"
                    "- issn: ISSN (nếu có)\n"
                    "- isbn: ISBN (nếu có)\n"
                    "- doi: DOI (nếu có)\n"
                    "- index_type: loại chỉ số (Scopus, ISI, SCIE, Trong nước...)\n"
                    "- quartile: chất lượng (Q1, Q2, Q3, Q4...)\n"
                    "- year: năm\n\n"
                    "Trả về CHỈ JSON thuần, không bao bọc markdown, không giải thích thêm.\n\n"
                    "NỘI DUNG FILE:\n" + "'''" + raw_text[:12000] + "'''"
                )
                gemini_text = generate_gemini_text_real(prompt)
                if not gemini_text:
                    st.error("❌ Không trích xuất được dữ liệu từ file qua Gemini.")
                    return
                cleaned = gemini_text.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                try:
                    parsed = json.loads(cleaned)
                except Exception as e:
                    st.error(f"❌ Lỗi phân tích JSON từ Gemini: {e}")
                    return
                if not isinstance(parsed, list):
                    st.error("❌ Gemini không trả về danh sách JSON.")
                    return
                # Chuẩn hóa thành DataFrame
                rows = []
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    rows.append({
                        "journal_name": str(item.get("journal_name", "")).strip(),
                        "issn": str(item.get("issn", "")).strip(),
                        "isbn": str(item.get("isbn", "")).strip(),
                        "doi": str(item.get("doi", "")).strip(),
                        "index_type": str(item.get("index_type", "")).strip(),
                        "quartile": str(item.get("quartile", "")).strip(),
                        "year": str(item.get("year", "")).strip(),
                    })
                df_cat = pd.DataFrame(rows)
                source_info = f"File {uploaded_cat.name} (trích xuất qua Gemini)"
            else:
                st.error("❌ Định dạng file không hỗ trợ.")
                return

            total_rows = len(df_cat)
            if total_rows == 0:
                st.warning("⚠️ File không chứa dữ liệu nào.")
                return

            st.success(f"✅ Đã đọc {total_rows} dòng từ file `{uploaded_cat.name}`.")

            # Chỉ hiển thị 10 dòng đầu
            preview_rows = min(total_rows, 10)
            st.caption(f"👀 Xem trước {preview_rows} dòng đầu (tổng {total_rows} dòng). Toàn bộ dữ liệu sẽ được lưu khi nhấn nút dưới đây.")
            edited_preview = st.data_editor(
                df_cat.head(preview_rows),
                num_rows="dynamic",
                width='stretch',
                key="catalog_preview_editor",
            )

        except Exception as e:
            st.error(f"❌ Lỗi đọc file: {e}")
            return

        if st.button("💾 Lưu danh mục chất lượng", type="primary", key="btn_save_catalog"):
            # Lưu toàn bộ df_cat (không chỉ preview)
            entries = df_cat.to_dict("records")

            # Chuẩn hóa entries trước khi lưu
            clean_entries = []
            for e in entries:
                clean_e = {
                    "journal_name": str(e.get("journal_name", "")).strip(),
                    "issn": str(e.get("issn", "")).strip(),
                    "isbn": str(e.get("isbn", "")).strip(),
                    "doi": str(e.get("doi", "")).strip(),
                    "index_type": str(e.get("index_type", "")).strip(),
                    "quartile": str(e.get("quartile", "")).strip(),
                    "year": str(e.get("year", "")).strip(),
                }
                clean_entries.append(clean_e)

            # Chia thành các batch 3000, lưu với key có tên file + index
            BATCH_SIZE = 3000
            batch_keys = []
            total_added = 0
            total_updated = 0

            # Tạo slug từ tên file (bỏ phần mở rộng, thay ký tự đặc biệt bằng _)
            base_name = uploaded_cat.name.rsplit(".", 1)[0] if "." in uploaded_cat.name else uploaded_cat.name
            file_slug = "".join(c if c.isalnum() or c == "_" else "_" for c in base_name)

            for i in range(0, len(clean_entries), BATCH_SIZE):
                batch = clean_entries[i:i + BATCH_SIZE]
                batch_idx = i // BATCH_SIZE + 1
                batch_key = f"journal_quality_catalog_{file_slug}_{batch_idx:02d}"

                # Đọc batch cũ nếu có để upsert
                existing = load_json_from_db(batch_key) or {}
                add_cnt = 0
                upd_cnt = 0
                for entry in batch:
                    # Tạo khóa duy nhất: DOI > ISSN > ISBN > tên
                    entry_doi = str(entry.get("doi", "")).strip()
                    entry_issn = str(entry.get("issn", "")).strip()
                    entry_isbn = str(entry.get("isbn", "")).strip()
                    entry_name = str(entry.get("journal_name", "")).strip()

                    match_key = None
                    if entry_doi:
                        match_key = f"doi:{entry_doi.lower()}"
                    elif entry_issn:
                        match_key = f"issn:{entry_issn.lower()}"
                    elif entry_isbn:
                        match_key = f"isbn:{entry_isbn.lower()}"
                    elif entry_name:
                        match_key = f"name:{entry_name.lower()}"

                    if match_key and match_key in existing:
                        existing[match_key].update(entry)
                        upd_cnt += 1
                    else:
                        if not match_key:
                            match_key = f"auto_{len(existing) + add_cnt + upd_cnt}"
                        existing[match_key] = entry
                        add_cnt += 1

                ok = save_json_to_db(batch_key, existing)
                if ok:
                    batch_keys.append(batch_key)
                    total_added += add_cnt
                    total_updated += upd_cnt
                else:
                    st.error(f"❌ Không lưu được batch {batch_idx}.")
                    return

            # Lưu meta key
            meta_key = f"journal_quality_catalog_{file_slug}_index"
            save_json_to_db(meta_key, {
                "batch_keys": sorted(batch_keys),
                "total": len(clean_entries),
                "source_file": uploaded_cat.name,
                "source_info": source_info,
            })

            # Lưu tên file đã upload vào Supabase để hiển thị lại lần sau
            fname = uploaded_cat.name
            if fname not in uploaded_files:
                uploaded_files.append(fname)
                save_json_to_db("uploaded_catalog_files", uploaded_files)

            write_system_log(
                ctx.username,
                f"Upsert danh mục chất lượng từ file {uploaded_cat.name} (tên: {cat_name})",
                f"+{total_added} mới, ~{total_updated} cập nhật, {len(batch_keys)} batch",
            )
            st.success(f"✅ Đã lưu: {total_added} mục mới, {total_updated} mục cập nhật. ({len(batch_keys)} batch)")
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
