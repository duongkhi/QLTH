#finance_module.py
import streamlit as st
import pandas as pd
import time
import base64
import os
import json
import io
from config import UserContext
from finance_service import (
    load_finance_data, format_currency, get_project_metrics,
    validate_and_import_excel,
    add_single_project, delete_single_project, update_single_project,
    add_transaction, delete_transaction, get_visible_project_ids,
)
from finance_agent import chat_with_finance_ai
from ai_client import generate_gemini_text_real
from docx_utils import (
    extract_text_from_docx, extract_text_from_pdf_bytes, fix_tcvn3_text,
)

# ============================================================
# TRÍCH XUẤT THÔNG TIN TỪ HỢP ĐỒNG THỰC HIỆN (chỉ trang đầu)
# ============================================================
def _read_first_page_text(file_bytes: bytes, filename: str) -> str:
    """Đọc chỉ văn bản của trang đầu (hoặc đoạn đầu) để tiết kiệm token."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if ext == "pdf":
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
        elif ext == "docx":
            doc = extract_text_from_docx(io.BytesIO(file_bytes))
            return doc[:3000]
        else:
            return ""
    except Exception:
        return ""


def extract_contract_info(text: str) -> dict:
    """Gọi Gemini trích xuất thông tin tổng quan từ trang đầu hợp đồng."""
    if not text or not text.strip():
        return {}

    prompt = (
        "Bạn là trợ lý trích xuất thông tin từ trang đầu của hợp đồng thực hiện "
        "nhiệm vụ khoa học công nghệ.\n"
        "Hãy đọc văn bản dưới đây và trích xuất các thông tin sau (nếu có):\n"
        "1. Mã đề tài (ví dụ: CBCLCA.02/25-27)\n"
        "2. Tên đề tài\n"
        "3. Chủ nhiệm đề tài (họ tên)\n"
        "4. Đơn vị chủ trì\n"
        "5. Thời gian thực hiện (ví dụ: 2025-2028)\n\n"
        "Trả về CHỈ duy nhất một đối tượng JSON thuần khiết, không markdown, không "
        "giải thích thêm:\n"
        '{"ma_de_tai": "...", "ten_de_tai": "...", "chu_nhiem": "...", '
        '"don_vi_chu_tri": "...", "thoi_gian": "..."}\n'
        "Nếu trường nào không có trong văn bản, để chuỗi rỗng \"\".\n\n"
        "Văn bản hợp đồng (trang đầu):\n"
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
            "ma_de_tai": str(data.get("ma_de_tai", "") or "").strip(),
            "ten_de_tai": str(data.get("ten_de_tai", "") or "").strip(),
            "chu_nhiem": str(data.get("chu_nhiem", "") or "").strip(),
            "don_vi_chu_tri": str(data.get("don_vi_chu_tri", "") or "").strip(),
            "thoi_gian": str(data.get("thoi_gian", "") or "").strip(),
        }
    except Exception:
        return {}


@st.dialog("✏️ Sửa đề tài")
def _edit_project_dialog(pid: str, project: dict):
    st.caption(f"Mã đề tài: **{pid}** (không thể đổi)")

    ci = st.session_state.get("edit_contract_info", {}) or {}

    name = st.text_input(
        "Tên đề tài",
        value=ci.get("ten_de_tai") or project.get("name", ""),
    )
    c1, c2 = st.columns(2)
    with c1:
        pi = st.text_input(
            "Chủ nhiệm",
            value=ci.get("chu_nhiem") or project.get("pi", ""),
        )
        group = st.text_input("Nhóm", value=project.get("group", ""))
    with c2:
        duration = st.text_input(
            "Thời gian",
            value=ci.get("thoi_gian") or project.get("duration", ""),
        )
        task_type = st.text_input("Loại nhiệm vụ", value=project.get("task_type", ""))

    unit = st.text_input(
        "Đơn vị chủ trì",
        value=ci.get("don_vi_chu_tri") or project.get("unit", "Viện Vật lý"),
    )

    st.markdown("**Kinh phí (VNĐ)**")
    c1, c2, c3 = st.columns(3)
    with c1:
        total_budget = st.number_input(
            "Tổng KP đề tài", min_value=0, step=1000000,
            value=int(project.get("total_budget", 0)),
        )
    with c2:
        allocated_budget = st.number_input(
            "KP giao dự toán", min_value=0, step=1000000,
            value=int(project.get("allocated_budget", 0)),
        )
    with c3:
        actual_budget = st.number_input(
            "KP sử dụng thực tế", min_value=0, step=1000000,
            value=int(project.get("actual_budget", 0)),
        )

    st.markdown("#### 📎 File dự toán tài chính")
    budget_file = st.file_uploader(
        "Chọn file dự toán (.xls, .xlsx, .pdf)",
        type=["xls", "xlsx", "pdf"],
        key=f"edit_proj_budget_file_{pid}",
    )
    current_file_name = project.get("budget_file_name", "")
    if current_file_name:
        st.caption(f"File hiện tại: {current_file_name}")

    st.markdown("#### 📄 Hợp đồng thực hiện (trích xuất tự động)")
    contract_file = st.file_uploader(
        "Chọn file hợp đồng (.docx, .pdf) để trích xuất mã/tên/chủ nhiệm/đơn vị/thời gian",
        type=["docx", "pdf"],
        key=f"edit_contract_file_{pid}",
    )
    if contract_file is not None:
        file_bytes = contract_file.getvalue()
        with st.spinner("🤖 Đang đọc trang đầu và trích xuất thông tin bằng AI..."):
            text = _read_first_page_text(file_bytes, contract_file.name)
            info = extract_contract_info(text)
        if info:
            st.session_state["edit_contract_info"] = info
            st.success("✅ Đã trích xuất thông tin từ hợp đồng. Các ô trên đã được pre-fill.")
            st.rerun()
        else:
            st.warning("Không trích xuất được thông tin từ hợp đồng. Vui lòng nhập thủ công.")

    if "edit_contract_info" in st.session_state:
        del st.session_state["edit_contract_info"]

    st.markdown("---")
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Lưu thay đổi", type="primary", width='stretch'):
            budget_file_name = project.get("budget_file_name", "")
            budget_file_b64 = project.get("budget_file_b64", "")
            if budget_file is not None:
                budget_file_name = budget_file.name
                budget_file_b64 = base64.b64encode(
                    budget_file.getvalue()
                ).decode("utf-8")
            ok, msg = update_single_project(pid, {
                "name": name, "pi": pi, "group": group,
                "duration": duration, "task_type": task_type, "unit": unit,
                "total_budget": total_budget,
                "allocated_budget": allocated_budget,
                "actual_budget": actual_budget,
                "budget_file_name": budget_file_name,
                "budget_file_b64": budget_file_b64,
            })
            st.session_state["editing_pid"] = None
            st.session_state["_project_flash"] = msg
            st.rerun()
    with col_cancel:
        if st.button("❌ Hủy", width='stretch'):
            st.session_state["editing_pid"] = None
            st.rerun()


def render_finance_module(ctx: UserContext):
    st.title("💰 Quản lý tài chính")
    st.caption("Tổng hợp giải ngân · Quản lý đề tài · Sổ chứng từ · Trợ lý AI")

    projects_raw, disb_raw, tx_raw = load_finance_data()

    visible_pids = get_visible_project_ids(ctx, projects_raw)
    if visible_pids is None:
        projects = projects_raw
        disbursements = disb_raw
        transactions = tx_raw
        is_restricted = False
    else:
        pset = set(visible_pids)
        projects = {k: v for k, v in projects_raw.items() if k in pset}
        disbursements = {k: v for k, v in disb_raw.items() if k in pset}
        transactions = [t for t in tx_raw if t.get("project_id") in pset]
        is_restricted = True

    if is_restricted:
        if not ctx.own_profile:
            st.error("⚠️ Tài khoản của bạn chưa có profile. Liên hệ admin để được cấp.")
        elif not projects:
            st.warning(
                f"ℹ️ Bạn chưa chủ nhiệm đề tài nào trong hệ thống. "
                f"(Họ tên đang dùng để so khớp: **{ctx.own_profile}**) "
                "Nếu đây là nhầm lẫn, liên hệ Quản trị viên."
            )
        else:
            st.info(
                f"🔒 Bạn đang xem **{len(projects)} đề tài** do mình chủ nhiệm. "
                "Liên hệ admin nếu cần xem thêm."
            )

    flash = st.session_state.pop("_project_flash", None)
    if flash:
        st.success(flash)

    tabs = st.tabs([
        "📊 Tổng quan",
        "📁 Quản lý Đề tài",
        "🧾 Sổ chứng từ",
        "📤 Nhập liệu Excel",
    ])

    # =================================================================
    # TAB 1: TỔNG QUAN
    # =================================================================
    with tabs[0]:
        if not projects:
            if not is_restricted:
                st.info("Chưa có dữ liệu. Vui lòng sang tab 'Nhập liệu Excel' để nạp dữ liệu.")
        else:
            search_q = st.text_input(
                "🔍 Tìm đề tài",
                value=st.session_state.get("finance_search_q", ""),
                placeholder="Nhập mã đề tài, tên đề tài hoặc chủ nhiệm...",
                key="finance_search_input",
                label_visibility="collapsed",
            )
            st.session_state["finance_search_q"] = search_q
            search_lower = (search_q or "").strip().lower()

            filtered = {}
            for pid, p in projects.items():
                haystack = f"{pid} {p.get('name','')} {p.get('pi','')}".lower()
                if search_lower in haystack:
                    filtered[pid] = p

            total_budget = sum(p.get("actual_budget", 0) for p in filtered.values())
            total_cum = sum(
                max(d.get("cumulative", {}).values() or [0])
                for d in (disbursements.get(pid, {}) for pid in filtered)
            )
            total_settled = sum(d.get("settled_2026", 0) for d in (disbursements.get(pid, {}) for pid in filtered))

            c1, c2, c3 = st.columns(3)
            c1.metric("Tổng kinh phí thực tế", format_currency(total_budget))
            c2.metric("Đã giải ngân lũy kế", format_currency(total_cum),
                      delta=f"{(total_cum/total_budget*100):.1f}%" if total_budget else "0%")
            c3.metric("Đã quyết toán 2026", format_currency(total_settled))

            st.markdown("### 📋 Danh sách tổng hợp")
            for pid, p in filtered.items():
                d = disbursements.get(pid, {})
                m = get_project_metrics(pid, p, d)
                with st.container(border=True):
                    c1, c2, c3, c4, c5, c6 = st.columns([1, 2.6, 1.4, 1.1, 1.1, 0.9])
                    c1.markdown(f"**{pid}**")
                    c2.markdown(p.get("name", ""))
                    c3.markdown(p.get("pi", ""))
                    c4.markdown(format_currency(m["actual_budget"]))
                    c5.markdown(format_currency(m["current_cum"]))
                    if c6.button("🔍 Xem", key=f"finance_select_{pid}"):
                        st.session_state["finance_selected_pid"] = pid
                        st.rerun()

            detail_pid = None
            selected = st.session_state.get("finance_selected_pid")
            if selected and selected in filtered:
                detail_pid = selected
            elif len(filtered) == 1:
                detail_pid = next(iter(filtered))
                st.session_state["finance_selected_pid"] = detail_pid

            if detail_pid:
                p = filtered[detail_pid]
                d = disbursements.get(detail_pid, {})
                m = get_project_metrics(detail_pid, p, d)

                st.markdown("---")
                st.markdown(f"### 📄 Chi tiết đề tài: {detail_pid}")

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Mã đề tài:** {detail_pid}")
                    st.markdown(f"**Tên đề tài:** {p.get('name', '')}")
                    st.markdown(f"**Chủ nhiệm:** {p.get('pi', '')}")
                    st.markdown(f"**Nhóm:** {p.get('group', '')}")
                    st.markdown(f"**Loại nhiệm vụ:** {p.get('task_type', '')}")
                    st.markdown(f"**Đơn vị chủ trì:** {p.get('unit', '')}")
                    st.markdown(f"**Thời gian:** {p.get('duration', '')}")
                with c2:
                    st.markdown(f"**Tổng KP đề tài:** {format_currency(p.get('total_budget', 0))}")
                    st.markdown(f"**KP giao dự toán:** {format_currency(p.get('allocated_budget', 0))}")
                    st.markdown(f"**KP sử dụng thực tế:** {format_currency(p.get('actual_budget', 0))}")
                    st.markdown(f"**Đã giải ngân lũy kế:** {format_currency(m['current_cum'])}")
                    st.markdown(f"**Tỷ lệ giải ngân:** {m['rate']:.1f}%")
                    st.markdown(f"**Đã quyết toán 2026:** {format_currency(d.get('settled_2026', 0))}")

                st.markdown("#### 📄 Sheet tổng kinh phí (dự toán tài chính)")

                budget_file_name = p.get("budget_file_name", "")
                budget_file_b64 = p.get("budget_file_b64", "")

                df_show = None
                label_show = ""

                if budget_file_name and budget_file_b64:
                    try:
                        file_bytes = base64.b64decode(budget_file_b64)
                        df_show = pd.read_excel(file_bytes, sheet_name=0, header=None)
                        label_show = f"Dự toán của đề tài: {budget_file_name}"
                    except Exception:
                        st.error("Không đọc được file dự toán đã lưu của đề tài.")
                else:
                    st.info("Chưa có dữ liệu tài chính.")

                if df_show is not None:
                    st.caption(label_show)
                    st.dataframe(df_show, width='stretch', hide_index=True)

    # =================================================================
    # TAB 2: QUẢN LÝ ĐỀ TÀI (chỉ admin/manager)
    # =================================================================
    with tabs[1]:
        if ctx.role not in ("admin", "manager"):
            st.warning(
                "🔒 Chỉ **Admin/Quản lý tổng hợp** mới có quyền Thêm/Sửa/Xóa đề tài. "
                "Bạn chỉ có thể xem dữ liệu ở tab **Tổng quan**."
            )
        else:
            with st.expander("➕ Thêm Đề tài mới", expanded=False):
                ci = st.session_state.get("add_contract_info", {}) or {}

                with st.form("add_proj", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        new_pid = st.text_input(
                            "Mã đề tài",
                            value=ci.get("ma_de_tai", ""),
                        )
                        new_name = st.text_input(
                            "Tên đề tài",
                            value=ci.get("ten_de_tai", ""),
                        )
                        new_pi = st.text_input(
                            "Chủ nhiệm",
                            value=ci.get("chu_nhiem", ""),
                        )
                        new_unit = st.text_input(
                            "Đơn vị chủ trì",
                            value=ci.get("don_vi_chu_tri") or "Viện Vật lý",
                        )
                    with c2:
                        new_group = st.text_input("Nhóm", placeholder="VD: a / b / Chuyển tiếp")
                        new_duration = st.text_input(
                            "Thời gian",
                            value=ci.get("thoi_gian", ""),
                            placeholder="VD: 2025-2028",
                        )
                        new_task_type = st.text_input("Loại nhiệm vụ")
                        new_total_budget = st.number_input(
                            "Tổng KP đề tài (VNĐ)", step=1000000, min_value=0,
                        )
                        new_allocated_budget = st.number_input(
                            "KP giao dự toán (VNĐ)", step=1000000, min_value=0,
                        )
                    new_actual_budget = st.number_input(
                        "KP sử dụng thực tế (VNĐ)", step=1000000, min_value=0,
                    )

                    st.markdown("#### 📎 File dự toán tài chính")
                    budget_file = st.file_uploader(
                        "Chọn file dự toán (.xls, .xlsx, .pdf)",
                        type=["xls", "xlsx", "pdf"],
                        key="add_proj_budget_file",
                    )

                    st.markdown("#### 📄 Hợp đồng thực hiện (trích xuất tự động)")
                    contract_file = st.file_uploader(
                        "Chọn file hợp đồng (.docx, .pdf) để trích xuất mã/tên/chủ nhiệm/đơn vị/thời gian",
                        type=["docx", "pdf"],
                        key="add_contract_file",
                    )
                    if contract_file is not None:
                        file_bytes = contract_file.getvalue()
                        with st.spinner("🤖 Đang đọc trang đầu và trích xuất thông tin bằng AI..."):
                            text = _read_first_page_text(file_bytes, contract_file.name)
                            info = extract_contract_info(text)
                        if info:
                            st.session_state["add_contract_info"] = info
                            st.success("✅ Đã trích xuất thông tin từ hợp đồng. Các ô trên đã được pre-fill.")
                            st.rerun()
                        else:
                            st.warning("Không trích xuất được thông tin từ hợp đồng. Vui lòng nhập thủ công.")

                    if "add_contract_info" in st.session_state:
                        del st.session_state["add_contract_info"]

                    if st.form_submit_button("Lưu Đề tài", type="primary"):
                        if not new_pid or not new_name:
                            st.error("Cần nhập Mã và Tên đề tài.")
                        else:
                            budget_file_name = ""
                            budget_file_b64 = ""
                            if budget_file is not None:
                                budget_file_name = budget_file.name
                                budget_file_b64 = base64.b64encode(
                                    budget_file.getvalue()
                                ).decode("utf-8")
                            ok, msg = add_single_project(
                                new_pid, new_name, new_pi, new_group,
                                new_total_budget,
                                unit=new_unit,
                                duration=new_duration,
                                task_type=new_task_type,
                                allocated_budget=new_allocated_budget,
                                actual_budget=new_actual_budget,
                                budget_file_name=budget_file_name,
                                budget_file_b64=budget_file_b64,
                            )
                            if ok:
                                st.success(msg)
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(msg)

            if projects:
                def _on_search_change():
                    st.session_state["finance_tab2_search"] = st.session_state["finance_tab2_search_input"]

                search_q = st.text_input(
                    "🔍 Tìm đề tài",
                    value=st.session_state.get("finance_tab2_search", ""),
                    placeholder="Nhập mã đề tài, tên đề tài hoặc chủ nhiệm...",
                    key="finance_tab2_search_input",
                    on_change=_on_search_change,
                    label_visibility="collapsed",
                )
                search_lower = (st.session_state.get("finance_tab2_search", "") or "").strip().lower()

                filtered_projects = {}
                if search_lower:
                    for pid, p in projects.items():
                        haystack = f"{pid} {p.get('name','')} {p.get('pi','')}".lower()
                        if search_lower in haystack:
                            filtered_projects[pid] = p
                else:
                    filtered_projects = projects

                st.markdown("### 📋 Danh sách đề tài")
                if not filtered_projects:
                    st.info("Không tìm thấy đề tài nào khớp với từ khóa tìm kiếm.")
                else:
                    for pid, p in filtered_projects.items():
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([5, 0.6, 0.6])
                            with c1:
                                st.markdown(f"**{pid}** — {p.get('name', '')}")
                                st.caption(
                                    f"Chủ nhiệm: {p.get('pi', '')} · "
                                    f"Nhóm: {p.get('group', '')} · "
                                    f"KP sử dụng: {format_currency(p.get('actual_budget', 0))}"
                                )
                            with c2:
                                if st.button("✏️", key=f"edit_{pid}",
                                             help="Sửa đề tài", width='stretch'):
                                    st.session_state["editing_pid"] = pid
                                    st.rerun()
                            with c3:
                                if st.button("🗑️", key=f"del_{pid}",
                                             help="Xóa đề tài", width='stretch'):
                                    delete_single_project(pid)
                                    st.session_state["_project_flash"] = f"Đã xóa `{pid}`."
                                    st.rerun()

        editing_pid = st.session_state.get("editing_pid")
        if editing_pid:
            if editing_pid in projects:
                _edit_project_dialog(editing_pid, projects[editing_pid])
            else:
                st.session_state["editing_pid"] = None

    # =================================================================
    # TAB 3: SỔ CHỨNG TỪ
    # =================================================================
    with tabs[2]:
        if not projects:
            st.info("Cần có Đề tài trước khi nhập chứng từ.")
        else:
            with st.expander("➕ Thêm Chứng từ Mới", expanded=False):
                with st.form("add_tx", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        tx_proj = st.selectbox(
                            "Thuộc Đề tài",
                            list(projects.keys()),
                            format_func=lambda x: f"{x} - {projects[x].get('name', '')}",
                        )
                        tx_no = st.text_input("Số chứng từ (Hóa đơn/Phiếu chi)")
                        tx_date = st.date_input("Ngày chứng từ")
                        tx_type = st.selectbox("Loại", ["chi", "thu"])
                    with c2:
                        tx_amount = st.number_input("Số tiền (VNĐ)", min_value=0, step=100000)
                        tx_source = st.text_input("Nguồn chi")
                        tx_signer = st.text_input("Người ký duyệt")
                        tx_payer = st.text_input("Người chi / Thụ hưởng")
                    tx_content = st.text_input("Nội dung chi")

                    if st.form_submit_button("💾 Lưu Chứng từ", type="primary"):
                        if not tx_no or tx_amount <= 0:
                            st.error("Số chứng từ và số tiền > 0 là bắt buộc.")
                        else:
                            data = {
                                "project_id": tx_proj, "voucher_no": tx_no,
                                "date": str(tx_date), "type": tx_type,
                                "amount": tx_amount, "content": tx_content,
                                "source": tx_source, "signer": tx_signer,
                                "payer": tx_payer, "notes": "",
                            }
                            add_transaction(data)
                            st.success("Đã thêm chứng từ!")
                            time.sleep(0.5)
                            st.rerun()

            st.markdown("### Lịch sử chứng từ")
            if not transactions:
                st.info("Chưa có chứng từ nào.")
            else:
                df_tx = pd.DataFrame(transactions)
                df_tx = df_tx.sort_values(by="date", ascending=False)
                for _, row in df_tx.iterrows():
                    with st.container(border=True):
                        c1, c2 = st.columns([5, 1])
                        with c1:
                            st.markdown(
                                f"**{row.get('voucher_no', '')}** | "
                                f"{row.get('date', '')} | "
                                f"{format_currency(row.get('amount', 0))} | "
                                f"{row.get('content', '')}"
                            )
                            st.caption(
                                f"Đề tài: {row.get('project_id', '')} | "
                                f"Người ký: {row.get('signer', '')} | "
                                f"Người chi: {row.get('payer', '')}"
                            )
                        with c2:
                            if st.button("🗑️", key=f"del_tx_{row['id']}"):
                                delete_transaction(row["id"])
                                st.rerun()

    # =================================================================
    # TAB 4: NHẬP LIỆU EXCEL (chỉ admin/manager)
    # =================================================================
    with tabs[3]:
        if ctx.role not in ("admin", "manager"):
            st.warning(
                "🔒 Chỉ **Admin/Quản lý tổng hợp** mới có quyền upload Excel.")
        else:
            st.info(
                "💡 File Excel phải có tên chính xác là "
                "**'danh sách đề tài đang thực hiện IOP.xlsx'** và chứa 2 sheet: "
                "`Danh muc de tai`, `Giai ngan 2026`."
            )
            st.warning(
                "⚠️ Upload sẽ **GHI ĐÈ toàn bộ** danh sách đề tài và dữ liệu giải ngân. "
                "Sổ chứng từ (nhập tay) **sẽ được giữ nguyên**."
            )
            uploaded = st.file_uploader("Tải file Excel chuẩn", type=["xlsx"])
            if uploaded:
                if st.button("⚠️ Kiểm tra & Ghi đè dữ liệu", type="primary"):
                    with st.spinner("Đang xử lý..."):
                        ok, msg = validate_and_import_excel(uploaded.getvalue(), uploaded.name)
                        if ok:
                            st.success(msg)
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
