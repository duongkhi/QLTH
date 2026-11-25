# ui/salary_management.py
# Quản trị lương - Chỉ Admin/Manager được truy cập
# Dữ liệu lưu trên Supabase key `salary_profiles` (JSONB)
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
from user_service import tra_cuu_luong, get_salary_profiles, lay_luong_theo_thang

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
    """Đọc văn bản trang đầu PDF để trích xuất (tiết kiệm token)."""
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
                        chars = [
                            ch.get("c", "")
                            for span in line.get("spans", [])
                            for ch in span.get("chars", [])
                        ]
                        lines.append("".join(chars))
                text = "\n".join(lines)
            return fix_tcvn3_text(text or "")
    except Exception:
        return ""


def _extract_qd_luong(text: str) -> dict:
    """Gọi Gemini trích xuất thông tin từ văn bản quyết định lương."""
    if not text or not text.strip():
        return {}
    prompt = (
        "Bạn là trợ lý trích xuất thông tin từ văn bản quyết định lương/cán bộ.\n"
        "Hãy đọc văn bản sau và trích xuất các thông tin (nếu có):\n"
        "1. Ngày quyết định (dd/mm/yyyy)\n"
        "2. Số quyết định\n"
        "3. Mã ngạch\n"
        "4. Bậc lương\n"
        "5. Hệ số lương\n"
        "6. Lương cơ bản (số)\n"
        "7. Phụ cấp (nếu có, số)\n"
        "8. Ghi chú ngắn về nội dung quyết định\n\n"
        "Trả về CHỈ duy nhất một đối tượng JSON thuần khiết, không markdown:\n"
        '{"ngay": "...", "so_quyet_dinh": "...", "ma_ngach": "...", '
        '"bac_luong": "...", "he_so_luong": "...", "luong_co_ban": "...", '
        '"phu_cap": "...", "ghi_chu": "..."}\n'
        "Nếu trường nào không có, để chuỗi rỗng \"\".\n\n"
        "Văn bản:\n"
        f"{text[:4000]}"
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
    """Chỉ giữ các bản ghi từ 1/1 của năm trước đến nay."""
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
            # Nếu không parse được ngày, vẫn giữ lại
            ket_qua.append(item)
    return ket_qua


def _load_smtp_config() -> dict:
    """Đọc cấu hình SMTP từ Supabase (key smtp_config)."""
    cfg = load_json_from_db("smtp_config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def _save_smtp_config(cfg: dict) -> bool:
    """Lưu cấu hình SMTP lên Supabase (key smtp_config)."""
    return save_json_to_db("smtp_config", cfg)


def _send_salary_email(to_email: str, subject: str, body: str) -> bool:
    """Gửi email thông báo lương.

    Đọc cấu hình SMTP từ Supabase (key smtp_config) trước. Nếu không có,
    fallback sang st.secrets. Nếu cả hai đều không có, in preview ra console.
    """
    cfg = _load_smtp_config()
    smtp_server = cfg.get("smtp_server", "")
    try:
        smtp_port = int(cfg.get("smtp_port", 587) or 587)
    except Exception:
        smtp_port = 587
    smtp_user = cfg.get("smtp_user", "")
    smtp_password = cfg.get("smtp_password", "")
    smtp_from = cfg.get("smtp_from", smtp_user)

    # Fallback sang st.secrets nếu Supabase không có
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
            print(f"[Email] Đã gửi đến {to_email}: {subject}")
            return True
        except Exception as e:
            print(f"[Email] Lỗi gửi đến {to_email}: {e}")
            return False
    else:
        # Chưa cấu hình SMTP -> in preview ra console
        print("=" * 60)
        print(f"[EMAIL PREVIEW] To: {to_email}")
        print(f"[EMAIL PREVIEW] Subject: {subject}")
        print("-" * 60)
        print(body)
        print("=" * 60)
        return True


def render_salary_management_page(ctx):
    st.title("💰 Quản trị Lương")
    st.caption("Chỉ Admin và Kế toán lương (Manager được phân quyền) được truy cập.")

    # =================================================================
    # BẢNG DANH SÁCH CÁN BỘ LƯƠNG THÁNG (gộp tìm kiếm + gửi thông báo)
    # =================================================================

    summary = load_json_from_db("salary_monthly_summary") or {}
    thang = summary.get("thang", "-")
    nam = summary.get("nam", "-")

    if not summary or not summary.get("du_lieu"):
        st.info("Chưa có dữ liệu tổng hợp lương tháng. Vui lòng đồng bộ từ file Excel trước.")
    else:
        du_lieu = summary["du_lieu"]
        if not isinstance(du_lieu, list):
            du_lieu = []

        # -----------------------
        # Ô tìm kiếm
        # -----------------------
        def _on_salary_table_search_change():
            st.session_state["salary_table_search"] = st.session_state["salary_table_search_input"]
            st.session_state["salary_table_page"] = 1

        search_q = st.text_input(
            "🔍 Tìm kiếm (tên, email, mã ngạch...)",
            value=st.session_state.get("salary_table_search", ""),
            placeholder="Nhập tên, email hoặc mã ngạch...",
            key="salary_table_search_input",
            on_change=_on_salary_table_search_change,
            label_visibility="collapsed",
        )
        search_lower = (st.session_state.get("salary_table_search", "") or "").strip().lower()

        # Lọc danh sách theo từ khóa (tên, email, mã ngạch, nguồn lương, trạng thái)
        filtered = []
        for item in du_lieu:
            nguon = ", ".join(item.get("nguon_luong", []))
            trang_thai = item.get("trang_thai", "")
            haystack = f"{item.get('ho_ten','')} {item.get('email','')} {item.get('ma_ngach','')} {nguon} {trang_thai} {item.get('tong_cong','')}".lower()
            if not search_lower or search_lower in haystack:
                filtered.append(item)

        total = len(filtered)
        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)

        # Khởi tạo trạng thái phân trang và chọn email
        if "salary_table_page" not in st.session_state:
            st.session_state["salary_table_page"] = 1
        page = st.session_state["salary_table_page"]
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        st.session_state["salary_table_page"] = page

        if "salary_selected_indices" not in st.session_state:
            st.session_state["salary_selected_indices"] = []
        if "salary_chk_suffix" not in st.session_state:
            st.session_state["salary_chk_suffix"] = 0

        start = (page - 1) * per_page
        end = start + per_page
        page_items = filtered[start:end]

        # -----------------------
        # Header bảng
        # -----------------------
        hc1, hc2, hc3, hc4, hc5, hc6, hc7, hc8, hc9, hc10 = st.columns([0.5, 2, 2.5, 1, 1.5, 1.5, 1.2, 1, 1, 1])
        hc1.markdown("**STT**")
        hc2.markdown("**Họ tên**")
        hc3.markdown("**Email**")
        hc4.markdown("**Mã ngạch**")
        hc5.markdown("**Nguồn lương**")
        hc6.markdown("**Hệ số**")
        hc7.markdown("**Lương thực nhận**")
        hc8.markdown("**Trạng thái**")
        hc9.markdown("**Chi tiết**")
        hc10.markdown("**Nhận email**")

    if summary and summary.get("du_lieu"):
        # Lọc các cán bộ có email
        du_lieu = summary["du_lieu"]
        co_email = [item for item in du_lieu if item.get("email")]
        khong_email = [item for item in du_lieu if not item.get("email")]

        # -----------------------
        # Các hàng dữ liệu
        # -----------------------
        selected_indices = set(st.session_state.get("salary_selected_indices", []))
        chk_suffix = st.session_state.get("salary_chk_suffix", 0)

        for i, item in enumerate(page_items):
            idx = start + i
            ho_ten = item.get("ho_ten", "")
            email = item.get("email", "")
            ma_ngach = item.get("ma_ngach", "")
            nguon_luong = ", ".join(item.get("nguon_luong", []))
            tong_cong = item.get("tong_cong", 0)
            trang_thai = item.get("trang_thai", "")
            ghi_chu = item.get("ghi_chu", "")
            co_email = bool(email)
            is_checked = idx in selected_indices

            # Lấy hệ số lương từ nguồn lương đầu tiên (nếu có)
            he_so = ""
            if item.get("nguon_luong"):
                nguon_0 = item["nguon_luong"][0]
                he_so = str(nguon_0.get("he_so_luong", "")) if isinstance(nguon_0, dict) else ""

            c1, c2, c3, c4, c5, c6, c7, hc8, hc9, hc10 = st.columns([0.5, 2, 2.5, 1, 1.5, 1.5, 1.2, 1, 1, 1])
            c1.markdown(f"{idx + 1}")
            c2.markdown(f"**{ho_ten}**")
            c3.markdown(email if email else "—")
            c4.markdown(ma_ngach if ma_ngach else "—")
            c5.markdown(nguon_luong if nguon_luong else "—")
            c6.markdown(he_so if he_so != "" else "—")
            c7.markdown(f"{tong_cong:,.0f} đ" if tong_cong else "—")
            hc8.markdown(trang_thai if trang_thai else "—")

            # Nút xem chi tiết (kính lúp)
            with hc9.popover("🔍", use_container_width=True,
                            key=f"popover_detail_{idx}_{chk_suffix}"):
                st.markdown(f"### 👤 Chi tiết: {ho_ten}")
                st.markdown(f"**Email:** {email if email else '—'}")
                st.markdown(f"**Mã ngạch:** {ma_ngach if ma_ngach else '—'}")
                st.markdown(f"**Tháng/Năm:** {thang}/{nam}")
                st.markdown(f"**Trạng thái:** {trang_thai if trang_thai else '—'}")
                if ghi_chu:
                    st.markdown(f"**Ghi chú:** {ghi_chu}")
                else:
                    st.markdown("**Ghi chú:** —")

                # Chi tiết từng nguồn lương
                st.markdown("#### 💰 Chi tiết nguồn lương")
                nguon_list = item.get("nguon_luong", [])
                if nguon_list:
                    for n in nguon_list:
                        if isinstance(n, dict):
                            st.markdown(f"- **{n.get('loai', '—')}**: hệ số {n.get('he_so_luong', '—')}, tiền {n.get('tien_luong', 0):,.0f} đ" if n.get('tien_luong') else f"- **{n.get('loai', '—')}**: hệ số {n.get('he_so_luong', '—')}")
                        else:
                            st.markdown(f"- {n}")
                else:
                    st.caption("Chưa có thông tin nguồn lương.")
                st.markdown("---")
                st.caption("Thông tin trên sẽ được đưa vào nội dung email thông báo lương.")

            # Checkbox nhận email (chỉ hiển thị nếu có email)
            if co_email:
                def _make_cb(index):
                    def _cb():
                        key = f"chk_{index}_{st.session_state.get('salary_chk_suffix', 0)}"
                        val = st.session_state.get(key, False)
                        sel = set(st.session_state.get("salary_selected_indices", []))
                        if val:
                            sel.add(index)
                        else:
                            sel.discard(index)
                        st.session_state["salary_selected_indices"] = list(sel)
                    return _cb

                hc10.checkbox(
                    "Nhận email",
                    value=is_checked,
                    key=f"chk_{idx}_{chk_suffix}",
                    on_change=_make_cb(idx),
                    label_visibility="collapsed",
                )
            else:
                hc10.markdown("—")

        st.markdown("---")

        # -----------------------
        # Điều khiển cuối bảng
        # -----------------------
        btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([1.5, 1.5, 2, 2])

        with btn_c1:
            if st.button("☑️ Chọn tất cả có email", key="btn_check_all", use_container_width=True):
                all_with_email = [start + i for i, it in enumerate(page_items) if it.get("email")]
                st.session_state["salary_selected_indices"] = list(
                    set(st.session_state.get("salary_selected_indices", [])) | set(all_with_email)
                )
                st.session_state["salary_chk_suffix"] = chk_suffix + 1
                st.rerun()

        with btn_c2:
            if st.button("☐ Bỏ chọn tất cả", key="btn_clear_all", use_container_width=True):
                st.session_state["salary_selected_indices"] = []
                st.session_state["salary_chk_suffix"] = chk_suffix + 1
                st.rerun()

        with btn_c3:
            st.markdown(f"**Trang {page} / {total_pages}** · **{total} người**")

        with btn_c4:
            nav_c1, nav_c2 = st.columns(2)
            if nav_c1.button("◀ Trang trước", key="btn_prev_page", use_container_width=True, disabled=(page <= 1)):
                st.session_state["salary_table_page"] = page - 1
                st.rerun()
            if nav_c2.button("Trang sau ▶", key="btn_next_page", use_container_width=True, disabled=(page >= total_pages)):
                st.session_state["salary_table_page"] = page + 1
                st.rerun()

        # Nút gửi email cho những người được chọn
        selected_indices = set(st.session_state.get("salary_selected_indices", []))
        selected_items = [filtered[i] for i in selected_indices if i < len(filtered)]
        selected_with_email = [it for it in selected_items if it.get("email")]
        if selected_with_email:
            st.info(f"Đã chọn **{len(selected_with_email)}** người có email để gửi thông báo.")
            if st.button("📧 Gửi thông báo lương cho người đã chọn", type="primary", key="btn_send_selected"):
                # Tạo nội dung email cho mỗi người
                sent_count = 0
                fail_count = 0
                for item in selected_with_email:
                    email = item.get("email", "")
                    ho_ten = item.get("ho_ten", "")
                    tong_cong = item.get("tong_cong", 0)
                    ghi_chu = item.get("ghi_chu", "")
                    trang_thai = item.get("trang_thai", "")

                    # Lấy hệ số và lương cơ bản từ nguồn lương đầu tiên
                    he_so = ""
                    luong_cb = 0
                    nguon_list = item.get("nguon_luong", [])
                    if nguon_list:
                        he_so = str(nguon_list[0].get("he_so_luong", ""))
                        luong_cb = nguon_list[0].get("tien_luong", 0) or 0

                    nguon_str = ", ".join(nguon_list)

                    subject = f"[Lương tháng {thang}/{nam}] Thông báo lương của {ho_ten}"
                    body = f"""Kính gửi {ho_ten},

Đây là thông báo lương tháng {thang}/{nam} của bạn.

Chi tiết:
- Nguồn lương: {nguon_str}
- Mã ngạch / Hệ số lương: {ma_ngach if ma_ngach else '—'} / {he_so if he_so else '—'}
- Lương cơ bản: {luong_cb:,.0f} đ
- Tổng lương thực lĩnh: {tong_cong:,.0f} đ
- Trạng thái: {trang_thai if trang_thai else '—'}
- Ghi chú: {ghi_chu if ghi_chu else '—'}

Vui lòng kiểm tra và phản hồi lại phòng Kế toán nếu có thắc mắc.

Trân trọng,
Phòng Kế toán - Viện Vật lý
"""
                    # Gửi email
                    ok = _send_salary_email(email, subject, body)
                    if ok:
                        sent_count += 1
                    else:
                        fail_count += 1

                if sent_count > 0:
                    st.success(f"✅ Đã gửi thông báo lương cho {sent_count} cán bộ.")
                if fail_count > 0:
                    st.error(f"❌ Không gửi được cho {fail_count} cán bộ.")
        else:
            st.caption("Vui lòng tích ô 'Nhận email' ít nhất cho một người để gửi thông báo.")
    else:
        st.info("Chưa có dữ liệu tổng hợp lương tháng. Vui lòng đồng bộ từ file Excel trước.")

    st.markdown("---")

    # =================================================================
    # PHẦN 4: CẤU HÌNH SMTP (chỉ Admin/Manager)
    # =================================================================
    st.markdown("### 📮 Cấu hình gửi email (SMTP)")
    st.caption("Cấu hình lưu trên Supabase, máy tính khác dùng chung được. Kế toán lương có thể đổi ở đây mà không cần chỉnh sửa file hệ thống.")

    smtp_cfg = _load_smtp_config()
    with st.expander("⚙️ Cấu hình SMTP gửi thông báo lương", expanded=not smtp_cfg.get("smtp_server")):
        with st.form("form_smtp_config", clear_on_submit=False):
            c1, c2 = st.columns(2)
            s_server = c1.text_input("SMTP Server", value=smtp_cfg.get("smtp_server", ""), key="smtp_server")
            s_port = c2.text_input("Port", value=str(smtp_cfg.get("smtp_port", 587)), key="smtp_port")
            s_user = c1.text_input("Tài khoản SMTP", value=smtp_cfg.get("smtp_user", ""), key="smtp_user")
            s_pass = c2.text_input("Mật khẩu SMTP", type="password", value=smtp_cfg.get("smtp_password", ""), key="smtp_password")
            s_from = c1.text_input("Email gửi từ (From)", value=smtp_cfg.get("smtp_from", smtp_cfg.get("smtp_user", "")), key="smtp_from")

            st.info("💡 Nếu dùng Gmail, hãy tạo App Password (Mật khẩu ứng dụng) thay vì mật khẩu đăng nhập thông thường.")

            if st.form_submit_button("💾 Lưu cấu hình SMTP", type="primary"):
                new_cfg = {
                    "smtp_server": (s_server or "").strip(),
                    "smtp_port": (s_port or "").strip(),
                    "smtp_user": (s_user or "").strip(),
                    "smtp_password": (s_pass or "").strip(),
                    "smtp_from": ((s_from or s_user or "").strip()),
                }
                if _save_smtp_config(new_cfg):
                    st.success("✅ Đã lưu cấu hình SMTP lên Supabase.")
                    st.rerun()
                else:
                    st.error("❌ Không lưu được cấu hình SMTP.")

    if smtp_cfg.get("smtp_server"):
        st.success(f"✅ Đã cấu hình SMTP: {smtp_cfg.get('smtp_server')} (tài khoản: {smtp_cfg.get('smtp_user')})")
    else:
        st.info("Chưa cấu hình SMTP. Vui lòng cấu hình để gửi email thật. Nếu chưa cấu hình, hệ thống sẽ chỉ preview nội dung email ra terminal.")

    st.markdown("---")

    data = get_salary_profiles()
    if not isinstance(data, dict):
        data = {}

    all_users = list(data.keys())
    if not all_users:
        st.info("Chưa có dữ liệu lương cho cualquier user.")
        return

    # -----------------------
    # Ô tìm kiếm
    # -----------------------
    def _on_search_change():
        st.session_state["salary_search"] = st.session_state["salary_search_input"]

    search_q = st.text_input(
        "🔍 Tìm cán bộ (tên, mã ngạch, hệ số...)",
        value=st.session_state.get("salary_search", ""),
        placeholder="Nhập tên hoặc mã ngạch...",
        key="salary_search_input",
        on_change=_on_search_change,
        label_visibility="collapsed",
    )
    search_lower = (st.session_state.get("salary_search", "") or "").strip().lower()

    # Lọc user theo từ khóa (tên hoặc bất kỳ thông tin trong bien_dong_luong cuối)
    filtered = {}
    for uid, rec in data.items():
        ten = rec.get("ho_va_ten", uid)
        email = rec.get("email", "")
        haystack = f"{uid} {ten} {email}".lower()
        if not search_lower:
            filtered[uid] = rec
        else:
            match = search_lower in haystack
            if not match:
                for bd in rec.get("lich_su_bien_dong_luong", []):
                    bd_text = " ".join(str(v) for v in bd.values()).lower()
                    if search_lower in bd_text:
                        match = True
                        break
            if match:
                filtered[uid] = rec

    st.markdown("### 📋 Tổng hợp lương tháng tới")
    st.caption("Danh sách tất cả user có hồ sơ lương. Bấm 'Chi tiết/Sửa' để xem chi tiết cá nhân.")

    # Hiển thị bảng tổng hợp (mỗi user một hàng)
    for uid, rec in filtered.items():
        ho_ten = rec.get("ho_va_ten", uid)
        email = rec.get("email", "")
        # Lấy biến động gần nhất để hiển thị tóm tắt
        bd_list = rec.get("lich_su_bien_dong_luong", [])
        bd_cuoi = bd_list[-1] if bd_list else {}
        he_so = bd_cuoi.get("he_so_luong", "")
        luong_cb = bd_cuoi.get("luong_cb", "")
        ma_ngach = bd_cuoi.get("bac_luong", "")

        with st.container(border=True):
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1.5, 1.2, 1.2, 1.5, 1])
            c1.markdown(f"**{ho_ten}** (@{uid})" + (f" · {email}" if email else ""))
            c2.markdown(ma_ngach or "—")
            c3.markdown(he_so or "—")
            c4.markdown(str(luong_cb) if luong_cb != "" else "—")
            c5.markdown(str(bd_cuoi.get("tong_cong", "")) if bd_cuoi.get("tong_cong") not in (None, "") else "—")
            if c6.button("🔍 Chi tiết/Sửa", key=f"salary_det_{uid}"):
                st.session_state["salary_selected_user"] = uid
                st.rerun()

    # Nếu tìm kiếm còn 1 kết quả, tự chọn
    if search_lower and len(filtered) == 1:
        st.session_state["salary_selected_user"] = next(iter(filtered))

    # -----------------------
    # Chi tiết user đã chọn
    # -----------------------
    selected_uid = st.session_state.get("salary_selected_user")
    if selected_uid and selected_uid in filtered:
        rec = filtered[selected_uid]
        ho_ten = rec.get("ho_va_ten", selected_uid)

        st.markdown("---")
        st.markdown(f"### 👤 Chi tiết lương: {ho_ten} (@{selected_uid})")

        # --- Bảng biến động lương ---
        st.markdown("#### 📈 Biến động lương (toàn bộ)")
        bd_list = rec.get("lich_su_bien_dong_luong", [])
        if not bd_list:
            st.info("Chưa có biến động lương nào.")
        else:
            # Hiển thị bảng biến động (mới nhất lên trên)
            for idx, bd in enumerate(reversed(bd_list)):
                with st.container(border=True):
                    cols = st.columns([1.2, 1.5, 1, 0.8, 1, 1, 1.5, 2])
                    cols[0].markdown(f"**{bd.get('ngay_hieu_luc','')}**")
                    cols[1].markdown(bd.get("quyet_dinh_so", ""))
                    cols[2].markdown(bd.get("bac_luong", ""))
                    cols[3].markdown(bd.get("he_so_luong", ""))
                    cols[4].markdown(bd.get("luong_cb", ""))
                    cols[5].markdown(bd.get("tong_cong", ""))
                    cols[6].markdown(bd.get("doc_hai_tien", ""))
                    cols[7].markdown(bd.get("ly_do_bien_dong", ""))

            st.markdown("---")
            # Nút thêm biến động
            with st.popover("➕ Thêm biến động lương", use_container_width=True):
                st.markdown(f"Thêm biến động lương cho **{ho_ten}**")
                tmp_key = f"tmp_bd_{selected_uid}"
                if tmp_key not in st.session_state:
                    st.session_state[tmp_key] = {
                        "nam": datetime.now().year,
                        "thang": datetime.now().month,
                        "ngay_hieu_luc": "",
                        "quyet_dinh_so": "",
                        "bac_luong": "",
                        "he_so_luong": "",
                        "luong_cb": "",
                        "pc_ld": "",
                        "pc_ld_bang_tien": "",
                        "vuot_khung": "",
                        "he_so_vuot_khung": "",
                        "vuot_khung_bang_tien": "",
                        "phan_tram_huong": "",
                        "he_so_doc_hai_theo_vi_tri": "",
                        "he_so_doc_hai_tien": "",
                        "doc_hai_theo_luong": "",
                        "doc_hai_tien": "",
                        "truy_linh": "",
                        "bhiem_10_5": "",
                        "truy_thu": "",
                        "tong_cong": "",
                        "ghi_chu": "",
                        "tien_tinh_thue": "",
                        "ban_cung_luu_o_dau": "",
                        "ly_do_bien_dong": "",
                    }
                tmp = st.session_state[tmp_key]

                with st.form(f"form_add_bd_{selected_uid}", clear_on_submit=False):
                    c1, c2 = st.columns(2)
                    tmp["nam"] = c1.number_input("Năm", min_value=2000, max_value=2100,
                                                 value=int(tmp.get("nam") or datetime.now().year))
                    tmp["thang"] = c2.number_input("Tháng", min_value=1, max_value=12,
                                                   value=int(tmp.get("thang") or datetime.now().month))
                    tmp["ngay_hieu_luc"] = st.text_input("Ngày hiệu lực (dd/mm/yyyy)",
                                                         value=tmp.get("ngay_hieu_luc", ""))
                    tmp["quyet_dinh_so"] = st.text_input("Số quyết định",
                                                         value=tmp.get("quyet_dinh_so", ""))
                    tmp["bac_luong"] = st.text_input("Bậc lương", value=tmp.get("bac_luong", ""))
                    tmp["he_so_luong"] = st.text_input("Hệ số lương", value=tmp.get("he_so_luong", ""))
                    tmp["luong_cb"] = st.text_input("Lương cơ bản", value=tmp.get("luong_cb", ""))
                    tmp["tong_cong"] = st.text_input("Tổng cộng (lương thực nhận)",
                                                     value=tmp.get("tong_cong", ""))
                    tmp["doc_hai_tien"] = st.text_input("Phụ cấp độc hại (tiền)",
                                                        value=tmp.get("doc_hai_tien", ""))
                    tmp["ghi_chu"] = st.text_area("Ghi chú", value=tmp.get("ghi_chu", ""))
                    tmp["ly_do_bien_dong"] = st.text_area("Lý do biến động (bắt buộc)",
                                                          value=tmp.get("ly_do_bien_dong", ""))
                    tmp["ban_cung_luu_o_dau"] = st.text_input("Bản cứng lưu ở đâu (đường dẫn/file)",
                                                              value=tmp.get("ban_cung_luu_o_dau", ""))

                    st.markdown("**📎 Hoặc upload quyết định (PDF) để tự điền:**")
                    qd_file = st.file_uploader("Chọn file PDF quyết định", type=["pdf"],
                                               key=f"qd_upload_{selected_uid}")
                    if qd_file is not None:
                        file_bytes = qd_file.getvalue()
                        with st.spinner("🤖 Đang đọc PDF và trích xuất bằng AI..."):
                            text = _read_pdf_first_page(file_bytes)
                            info = _extract_qd_luong(text)
                        if info:
                            # Map ket qua tu PDF sang cac truong moi
                            mapped = {}
                            if info.get("ngay"):
                                tmp["ngay_hieu_luc"] = info["ngay"]
                            if info.get("so_quyet_dinh"):
                                tmp["quyet_dinh_so"] = info["so_quyet_dinh"]
                            if info.get("bac_luong"):
                                tmp["bac_luong"] = info["bac_luong"]
                            if info.get("he_so_luong"):
                                tmp["he_so_luong"] = str(info["he_so_luong"])
                            if info.get("luong_co_ban"):
                                tmp["luong_cb"] = str(info["luong_co_ban"])
                            if info.get("phu_cap"):
                                tmp["doc_hai_tien"] = str(info["phu_cap"])
                            if info.get("ghi_chu"):
                                tmp["ly_do_bien_dong"] = info["ghi_chu"]
                            st.session_state[tmp_key] = {**tmp, **mapped}
                            st.success("✅ Đã trích xuất từ PDF. Vui lòng kiểm tra lại các ô trên.")
                            st.rerun()
                        else:
                            st.warning("Không trích xuất được thông tin từ PDF.")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.form_submit_button("💾 Lưu biến động"):
                            if not tmp.get("ly_do_bien_dong"):
                                st.error("❌ Vui lòng nhập lý do biến động.")
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
                                # Sap xep theo nam, thang
                                rec["lich_su_bien_dong_luong"] = sorted(
                                    rec["lich_su_bien_dong_luong"],
                                    key=lambda b: (b.get("nam", 0), b.get("thang", 0))
                                )
                                data[selected_uid] = rec
                                if _save_salary_data(data):
                                    st.success("✅ Đã lưu biến động lương.")
                                    st.session_state[tmp_key] = {
                                        "nam": datetime.now().year,
                                        "thang": datetime.now().month,
                                        "ngay_hieu_luc": "",
                                        "quyet_dinh_so": "",
                                        "bac_luong": "",
                                        "he_so_luong": "",
                                        "luong_cb": "",
                                        "pc_ld": "",
                                        "pc_ld_bang_tien": "",
                                        "vuot_khung": "",
                                        "he_so_vuot_khung": "",
                                        "vuot_khung_bang_tien": "",
                                        "phan_tram_huong": "",
                                        "he_so_doc_hai_theo_vi_tri": "",
                                        "he_so_doc_hai_tien": "",
                                        "doc_hai_theo_luong": "",
                                        "doc_hai_tien": "",
                                        "truy_linh": "",
                                        "bhiem_10_5": "",
                                        "truy_thu": "",
                                        "tong_cong": "",
                                        "ghi_chu": "",
                                        "tien_tinh_thue": "",
                                        "ban_cung_luu_o_dau": "",
                                        "ly_do_bien_dong": "",
                                    }
                                    st.rerun()
                                else:
                                    st.error("❌ Không lưu được dữ liệu.")
                    with col2:
                        if st.form_submit_button("❌ Hủy"):
                            st.session_state[tmp_key] = {
                                "nam": datetime.now().year,
                                "thang": datetime.now().month,
                                "ngay_hieu_luc": "",
                                "quyet_dinh_so": "",
                                "bac_luong": "",
                                "he_so_luong": "",
                                "luong_cb": "",
                                "pc_ld": "",
                                "pc_ld_bang_tien": "",
                                "vuot_khung": "",
                                "he_so_vuot_khung": "",
                                "vuot_khung_bang_tien": "",
                                "phan_tram_huong": "",
                                "he_so_doc_hai_theo_vi_tri": "",
                                "he_so_doc_hai_tien": "",
                                "doc_hai_theo_luong": "",
                                "doc_hai_tien": "",
                                "truy_linh": "",
                                "bhiem_10_5": "",
                                "truy_thu": "",
                                "tong_cong": "",
                                "ghi_chu": "",
                                "tien_tinh_thue": "",
                                "ban_cung_luu_o_dau": "",
                                "ly_do_bien_dong": "",
                            }
                            st.rerun()

    elif selected_uid:
        st.warning("Không tìm thấy dữ liệu của user này.")
