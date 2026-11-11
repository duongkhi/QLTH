import io
import re
import streamlit as st
import streamlit.components.v1 as components
from docx import Document
import mammoth

from config import MAX_CHARS

# =====================================================================
# BẢNG MÃ SỬA LỖI FONT TCVN3 (Mojibake)
# =====================================================================
TCVN3_MAP = {
    "H·": "Họ", "h·": "họ", "vµ": "và", "tªn": "tên", "Sè": "Số", "chong": "chứng", 
    "minh": "minh", "Tªn": "Tên", "trêng": "trường", "Mèi": "Mối", "quan": "quan", 
    "hÖ": "hệ", "Hä": "Họ", "®": "đ", "tõ": "từ", "®Õn": "đến", "b³ng": "bằng", 
    "cÊp": "cấp", "ngµy": "ngày", "th,ng": "tháng", "n¨m": "năm", "nam": "nam", 
    "n÷": "nữ", "tr×nh": "trình", "®é": "độ", "chuyªn": "chuyên", "m«n": "môn",
    "®-n": "đơn", "vÞ": "vị", "c«ng": "công", "t¸c": "tác", "®¶ng": "đảng",
    "®oµn": "đoàn", "thÓ": "thể", "trêng": "trường", "tØnh": "tỉnh", "phè": "phố",
    "quËn": "quận", "huyÖn": "huyện", "x·": "xã", "th«n": "thôn", "ng¸ch": "ngách",
    "nghiÖp": "nghiệp", "chÝnh": "chính", "trÞ": "trị", "ngo¹i": "ngoại", "ng÷": "ngữ",
    "tin": "tin", "häc": "học", "Tªn": "Tên", "®µo": "đào", "t¹o": "tạo", "båi": "bồi",
    "dìng": "dưỡng", "H×nh": "Hình", "thøc": "thức", "V¨n": "Văn", "chøng": "chứng",
    "chØ": "chỉ", "Kü": "Kỹ", "s-": "sư", "Cö": "Cử", "nh©n": "nhân", "Th.s": "Th.s",
    "TS": "TS", "TSKH": "TSKH", "Gi¸o": "Giáo", "s-": "sư", "Phã": "Phó"
}

def fix_tcvn3_text(text: str) -> str:
    """Sửa lỗi font TCVN3 cơ bản sang Unicode."""
    if not text:
        return text
    for k, v in TCVN3_MAP.items():
        text = text.replace(k, v)
    return text


# ---------- Extract ----------
def extract_text_from_docx(uf):
    doc = Document(uf)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(fix_tcvn3_text(p.text.strip()))
            
    for t in doc.tables:
        for r in t.rows:
            cells = [fix_tcvn3_text(c.text.strip()) for c in r.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
                
    return "\n".join(parts)


@st.cache_data(show_spinner=False, max_entries=20)
def cached_extract_docx(b: bytes) -> str:
    return extract_text_from_docx(io.BytesIO(b))


def smart_truncate(t, m=MAX_CHARS):
    return t if len(t) <= m else t[:m] + f"\n\n[...lược {len(t) - m:,} ký tự...]"


# ---------- Preview ----------
def render_docx_preview(b, height=600):
    try:
        html = mammoth.convert_to_html(io.BytesIO(b)).value
        if not html.strip():
            return
        styled = f"""<div style="font-family:'Segoe UI',Arial;font-size:15px;
        line-height:1.7;padding:20px;background:white;color:#222;">
        <style>table{{border-collapse:collapse;width:100%;margin:8px 0;}}
        td,th{{border:1px solid #ccc;padding:6px 10px;}}
        th{{background:#f0f0f0;}}p{{margin:6px 0;}}</style>{html}</div>"""
        components.html(styled, height=height, scrolling=True)
    except Exception as e:
        st.warning(f"Không hiển thị được: {e}")


# ---------- Title ----------
FORM_TITLE_KEYWORDS = [
    "sơ yếu", "lý lịch", "curriculum", "cv", "resume",
    "đơn xin", "đơn đề nghị", "đơn đăng ký", "đơn ứng tuyển",
    "bản khai", "hồ sơ", "thông tin cá nhân", "biểu mẫu", "mẫu số",
]


def extract_document_title(docx_bytes):
    try:
        doc = Document(io.BytesIO(docx_bytes))
    except Exception:
        return None
    from security import _strip_diacritics
    for p in doc.paragraphs[:20]:
        txt = fix_tcvn3_text(p.text.strip())
        if not txt:
            continue
        low = _strip_diacritics(txt).lower()
        for kw in FORM_TITLE_KEYWORDS:
            if kw in low:
                return txt[:120]
    for p in doc.paragraphs[:15]:
        txt = fix_tcvn3_text(p.text.strip())
        if not txt or len(txt) > 120:
            continue
        if p.runs and any(r.bold for r in p.runs if r.text and r.bold):
            return txt
        try:
            if p.alignment is not None and "CENTER" in str(p.alignment).upper():
                return txt
        except Exception:
            pass
    for p in doc.paragraphs:
        if p.text.strip():
            return fix_tcvn3_text(p.text.strip())[:120]
    return None


# ---------- Strip personal content (template cleaning) ----------
def _strip_paragraph(p, field):
    txt = fix_tcvn3_text(p.text)
    pat1 = re.compile(rf"^(\s*{re.escape(field)}\s*[:：]\s*)(.*)$")
    m = pat1.match(txt)
    if m:
        prefix = m.group(1)
        new = prefix + "...................."
        if p.runs:
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
        else:
            p.text = new
        return True
    pat2 = re.compile(rf"^(\s*{re.escape(field)})\s*\.{{3,}}.*$")
    m2 = pat2.match(txt)
    if m2:
        prefix = m2.group(1)
        new = prefix + " ...................."
        if p.runs:
            p.runs[0].text = new
            for r in p.runs[1:]:
                r.text = ""
        else:
            p.text = new
        return True
    return False


def strip_personal_content(docx_bytes, fields):
    doc = Document(io.BytesIO(docx_bytes))
    for p in doc.paragraphs:
        for f in fields:
            _strip_paragraph(p, f)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for f in fields:
                        _strip_paragraph(p, f)
    bio = io.BytesIO()
    doc.save(bio)
    return bio.getvalue()


# ---------- Truncate profile ----------
def truncate_profile_for_prompt(data, max_chars):
    """Cắt profile nhưng vẫn giữ JSON hợp lệ."""
    import json
    s = json.dumps(data, ensure_ascii=False)
    if len(s) <= max_chars:
        return data
    priority = ["ho_va_ten", "ho_ten", "full_name", "fullName", "name",
                "ngay_sinh", "dob", "date_of_birth", "gioi_tinh",
                "que_quan", "dia_chi", "cccd", "cmnd",
                "so_dien_thoai", "email"]
    result, total = {}, 2
    for f in priority:
        if f in data:
            v = str(data[f])[:200]
            chunk = len(json.dumps({f: v}, ensure_ascii=False))
            if total + chunk < max_chars:
                result[f] = v
                total += chunk
    for k, v in data.items():
        if k in result:
            continue
        v = str(v)[:200]
        chunk = len(json.dumps({k: v}, ensure_ascii=False))
        if total + chunk < max_chars:
            result[k] = v
            total += chunk
    return result