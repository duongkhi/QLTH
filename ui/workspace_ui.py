# ui/workspace_ui.py
import streamlit as st
from config import UserContext, SYSTEM_TOOLS
from ui.finance_module import render_finance_module
from ui.knowledge_ui import render_knowledge_ui
from form_templates import (
    list_form_templates, delete_form_template, save_form_template,
    extract_fields_heuristic, extract_fields_with_ai, slugify_template_id,
)
from docx_utils import extract_document_title, strip_personal_content


def render_workspace_module(ctx: UserContext, allowed_tools: list[str]):
    effective_tools = list(SYSTEM_TOOLS.keys()) if ctx.role == "admin" else [
        t for t in allowed_tools if t in SYSTEM_TOOLS
    ]

    if "workspace" not in effective_tools:
        st.warning("⚠️ Bạn chưa được cấp quyền sử dụng Quản lý tài chính.")
        return

    render_finance_module(ctx)


def _render_template_library_manager(ctx: UserContext):
    st.subheader("📚 Quản Lý Thư Viện Biểu Mẫu Dùng Chung")
    upf = st.file_uploader("Nạp biểu mẫu mới vào thư viện (.docx)", type=["docx"], key="ws_tpl_up")
    if upf:
        raw_bytes = upf.getvalue()
        title = extract_document_title(raw_bytes) or upf.name.replace(".docx", "")
        title_in = st.text_input("Tên biểu mẫu:", value=title, key="ws_tpl_title")
        if st.button("💾 Lưu biểu mẫu vào thư viện", type="primary"):
            fields = extract_fields_heuristic(raw_bytes)
            if len(fields) < 3:
                prog = st.progress(20, text="🤖 AI đang phân tích trường...")
                fields, _, _ = extract_fields_with_ai(raw_bytes, prog)
                prog.progress(100, text="✅ Xong")
            clean_bytes = strip_personal_content(raw_bytes, fields)
            tid = slugify_template_id(title_in)
            save_form_template(tid=tid, title=title_in, fields=fields, docx_bytes=clean_bytes, created_by=ctx.username)
            st.success(f"✅ Đã lưu mẫu **{title_in}** ({len(fields)} trường).")
            st.rerun()

    st.markdown("---")
    for t in list_form_templates():
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"**{t['title']}** (`{t['id']}`) · {len(t.get('fields', []))} trường")
            if c2.button("🗑️ Xóa", key=f"ws_del_{t['id']}", width='stretch'):
                delete_form_template(t["id"])
                st.rerun()