import streamlit as st
import pandas as pd
import time
from config import UserContext
from finance_service import (
    load_finance_data, format_currency, get_project_metrics,
    validate_and_import_excel,
    add_single_project, delete_single_project, update_single_project,
    add_transaction, delete_transaction, get_visible_project_ids,
)
from finance_agent import chat_with_finance_ai


@st.dialog("✏️ Sửa đề tài")
def _edit_project_dialog(pid: str, project: dict):
    st.caption(f"Mã đề tài: **{pid}** (không thể đổi)")

    name = st.text_input("Tên đề tài", value=project.get("name", ""))
    c1, c2 = st.columns(2)
    with c1:
        pi = st.text_input("Chủ nhiệm", value=project.get("pi", ""))
        group = st.text_input("Nhóm", value=project.get("group", ""))
    with c2:
        duration = st.text_input("Thời gian", value=project.get("duration", ""))
        task_type = st.text_input("Loại nhiệm vụ", value=project.get("task_type", ""))

    unit = st.text_input("Đơn vị chủ trì", value=project.get("unit", "Viện Vật lý"))

    st.markdown("**Kinh phí (VNĐ)**")
    c1, c2, c3 = st.columns(3)
    with c1:
        total_budget = st.number_input(
            "Tổng KP đề tài", min_value=0, step=1000000,
            value=int(project.get("total_budget", 0)))
    with c2:
        allocated_budget = st.number_input(
            "KP giao dự toán", min_value=0, step=1000000,
            value=int(project.get("allocated_budget", 0)))
    with c3:
        actual_budget = st.number_input(
            "KP sử dụng thực tế", min_value=0, step=1000000,
            value=int(project.get("actual_budget", 0)))

    st.markdown("---")
    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button("💾 Lưu thay đổi", type="primary", use_container_width=True):
            ok, msg = update_single_project(pid, {
                "name": name, "pi": pi, "group": group,
                "duration": duration, "task_type": task_type, "unit": unit,
                "total_budget": total_budget,
                "allocated_budget": allocated_budget,
                "actual_budget": actual_budget,
            })
            st.session_state["editing_pid"] = None
            st.session_state["_project_flash"] = msg
            st.rerun()
    with col_cancel:
        if st.button("❌ Hủy", use_container_width=True):
            st.session_state["editing_pid"] = None
            st.rerun()


def render_finance_module(ctx: UserContext):
    st.title("💰 Quản Lý Tài Chính Đề Tài")
    st.caption("Tổng hợp giải ngân · Quản lý đề tài · Sổ chứng từ · Trợ lý AI")

    projects_raw, disb_raw, tx_raw = load_finance_data()

    # --- PHÂN QUYỀN ---
    visible_pids = get_visible_project_ids(ctx, projects_raw)
    if visible_pids is None:
        # admin/manager: xem tất cả
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

    # --- Banner thông báo cho user thường ---
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

    # Flash message sau khi lưu
    flash = st.session_state.pop("_project_flash", None)
    if flash:
        st.success(flash)

    tabs = st.tabs([
        "📊 Tổng quan",
        "📁 Quản lý Đề tài",
        "🧾 Sổ chứng từ",
        "📤 Nhập liệu Excel",
        "🤖 Trợ lý AI",
    ])

    # =================================================================
    # TAB 1: TỔNG QUAN
    # =================================================================
    with tabs[0]:
        if not projects:
            if not is_restricted:
                st.info("Chưa có dữ liệu. Vui lòng sang tab 'Nhập liệu Excel' để nạp dữ liệu.")
            # user thường đã có warning ở đầu module
        else:
            total_budget = sum(p.get("actual_budget", 0) for p in projects.values())
            total_cum = sum(
                max(d.get("cumulative", {}).values() or [0])
                for d in disbursements.values())
            total_settled = sum(d.get("settled_2026", 0) for d in disbursements.values())

            c1, c2, c3 = st.columns(3)
            c1.metric("Tổng kinh phí thực tế", format_currency(total_budget))
            c2.metric("Đã giải ngân lũy kế", format_currency(total_cum),
                      delta=f"{(total_cum/total_budget*100):.1f}%" if total_budget else "0%")
            c3.metric("Đã quyết toán 2026", format_currency(total_settled))

            st.markdown("### 📋 Danh sách tổng hợp")
            table_data = []
            for pid, p in projects.items():
                d = disbursements.get(pid, {})
                m = get_project_metrics(pid, p, d)
                table_data.append({
                    "Mã ĐT": pid,
                    "Tên đề tài": p.get("name", ""),
                    "Chủ nhiệm": p.get("pi", ""),
                    "Kinh phí": m["actual_budget"],
                    "Giải ngân": m["current_cum"],
                    "Tỷ lệ %": m["rate"],
                })
            df = pd.DataFrame(table_data)
            st.dataframe(df, column_config={
                "Kinh phí": st.column_config.NumberColumn(format="%d đ"),
                "Giải ngân": st.column_config.NumberColumn(format="%d đ"),
                "Tỷ lệ %": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0, max_value=100),
            }, use_container_width=True, hide_index=True)

    # =================================================================
    # TAB 2: QUẢN LÝ ĐỀ TÀI (chỉ admin/manager)
    # =================================================================
    with tabs[1]:
        if ctx.role not in ("admin", "manager"):
            st.warning(
                "🔒 Chỉ **Admin/Quản lý tổng hợp** mới có quyền Thêm/Sửa/Xóa đề tài. "
                "Bạn chỉ có thể xem dữ liệu ở tab **Tổng quan**.")
        else:
            with st.expander("➕ Thêm Đề tài mới", expanded=False):
                with st.form("add_proj", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        new_pid = st.text_input("Mã đề tài")
                        new_name = st.text_input("Tên đề tài")
                        new_pi = st.text_input("Chủ nhiệm")
                    with c2:
                        new_group = st.text_input("Nhóm", placeholder="VD: a / b / Chuyển tiếp")
                        new_budget = st.number_input(
                            "Kinh phí thực tế (VNĐ)", step=1000000, min_value=0)
                    if st.form_submit_button("Lưu Đề tài", type="primary"):
                        if not new_pid or not new_name:
                            st.error("Cần nhập Mã và Tên đề tài.")
                        else:
                            ok, msg = add_single_project(
                                new_pid, new_name, new_pi, new_group, new_budget)
                            if ok:
                                st.success(msg)
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(msg)

            if projects:
                st.markdown("### 📋 Danh sách đề tài")
                for pid, p in projects.items():
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
                                         help="Sửa đề tài", use_container_width=True):
                                st.session_state["editing_pid"] = pid
                                st.rerun()
                        with c3:
                            if st.button("🗑️", key=f"del_{pid}",
                                         help="Xóa đề tài", use_container_width=True):
                                delete_single_project(pid)
                                st.session_state["_project_flash"] = f"Đã xóa `{pid}`."
                                st.rerun()

        # Dialog nằm ngoài role-check để vẫn mở được nếu state còn sót
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

    # =================================================================
    # TAB 5: TRỢ LÝ AI (phân quyền theo allowed_project_ids)
    # =================================================================
    with tabs[4]:
        st.markdown(
            "Hỏi AI về tài chính. VD: *'Tổng kinh phí đề tài của tôi là bao nhiêu?'*, "
            "*'Đề tài CT0000 có những chứng từ nào?'*"
        )

        if is_restricted:
            st.caption(
                f"🔒 AI chỉ trả lời về **{len(projects)} đề tài** do bạn chủ nhiệm.")

        if "finance_chat" not in st.session_state:
            st.session_state.finance_chat = []
        if st.button("🗑️ Xóa lịch sử chat", key="clear_f_chat"):
            st.session_state.finance_chat = []
            st.rerun()

        for msg in st.session_state.finance_chat:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Nhập câu hỏi tài chính..."):
            st.session_state.finance_chat.append(
                {"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Đang truy xuất dữ liệu..."):
                    ans, used_tool = chat_with_finance_ai(
                        prompt,
                        st.session_state.finance_chat,
                        allowed_project_ids=visible_pids,
                    )
                    st.markdown(ans)
                    if used_tool:
                        st.caption("📊 Đã truy xuất từ Database")

            st.session_state.finance_chat.append(
                {"role": "assistant", "content": ans})