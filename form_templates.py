# form_templates.py
import base64
import io
import re
import time
from datetime import datetime

import mammoth
from docx import Document

from supabase_adapter import get_client  # ⚠️ đổi theo adapter của bạn
from config import MAX_CHARS
from security import _norm, _strip_diacritics
from docx_utils import extract_document_title, smart_truncate
from ai_client import call_model_json
from form_prompts import detect_category_from_title, CATEGORIES


TABLE = "form_templates"


# =============================================================
# 1. Đọc metadata (nhẹ, KHÔNG kéo docx_bytes)
# =============================================================
def list_form_templates(include_markdown=False):
    """Trả về list[dict] không có docx_bytes."""
    cols = "id,title,title_normalized,category,fields,created_at,created_by,updated_at"
    if include_markdown:
        cols += ",markdown,fill_prompt"
    resp = get_client().table(TABLE).select(cols).order(
        "updated_at", desc=True).execute()
    return resp.data or []


def get_form_template(tid):
    """Metadata + markdown + fill_prompt (KHÔNG có docx_bytes)."""
    resp = get_client().table(TABLE).select(
        "id,title,title_normalized,category,fields,markdown,fill_prompt,"
        "created_at,created_by,updated_at"
    ).eq("id", tid).single().execute()
    return resp.data


def get_template_docx_bytes(tid):
    """Lazy load — CHỈ gọi khi user bấm 'Điền'."""
    resp = get_client().table(TABLE).select("docx_bytes").eq(
        "id", tid).single().execute()
    raw = resp.data.get("docx_bytes") if resp.data else None
    if not raw:
        return None
    # Supabase trả về BYTEA dạng hex string "\x..." hoặc base64 tùy driver
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        if raw.startswith("\\x"):
            return bytes.fromhex(raw[2:])
        try:
            return bytes.fromhex(raw)
        except ValueError:
            try:
                return base64.b64decode(raw)
            except Exception:
                return raw.encode("latin-1")
    return None


# =============================================================
# 2. Lưu template (markdown + docx_bytes + prompt)
# =============================================================
def _docx_to_markdown(docx_bytes):
    """Convert DOCX → markdown qua mammoth (giữ heading, table, list)."""
    try:
        with io.BytesIO(docx_bytes) as f:
            result = mammoth.convert_to_markdown(f)
        return result.value or ""
    except Exception:
        return ""


def _docx_to_bytea(docx_bytes):
    """Chuyển sang hex cho PostgREST BYTEA."""
    return "\\x" + docx_bytes.hex()


def save_form_template(tid, title, fields, docx_bytes,
                       created_by, category=None, custom_prompt=None):
    """Insert/Update template."""
    markdown = _docx_to_markdown(docx_bytes)
    if not markdown.strip():
        raise ValueError("Không convert được DOCX sang markdown.")

    cat = category or detect_category_from_title(title)
    payload = {
        "id": tid,
        "title": title.strip(),
        "title_normalized": _norm(_strip_diacritics(title)),
        "category": cat,
        "fields": list(fields),
        "markdown": markdown,
        "fill_prompt": (custom_prompt or "").strip() or None,
        "docx_bytes": _docx_to_bytea(docx_bytes),
        "created_by": created_by,
    }
    # upsert
    get_client().table(TABLE).upsert(payload, on_conflict="id").execute()
    return payload


def update_template_prompt(tid, custom_prompt):
    """Admin sửa prompt riêng cho template."""
    get_client().table(TABLE).update({
        "fill_prompt": (custom_prompt or "").strip() or None,
    }).eq("id", tid).execute()


def update_template_meta(tid, title=None, category=None, fields=None):
    patch = {}
    if title is not None:
        patch["title"] = title.strip()
        patch["title_normalized"] = _norm(_strip_diacritics(title))
    if category is not None:
        patch["category"] = category
    if fields is not None:
        patch["fields"] = list(fields)
    if patch:
        get_client().table(TABLE).update(patch).eq("id", tid).execute()


def delete_form_template(tid):
    get_client().table(TABLE).delete().eq("id", tid).execute()


# =============================================================
# 3. Matching & Slug
# =============================================================
def slugify_template_id(title):
    s = _strip_diacritics(title or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or f"tpl_{int(time.time())}"


def match_template_by_title(title, templates):
    """templates = list[dict] từ list_form_templates()."""
    if not title:
        return None
    tn = _norm(_strip_diacritics(title))
    for t in templates:
        tt = t.get("title_normalized", "")
        if tt and tn and (tn == tt or tn in tt or tt in tn):
            return t["id"]
    return None


# =============================================================
# 4. Field extraction (giữ nguyên)
# =============================================================
def extract_fields_heuristic(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    fields, seen = [], set()

    def add(s):
        s = (s or "").strip()
        if not s:
            return
        m = re.match(r"^([^:\.：]{1,80}?)\s*[:：]", s)
        if m:
            label = m.group(1).strip()
            if label and label not in seen:
                seen.add(label); fields.append(label)
            return
        m = re.match(r"^([^\.]{1,80}?)\s*\.{3,}", s)
        if m:
            label = m.group(1).strip()
            if label and label not in seen:
                seen.add(label); fields.append(label)

    for p in doc.paragraphs:
        add(p.text)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    add(p.text)
    return fields


def extract_fields_with_ai(docx_bytes, progress=None):
    doc = Document(io.BytesIO(docx_bytes))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for t in doc.tables:
        for r in t.rows:
            cells = [c.text.strip() for c in r.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    raw = smart_truncate("\n".join(parts), 12000)
    prompt = f"""Trích xuất danh sách TÊN TRƯỜNG cần điền từ văn bản sau.
Văn bản:
\"\"\"
{raw}
\"\"\"
Trả về DUY NHẤT JSON: {{"title": "...", "category": "cv|ly_lich|don_xin_viec|don_de_nghi|bang_khai|hop_dong|other", "fields": [...]}}
- Chỉ lấy nhãn trường, KHÔNG lấy giá trị cá nhân.
"""
    if progress is None:
        class _Dummy:
            def progress(self, *a, **kw): pass
        progress = _Dummy()
    try:
        import json
        out = call_model_json(prompt, progress, 20, 80, label="🤖 Trích fields")
        data = json.loads(out)
        fields = [f.strip() for f in data.get("fields", []) if f and f.strip()]
        title = (data.get("title") or "").strip() or None
        cat = (data.get("category") or "").strip() or None
        return fields, title, cat
    except Exception:
        return [], None, None