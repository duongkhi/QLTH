import io
import json
import re
import time

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
    truncate_profile_for_prompt,
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
# SECTION 1: Upload profile (giữ nguyên, không đổi)
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

    if st.session_state.get("upload_stage") is None:
        _render_upload_first_step(ctx)
    else:
        _render_upload_review(ctx)


def _render_upload_first_step(ctx: UserContext):
    upf = st.file_uploader("File hồ sơ thô (.docx)", type=["docx"],
                           key="uploader_profile")
    if not upf:
        return
    if not st.button("🔍 Phân tích file", use_container_width=True,
                     key="btn_analyze"):
        return

    progress = st.progress(5, text="📄 Đang đọc file...")
    try:
        raw = cached_extract_docx(upf.getvalue())
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
        jt = call_model_json(prompt, progress, 20, 95,
                             label="🤖 Đang trích xuất")
        extracted = json.loads(jt)
        progress.progress(100, text="✅ Xong")
        st.session_state.upload_extracted = extracted
        st.session_state.upload_detected_name = detect_name_from_data(extracted)
        st.session_state.upload_detected_dob = detect_dob_from_data(extracted)
        st.session_state.upload_stage = "review"
        time.sleep(0.3)
        st.rerun()
    except Exception as e:
        progress.empty()
        st.error(f"Lỗi: {e}")


def _render_upload_review(ctx: UserContext):
    extracted = st.session_state.upload_extracted
    det_name = st.session_state.upload_detected_name
    det_dob = st.session_state.upload_detected_dob

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
    if st.button("❌ Hủy, upload lại", use_container_width=True,
                 key="u_cancel"):
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
                        merged = merge_and_save(mk, extracted)
                        write_system_log(ctx.username, f"Gộp vào {mk}",
                                         f"OK ({len(merged)})")
                        st.success(f"✅ Đã gộp vào `{mk}`.")
                        _reset_upload_state()
                        time.sleep(0.5)
                        st.rerun()
                with cc2:
                    if st.button("♻️ Ghi đè", key=f"ow_{mk}",
                                 use_container_width=True):
                        merged = merge_and_save(mk, extracted, overwrite=True)
                        write_system_log(ctx.username, f"Ghi đè {mk}",
                                         f"OK ({len(merged)})")
                        st.success(f"✅ Đã ghi đè `{mk}`.")
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
        if st.button(f"⚠️ Ghi đè `{new_key}`", use_container_width=True,
                     key="btn_new_ow"):
            merged = merge_and_save(new_key, extracted, overwrite=True)
            write_system_log(ctx.username, f"Ghi đè {new_key}",
                             f"OK ({len(merged)})")
            st.success(f"✅ Đã ghi đè `{new_key}`.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()
    else:
        if st.button("🆕 Tạo hồ sơ mới", type="primary",
                     use_container_width=True, key="btn_new_mk"):
            merged = merge_and_save(new_key, extracted)
            write_system_log(ctx.username, f"Tạo mới {new_key}",
                             f"OK ({len(merged)})")
            st.success(f"✅ Đã tạo `{new_key}`.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()


def _render_upload_review_user(ctx, extracted, det_name, det_dob):
    existing = load_user_profile(ctx.own_profile)
    if not existing:
        st.info(f"📁 Hồ sơ **{ctx.own_profile}** chưa có dữ liệu. "
                f"Đây sẽ là lần nạp đầu tiên.")
        if st.button("💾 Lưu vào hồ sơ của tôi", type="primary",
                     use_container_width=True, key="u_first"):
            merged = merge_and_save(ctx.own_profile, extracted)
            write_system_log(ctx.username,
                             f"Nạp lần đầu vào {ctx.own_profile}",
                             f"OK ({len(merged)})")
            st.success(f"✅ Đã nạp {len(merged)} trường.")
            _reset_upload_state()
            time.sleep(0.5)
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
        if st.button("🔄 Gộp thêm", key="u_merge",
                     use_container_width=True, type="primary"):
            merged = merge_and_save(ctx.own_profile, extracted)
            write_system_log(ctx.username,
                             f"Gộp vào {ctx.own_profile}",
                             f"OK ({len(merged)})")
            st.success("✅ Đã gộp.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()
    with cc2:
        if st.button("♻️ Ghi đè", key="u_ow", use_container_width=True):
            merged = merge_and_save(ctx.own_profile, extracted, overwrite=True)
            write_system_log(ctx.username,
                             f"Ghi đè {ctx.own_profile}",
                             f"OK ({len(merged)})")
            st.success("✅ Đã ghi đè.")
            _reset_upload_state()
            time.sleep(0.5)
            st.rerun()


# =====================================================================
# SECTION 2: Fill form
# =====================================================================
def _render_form_section(ctx):
    st.markdown("---")
    st.subheader("📝 2. Điền biểu mẫu")

    templates_meta = list_form_templates()  # list[dict], KHÔNG có docx_bytes

    mode = st.radio(
        "Nguồn:", ["📚 Thư viện", "📤 Upload file mới"],
        horizontal=True, key="form_src_mode",
    )

    tid = fields = title = None

    if mode == "📚 Thư viện":
        tid, fields, title = _render_form_library(ctx, templates_meta)
    else:
        tid, fields, title = _render_form_upload(ctx, templates_meta)

    # Xử lý "use library template" được set từ _render_form_upload
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

    if st.button("✍️ Điền biểu mẫu", use_container_width=True,
                 type="primary", key="btn_fill"):
        _fill_form(ctx, tid, fields or [], title or tid,
                   sel_target, form_prompt)


def _render_form_library(ctx, templates_meta):
    """Trả về (tid, fields, title) hoặc (None, None, None)."""
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
            write_system_log(ctx.username,
                             f"Xóa form template '{sel_tid}'", "OK")
            st.success("Đã xóa.")
            st.rerun()

    return sel_tid, meta.get("fields", []), meta.get("title", sel_tid)


def _render_admin_template_tools(ctx, meta):
    with st.expander("⚙️ Tuỳ chỉnh mẫu (admin)", expanded=False):
        from form_prompts import CATEGORIES, CATEGORY_RULES
        cur_cat = meta.get("category", "other")
        idx = list(CATEGORIES.keys()).index(cur_cat) \
            if cur_cat in CATEGORIES else 0
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
    """
    Trả về (tid, fields, title) HOẶC (None, None, None).
    ⚠️ Luôn trả tid STRING, KHÔNG trả bytes — bytes được dùng nội bộ
    lúc lưu mẫu, sau khi lưu sẽ set `_use_lib_tid` để _fill_form dùng.
    """
    uploaded = st.file_uploader(
        "Upload file .docx (biểu mẫu trống hoặc đã điền)",
        type=["docx"], key="uploader_template",
    )
    if not uploaded:
        return None, None, None

    new_bytes = uploaded.getvalue()
    new_title = extract_document_title(new_bytes)
    matched_tid = match_template_by_title(new_title, templates) \
        if new_title else None

    # ---------- Đã có template khớp ----------
    if matched_tid:
        matched_meta = _find_template_meta(templates, matched_tid) or {}
        matched_title = matched_meta.get("title", matched_tid)

        st.success(f"✅ Khớp thư viện: **{matched_title}**")
        st.caption("Dùng mẫu sẵn có để tiết kiệm token.")

        if st.button("📚 Dùng mẫu thư viện", type="primary",
                     key="use_matched_tpl"):
            st.session_state["_use_lib_tid"] = matched_tid
            st.rerun()

        return None, None, None

    # ---------- Template mới ----------
    st.info(f"🆕 Biểu mẫu mới: **{new_title or '(chưa rõ tiêu đề)'}**")

    if st.button("🔍 Phân tích trường", key="btn_analyze_tpl"):
        with st.spinner("Đang trích xuất..."):
            f1 = extract_fields_heuristic(new_bytes)
            if len(f1) >= 3:
                st.session_state["_new_tpl_fields"] = f1
                st.session_state["_new_tpl_bytes"] = new_bytes
                st.session_state["_new_tpl_title"] = new_title
            else:
                prog = st.progress(10, text="🤖 AI đang trích...")
                f2, ai_title, _ai_cat = extract_fields_with_ai(
                    new_bytes, prog)
                prog.progress(100, text="✅")
                st.session_state["_new_tpl_fields"] = f2
                st.session_state["_new_tpl_bytes"] = new_bytes
                st.session_state["_new_tpl_title"] = new_title or ai_title
        st.rerun()

    if not st.session_state.get("_new_tpl_fields"):
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
        lbl = ("♻️ Lưu đè (đã lọc nội dung)" if existing
               else "💾 Lưu mẫu (đã lọc)")
        if st.button(lbl, type="primary", use_container_width=True,
                     key="btn_save_clean"):
            if not new_title_input.strip():
                st.error("Nhập tên biểu mẫu.")
            else:
                try:
                    clean = strip_personal_content(
                        st.session_state["_new_tpl_bytes"], fields)
                    save_form_template(
                        tid=new_tid,
                        title=new_title_input.strip(),
                        fields=fields,
                        docx_bytes=clean,
                        created_by=ctx.username,
                    )
                    write_system_log(
                        ctx.username,
                        f"Lưu form template '{new_tid}' (clean)", "OK")
                    # ⭐ Auto-select để user điền ngay sau rerun
                    st.session_state["_use_lib_tid"] = new_tid
                    for k in ("_new_tpl_fields", "_new_tpl_bytes",
                              "_new_tpl_title"):
                        st.session_state[k] = None
                    st.success(f"✅ Đã lưu mẫu **{new_title_input}**.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu mẫu: {e}")

    with cB:
        if st.button("💾 Lưu nguyên bản", use_container_width=True,
                     key="btn_save_raw"):
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
                    write_system_log(
                        ctx.username,
                        f"Lưu form template '{new_tid}' (raw)", "OK")
                    st.session_state["_use_lib_tid"] = new_tid
                    for k in ("_new_tpl_fields", "_new_tpl_bytes",
                              "_new_tpl_title"):
                        st.session_state[k] = None
                    st.success(f"✅ Đã lưu mẫu **{new_title_input}**.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi lưu mẫu: {e}")

    # Chưa lưu → không cho điền (tránh dùng bytes)
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


# =====================================================================
# TARGET RESOLUTION — không dùng st.stop(), trả None khi lỗi
# =====================================================================
def _resolve_target(ctx: UserContext, sel_target, form_prompt, progress):
    """
    Trả về target (str) hoặc None (khi lỗi/không xác định).
    KHÔNG dùng st.stop() — caller phải check return.
    """
    if ctx.is_power:
        target = None
        if sel_target and sel_target != "(tự động theo yêu cầu)":
            target = sel_target
        elif form_prompt and form_prompt.strip():
            found = find_profile_in_text(form_prompt, ctx.allowed_profiles)
            if found:
                target = found
            else:
                resolved, _, _, _ = resolve_profile(
                    form_prompt, ctx.allowed_profiles)
                target = resolved

        if not target:
            progress.empty()
            st.error("❌ Không xác định được hồ sơ đích. "
                     "Chọn dropdown hoặc nhập tên rõ ràng hơn "
                     "(vd: 'điền thông tin Vũ Dương vào form').")
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


# =====================================================================
# FILL FORM — restructure để tránh st.stop() bị catch
# =====================================================================
def _fill_form(ctx, tid, fields, title, sel_target, form_prompt):
    from form_prompts import build_fill_prompt

    progress = st.progress(5, text="📄 Đang chuẩn bị...")

    # --- Bước 1: target (không trong try lớn) ---
    target = _resolve_target(ctx, sel_target, form_prompt, progress)
    if not target:
        return

    # --- Bước 2: load template ---
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

    # --- Bước 3: profile ---
    tdata = load_user_profile(target)
    if not tdata:
        progress.empty()
        st.warning(f"⚠️ Hồ sơ **[{target}]** chưa có dữ liệu.")
        return

    # --- Bước 4: AI + ghi DOCX (try riêng) ---
    try:
        progress.progress(20, text="🧠 AI đang điền...")
        tdata_small = truncate_profile_for_prompt(tdata, MAX_CHARS // 2)
        prompt = build_fill_prompt(
            profile_data=json.dumps(tdata_small, ensure_ascii=False),
            template_markdown=meta["markdown"],
            category=meta.get("category", "other"),
            custom_prompt=meta.get("fill_prompt"),
        )

        jt = call_model_json(prompt, progress, 25, 80,
                             label="🤖 Đang điền")
        result = json.loads(jt)
        filled_md = result.get("filled_markdown", "")

        if not filled_md.strip():
            progress.empty()
            st.error("AI không trả về markdown.")
            return

        progress.progress(85, text="✍️ Đang ghi vào DOCX...")

        doc = Document(io.BytesIO(docx_bytes))
        filled_count = _apply_markdown_deltas(
            doc,
            original_md=meta["markdown"],
            filled_md=filled_md,
            fields=fields,
        )

        bio = io.BytesIO()
        doc.save(bio)
        docx_out = bio.getvalue()
        progress.progress(100, text=f"✅ Đã điền {filled_count} trường")

        write_system_log(
            ctx.username,
            f"Điền form '{title}' cho {target}",
            f"OK ({filled_count}/{len(fields)})",
        )

        st.success(f"✅ Đã điền **{filled_count}/{len(fields)}** trường "
                   f"cho **[{target}]**.")

        tab1, tab2 = st.tabs(["📝 Markdown (AI output)", "📄 DOCX (final)"])
        with tab1:
            st.markdown(filled_md)
        with tab2:
            render_docx_preview(docx_out, height=600)
            st.download_button(
                label=f"📥 Tải DOCX của {target}",
                data=docx_out,
                file_name=f"{target}_{tid}.docx",
                mime="application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
                use_container_width=True, key="btn_dl_filled",
            )
        st.download_button(
            label="📥 Tải Markdown (nhẹ)",
            data=filled_md.encode("utf-8"),
            file_name=f"{target}_{tid}.md",
            mime="text/markdown",
            use_container_width=True, key="btn_dl_md",
        )

    except Exception as e:
        progress.empty()
        write_system_log(ctx.username,
                         f"Điền form cho {title}", f"Lỗi ({e})")
        st.error(f"Lỗi: {e}")


# =====================================================================
# HELPERS
# =====================================================================
def _apply_markdown_deltas(doc, original_md, filled_md, fields):
    orig_lines = original_md.splitlines()
    filled_lines = filled_md.splitlines()
    deltas = {}
    for o, f in zip(orig_lines, filled_lines):
        if o == f:
            continue
        for fld in fields:
            pat = re.compile(
                rf"^(\s*(?:[-*]\s*)?{re.escape(fld)}\s*[:：])\s*(.*)$")
            mo = pat.match(o)
            mf = pat.match(f)
            if mo and mf and mo.group(2) != mf.group(2):
                deltas[fld] = mf.group(2).strip()
                break

    count = 0

    def _apply(p):
        nonlocal count
        for label, value in deltas.items():
            if not value:
                continue
            if _apply_value_to_paragraph(p, label, value):
                count += 1
                return

    for p in doc.paragraphs:
        _apply(p)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    _apply(p)
    return count


def _apply_value_to_paragraph(p, label, value):
    txt = p.text
    pat1 = re.compile(rf"^(\s*{re.escape(label)}\s*[:：]\s*)(.*)$")
    m = pat1.match(txt)
    if m:
        prefix = m.group(1)
        new = prefix + str(value)
        if p.runs:
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
        else:
            p.text = new
        return True

    pat2 = re.compile(rf"^(\s*{re.escape(label)})\s*\.{{3,}}.*$")
    m2 = pat2.match(txt)
    if m2:
        prefix = m2.group(1)
        new = prefix + " " + str(value)
        if p.runs:
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
        else:
            p.text = new
        return True
    return False