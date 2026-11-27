# ui/salary_management.py
import streamlit as st
import json
import io
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from storage import load_json_from_db, save_json_to_db
from ai_client import generate_gemini_text_real
from docx_utils import extract_text_from_pdf_bytes, fix_tcvn3_text
from user_service import get_salary_profiles
from security import _strip_diacritics

SALARY_KEY = "salary_profiles"
SALARY_OUTPUT_KEY = "salary_output"


def _load_salary_data() -> dict:
    return load_json_from_db(SALARY_KEY) or {}


def _save_salary_data(data: dict) -> bool:
    return save_json_to_db(SALARY_KEY, data)


def _load_salary_outputs() -> list:
    return load_json_from_db(SALARY_OUTPUT_KEY) or []


def _save_salary_outputs(outputs: list) -> bool:
    return save_json_to_db(SALARY_OUTPUT_KEY, outputs)


def _read_pdf_first_page(file_bytes: bytes) -> str:
    try:
        import pymupdf
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
            if doc.page_count == 0:
                return ""
            page = doc[0]
            text = page.get_text("text")
            if not text or len(text.strip()) < 10:
                rawdict = page.get_text("rawdict")
                lines = []
                for block in rawdict.get("blocks", []):
                    for line in block.get("lines", []):
                        chars = [ch.get("c", "") for span in line.get("spans", []) for ch in span.get("chars", [])]
                        lines.append("".join(chars))
                text = "\n".join(lines)
            return fix_tcvn3_text(text or "")
    except Exception:
        return ""


def _extract_qd_luong(text: str) -> dict:
    if not text or not text.strip():
        return {}
    prompt = (
        "Ban la tro ly trich xuat thong tin tu van ban quyet dinh luong/can bo.\n"
        "Hay doc van ban sau va trich xuat cac thong tin (neu co):\n"
        "1. Ngay quyet dinh (dd/mm/yyyy)\n2. So quyet dinh\n3. Ma ngach\n4. Bac luong\n"
        "5. He so luong\n6. Luong co ban (so)\n7. Phu cap (neu co, so)\n8. Ghi chu ngan ve noi dung quyet dinh\n\n"
        "Tra ve CHI duy mot doi tuong JSON thuan khiet, khong markdown:\n"
        '{"ngay": "...", "so_quyet_dinh": "...", "ma_ngach": "...", '
        '"bac_luong": "...", "he_so_luong": "...", "luong_co_ban": "...", '
        '"phu_cap": "...", "ghi_chu": "..."}\n'
        "Neu truong nao khong co, de chuoi rong \"\".\n\nVan ban:\n" + text[:4000]
    )
    try:
        resp = generate_gemini_text_real(prompt)
        if not resp:
            return {}
        resp = resp.strip()
        if resp.startswith("```json"):
            resp = resp[7:]
        if resp.startswith("```"):
            resp = resp[3:]
        if resp.endswith("```"):
            resp = resp[:-3]
        resp = resp.strip()
        data = json.loads(resp)
        if not isinstance(data, dict):
            return {}
        return {
            "ngay": str(data.get("ngay", "") or "").strip(),
            "so_quyet_dinh": str(data.get("so_quyet_dinh", "") or "").strip(),
            "ma_ngach": str(data.get("ma_ngach", "") or "").strip(),
            "bac_luong": str(data.get("bac_luong", "") or "").strip(),
            "he_so_luong": str(data.get("he_so_luong", "") or "").strip(),
            "luong_co_ban": str(data.get("luong_co_ban", "") or "").strip(),
            "phu_cap": str(data.get("phu_cap", "") or "").strip(),
            "ghi_chu": str(data.get("ghi_chu", "") or "").strip(),
        }
    except Exception:
        return {}


def _loc_lich_su_tu_nam_truoc(lich_su: list) -> list:
    if not lich_su:
        return []
    now = datetime.now()
    nam_truoc = now.year - 1
    tu_ngay = datetime(nam_truoc, 1, 1)
    ket_qua = []
    for item in lich_su:
        try:
            d = datetime.strptime(item.get("ngay", ""), "%d/%m/%Y")
            if d >= tu_ngay:
                ket_qua.append(item)
        except Exception:
            ket_qua.append(item)
    return ket_qua


def _get_latest_change(rec: dict) -> dict:
    lich_su = rec.get("lich_su_bien_dong_luong", [])
    if not lich_su:
        return {}
    return max(lich_su, key=lambda b: (b.get("nam", 0), b.get("thang", 0)))


def _load_smtp_config() -> dict:
    cfg = load_json_from_db("smtp_config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def _save_smtp_config(cfg: dict) -> bool:
    return save_json_to_db("smtp_config", cfg)


def _send_salary_email(to_email: str, subject: str, body: str) -> bool:
    cfg = _load_smtp_config()
    smtp_server = cfg.get("smtp_server", "")
    try:
        smtp_port = int(cfg.get("smtp_port", 587) or 587)
    except Exception:
        smtp_port = 587
    smtp_user = cfg.get("smtp_user", "")
    smtp_password = cfg.get("smtp_password", "")
    smtp_from = cfg.get("smtp_from", smtp_user)
    if not smtp_server:
        try:
            import streamlit as st
            smtp_server = st.secrets.get("SMTP_SERVER", "")
            smtp_port = int(st.secrets.get("SMTP_PORT", 587))
            smtp_user = st.secrets.get("SMTP_USER", "")
            smtp_password = st.secrets.get("SMTP_PASSWORD", "")
            smtp_from = st.secrets.get("SMTP_FROM", smtp_user)
        except Exception:
            pass
    if smtp_server and smtp_user and smtp_password:
        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_from
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
            server.quit()
            print(f"[Email] Da gui den {to_email}: {subject}")
            return True
        except Exception as e:
            print(f"[Email] Loi gui den {to_email}: {e}")
            return False
    else:
        print("=" * 60)
        print(f"[EMAIL PREVIEW] To: {to_email}")
        print(f"[EMAIL PREVIEW] Subject: {subject}")
        print("-" * 60)
        print(body)
        print("=" * 60)
        return True


def _build_notice_body(ho_ten: str, thang: str, nam: str, loai: str, latest: dict) -> str:
    he_so = latest.get("he_so_luong", "")
    tien_luong = latest.get("tien_luong", "")
    tong_cong = latest.get("tong_cong", "")
    bac_luong = latest.get("bac_luong", "")
    luong_cb = latest.get("luong_cb", "")
    ghi_chu = latest.get("ghi_chu", "")
    if loai == "Bien che":
        loai_display = "Bien che"
    elif loai == "Hop dong":
        loai_display = "Hop dong"
    else:
        loai_display = "Khac"
    body = f"""Kính gửi {ho_ten},

Day la thong bao luong thang {thang}/{nam} cua ban.

Loai hinh lao dong: {loai_display}
- Bac luong: {bac_luong if bac_luong else '—'}
- He so luong: {he_so if he_so else '—'}
- Luong co ban: {luong_cb if luong_cb else '—'}
- Tien luong: {tien_luong if tien_luong else '—'}
- Tong luong thuc linh: {tong_cong if tong_cong else '—'}

"""
    if ghi_chu:
        body += f"- Ghi chu: {ghi_chu}\n"
    body += """
Trong trong,
Phong Ke toan - Vien Vat ly

"""
    return body


def render_salary_management_page(ctx):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.title("💰 Quan tri Luong")
    st.caption("Chi Admin va Ke toan luong (Manager duoc phan quyen) duoc truy cap.")
    data = get_salary_profiles()
    if not isinstance(data, dict):
        data = {}
    users_with_salary = {}
    for uid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        lich_su = rec.get("lich_su_bien_dong_luong", [])
        if isinstance(lich_su, list) and lich_su:
            users_with_salary[uid] = rec
    latest_map = {}
    for uid, rec in users_with_salary.items():
        latest_map[uid] = _get_latest_change(rec)

    tab_tong_hop, tab_thong_bao = st.tabs(["📊 Tong hop", "📋 Thong bao luong"])

    # =========================================================
    # TAB TỔNG HỢP
    # =========================================================
    with tab_tong_hop:
        st.markdown("### 📊 Tong hop luong thang")
        st.caption("Danh sach tat ca can bo co ho so luong. Moi hang co nut 'Xem', 'Xoa', 'Sua'.")

        if "salary_tab1_search" not in st.session_state:
            st.session_state["salary_tab1_search"] = ""
        if "salary_tab1_search_input" not in st.session_state:
            st.session_state["salary_tab1_search_input"] = ""

        def _on_tab1_search_change():
            st.session_state["salary_tab1_search"] = st.session_state["salary_tab1_search_input"]
            st.session_state["salary_tab1_page"] = 1

        search_q = st.text_input(
            "🔍 Tim kiem (ten, email, phong ban...)",
            value=st.session_state.get("salary_tab1_search", ""),
            placeholder="Nhap ten, email hoac phong ban...",
            key="salary_tab1_search_input",
            on_change=_on_tab1_search_change,
            label_visibility="collapsed",
        )
        search_lower = (st.session_state.get("salary_tab1_search", "") or "").strip().lower()
        filtered_items = []
        for uid, rec in users_with_salary.items():
            ho_ten = rec.get("ho_va_ten", uid)
            email = rec.get("email", "")
            phong = rec.get("don_vi_cong_tac_phong", "")
            haystack = f"{uid} {ho_ten} {email} {phong}".lower()
            if not search_lower or search_lower in haystack:
                filtered_items.append((uid, rec))
        filtered_items.sort(key=lambda x: x[1].get("ho_va_ten", ""))
        total = len(filtered_items)
        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)
        if "salary_tab1_page" not in st.session_state:
            st.session_state["salary_tab1_page"] = 1
        page = st.session_state["salary_tab1_page"]
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        st.session_state["salary_tab1_page"] = page
        start = (page - 1) * per_page
        end = start + per_page
        page_items = filtered_items[start:end]

        # =========================================================
        # ANH XA VIET TAT PHONG BAN (chi hien thi, luu du lieu chua thay doi)
        # =========================================================
        DON_VI_RUT_GON = {
            "Trung tinh Dien tu luong tu": "ĐTLT",
            "Trung tinh Vat ly hat nhan": "VLHN",
            "Trung tinh Vat ly ky thuat": "VLKT",
            "Trung tinh Vat ly ly thuyet": "VLLT",
            "Trung tinh Vat ly tinh toan": "VLTT",
            "Trung tinh Vat ly ung dung va Thiet bi khoa hoc": "VLUĐTK",
            "Phong tu dong hoa": "PTHĐ",
            "Phong quan ly tong hop": "PQLTH",
        }

        def _rut_gon_phong(ten: str) -> str:
            for full, short in DON_VI_RUT_GON.items():
                if full in ten:
                    return short
            return ten

        # Render bang luong theo HTML table (cot cot deu co border, font nho, header can giua 2 dong, so can phai, ho ten can trai)
        # Ty le cot: Ho ten(2.2) Phong(0.9) He so(0.7 x4) Luong(1.4)
        col_widths = [2.2, 0.9, 0.7, 0.7, 0.7, 0.7, 1.4]
        html_rows = []
        for i, (uid, rec) in enumerate(page_items):
            ho_ten = rec.get("ho_va_ten", uid)
            phong_full = rec.get("don_vi_cong_tac_phong", "")
            phong_display = _rut_gon_phong(phong_full) if phong_full else "—"
            latest = latest_map.get(uid, {})
            bac_luong = str(latest.get("bac_luong", "") or "—")
            he_so_luong = str(latest.get("he_so_luong", "") or "—")
            he_so_dh = str(latest.get("he_so_doc_hai_theo_vi_tri", "") or "—")
            he_so_pc_ld = str(latest.get("pc_ld", "") or "—")
            tong_cong = latest.get("tong_cong", "")
            tong_cong_str = f"{tong_cong:,.0f} đ" if tong_cong else "—"

            html_rows.append(
                f"<tr>"
                f"<td class='name'>{ho_ten}</td>"
                f"<td class='cen'>{phong_display}</td>"
                f"<td class='num'>{bac_luong}</td>"
                f"<td class='num'>{he_so_luong}</td>"
                f"<td class='num'>{he_so_dh}</td>"
                f"<td class='num'>{he_so_pc_ld}</td>"
                f"<td class='luong num'>{tong_cong_str}</td>"
                f"</tr>"
            )

        table_html = f"""
        <table class="salary-table">
            <thead>
                <tr>
                    <th>Ho ten</th>
                    <th>Phong</th>
                    <th>Bac<br>luong</th>
                    <th>He so<br>Luong</th>
                    <th>He so<br>doc hai</th>
                    <th>He so<br>phu cap LD</th>
                    <th class="luong">Luong</th>
                </tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
        """
        st.markdown(table_html, unsafe_allow_html=True)

        if total > per_page:
            st.markdown("---")
            nav_cols = st.columns([1, 2, 1])
            with nav_cols[0]:
                if st.button("◀ Trang truoc", key="btn_tab1_prev", disabled=(page <= 1), width='stretch'):
                    st.session_state["salary_tab1_page"] = page - 1
                    st.rerun()
            with nav_cols[1]:
                st.markdown(f"**Trang {page} / {total_pages}** · **{total} nguoi**")
            with nav_cols[2]:
                if st.button("Trang sau ▶", key="btn_tab1_next", disabled=(page >= total_pages), width='stretch'):
                    st.session_state["salary_tab1_page"] = page + 1
                    st.rerun()

        # Label ngoài container; trong container chỉ còn ô nhập và 3 nút chức năng
        st.markdown("---")
        st.caption("Nhập họ tên cán bộ cần thao tác")
        # Giới hạn tổng chiều rộng của hàng hành động; ô nhập và các nút có kích thước cố định (rem), nút sát nhau và căn trái
        st.markdown(
            """
            <style>
            div[data-testid="stHorizontalBlock"]:has(input[placeholder="Nhập họ và tên cán bộ..."]) {
                max-width: 72rem !important;
                width: 100% !important;
                gap: 0.5rem !important;
            }
            div[data-testid="stHorizontalBlock"]:has(input[placeholder="Nhập họ và tên cán bộ..."]) .stTextInput > div > div > input {
                width: 30rem !important;
                max-width: 30rem !important;
            }
            div[data-testid="stHorizontalBlock"]:has(input[placeholder="Nhập họ và tên cán bộ..."]) .stButton > button {
                width: auto !important;
                min-width: 4rem !important;
                max-width: 6rem !important;
                padding: 0.2rem 0.6rem !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        with st.container():
            fu_c1, fu_c2, fu_c3, fu_c4 = st.columns([9, 1, 1, 1])
            with fu_c1:
                fullname_input = st.text_input(
                    "",
                    key="salary_fullname_input",
                    placeholder="Nhập họ và tên cán bộ...",
                    label_visibility="collapsed",
                )
            with fu_c2:
                if st.button("📄", key="btn_table_view_full", help="Xem chi tiết lương của cán bộ này"):
                    matched_uid = None
                    q = _strip_diacritics(fullname_input.strip().lower()).replace(" ", "")
                    for uid, rec in users_with_salary.items():
                        ten = rec.get("ho_va_ten", "")
                        if _strip_diacritics(ten.lower()).replace(" ", "") == q:
                            matched_uid = uid
                            break
                    if matched_uid:
                        st.session_state["salary_view_uid"] = matched_uid
                        st.session_state["salary_edit_uid"] = None
                        st.rerun()
                    else:
                        st.warning(f"⚠️ Không tìm thấy cán bộ có họ tên: {fullname_input}")
            with fu_c3:
                if st.button("🗑️", key="btn_table_del_full", help="Xóa toàn bộ biến động"):
                    matched_uid = None
                    q = _strip_diacritics(fullname_input.strip().lower()).replace(" ", "")
                    for uid, rec in users_with_salary.items():
                        ten = rec.get("ho_va_ten", "")
                        if _strip_diacritics(ten.lower()).replace(" ", "") == q:
                            matched_uid = uid
                            break
                    if matched_uid:
                        data[matched_uid]["lich_su_bien_dong_luong"] = []
                        data[matched_uid]["cap_nhat_luc"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                        if _save_salary_data(data):
                            st.success(f"✅ Đã xóa toàn bộ biến động của {fullname_input}.")
                            st.rerun()
                        else:
                            st.error("❌ Không xóa được dữ liệu.")
                    else:
                        st.warning(f"⚠️ Không tìm thấy cán bộ có họ tên: {fullname_input}")
            with fu_c4:
                if st.button("✏️", key="btn_table_edit_full", help="Chỉnh sửa biến động"):
                    matched_uid = None
                    q = _strip_diacritics(fullname_input.strip().lower()).replace(" ", "")
                    for uid, rec in users_with_salary.items():
                        ten = rec.get("ho_va_ten", "")
                        if _strip_diacritics(ten.lower()).replace(" ", "") == q:
                            matched_uid = uid
                            break
                    if matched_uid:
                        st.session_state["salary_edit_uid"] = matched_uid
                        st.session_state["salary_view_uid"] = None
                        st.rerun()
                    else:
                        st.warning(f"⚠️ Không tìm thấy cán bộ có họ tên: {fullname_input}")

        view_uid = st.session_state.get("salary_view_uid")
        if view_uid and view_uid in users_with_salary:
            rec = users_with_salary[view_uid]
            ho_ten = rec.get("ho_va_ten", view_uid)
            latest = latest_map.get(view_uid, {})
            with st.expander(f"📄 Chi tiet luong: {ho_ten}", expanded=True):
                st.markdown(f"### 👤 {ho_ten} (@{view_uid})")
                st.markdown(f"**Phong:** {rec.get('don_vi_cong_tac_phong', '') or '—'}")
                st.markdown("**Thong tin luong gan nhat (chi xem):**")
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown(f"- Bac luong: {latest.get('bac_luong', '') or '—'}")
                    st.markdown(f"- He so luong: {latest.get('he_so_luong', '') or '—'}")
                    st.markdown(f"- Luong co ban: {latest.get('luong_cb', '') or '—'}")
                    st.markdown(f"- Phu cap LD: {latest.get('pc_ld', '') or '—'}")
                with col_b:
                    st.markdown(f"- He so vuot khung: {latest.get('he_so_vuot_khung', '') or '—'}")
                    st.markdown(f"- He so doc hai (vt): {latest.get('he_so_doc_hai_theo_vi_tri', '') or '—'}")
                    st.markdown(f"- He so doc hai (tien): {latest.get('he_so_doc_hai_tien', '') or '—'}")
                    st.markdown(f"- Tong cong: {latest.get('tong_cong', '') or '—'}")
                st.markdown(f"- Ngay hieu luc: {latest.get('ngay_hieu_luc', '') or '—'}")
                st.markdown(f"- So quyet dinh: {latest.get('quyet_dinh_so', '') or '—'}")
                st.markdown(f"- Thang/Nam: {latest.get('thang', '')}/{latest.get('nam', '')}")
                if latest.get("ly_do_bien_dong"):
                    st.markdown(f"- Ly do: {latest['ly_do_bien_dong']}")
                if latest.get("ghi_chu"):
                    st.markdown(f"- Ghi chu: {latest['ghi_chu']}")

    # =========================================================
    # TAB THÔNG BÁO LƯƠNG
    # =========================================================
    with tab_thong_bao:
        h_title, h_cfg = st.columns([6, 1])
        with h_title:
            st.markdown("### 📋 Thong bao luong")
            st.caption("Tao mau thong bao luong theo loai (Bien che / Hop dong / Khach) va gui email.")
        with h_cfg:
            st.write("")
            if st.button("⚙️ Configure", key="btn_smtp_config", width='stretch'):
                st.session_state["smtp_config_open"] = True

        if st.session_state.get("smtp_config_open", False):
            smtp_cfg = _load_smtp_config()
            with st.popover("⚙️ Cau hinh SMTP gui thong bao luong", use_container_width=True):
                st.markdown("**Cau hinh SMTP**")
                with st.form("form_smtp_config_popover", clear_on_submit=False):
                    s_c1, s_c2 = st.columns(2)
                    s_server = s_c1.text_input("SMTP Server", value=smtp_cfg.get("smtp_server", ""), key="pop_smtp_server")
                    s_port = s_c2.text_input("Port", value=str(smtp_cfg.get("smtp_port", 587)), key="pop_smtp_port")
                    s_user = s_c1.text_input("Tai khoan SMTP", value=smtp_cfg.get("smtp_user", ""), key="pop_smtp_user")
                    s_pass = s_c2.text_input("Mat khau SMTP", type="password", value=smtp_cfg.get("smtp_password", ""), key="pop_smtp_password")
                    s_from = s_c1.text_input("Email gui tu (From)", value=smtp_cfg.get("smtp_from", smtp_cfg.get("smtp_user", "")), key="pop_smtp_from")
                    st.info("💡 Neu dung Gmail, hay tao App Password (Mat khau ung dung) thay vi mat khau dang nhap thuong.")
                    pc1, pc2 = st.columns(2)
                    with pc1:
                        if st.form_submit_button("💾 Luu", width='stretch'):
                            new_cfg = {
                                "smtp_server": (s_server or "").strip(),
                                "smtp_port": (s_port or "").strip(),
                                "smtp_user": (s_user or "").strip(),
                                "smtp_password": (s_pass or "").strip(),
                                "smtp_from": ((s_from or s_user or "").strip()),
                            }
                            if _save_smtp_config(new_cfg):
                                st.success("✅ Da luu cau hinh SMTP.")
                                st.session_state["smtp_config_open"] = False
                                st.rerun()
                            else:
                                st.error("❌ Khong luu duoc cau hinh SMTP.")
                    with pc2:
                        if st.form_submit_button("❌ Dong", width='stretch'):
                            st.session_state["smtp_config_open"] = False
                            st.rerun()
            smtp_cfg = _load_smtp_config()
            if smtp_cfg.get("smtp_server"):
                st.success(f"✅ Da cau hinh SMTP: {smtp_cfg.get('smtp_server')} (tai khoan: {smtp_cfg.get('smtp_user')})")
            else:
                st.info("Chua cau hinh SMTP. He thong se chi preview noi dung email ra terminal.")

        st.markdown("---")
        st.markdown("#### 🔍 Tim kiem nguoi nhan")
        if "salary_notice_search" not in st.session_state:
            st.session_state["salary_notice_search"] = ""
        if "salary_notice_search_input" not in st.session_state:
            st.session_state["salary_notice_search_input"] = ""

        def _on_notice_search_change():
            st.session_state["salary_notice_search"] = st.session_state["salary_notice_search_input"]
            st.session_state["salary_notice_selected_uid"] = ""

        search_notice = st.text_input(
            "Nhap username hoac fullname",
            value=st.session_state.get("salary_notice_search", ""),
            placeholder="Nhap username hoac ho ten...",
            key="salary_notice_search_input",
            on_change=_on_notice_search_change,
            label_visibility="collapsed",
        )
        search_notice_lower = (st.session_state.get("salary_notice_search", "") or "").strip().lower()
        matched_uid = None
        matched_rec = None
        if search_notice_lower:
            for uid, rec in users_with_salary.items():
                ho_ten = rec.get("ho_va_ten", uid)
                email = rec.get("email", "")
                if search_notice_lower in uid.lower() or search_notice_lower in ho_ten.lower() or search_notice_lower in email.lower():
                    matched_uid = uid
                    matched_rec = rec
                    break

        if matched_uid and matched_rec:
            st.session_state["salary_notice_selected_uid"] = matched_uid
            ho_ten = matched_rec.get("ho_va_ten", matched_uid)
            email = matched_rec.get("email", "")
            latest = latest_map.get(matched_uid, {})
            loai = latest.get("loai", "Khac")
            st.success(f"✅ Tim thay: **{ho_ten}** (@{matched_uid})")
            st.markdown(f"**Email:** {email if email else '—'}")
            st.markdown(f"**Loai:** {loai}")

            st.markdown("#### 📋 Chon loai thong bao")
            loai_selected = st.session_state.get("notice_loai_selected", loai)
            loai_col1, loai_col2, loai_col3 = st.columns(3)
            with loai_col1:
                if st.checkbox("Bien che", value=(loai_selected == "Bien che"), key="cb_loai_bien_che"):
                    loai_selected = "Bien che"
                    st.session_state["notice_loai_selected"] = "Bien che"
            with loai_col2:
                if st.checkbox("Hop dong", value=(loai_selected == "Hop dong"), key="cb_loai_hop_dong"):
                    loai_selected = "Hop dong"
                    st.session_state["notice_loai_selected"] = "Hop dong"
            with loai_col3:
                if st.checkbox("Khac", value=(loai_selected == "Khac"), key="cb_loai_khac"):
                    loai_selected = "Khac"
                    st.session_state["notice_loai_selected"] = "Khac"
            notice_body = _build_notice_body(ho_ten, str(latest.get("thang", "")), str(latest.get("nam", "")), loai_selected, latest)
            st.markdown("#### 📄 Xem truoc noi dung email")
            st.text_area("Noi dung email", value=notice_body, height=300, key="notice_preview_body")
            st.markdown("#### 👥 Chon nguoi nhan")
            preset_options = []
            preset_data = {}
            if email:
                label_1 = f"👤 Nguoi vua tim thay: {ho_ten}"
                preset_options.append(label_1)
                preset_data[label_1] = [{"uid": matched_uid, "ho_ten": ho_ten, "email": email}]
            phong_set = sorted({r2.get("don_vi_cong_tac_phong", "") for r2 in users_with_salary.values() if r2.get("don_vi_cong_tac_phong")})
            for p in phong_set:
                label_p = f"🏢 Phong: {p}"
                preset_options.append(label_p)
                recv_list = []
                for u2, r2 in users_with_salary.items():
                    if r2.get("don_vi_cong_tac_phong") == p and r2.get("email"):
                        recv_list.append({"uid": u2, "ho_ten": r2.get("ho_va_ten", u2), "email": r2.get("email")})
                preset_data[label_p] = recv_list
            loai_map = {"Bien che": "Bien che", "Hop dong": "Hop dong"}
            for loai_val, label_loai in loai_map.items():
                label_l = f"🏷️ Loai: {label_loai}"
                preset_options.append(label_l)
                recv_list = []
                for u2, r2 in users_with_salary.items():
                    if _get_latest_change(r2).get("loai") == loai_val and r2.get("email"):
                        recv_list.append({"uid": u2, "ho_ten": r2.get("ho_va_ten", u2), "email": r2.get("email")})
                preset_data[label_l] = recv_list
            label_all = "📋 Tat ca can bo"
            preset_options.append(label_all)
            recv_all = []
            for u2, r2 in users_with_salary.items():
                if r2.get("email"):
                    recv_all.append({"uid": u2, "ho_ten": r2.get("ho_va_ten", u2), "email": r2.get("email")})
            preset_data[label_all] = recv_all

            selected_preset = st.selectbox("Chon nhom nguoi nhan", options=preset_options, key="notice_preset_select")
            recv_list = preset_data.get(selected_preset, [])
            if recv_list:
                st.info(f"Da chon **{len(recv_list)}** nguoi nhan co email.")
                st.caption(", ".join([f"{r['ho_ten']} ({r['email']})" for r in recv_list[:5]]) + ("..." if len(recv_list) > 5 else ""))
            else:
                st.warning("⚠️ Nhom nay chua co nguoi nhan nao co email.")
            subject_default = f"[Luong thang {latest.get('thang', '')}/{latest.get('nam', '')}] Thong bao luong cua {ho_ten}"
            subject = st.text_input("Tieu de email", value=subject_default, key="notice_subject")
            body = st.text_area("Noi dung email (co the chinh sua)", value=notice_body, height=350, key="notice_body")
            if st.button("📧 Gui thong bao luong", type="primary", key="btn_send_notice", width='stretch'):
                if not recv_list:
                    st.warning("⚠️ Khong co nguoi nhan nao trong nhom da chon.")
                else:
                    sent_count = 0
                    fail_count = 0
                    for r in recv_list:
                        ok = _send_salary_email(r["email"], subject, body)
                        if ok:
                            sent_count += 1
                        else:
                            fail_count += 1
                    if sent_count > 0:
                        st.success(f"✅ Da gui thong bao luong cho {sent_count} nguoi.")
                    if fail_count > 0:
                        st.error(f"❌ Khong gui duoc cho {fail_count} nguoi.")
        else:
            if search_notice_lower:
                st.warning("Khong tim thay can bo nao khop voi tu khoa tim kiem.")
            else:
                st.info("Nhap username hoac fullname vao o tim kiem o tren de tra cuu va tao thong bao luong.")

    # =========================================================
    # SUA BIEN DONG LUONG (popover)
    # =========================================================
    edit_uid = st.session_state.get("salary_edit_uid")
    if edit_uid and edit_uid in users_with_salary:
        rec = users_with_salary[edit_uid]
        ho_ten = rec.get("ho_va_ten", edit_uid)
        latest = latest_map.get(edit_uid, {})
        with st.expander(f"✏️ Chinh sua bien dong: {ho_ten}", expanded=True):
            st.markdown(f"### ✏️ Chinh sua thong tin luong: {ho_ten} (@{edit_uid})")
            st.caption("Sua gia tri tung truong. Neu co thay doi, nut 'Luu' se bat de bo sung bien dong moi.")
            tmp_key = f"tmp_edit_{edit_uid}"
            if tmp_key not in st.session_state:
                st.session_state[tmp_key] = dict(latest)
            tmp = st.session_state[tmp_key]
            e_c1, e_c2 = st.columns(2)
            with e_c1:
                tmp["nam"] = st.number_input("Nam", min_value=2000, max_value=2100, value=int(tmp.get("nam") or datetime.now().year), key=f"e_nam_{edit_uid}")
                tmp["thang"] = st.number_input("Thang", min_value=1, max_value=12, value=int(tmp.get("thang") or datetime.now().month), key=f"e_thang_{edit_uid}")
                tmp["ngay_hieu_luc"] = st.text_input("Ngay hieu luc (dd/mm/yyyy)", value=tmp.get("ngay_hieu_luc", ""), key=f"e_ngay_{edit_uid}")
                tmp["quyet_dinh_so"] = st.text_input("So quyet dinh", value=tmp.get("quyet_dinh_so", ""), key=f"e_qd_{edit_uid}")
                tmp["bac_luong"] = st.text_input("Bac luong", value=tmp.get("bac_luong", ""), key=f"e_bac_{edit_uid}")
                tmp["he_so_luong"] = st.text_input("He so luong", value=tmp.get("he_so_luong", ""), key=f"e_hsl_{edit_uid}")
                tmp["luong_cb"] = st.text_input("Luong co ban", value=tmp.get("luong_cb", ""), key=f"e_lcb_{edit_uid}")
            with e_c2:
                tmp["tien_luong"] = st.text_input("Tien luong", value=tmp.get("tien_luong", ""), key=f"e_tl_{edit_uid}")
                tmp["phu_cap"] = st.text_input("Phu cap", value=tmp.get("phu_cap", ""), key=f"e_pc_{edit_uid}")
                tmp["tong_cong"] = st.text_input("Tong cong", value=tmp.get("tong_cong", ""), key=f"e_tc_{edit_uid}")
                tmp["pc_ld"] = st.text_input("Phu cap LD", value=tmp.get("pc_ld", ""), key=f"e_pcld_{edit_uid}")
                tmp["he_so_vuot_khung"] = st.text_input("He so vuot khung", value=tmp.get("he_so_vuot_khung", ""), key=f"e_vk_{edit_uid}")
                tmp["he_so_doc_hai_theo_vi_tri"] = st.text_input("He so doc hai (vt)", value=tmp.get("he_so_doc_hai_theo_vi_tri", ""), key=f"e_dh1_{edit_uid}")
                tmp["he_so_doc_hai_tien"] = st.text_input("He so doc hai (tien)", value=tmp.get("he_so_doc_hai_tien", ""), key=f"e_dh2_{edit_uid}")
            tmp["doc_hai_theo_luong"] = st.text_input("Doc hai theo luong", value=tmp.get("doc_hai_theo_luong", ""), key=f"e_dh3_{edit_uid}")
            tmp["doc_hai_tien"] = st.text_input("Doc hai tien", value=tmp.get("doc_hai_tien", ""), key=f"e_dh4_{edit_uid}")
            tmp["truy_linh"] = st.text_input("Truy linh", value=tmp.get("truy_linh", ""), key=f"e_tl1_{edit_uid}")
            tmp["bhiem_10_5"] = st.text_input("BH 10,5%", value=tmp.get("bhiem_10_5", ""), key=f"e_bh_{edit_uid}")
            tmp["truy_thu"] = st.text_input("Truy thu", value=tmp.get("truy_thu", ""), key=f"e_tt_{edit_uid}")
            tmp["tien_tinh_thue"] = st.text_input("Tien tinh thue", value=tmp.get("tien_tinh_thue", ""), key=f"e_tt2_{edit_uid}")
            tmp["ghi_chu"] = st.text_area("Ghi chu", value=tmp.get("ghi_chu", ""), key=f"e_ghichu_{edit_uid}")
            tmp["ly_do_bien_dong"] = st.text_area("Ly do bien dong (bat buoc)", value=tmp.get("ly_do_bien_dong", ""), key=f"e_lydo_{edit_uid}")
            da_thay_doi = False
            for k, v in latest.items():
                if str(tmp.get(k, "")) != str(v or ""):
                    da_thay_doi = True
                    break
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("💾 Luu bien dong", type="primary", disabled=not da_thay_doi or not tmp.get("ly_do_bien_dong"), key=f"btn_save_edit_{edit_uid}", width='stretch'):
                    if not tmp.get("ly_do_bien_dong"):
                        st.error("❌ Vui long nhap ly do bien dong.")
                    else:
                        moi = {
                            "nam": int(tmp.get("nam") or datetime.now().year),
                            "thang": int(tmp.get("thang") or datetime.now().month),
                            "ngay_hieu_luc": tmp.get("ngay_hieu_luc", ""),
                            "quyet_dinh_so": tmp.get("quyet_dinh_so", ""),
                            "ban_cung_luu_o_dau": tmp.get("ban_cung_luu_o_dau", ""),
                            "bac_luong": tmp.get("bac_luong", ""),
                            "ly_do_bien_dong": tmp.get("ly_do_bien_dong", ""),
                            "stt": tmp.get("stt", ""),
                            "pc_ld": tmp.get("pc_ld", ""),
                            "pc_ld_bang_tien": tmp.get("pc_ld_bang_tien", ""),
                            "he_so_luong": tmp.get("he_so_luong", ""),
                            "luong_he_so": tmp.get("luong_he_so", ""),
                            "vuot_khung": tmp.get("vuot_khung", ""),
                            "he_so_vuot_khung": tmp.get("he_so_vuot_khung", ""),
                            "vuot_khung_bang_tien": tmp.get("vuot_khung_bang_tien", ""),
                            "phan_tram_huong": tmp.get("phan_tram_huong", ""),
                            "luong_cb": tmp.get("luong_cb", ""),
                            "he_so_doc_hai_theo_vi_tri": tmp.get("he_so_doc_hai_theo_vi_tri", ""),
                            "he_so_doc_hai_tien": tmp.get("he_so_doc_hai_tien", ""),
                            "doc_hai_theo_luong": tmp.get("doc_hai_theo_luong", ""),
                            "doc_hai_tien": tmp.get("doc_hai_tien", ""),
                            "truy_linh": tmp.get("truy_linh", ""),
                            "bhiem_10_5": tmp.get("bhiem_10_5", ""),
                            "truy_thu": tmp.get("truy_thu", ""),
                            "tong_cong": tmp.get("tong_cong", ""),
                            "ghi_chu": tmp.get("ghi_chu", ""),
                            "tien_tinh_thue": tmp.get("tien_tinh_thue", ""),
                        }
                        rec["lich_su_bien_dong_luong"].append(moi)
                        rec["lich_su_bien_dong_luong"] = sorted(rec["lich_su_bien_dong_luong"], key=lambda b: (b.get("nam", 0), b.get("thang", 0)))
                        data[edit_uid] = rec
                        if _save_salary_data(data):
                            st.success("✅ Da luu bien dong luong moi.")
                            st.session_state[tmp_key] = {}
                            st.session_state["salary_edit_uid"] = None
                            st.rerun()
                        else:
                            st.error("❌ Khong luu duoc du lieu.")
            with col_cancel:
                if st.button("❌ Huy", key=f"btn_cancel_edit_{edit_uid}", width='stretch'):
                    st.session_state[tmp_key] = {}
                    st.session_state["salary_edit_uid"] = None
                    st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)
