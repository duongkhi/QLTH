# ui/profile_ui.py
from __future__ import annotations
import base64
import io
import json
import re
import time
from datetime import datetime
import streamlit as st
from docx import Document

from config import UserContext, MAX_CHARS
from storage import (
    load_user_profile, save_user_profile, write_system_log,
    get_all_existing_profiles, load_name_mapping,
)
from security import detect_name_from_data, detect_dob_from_data
from profile_service import merge_and_save
from docx_utils import (
    extract_profile_document, ScannedPdfError, smart_truncate,
    render_docx_preview, truncate_profile_for_prompt, fix_tcvn3_text,
)
from ai_client import call_model_json, get_client
from form_templates import (
    list_form_templates, get_form_template, get_template_docx_bytes,
)

DEFAULT_PUBLIC_FIELDS = {
    "ho_va_ten", "ho_ten", "full_name", "hoc_ham", "hoc_vi",
    "chuc_vu", "don_vi", "don_vi_cong_tac", "email", "linh_vuc",
    "huong_nghien_cuu", "de_tai", "cong_bo", "bai_bao", "san_pham_khoa_hoc", "giai_thuong",
}

HEADER_AND_SECTION_KEYS = {
    "ho_va_ten", "ho_ten", "full_name",
    "hoc_ham", "hoc_vi", "hoc_ham_hoc_vi",
    "chuc_vu", "don_vi", "don_vi_cong_tac",
    "huong_nghien_cuu", "linh_vuc_nghien_cuu",
    "de_tai", "cong_bo", "bai_bao", "cong_trinh", "san_pham_khoa_hoc",
}

HIDDEN_SYSTEM_KEYS = {"_public_fields", "_updated_at", "_avatar_b64"}

# Các giá trị rỗng hoặc mang nghĩa phủ định không cần hiển thị lên CV
EMPTY_PLACEHOLDERS = {
    "", "không", "khong", "không có", "khong co", "chưa có", "chua co",
    "none", "null", "nan", "n/a", "na", "-", "--", "—", "0",
}

FIELD_LABELS_VI = {
    "ngay_sinh": "Ngày sinh",
    "gioi_tinh": "Giới tính",
    "que_quan": "Quê quán",
    "noi_sinh": "Nơi sinh",
    "dia_chi": "Địa chỉ liên hệ",
    "email": "Email",
    "dien_thoai": "Điện thoại",
    "so_dien_thoai": "Số điện thoại",
    "linh_vuc": "Lĩnh vực chuyên môn",
    "ngach_vien_chuc": "Ngạch viên chức",
    "chuc_danh": "Chức danh",
    "ngoai_ngu": "Ngoại ngữ",
    "hoc_ham": "Học hàm",
    "hoc_vi": "Học vị",
    "nam_phong_hoc_ham": "Năm phong học hàm",
    "nam_dat_hoc_vi": "Năm đạt học vị",
    "chuyen_nganh": "Chuyên ngành",
    "co_quan_cong_tac": "Cơ quan công tác",
    "giai_thuong": "Giải thưởng khoa học",
    "khen_thuong": "Khen thưởng",
    "can_nang": "Cân nặng",
    "chieu_cao": "Chiều cao",
    "cong_viec_chinh_duoc_giao": "Công việc chính được giao",
}


def _is_meaningful_value(val) -> bool:
    """Kiểm tra giá trị có thực sự có nội dung hay chỉ là rỗng / 'không'."""
    if val is None:
        return False
    if isinstance(val, (list, dict)):
        return len(val) > 0
    s = str(val).strip()
    return s.lower() not in EMPTY_PLACEHOLDERS


def _clean_text(val) -> str:
    """Trả về chuỗi sạch nếu có giá trị thực, ngược lại trả về chuỗi rỗng."""
    return str(val).strip() if _is_meaningful_value(val) else ""


def _format_label(key: str) -> str:
    return FIELD_LABELS_VI.get(key, key.replace("_", " ").capitalize())


# =====================================================================
# HÀM GẮN LINK TỰ ĐỘNG CHO TÊN CÁ NHÂN TRONG TOÀN HỆ THỐNG
# =====================================================================
def get_public_profile_links_map() -> dict[str, str]:
    mapping = load_name_mapping()
    name_to_key = {}
    for pk in get_all_existing_profiles():
        data = load_user_profile(pk)
        if not isinstance(data, dict) or not data:
            continue
        if "history" in data and len(data) == 1:
            continue
        valid_fields = [
            k for k, v in data.items()
            if not k.startswith("_") and _is_meaningful_value(v)
        ]
        if not valid_fields:
            continue
        disp = (
            _clean_text(data.get("ho_va_ten"))
            or _clean_text(data.get("ho_ten"))
            or _clean_text(data.get("full_name"))
            or _clean_text(mapping.get(pk, {}).get("display_name"))
        )
        if disp and len(disp) >= 3:
            name_to_key[disp] = pk
    return name_to_key


def linkify_profile_names(text: str, exclude_key: str = None) -> str:
    if not text:
        return text
    name_map = get_public_profile_links_map()
    if not name_map:
        return text
    sorted_names = sorted(name_map.keys(), key=len, reverse=True)
    result = str(text)
    for name in sorted_names:
        pk = name_map[name]
        if exclude_key and pk == exclude_key:
            continue
        pat = re.compile(rf"(?<!\[)\b({re.escape(name)})\b(?!\]\()", re.IGNORECASE)
        result = pat.sub(
            rf'<a class="profile-link" href="?profile={pk}" target="_self">\1</a>',
            result,
        )
    return result


# =====================================================================
# HELPER LỌC NĂM, RENDER AVATAR & TỔNG HỢP AI
# =====================================================================
def _extract_year(item) -> int | None:
    text = json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    return max(years) if years else None


def _render_avatar_html(data: dict, full_name: str) -> str:
    b64 = data.get("_avatar_b64")
    if b64:
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'style="width:136px;height:136px;border-radius:50%;object-fit:cover;'
            f'border:3px solid #3b82f6;box-shadow:0 4px 12px rgba(0,0,0,0.25);" />'
        )
    parts = [p for p in str(full_name).strip().split() if p]
    if len(parts) >= 2:
        initials = (parts[0][0] + parts[-1][0]).upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "CV"
    return (
        f'<div style="width:136px;height:136px;border-radius:50%;'
        f'background:linear-gradient(135deg,#2563eb,#7c3aed);'
        f'display:flex;align-items:center;justify-content:center;'
        f'color:#fff;font-size:46px;font-weight:700;letter-spacing:1px;'
        f'border:3px solid rgba(255,255,255,0.2);box-shadow:0 4px 12px rgba(0,0,0,0.25);">'
        f'{initials}</div>'
    )


def _generate_ai_research_summary(profile_key: str, data: dict) -> str:
    if not get_client():
        return ""
    current_year = datetime.now().year
    cutoff_10y = current_year - 10

    raw_items = []
    for k in ("cong_bo", "bai_bao", "cong_trinh", "san_pham_khoa_hoc", "de_tai"):
        val = data.get(k)
        if isinstance(val, list):
            for it in val:
                yr = _extract_year(it)
                if yr is None or yr >= cutoff_10y:
                    raw_items.append(it)

    context_payload = {
        "chuyen_nganh": _clean_text(data.get("chuyen_nganh")) or _clean_text(data.get("linh_vuc")),
        "don_vi": _clean_text(data.get("don_vi_cong_tac")) or _clean_text(data.get("don_vi")),
        "ket_qua_10_nam": raw_items[:40],
    }
    prompt = (
        f"Bạn là chuyên gia phân tích lý lịch khoa học. Hãy viết một đoạn tổng hợp ngắn gọn "
        f"(khoảng 4-6 câu, văn phong học thuật chuẩn mực bằng tiếng Việt) về **Hướng nghiên cứu chính** "
        f"của nhà khoa học dựa trên dữ liệu đề tài và công bố 10 năm gần nhất ({cutoff_10y} - {current_year}) dưới đây.\n"
        f"Nếu dữ liệu công bố ít, hãy tổng hợp dựa trên chuyên ngành và đơn vị công tác. Không bịa tên bài báo cụ thể.\n"
        f'Trả về JSON: {{"huong_nghien_cuu": "..."}}\n\n'
        f"Dữ liệu:\n{json.dumps(context_payload, ensure_ascii=False)}"
    )
    prog = st.progress(20, text="🤖 AI đang phân tích kết quả nghiên cứu 10 năm gần nhất...")
    try:
        out = call_model_json(prompt, prog, 25, 95, label="🤖 Tổng hợp hướng nghiên cứu")
        prog.empty()
        parsed = json.loads(out)
        summary = _clean_text(parsed.get("huong_nghien_cuu"))
        if summary:
            data["huong_nghien_cuu"] = summary
            pub = set(data.get("_public_fields", list(DEFAULT_PUBLIC_FIELDS)))
            pub.add("huong_nghien_cuu")
            data["_public_fields"] = list(pub)
            save_user_profile(profile_key, data)
        return summary
    except Exception as e:
        prog.empty()
        st.error(f"Không thể tổng hợp bằng AI: {e}")
        return ""


# =====================================================================
# 1. TRANG CÁ NHÂN PUBLIC (BỐ CỤC CHUẨN CV KHOA HỌC)
# =====================================================================
def render_public_profile(ctx: UserContext, target_profile_key: str):
    data = load_user_profile(target_profile_key)

    if not data:
        st.title(f"👤 {target_profile_key}")
        st.info("Hồ sơ này chưa cập nhật thông tin công khai.")
        return

    full_name = (
        _clean_text(data.get("ho_va_ten"))
        or _clean_text(data.get("ho_ten"))
        or _clean_text(data.get("full_name"))
        or target_profile_key
    )
    hoc_ham = _clean_text(data.get("hoc_ham"))
    hoc_vi = _clean_text(data.get("hoc_vi"))
    prefix_title = " ".join(x for x in [hoc_ham, hoc_vi] if x).strip()

    if prefix_title and not full_name.lower().startswith(prefix_title.lower()):
        sep = " " if prefix_title.endswith(".") else ". "
        display_heading = f"{prefix_title}{sep}{full_name}"
    else:
        display_heading = full_name

    chuc_vu = _clean_text(data.get("chuc_vu"))
    don_vi = _clean_text(data.get("don_vi_cong_tac")) or _clean_text(data.get("don_vi"))

    # =========================================================
    # HEADER: AVATAR LỚN BÊN TRÁI + HỌ TÊN & CHỨC VỤ BÊN PHẢI
    # (Đã bỏ nút Setting trùng lặp vì đã có ở Sidebar)
    # =========================================================
    col_av, col_info = st.columns([1.4, 6.2], vertical_alignment="center")

    with col_av:
        st.markdown(_render_avatar_html(data, full_name), unsafe_allow_html=True)

    with col_info:
        st.markdown(
            f"<h1 style='margin:0 0 8px 0;font-size:2.3rem;line-height:1.2;'>{display_heading}</h1>",
            unsafe_allow_html=True,
        )
        if chuc_vu:
            st.markdown(
                f"<div style='font-size:1.25rem;font-weight:600;color:#60a5fa;margin-bottom:6px;'>{chuc_vu}</div>",
                unsafe_allow_html=True,
            )
        if don_vi:
            st.markdown(
                f"<div style='font-size:1.1rem;opacity:0.88;'>🏛️ {don_vi}</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    configured_public = data.get("_public_fields")
    allowed_keys = (
        set(configured_public)
        if isinstance(configured_public, list)
        else DEFAULT_PUBLIC_FIELDS
    )

    # =========================================================
    # MỤC I: THÔNG TIN CHUNG (LỌC BỎ RỖNG & CHỮ "KHÔNG")
    # =========================================================
    st.markdown("### I. Thông tin chung")
    general_items = {
        k: v for k, v in data.items()
        if k not in HIDDEN_SYSTEM_KEYS
        and k not in HEADER_AND_SECTION_KEYS
        and not isinstance(v, (list, dict))
        and (k in allowed_keys or k in DEFAULT_PUBLIC_FIELDS)
        and _is_meaningful_value(v)
    }

    if general_items:
        cols = st.columns(2)
        for idx, (k, v) in enumerate(general_items.items()):
            label = _format_label(k)
            linked_val = linkify_profile_names(_clean_text(v), exclude_key=target_profile_key)
            with cols[idx % 2]:
                st.markdown(
                    f"<div style='font-size:1.08rem;margin-bottom:8px;'><strong>{label}:</strong> {linked_val}</div>",
                    unsafe_allow_html=True,
                )
    else:
        st.caption("Không có thông tin bổ sung được công khai.")

    st.markdown("---")

    # =========================================================
    # MỤC II: HƯỚNG NGHIÊN CỨU
    # =========================================================
    col_ii_title, col_ii_ai = st.columns([4.5, 2.2], vertical_alignment="center")
    with col_ii_title:
        st.markdown("### II. Hướng nghiên cứu")

    can_trigger_ai = st.session_state.logged_in and (
        ctx.own_profile == target_profile_key or ctx.role in ("admin", "manager")
    )
    research_dir = _clean_text(data.get("huong_nghien_cuu")) or _clean_text(data.get("linh_vuc_nghien_cuu"))

    with col_ii_ai:
        if can_trigger_ai:
            btn_label = "🤖 AI tổng hợp (10 năm)" if not research_dir else "🔄 AI cập nhật hướng NC"
            if st.button(btn_label, key=f"btn_ai_res_{target_profile_key}", use_container_width=True):
                new_summary = _generate_ai_research_summary(target_profile_key, data)
                if new_summary:
                    st.rerun()

    if research_dir:
        st.markdown(
            f"<div style='background:rgba(59,130,246,0.08);border-left:4px solid #3b82f6;"
            f"padding:16px 20px;border-radius:6px;font-size:1.08rem;line-height:1.7;'>{research_dir}</div>",
            unsafe_allow_html=True,
        )
    else:
        hint_txt = (
            " Bấm nút **AI tổng hợp (10 năm)** ở góc phải để tự động tổng hợp từ kết quả nghiên cứu."
            if can_trigger_ai
            else ""
        )
        st.info("Chưa có mô tả hướng nghiên cứu." + hint_txt)

    st.markdown("---")

    # =========================================================
    # MỤC III: KẾT QUẢ NGHIÊN CỨU (SẢN PHẨM KHOA HỌC 5 NĂM GẦN NHẤT)
    # =========================================================
    current_year = datetime.now().year
    cutoff_5y = current_year - 4

    col_iii_title, col_iii_filter = st.columns([4.5, 2.2], vertical_alignment="center")
    with col_iii_title:
        st.markdown(f"### III. Kết quả nghiên cứu ({cutoff_5y} – {current_year})")
    with col_iii_filter:
        show_all_years = st.checkbox(
            "Hiển thị tất cả các năm",
            value=False,
            key=f"chk_all_yrs_{target_profile_key}",
        )

    pub_list = []
    for k in ("san_pham_khoa_hoc", "cong_bo", "bai_bao", "cong_trinh"):
        val = data.get(k)
        if isinstance(val, list):
            pub_list.extend(val)

    filtered_pubs = []
    for item in pub_list:
        if not _is_meaningful_value(item):
            continue
        yr = _extract_year(item)
        if show_all_years or yr is None or yr >= cutoff_5y:
            filtered_pubs.append(item)

    if filtered_pubs:
        st.markdown("#### 📄 Công bố khoa học & Sản phẩm trí tuệ")
        for idx, item in enumerate(filtered_pubs, 1):
            if isinstance(item, dict):
                title = (
                    _clean_text(item.get("ten_bai_bao"))
                    or _clean_text(item.get("ten"))
                    or _clean_text(item.get("title"))
                    or str(item)
                )
                journal = _clean_text(item.get("tap_chi")) or _clean_text(item.get("noi_cong_bo"))
                year = _clean_text(item.get("nam")) or str(_extract_year(item) or "")
                authors = _clean_text(item.get("tac_gia"))
                line = f"**{idx}.** {title}"
                meta_parts = [
                    p for p in [
                        authors,
                        f"*{journal}*" if journal else "",
                        f"({year})" if year else "",
                    ]
                    if p
                ]
                if meta_parts:
                    line += " — " + ", ".join(meta_parts)
                st.markdown(
                    linkify_profile_names(line, exclude_key=target_profile_key),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f"**{idx}.** {linkify_profile_names(str(item), exclude_key=target_profile_key)}",
                    unsafe_allow_html=True,
                )

    projects = data.get("de_tai", [])
    filtered_projects = []
    if isinstance(projects, list):
        for dt in projects:
            if not _is_meaningful_value(dt):
                continue
            yr = _extract_year(dt)
            if show_all_years or yr is None or yr >= cutoff_5y:
                filtered_projects.append(dt)

    if filtered_projects:
        st.markdown("#### 📑 Đề tài & Dự án nghiên cứu")
        for idx, dt in enumerate(filtered_projects, 1):
            if isinstance(dt, dict):
                ten = _clean_text(dt.get("ten_de_tai")) or "Chưa đặt tên"
                ma = _clean_text(dt.get("ma_so"))
                vai_tro = _clean_text(dt.get("vai_tro"))
                thoi_gian = _clean_text(dt.get("thoi_gian"))
                trang_thai = _clean_text(dt.get("trang_thai"))
                with st.container(border=True):
                    st.markdown(f"**{idx}. {ten}**" + (f" (`{ma}`)" if ma else ""))
                    sub_parts = [
                        f"Vai trò: **{vai_tro}**" if vai_tro else "",
                        f"Thời gian: {thoi_gian}" if thoi_gian else "",
                        f"Trạng thái: {trang_thai}" if trang_thai else "",
                    ]
                    sub_line = " · ".join(p for p in sub_parts if p)
                    if sub_line:
                        st.caption(sub_line)
            else:
                st.markdown(f"- {dt}")

    if not filtered_pubs and not filtered_projects:
        st.info(
            f"Chưa có kết quả nghiên cứu nào được ghi nhận trong giai đoạn {cutoff_5y} – {current_year}."
        )


# =====================================================================
# 2. GIAO DIỆN SETTING (3 TAB DÀNH CHO CÁ NHÂN ĐÃ SIGN IN)
# =====================================================================
def render_settings_page(ctx: UserContext):
    col_t, col_b = st.columns([4, 1.5])
    with col_t:
        st.title("⚙️ Setting Hồ Sơ Cá Nhân")
        st.caption(
            f"Tài khoản: **{ctx.username}** · Hồ sơ gắn kết: **{ctx.own_profile or 'Chưa gán'}**"
        )
    with col_b:
        st.write("")
        if ctx.own_profile and st.button("👁️ Xem trang Public", use_container_width=True):
            st.session_state.viewing_profile = ctx.own_profile
            st.session_state.view_mode = "public_profile"
            st.rerun()

    if not ctx.own_profile:
        st.warning("⚠️ Tài khoản của bạn chưa được gán hồ sơ cá nhân. Vui lòng liên hệ Admin.")
        return

    tab_info, tab_cv, tab_projects = st.tabs([
        "👤 Thông tin cá nhân & Avatar",
        "🎓 Lý lịch khoa học",
        "📑 Quản lý đề tài & Công bố",
    ])

    with tab_info:
        _render_tab_personal_info(ctx)
    with tab_cv:
        _render_tab_scientific_cv(ctx)
    with tab_projects:
        _render_tab_projects(ctx)


def _render_tab_personal_info(ctx: UserContext):
    data = load_user_profile(ctx.own_profile) or {}

    st.subheader("1. Ảnh đại diện (Avatar)")
    c_av1, c_av2 = st.columns([1.2, 4], vertical_alignment="center")
    with c_av1:
        full_name = _clean_text(data.get("ho_va_ten")) or ctx.own_profile
        st.markdown(_render_avatar_html(data, full_name), unsafe_allow_html=True)
    with c_av2:
        av_file = st.file_uploader(
            "Tải lên ảnh chân dung (.png, .jpg, .jpeg)",
            type=["png", "jpg", "jpeg"],
            key="up_avatar",
        )
        if av_file and st.button("🖼️ Lưu ảnh đại diện", type="primary"):
            data["_avatar_b64"] = base64.b64encode(av_file.getvalue()).decode("utf-8")
            save_user_profile(ctx.own_profile, data)
            st.success("✅ Đã cập nhật ảnh đại diện!")
            st.rerun()

    st.markdown("---")
    st.subheader("2. Nạp tự động từ file CV / Lý lịch (.docx hoặc .pdf)")
    _render_personal_uploader(ctx)

    st.markdown("---")
    st.subheader("3. Chỉnh sửa chi tiết & Cấu hình hiển thị Public")
    data = load_user_profile(ctx.own_profile) or {}

    editable_keys = [
        k for k in data.keys()
        if k not in HIDDEN_SYSTEM_KEYS and not isinstance(data[k], (list, dict))
    ]
    current_public = set(data.get("_public_fields", list(DEFAULT_PUBLIC_FIELDS)))

    with st.form("form_edit_personal_info"):
        updated_values = {}
        new_public_list = []

        if editable_keys:
            h1, h2, h3 = st.columns([2, 4, 1.2])
            h1.markdown("**Trường dữ liệu**")
            h2.markdown("**Giá trị**")
            h3.markdown("**Public?**")

            for k in editable_keys:
                c1, c2, c3 = st.columns([2, 4, 1.2])
                c1.text_input(
                    "Key",
                    value=_format_label(k),
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"lbl_{k}",
                )
                val = c2.text_input(
                    "Val",
                    value=str(data.get(k, "")),
                    label_visibility="collapsed",
                    key=f"val_{k}",
                )
                is_pub = c3.checkbox(
                    "Public",
                    value=(k in current_public),
                    label_visibility="collapsed",
                    key=f"pub_{k}",
                )
                updated_values[k] = val
                if is_pub:
                    new_public_list.append(k)

        st.markdown("**➕ Thêm trường mới (tuỳ chọn):**")
        nc1, nc2, nc3 = st.columns([2, 4, 1.2])
        new_k = nc1.text_input("Tên trường (VD: hoc_vi, huong_nghien_cuu)", key="new_field_k")
        new_v = nc2.text_input("Giá trị", key="new_field_v")
        new_pub = nc3.checkbox("Public", value=True, key="new_field_pub")

        if st.form_submit_button("💾 Lưu thay đổi", type="primary", use_container_width=True):
            for k, v in updated_values.items():
                data[k] = v
            if new_k.strip():
                clean_k = re.sub(r"[^a-zA-Z0-9_]", "_", new_k.strip().lower())
                data[clean_k] = new_v.strip()
                if new_pub:
                    new_public_list.append(clean_k)

            for list_k in ("de_tai", "cong_bo", "san_pham_khoa_hoc"):
                if list_k in current_public:
                    new_public_list.append(list_k)

            data["_public_fields"] = list(set(new_public_list))
            save_user_profile(ctx.own_profile, data)
            write_system_log(ctx.username, f"Cập nhật hồ sơ {ctx.own_profile}", "OK")
            st.success("✅ Đã lưu thông tin và quyền hiển thị Public!")
            time.sleep(0.5)
            st.rerun()


def _render_personal_uploader(ctx: UserContext):
    stage = st.session_state.get("upload_stage")

    if stage is None:
        upf = st.file_uploader(
            "Chọn file hồ sơ (.docx hoặc .pdf có lớp văn bản)",
            type=["docx", "pdf"],
            key="personal_uploader_file",
        )
        if upf:
            st.session_state["_upload_profile_bytes"] = upf.getvalue()
            st.session_state["_upload_profile_name"] = upf.name
            st.session_state.upload_stage = "processing"
            st.rerun()

    elif stage == "processing":
        if not get_client():
            st.error("⚠️ Chưa cấu hình GEMINI_API_KEY.")
            st.session_state.upload_stage = None
            return

        prog = st.progress(10, text="📄 Đang đọc file...")
        try:
            raw_bytes = st.session_state.get("_upload_profile_bytes")
            filename = st.session_state.get("_upload_profile_name", "profile.docx")
            raw = smart_truncate(extract_profile_document(raw_bytes, filename))
            prog.progress(25, text="🤖 AI đang trích xuất thông tin...")

            prompt = (
                "Trích xuất TOÀN BỘ thông tin cá nhân và khoa học từ văn bản sau thành JSON "
                "(key viết thường, gạch dưới, tiếng Việt không dấu). Trường nào không có trong văn bản thì để null hoặc bỏ qua (KHÔNG ghi chữ 'không').\n"
                "Bắt buộc có:\n"
                "- 'ho_va_ten', 'hoc_ham', 'hoc_vi', 'chuc_vu', 'don_vi_cong_tac', 'ngay_sinh' (DD/MM/YYYY) nếu có.\n"
                "- 'huong_nghien_cuu': đoạn mô tả hướng nghiên cứu chính nếu có.\n"
                "- 'cong_bo': danh sách mảng các công trình/bài báo khoa học "
                '(mỗi phần tử là dict {"ten_bai_bao", "tac_gia", "tap_chi", "nam"}).\n'
                "- 'de_tai': danh sách mảng các đề tài nghiên cứu "
                '(mỗi phần tử là dict {"ten_de_tai", "ma_so", "vai_tro", "thoi_gian", "trang_thai"}).\n\n'
                f'Văn bản:\n"""{raw}"""'
            )
            jt = call_model_json(prompt, prog, 30, 95, label="🤖 Đang phân tích CV")
            extracted = json.loads(jt)
            prog.progress(100, text="✅ Hoàn tất")

            st.session_state.upload_extracted = extracted
            st.session_state.upload_detected_name = detect_name_from_data(extracted)
            st.session_state.upload_detected_dob = detect_dob_from_data(extracted)
            st.session_state.upload_stage = "review"
            st.rerun()

        except ScannedPdfError:
            prog.empty()
            st.warning(
                "⚠️ **File PDF này là bản scan ảnh (không có lớp văn bản - text layer).**\n\n"
                "👉 Vui lòng dùng **[iLovePDF OCR PDF](https://www.ilovepdf.com/ocr-pdf)** "
                "(chọn ngôn ngữ **Vietnamese**) để tạo lớp văn bản trước khi upload lại."
            )
            if st.button("🔄 Chọn file khác", key="btn_retry_scan_personal"):
                st.session_state.upload_stage = None
                st.rerun()
        except Exception as e:
            prog.empty()
            st.error(f"Lỗi đọc file: {e}")
            st.session_state.upload_stage = None

    elif stage == "review":
        extracted = st.session_state.upload_extracted or {}
        st.success(f"✅ Trích xuất được **{len(extracted)} trường** dữ liệu.")
        with st.expander("👁️ Xem dữ liệu trích xuất", expanded=True):
            st.json(extracted)

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("🔄 Gộp vào hồ sơ", type="primary", use_container_width=True):
                merge_and_save(ctx.own_profile, extracted)
                st.session_state.upload_stage = None
                st.success("✅ Đã gộp vào hồ sơ!")
                time.sleep(0.5)
                st.rerun()
        with c2:
            if st.button("♻️ Ghi đè hồ sơ", use_container_width=True):
                merge_and_save(ctx.own_profile, extracted, overwrite=True)
                st.session_state.upload_stage = None
                st.success("✅ Đã ghi đè hồ sơ!")
                time.sleep(0.5)
                st.rerun()
        with c3:
            if st.button("❌ Hủy", use_container_width=True):
                st.session_state.upload_stage = None
                st.rerun()


def _render_tab_scientific_cv(ctx: UserContext):
    st.subheader("🎓 Xuất & Điền Mẫu Lý Lịch Khoa Học")
    templates = list_form_templates()
    if not templates:
        st.info("Thư viện biểu mẫu chưa có mẫu nào.")
        return

    labels = {
        t["id"]: f"{t['title']} ({len(t.get('fields', []))} trường)"
        for t in templates
    }
    tpl_ids = [t["id"] for t in templates]
    sel_tid = st.selectbox(
        "Chọn mẫu Lý lịch khoa học / Biểu mẫu:",
        options=tpl_ids,
        format_func=lambda x: labels[x],
        key="cv_tpl_select",
    )

    if st.button("✍️ Điền tự động từ hồ sơ của tôi", type="primary", use_container_width=True):
        meta = get_form_template(sel_tid)
        docx_bytes = get_template_docx_bytes(sel_tid)
        tdata = load_user_profile(ctx.own_profile)

        if not meta or not docx_bytes or not tdata:
            st.error("Thiếu dữ liệu mẫu hoặc hồ sơ cá nhân trống.")
            return

        prog = st.progress(15, text="🤖 AI đang điền thông tin...")
        try:
            fields = meta.get("fields", [])
            tdata_small = truncate_profile_for_prompt(tdata, MAX_CHARS // 2)
            prompt = (
                "Điền thông tin từ HỒ SƠ sau vào các TRƯỜNG của biểu mẫu.\n"
                f"HỒ SƠ: {json.dumps(tdata_small, ensure_ascii=False)}\n"
                f"CÁC TRƯỜNG: {json.dumps(fields, ensure_ascii=False)}\n"
                'Trả về JSON object { "Tên trường": "Giá trị" }, không bịa đặt.'
            )
            jt = call_model_json(prompt, prog, 20, 80, label="🤖 Đang map dữ liệu")
            filled_json = json.loads(jt)

            doc = Document(io.BytesIO(docx_bytes))
            filled_count = 0

            def _fill_p(p, label, value):
                txt = fix_tcvn3_text(p.text)
                if not txt.strip():
                    return False
                pat = re.compile(
                    rf"({re.escape(fix_tcvn3_text(label))}\s*[:：]\s*)(.*)$",
                    re.IGNORECASE,
                )
                m = pat.search(txt)
                if m:
                    new_t = txt[:m.start(2)] + str(value)
                    for r in p.runs:
                        r.text = ""
                    if p.runs:
                        p.runs[0].text = new_t
                    else:
                        p.add_run(new_t)
                    return True
                return False

            for p in doc.paragraphs:
                for k, v in filled_json.items():
                    if v and _fill_p(p, k, v):
                        filled_count += 1
            for tbl in doc.tables:
                for row in tbl.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            for k, v in filled_json.items():
                                if v and _fill_p(p, k, v):
                                    filled_count += 1

            bio = io.BytesIO()
            doc.save(bio)
            out_bytes = bio.getvalue()
            prog.progress(100, text=f"✅ Đã điền {filled_count} trường")

            render_docx_preview(out_bytes, height=550)
            st.download_button(
                "📥 Tải về file (.docx)",
                data=out_bytes,
                file_name=f"LLKH_{ctx.own_profile}_{sel_tid}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as e:
            prog.empty()
            st.error(f"Lỗi xuất lý lịch: {e}")


def _render_tab_projects(ctx: UserContext):
    st.subheader("📑 Quản Lý Đề Tài & Công Bố Khoa Học")
    data = load_user_profile(ctx.own_profile) or {}
    projects = data.get("de_tai", [])
    if not isinstance(projects, list):
        projects = []

    with st.expander("➕ Thêm đề tài mới", expanded=len(projects) == 0):
        with st.form("form_add_project"):
            ten_dt = st.text_input("Tên đề tài *")
            c1, c2 = st.columns(2)
            ma_so = c1.text_input("Mã số đề tài")
            vai_tro = c2.selectbox(
                "Vai trò",
                ["Chủ nhiệm đề tài", "Thư ký khoa học", "Thành viên chính", "Thành viên"],
            )
            c3, c4 = st.columns(2)
            thoi_gian = c3.text_input("Thời gian thực hiện (VD: 2025 - 2027)")
            trang_thai = c4.selectbox(
                "Trạng thái",
                ["Đang thực hiện", "Đã nghiệm thu", "Đề xuất mới"],
            )

            if st.form_submit_button("💾 Thêm đề tài", type="primary"):
                if not ten_dt.strip():
                    st.error("Vui lòng nhập tên đề tài.")
                else:
                    projects.append({
                        "ten_de_tai": ten_dt.strip(),
                        "ma_so": ma_so.strip(),
                        "vai_tro": vai_tro,
                        "thoi_gian": thoi_gian.strip(),
                        "trang_thai": trang_thai,
                    })
                    data["de_tai"] = projects
                    pub = set(data.get("_public_fields", list(DEFAULT_PUBLIC_FIELDS)))
                    pub.add("de_tai")
                    data["_public_fields"] = list(pub)
                    save_user_profile(ctx.own_profile, data)
                    st.success("✅ Đã thêm đề tài!")
                    st.rerun()

    if projects:
        for idx, dt in enumerate(projects):
            with st.container(border=True):
                col_info, col_del = st.columns([5, 1])
                with col_info:
                    st.markdown(
                        f"**{idx + 1}. {dt.get('ten_de_tai', '')}** (`{dt.get('ma_so', 'N/A')}`)"
                    )
                    st.caption(
                        f"Vai trò: {dt.get('vai_tro')} · Thời gian: {dt.get('thoi_gian')} · "
                        f"Trạng thái: {dt.get('trang_thai')}"
                    )
                with col_del:
                    if st.button("🗑️ Xóa", key=f"del_dt_{idx}", use_container_width=True):
                        projects.pop(idx)
                        data["de_tai"] = projects
                        save_user_profile(ctx.own_profile, data)
                        st.rerun()
    else:
        st.info("Chưa có đề tài nào được lưu.")