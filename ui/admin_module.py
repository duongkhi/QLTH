import io
import json
import re
import time
import hashlib

import streamlit as st
from docx import Document

from config import UserContext, MAX_CHARS
from storage import load_user_profile, write_system_log
from security import (
    detect_name_from_data, detect_dob_from_data, get_identity,
    identity_matches,
)
from profile_service import (
    find_profile_in_text, resolve_profile, suggest_profile_key,
    merge_and_save, find_identity_matches,
)
from docx_utils import (
    cached_extract_docx, smart_truncate, render_docx_preview,
    extract_document_title, strip_personal_content,
    truncate_profile_for_prompt, fix_tcvn3_text,  # Đã thêm fix_tcvn3_text
)
from ai_client import call_model_json, get_client
from form_templates import (
    list_form_templates,
    get_form_template,
    get_template_docx_bytes,
    save_form_template,
    delete_form_template,
    update_template_prompt,
    update_template_meta,
    slugify_template_id,
    match_template_by_title,
    extract_fields_heuristic,
    extract_fields_with_ai,
)
from ui.chat_ui import render_chat_section


# =====================================================================
# HELPERS
# =====================================================================
def _find_template_meta(templates_list, tid):
    for t in templates_list:
        if t.get("id") == tid:
            return t
    return None


def _reset_upload_state():
    for k in ("upload_stage", "upload_extracted",
              "upload_detected_name", "upload_detected_dob"):
        st.session_state[k] = None
    # Xóa báo cáo gộp (nếu có)
    st.session_state.pop("_merge_report", None)


def _render_merge_report(changes):
    """Hiển thị báo cáo tóm tắt các thay đổi sau khi gộp."""
    n_added = len(changes.get("added", {}))
    n_updated = len(changes.get("updated", {}))
    n_appended = len(changes.get("appended", {}))

    if n_added == 0 and n_updated == 0 and n_appended == 0:
        st.info("ℹ️ Không có trường nào thay đổi (dữ liệu đã tồn tại hoặc file mới rỗng).")
        return

    st.success(f"✅ Gộp thành công! (Thêm mới: {n_added} | Ghi đè: {n_updated} | Nối tiếp: {n_appended})")
    
    with st.expander("👁️ Xem chi tiết các thay đổi", expanded=True):
        if n_added > 0:
            st.markdown("**➕ Trường mới thêm:**")
            st.json(changes["added"])
        if n_updated > 0:
            st.markdown("**♻️ Trường bị ghi đè:**")
            st.json(changes["updated"])
        if n_appended > 0:
            st.markdown("**🔗 Trường được nối thêm (List):**")
            st.json(changes["appended"])


# =====================================================================
# MAIN
# =====================================================================
def render_admin_module(ctx: UserContext):
    st.title("📄 Quản Lý Hành Chính")
    st.caption("Nạp hồ sơ · Điền biểu mẫu · Hỏi đáp trực tiếp")

    if not get_client():
        st.error("⚠️ Chưa cấu hình `GEMINI_API_KEY` trong `st.secrets`.")
        st.stop()

    _render_upload_section(ctx)
    _render_form_section(ctx)
    st.markdown("---")
    render_chat_section(ctx)


# =====================================================================
# SECTION 1: Upload profile (Auto-trigger & Cancel)
# =====================================================================
def _render_upload_section(ctx: UserContext):
    st.markdown("---")
    st.subheader("📄 1. Nạp dữ liệu hồ sơ")

    if ctx.is_power:
        st.caption("Upload file Word. AI sẽ trích xuất và "
                   "**tự so khớp họ tên + ngày sinh**.")
    else:
        if not ctx.own_profile:
            st.error("⚠️ Tài khoản của bạn chưa có profile. Liên hệ admin.")
            st.stop()
        st.caption(f"Upload file hồ sơ của bạn "
                   f"(hồ sơ **{ctx.own_profile}**).")

    stage = st.session_state.get("upload_stage")
    
    if stage is None:
        _render_upload_first_step(ctx)
    elif stage == "processing":
        _render_upload_processing(ctx)
    else:
        _render_upload_review(ctx)


def _render_upload_first_step(ctx: UserContext):
    upf = st.file_uploader("File hồ sơ thô (.docx)", type=["docx"],
                           key="uploader_profile")
    if upf:
        st.session_state["_upload_profile_bytes"] = upf.getvalue()
        st.session_state.upload_stage = "processing"
        st.rerun()


def _render_upload_processing(ctx: UserContext):
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("❌ Hủy", use_container_width=True, key="btn_cancel_upload"):
            _reset_upload_state()
            st.session_state.pop("_upload_profile_bytes", None)
            st.rerun()

    progress = st.progress(5, text="📄 Đang đọc file...")
    try:
        raw_bytes = st.session_state.get("_upload_profile_bytes")
        if not raw_bytes:
            _reset_upload_state()
            st.rerun()

        raw = cached_extract_docx(raw_bytes)
        raw = smart_truncate(raw)
        progress.progress(15, text=f"📤 Đọc {len(raw):,} ký tự, gửi AI...")
        
        prompt = f"""Bạn là AI Agent quản lý hồ sơ nhân sự.
                Trích xuất TOÀN BỘ thông tin từ văn bản thô sau thành JSON phẳng.
                Văn bản:
                \"\"\"
                {raw}
                \"\"\"
                Yêu cầu:
                - Trả về MỘT đối tượng JSON (key-value).
                - Key tiếng Anh, viết thường, gạch dưới.
                - BẮT BUỘC có 'ho_va_ten' nếu tìm được.
                - BẮT BUỘC có 'ngay_sinh' (DD/MM/YYYY) nếu tìm được.
                """
        jt = call_model_json(prompt, progress, 20, 95, label="🤖 Đang trích xuất")
        extracted = json.loads(jt)
        
        progress.progress(100, text="✅ Xong")
        st.session_state.upload_extracted = extracted
        st.session_state.upload_detected_name = detect_name_from_data(extracted)
        st.session_state.upload_detected_dob = detect_dob_from_data(extracted)
        st.session_state.upload_stage = "review"
        st.session_state.pop("_upload_profile_bytes", None)
        time.sleep(0.3)
        st.rerun()
        
    except Exception as e:
        progress.empty()
        st.error(f"Lỗi phân tích file: {e}")
        if st.button("Quay lại", key="btn_err_upload"):
            _reset_upload_state()
            st.session_state.pop("_upload_profile_bytes", None)
            st.rerun()


def _render_upload_review(ctx: UserContext):
    extracted = st.session_state.upload_extracted
    det_name = st.session_state.upload_detected_name
    det_dob = st.session_state.upload_detected_dob

    # Nếu có báo cáo gộp -> Hiển thị và đợi xác nhận
    if st.session_state.get("_merge_report"):
        _render_merge_report(st.session_state["_merge_report"])
        if st.button("✅ Hoàn tất, nạp file khác", type="primary", use_container_width=True):
            _reset_upload_state()
            st.rerun()
        return

    st.success(f"✅ Đã trích xuất **{len(extracted)} trường**.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Họ tên:** {det_name or '⚠️ không xác định'}")
    with c2:
        st.markdown(f"**Ngày sinh:** {det_dob or '⚠️ không xác định'}")
    with st.expander("👁️ Xem dữ liệu trích xuất"):
        st.json(extracted)

    if ctx.is_power:
        _render_upload_review_admin(ctx, extracted, det_name)
    else:
        _render_upload_review_user(ctx, extracted, det_name, det_dob)

    st.markdown("---")
    if st.button("❌ Hủy, upload lại", use_container_width=True, key="u_cancel"):
        _reset_upload_state()
        st.rerun()


def _render_upload_review_admin(ctx, extracted, det_name):
    if not det_name:
        st.error("⚠️ Không phát hiện họ tên — không thể so khớp.")
        return

    matches = find_identity_matches(extracted, ctx.allowed_profiles)
    if matches:
        st.markdown("### 🔍 Hồ sơ trùng khớp")
        for mk, strength in matches:
            existing = load_user_profile(mk)
            en, ed = get_identity(existing)
            tag = ("🟢 Khớp đầy đủ (họ tên + ngày sinh)"
                   if strength == "strong"
                   else "🟡 Chỉ khớp họ tên (thiếu ngày sinh)")
            with st.container(border=True):
                st.markdown(f"**`{mk}`** — {en or '?'} — {ed or '?'}")
                st.caption(tag)
                cc1, cc2 = st.columns(2)
                with cc1:
                    if st.button("🔄 Gộp thêm", key=f"mg_{mk}",
                                 use_container_width=True, type="primary"):
                        merged, changes = merge_and_save(mk, extracted)
                        write_system_log(ctx.username, f"Gộp vào {mk}", f"OK")
                        st.session_state["_merge_report"] = changes
                        st.rerun()
                with cc2:
                    if st.button("♻️ Ghi đè", key=f"ow_{mk}",
                                 use_container_width=True):
                        merged, _ = merge_and_save(mk, extracted, overwrite=True)
                        write_system_log(ctx.username, f"Ghi đè {mk}", f"OK")
                        st.success(f"✅ Đã ghi đè toàn bộ hồ sơ `{mk}`.")
                        _reset_upload_state()
                        time.sleep(0.5)
                        st.rerun()
    else:
        st.info("🔍 Không có hồ sơ trùng khớp → sẽ tạo hồ sơ mới.")

    st.markdown("### 🆕 Tạo hồ sơ mới")
    sk = suggest_profile_key(det_name)
    new_key = st.text_input("Key profile mới (tên file JSON):",
                            value=sk, key="new_key",
                            help="Chỉ chữ, số, gạch dưới. VD: VuDuong")
    if not new_key:
        return
    if not re.match(r"^[a-zA-Z0-9_]+$", new_key):
        st.error("Key chỉ chứa chữ, số, gạch dưới.")
        return
    if load_user_profile(new_key):
        st.warning(f"⚠️ Profile `{new_key}` đã tồn tại. Tiếp tục sẽ GHI ĐÈ.")
        if st.button(f"⚠️ Ghi đè `{new_key}`", use_container_width=True, key="btn_new_ow"):
            merged, _ = merge_and_save(new_key, extracted, overwrite=True)
            write_system_log(ctx.username, f"Ghi đè {new_key}", f"OK")
            st.success(f"✅ Đã tạo mới/ghi đè `{new_key}`.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()
    else:
        if st.button("🆕 Tạo hồ sơ mới", type="primary", use_container_width=True, key="btn_new_mk"):
            merged, changes = merge_and_save(new_key, extracted)
            write_system_log(ctx.username, f"Tạo mới {new_key}", f"OK")
            st.session_state["_merge_report"] = changes
            st.rerun()


def _render_upload_review_user(ctx, extracted, det_name, det_dob):
    existing = load_user_profile(ctx.own_profile)
    if not existing:
        st.info(f"📁 Hồ sơ **{ctx.own_profile}** chưa có dữ liệu. "
                f"Đây sẽ là lần nạp đầu tiên.")
        if st.button("💾 Lưu vào hồ sơ của tôi", type="primary", use_container_width=True, key="u_first"):
            merged, changes = merge_and_save(ctx.own_profile, extracted)
            write_system_log(ctx.username, f"Nạp lần đầu vào {ctx.own_profile}", f"OK")
            st.session_state["_merge_report"] = changes
            st.rerun()
        return

    en, ed = get_identity(existing)
    result = identity_matches(extracted, existing)
    if result == "no":
        st.error(f"🚫 **Không thể ghi.** File chứa **{det_name}** "
                 f"(DOB: {det_dob or '?'}), nhưng hồ sơ của bạn là "
                 f"**{en or '?'}** (DOB: {ed or '?'}). "
                 f"Đây không phải dữ liệu của bạn.")
        return

    if result == "strong":
        st.success(f"✅ Khớp hồ sơ **{en}** — {ed}.")
        can_write = True
    else:
        st.warning(f"⚠️ Chỉ khớp họ tên **{det_name}**, "
                   f"thiếu ngày sinh để đối chiếu.")
        can_write = st.checkbox(
            "Tôi xác nhận đây là dữ liệu của chính tôi",
            key="confirm_weak_identity",
        )

    if not can_write:
        return

    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button("🔄 Gộp thêm", key="u_merge", use_container_width=True, type="primary"):
            merged, changes = merge_and_save(ctx.own_profile, extracted)
            write_system_log(ctx.username, f"Gộp vào {ctx.own_profile}", f"OK")
            st.session_state["_merge_report"] = changes
            st.rerun()
    with cc2:
        if st.button("♻️ Ghi đè", key="u_ow", use_container_width=True):
            merged, _ = merge_and_save(ctx.own_profile, extracted, overwrite=True)
            write_system_log(ctx.username, f"Ghi đè {ctx.own_profile}", f"OK")
            st.success("✅ Đã ghi đè toàn bộ hồ sơ.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()


# =====================================================================
# SECTION 2: Fill form
# =====================================================================
def _render_form_section(ctx):
    st.markdown("---")
    st.subheader("📝 2. Điền biểu mẫu")

    templates_meta = list_form_templates()

    mode = st.radio(
        "Nguồn:", ["📚 Thư viện", "📤 Upload file mới"],
        horizontal=True, key="form_src_mode",
    )

    tid = fields = title = None

    if mode == "📚 Thư viện":
        tid, fields, title = _render_form_library(ctx, templates_meta)
    else:
        tid, fields, title = _render_form_upload(ctx, templates_meta)

    if st.session_state.get("_use_lib_tid"):
        use_tid = st.session_state.pop("_use_lib_tid")
        meta = get_form_template(use_tid)
        if meta:
            tid = use_tid
            fields = meta.get("fields", [])
            title = meta.get("title", use_tid)

    st.markdown("---")
    st.markdown("### 🎯 Hồ sơ đích")
    sel_target, form_prompt = _render_target_selector(ctx)

    st.markdown("---")
    if not tid:
        st.caption("⬆️ Chọn hoặc lưu biểu mẫu để bật nút điền.")
        return

    if st.button("✍️ Điền biểu mẫu", use_container_width=True, type="primary", key="btn_fill"):
        _fill_form(ctx, tid, fields or [], title or tid, sel_target, form_prompt)


def _render_form_library(ctx, templates_meta):
    if not templates_meta:
        st.info("Chưa có biểu mẫu. Chuyển sang *Upload file mới* để tạo.")
        return None, None, None

    from form_prompts import CATEGORIES

    by_cat = {}
    for t in templates_meta:
        by_cat.setdefault(t.get("category", "other"), []).append(t)

    cat_options = [c for c in CATEGORIES if c in by_cat] + \
                  [c for c in by_cat if c not in CATEGORIES]
    sel_cat = st.selectbox(
        "Loại biểu mẫu:",
        cat_options,
        format_func=lambda x: CATEGORIES.get(x, x),
        key="form_cat_select",
    )
    in_cat = by_cat.get(sel_cat, [])
    if not in_cat:
        return None, None, None

    labels = {
        t["id"]: f"{t['title']}  ·  {len(t.get('fields', []))} trường  ·  "
                 f"{t.get('updated_at', '')[:10]}"
        for t in in_cat
    }
    sel_tid = st.selectbox(
        "Chọn biểu mẫu:",
        options=[t["id"] for t in in_cat],
        format_func=lambda x: labels[x],
        key="form_template_select",
    )

    meta = get_form_template(sel_tid)
    if not meta:
        st.error("Không đọc được metadata mẫu.")
        return None, None, None

    with st.expander("👁️ Xem trước markdown (AI đọc cái này)", expanded=False):
        st.code(meta.get("markdown", "")[:3000], language="markdown")

    if ctx.role == "admin":
        _render_admin_template_tools(ctx, meta)
        if st.button("🗑️ Xóa mẫu này", key=f"del_tpl_{sel_tid}"):
            delete_form_template(sel_tid)
            write_system_log(ctx.username, f"Xóa form template '{sel_tid}'", "OK")
            st.success("Đã xóa.")
            st.rerun()

    return sel_tid, meta.get("fields", []), meta.get("title", sel_tid)


def _render_admin_template_tools(ctx, meta):
    with st.expander("⚙️ Tuỳ chỉnh mẫu (admin)", expanded=False):
        from form_prompts import CATEGORIES, CATEGORY_RULES
        cur_cat = meta.get("category", "other")
        idx = list(CATEGORIES.keys()).index(cur_cat) if cur_cat in CATEGORIES else 0
        new_cat = st.selectbox(
            "Category:",
            options=list(CATEGORIES.keys()),
            format_func=lambda x: CATEGORIES[x],
            index=idx,
            key=f"cat_{meta['id']}",
        )
        custom = st.text_area(
            "Prompt riêng (bỏ trống = dùng prompt mặc định của category)",
            value=meta.get("fill_prompt") or "",
            height=150,
            key=f"prompt_{meta['id']}",
            placeholder=CATEGORY_RULES.get(new_cat, "")[:300],
        )
        if st.button("💾 Lưu tuỳ chỉnh", key=f"save_meta_{meta['id']}"):
            update_template_meta(meta["id"], category=new_cat)
            update_template_prompt(meta["id"], custom)
            st.success("Đã lưu.")
            st.rerun()


def _render_form_upload(ctx, templates):
    uploaded = st.file_uploader(
        "Upload file .docx (biểu mẫu trống hoặc đã điền)",
        type=["docx"], key="uploader_template",
    )
    
    if not uploaded:
        st.session_state.pop("_new_tpl_bytes", None)
        st.session_state.pop("_new_tpl_fields", None)
        st.session_state.pop("_new_tpl_title", None)
        st.session_state.pop("_tpl_ignored_hash", None)
        return None, None, None

    new_bytes = uploaded.getvalue()
    new_title = extract_document_title(new_bytes)
    matched_tid = match_template_by_title(new_title, templates) if new_title else None

    # ---------- Đã có template khớp ----------
    if matched_tid:
        matched_meta = _find_template_meta(templates, matched_tid) or {}
        matched_title = matched_meta.get("title", matched_tid)

        st.warning(f"⚠️ Phát hiện biểu mẫu trùng tên trong thư viện: **{matched_title}**")
        
        st.markdown("Vui lòng chọn thao tác:")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📚 Dùng mẫu cũ trong thư viện", type="primary", key="use_matched_tpl", use_container_width=True):
                st.session_state["_use_lib_tid"] = matched_tid
                st.rerun()
                
        with col2:
            if st.button("♻️ Ghi đè file mới vào thư viện", key="btn_overwrite_tpl", use_container_width=True):
                with st.spinner("Đang phân tích và cập nhật mẫu..."):
                    # 1. Trích xuất fields từ file mới
                    f1 = extract_fields_heuristic(new_bytes)
                    if len(f1) >= 3:
                        new_fields = f1
                    else:
                        prog = st.progress(10, text="🤖 AI đang trích xuất trường...")
                        f2, _ai_title, _ai_cat = extract_fields_with_ai(new_bytes, prog)
                        prog.progress(100, text="✅ Xong")
                        new_fields = f2
                    
                    # 2. Lọc bỏ dữ liệu cá nhân (nếu file mới là file đã điền)
                    clean_bytes = strip_personal_content(new_bytes, new_fields)
                    
                    # 3. Lưu đè vào Database
                    save_form_template(
                        tid=matched_tid, # Giữ nguyên ID cũ
                        title=matched_title,
                        fields=new_fields,
                        docx_bytes=clean_bytes,
                        created_by=ctx.username,
                    )
                    write_system_log(ctx.username, f"Ghi đè form template '{matched_tid}'", "OK")
                    st.success("✅ Đã cập nhật mẫu mới vào Database!")
                    time.sleep(1.5)
                    st.rerun()

        st.markdown("---")
        use_uploaded = st.checkbox(
            "Chỉ dùng file vừa upload cho lần điền này (Không lưu vào Database)",
            key="use_uploaded_bytes",
        )
        if use_uploaded:
            # Trả về raw bytes từ file vừa upload + fields từ metadata cũ
            return new_bytes, matched_meta.get("fields", []), new_title or matched_title
        return None, None, None

    # ---------- Template mới ----------
    st.info(f"🆕 Biểu mẫu mới: **{new_title or '(chưa rõ tiêu đề)'}**")

    file_hash = hashlib.md5(new_bytes).hexdigest()

    if st.session_state.get("_tpl_ignored_hash") == file_hash:
        st.warning("⚠️ Đã hủy phân tích file này. Vui lòng chọn file khác.")
        return None, None, None

    if not st.session_state.get("_new_tpl_fields"):
        col1, col2 = st.columns([4, 1])
        with col2:
            if st.button("❌ Hủy", key="btn_cancel_tpl", use_container_width=True):
                st.session_state["_tpl_ignored_hash"] = file_hash
                st.rerun()

        prog = st.progress(10, text="🤖 Đang phân tích biểu mẫu...")
        try:
            f1 = extract_fields_heuristic(new_bytes)
            if len(f1) >= 3:
                st.session_state["_new_tpl_fields"] = f1
                st.session_state["_new_tpl_bytes"] = new_bytes
                st.session_state["_new_tpl_title"] = new_title
            else:
                prog.progress(30, text="🤖 AI đang trích xuất trường...")
                f2, ai_title, _ai_cat = extract_fields_with_ai(new_bytes, prog)
                st.session_state["_new_tpl_fields"] = f2
                st.session_state["_new_tpl_bytes"] = new_bytes
                st.session_state["_new_tpl_title"] = new_title or ai_title
                
            prog.progress(100, text="✅ Xong")
            st.session_state["_tpl_ignored_hash"] = None
            time.sleep(0.3)
            st.rerun()
        except Exception as e:
            st.error(f"Lỗi phân tích: {e}")
            return None, None, None

    fields = st.session_state["_new_tpl_fields"]
    st.markdown(f"**{len(fields)} trường phát hiện:** {', '.join(fields)}")

    new_title_input = st.text_input(
        "Tên biểu mẫu:",
        value=st.session_state.get("_new_tpl_title") or "",
        key="new_tpl_title_input",
    )
    new_tid = slugify_template_id(new_title_input)
    existing = _find_template_meta(templates, new_tid) is not None

    if existing:
        st.warning(f"⚠️ ID `{new_tid}` đã tồn tại — thao tác sẽ **ghi đè**.")

    st.markdown("**Chọn kiểu lưu:**")

    cA, cB = st.columns(2)
    with cA:
        lbl = ("♻️ Lưu đè (đã lọc nội dung)" if existing else "💾 Lưu mẫu (đã lọc)")
        if st.button(lbl, type="primary", use_container_width=True, key="btn_save_clean"):
            if not new_title_input.strip():
                st.error("Nhập tên biểu mẫu.")
            else:
                try:
                    clean = strip_personal_content(st.session_state["_new_tpl_bytes"], fields)
                    save_form_template(
                        tid=new_tid,
                        title=new_title_input.strip(),
                        fields=fields,
                        docx_bytes=clean,
                        created_by=ctx.username,
                    )
                    write_system_log(ctx.username, f"Lưu form template '{new_tid}' (clean)", "OK")
                    st.session_state["_use_lib_tid"] = new_tid
                    for k in ("_new_tpl_fields", "_new_tpl_bytes", "_new_tpl_title"):
                        st.session_state[k] = None
                    st.success(f"✅ Đã lưu mẫu **{new_title_input}**.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu mẫu: {e}")

    with cB:
        if st.button("💾 Lưu nguyên bản", use_container_width=True, key="btn_save_raw"):
            if not new_title_input.strip():
                st.error("Nhập tên biểu mẫu.")
            else:
                try:
                    save_form_template(
                        tid=new_tid,
                        title=new_title_input.strip(),
                        fields=fields,
                        docx_bytes=st.session_state["_new_tpl_bytes"],
                        created_by=ctx.username,
                    )
                    write_system_log(ctx.username, f"Lưu form template '{new_tid}' (raw)", "OK")
                    st.session_state["_use_lib_tid"] = new_tid
                    for k in ("_new_tpl_fields", "_new_tpl_bytes", "_new_tpl_title"):
                        st.session_state[k] = None
                    st.success(f"✅ Đã lưu mẫu **{new_title_input}**.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu mẫu: {e}")

    st.caption("ℹ️ Lưu mẫu trước để có thể điền.")
    return None, None, None


def _render_target_selector(ctx: UserContext):
    if ctx.is_power:
        options = ["(tự động theo yêu cầu)"] + ctx.allowed_profiles
        sel = st.selectbox(
            "Chọn hồ sơ cần điền:",
            options=options,
            key="form_target_dd",
            help="Chọn hồ sơ cụ thể, hoặc để AI đọc từ yêu cầu.",
        )
        prompt = ""
        if sel == "(tự động theo yêu cầu)":
            prompt = st.text_input(
                "Yêu cầu (để trống nếu đã chọn hồ sơ cụ thể)",
                placeholder="VD: điền thông tin Vũ Dương vào form",
                key="form_prompt",
            )
        return sel, prompt
    if ctx.own_profile:
        st.info(f"AI sẽ điền từ hồ sơ của bạn: **{ctx.own_profile}**")
    return None, ""


def _resolve_target(ctx: UserContext, sel_target, form_prompt, progress):
    if ctx.is_power:
        target = None
        if sel_target and sel_target != "(tự động theo yêu cầu)":
            target = sel_target
        elif form_prompt and form_prompt.strip():
            found = find_profile_in_text(form_prompt, ctx.allowed_profiles)
            if found:
                target = found
            else:
                resolved, _, _, _ = resolve_profile(form_prompt, ctx.allowed_profiles)
                target = resolved

        if not target:
            progress.empty()
            st.error("❌ Không xác định được hồ sơ đích. Chọn dropdown hoặc nhập tên rõ ràng hơn.")
            return None
    else:
        target = ctx.own_profile
        if not target:
            progress.empty()
            st.error("❌ Tài khoản chưa có profile. Liên hệ admin.")
            return None

    if target not in ctx.allowed_profiles:
        progress.empty()
        st.error(f"❌ Không có quyền truy cập **[{target}]**.")
        return None

    return target


def _fill_form(ctx, tid, fields, title, sel_target, form_prompt):
    progress = st.progress(5, text="📄 Đang chuẩn bị...")

    target = _resolve_target(ctx, sel_target, form_prompt, progress)
    if not target:
        return

    try:
        meta = get_form_template(tid)
    except Exception as e:
        progress.empty()
        st.error(f"Lỗi đọc mẫu: {e}")
        return

    if not meta:
        progress.empty()
        st.error(f"Không tìm thấy mẫu `{tid}`.")
        return

    docx_bytes = get_template_docx_bytes(tid)
    if not docx_bytes:
        progress.empty()
        st.error("Mẫu không có file DOCX (chỉ có markdown).")
        return

    tdata = load_user_profile(target)
    if not tdata:
        progress.empty()
        st.warning(f"⚠️ Hồ sơ **[{target}]** chưa có dữ liệu.")
        return

    try:
        progress.progress(20, text="🧠 AI đang map dữ liệu...")
        tdata_small = truncate_profile_for_prompt(tdata, MAX_CHARS // 2)
        
        prompt = f"""Bạn là trợ lý hành chính. Hãy trích xuất thông tin từ HỒ SƠ để điền vào BIỂU MẪU.
        
DỮ LIỆU HỒ SƠ:
{json.dumps(tdata_small, ensure_ascii=False)}

DANH SÁCH CÁC TRƯỜNG CẦN ĐIỀN TRONG BIỂU MẪU:
{json.dumps(fields, ensure_ascii=False)}

YÊU CẦU:
- Trả về DUY NHẤT JSON object dạng: {{ "Tên trường": "Giá trị điền" }}
- Key phải khớp CHÍNH XÁC từng chữ với danh sách trên.
- Bỏ qua các trường không có dữ liệu (không bịa).
- Không giải thích gì thêm.
"""
        jt = call_model_json(prompt, progress, 25, 80, label="🤖 Đang map data")
        filled_json = json.loads(jt)

        progress.progress(85, text="✍️ Đang ghi vào DOCX...")
        doc = Document(io.BytesIO(docx_bytes))
        filled_count = 0

        # Sắp xếp các trường giảm dần theo độ dài để tránh match nhầm
        sorted_fields = sorted(fields, key=len, reverse=True)

        def _replace_in_paragraph(p, label, value):
            text = p.text
            if not text.strip():
                return False
            
            fixed_text = fix_tcvn3_text(text)
            fixed_label = fix_tcvn3_text(str(label))
            
            # Lấy danh sách các trường khác làm ranh giới
            others = [f for f in sorted_fields if f != label]
            next_fields_pattern = "|".join([re.escape(fix_tcvn3_text(o)) for o in others])
            
            # REGEX QUAN TRỌNG: Lookahead
            # Dừng lại ngay khi:
            # 1. Gặp trường khác (VD: " Ngày sinh:")
            # 2. Gặp đầu mục La Mã / Chữ cái / Số thứ tự (VD: " I. ", " A. ", " 1. ")
            # 3. Gặp dấu xuống dòng (\n) hoặc kết thúc chuỗi ($)
            section_headers = r"\s+(?:[A-ZĐ]\.|[IVX]+\.|\d+\.)\s" # Bắt A., I., 1.
            
            if next_fields_pattern:
                lookahead = rf"(?={section_headers}|\s+(?:{next_fields_pattern})\s*[:：]?|\n|$)"
            else:
                lookahead = rf"(?={section_headers}|\n|$)"

            # Case 1: Dạng "Label: Value"
            pattern_colon = re.compile(
                rf"({re.escape(fixed_label)}\s*[:：]\s*)(.*?){lookahead}",
                re.IGNORECASE
            )
            m = pattern_colon.search(fixed_text)
            if m:
                # Giữ nguyên prefix, thay value, giữ nguyên phần đuôi (bao gồm cả "A. NỘI DUNG...")
                new_text = fixed_text[:m.start(2)] + str(value) + fixed_text[m.end(2):]
                for run in p.runs: run.text = ""
                if p.runs: p.runs[0].text = new_text
                else: p.add_run(new_text)
                return True

            # Case 2: Dạng "Label ..........."
            pattern_dots = re.compile(
                rf"({re.escape(fixed_label)}.*?[\.…]{{2,}}\s*)(.*?){lookahead}",
                re.IGNORECASE
            )
            m = pattern_dots.search(fixed_text)
            if m:
                # Với dạng dấu chấm, ta thay toàn bộ cụm "Label ..." thành "Label: Value"
                prefix = m.group(1)
                prefix = re.sub(r"[\.…]{2,}.*$", "", prefix).strip()
                new_text = prefix + ": " + str(value) + fixed_text[m.end(2):]
                for run in p.runs: run.text = ""
                if p.runs: p.runs[0].text = new_text
                else: p.add_run(new_text)
                return True

            return False

        # Quét toàn bộ đoạn văn
        for p in doc.paragraphs:
            for label, value in filled_json.items():
                if value and _replace_in_paragraph(p, label, value):
                    filled_count += 1

        # Quét toàn bộ bảng biểu
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for label, value in filled_json.items():
                            if value and _replace_in_paragraph(p, label, value):
                                filled_count += 1

        bio = io.BytesIO()
        doc.save(bio)
        docx_out = bio.getvalue()
        progress.progress(100, text=f"✅ Đã điền {filled_count} trường")

        write_system_log(
            ctx.username,
            f"Điền form '{title}' cho {target}",
            f"OK ({filled_count}/{len(fields)})",
        )

        st.success(f"✅ Đã điền **{filled_count}/{len(fields)}** trường cho **[{target}]**.")
        
        render_docx_preview(docx_out, height=600)
        st.download_button(
            label=f"📥 Tải DOCX của {target}",
            data=docx_out,
            file_name=f"{target}_{tid}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True, key="btn_dl_filled",
        )

    except Exception as e:
        progress.empty()
        write_system_log(ctx.username, f"Điền form cho {title}", f"Lỗi ({e})")
        st.error(f"Lỗi: {e}")