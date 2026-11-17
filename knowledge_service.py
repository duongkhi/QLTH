import os
import json
import pymupdf
import streamlit as st
from google.genai import types


def _extract_text_from_page(page):
    """Trích xuất text từ trang, fallback sang rawdict nếu là text ẩn/lỗi font."""
    # Bước 1: Thử đọc text thường
    text = page.get_text("text")
    if len(text.strip()) >= 10:
        return text
    
    # Bước 2: Fallback đọc rawdict (bắt text ẩn và text lỗi font TCVN3)
    raw_text = ""
    rawdict = page.get_text("rawdict")
    for block in rawdict.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                raw_text += span.get("text", "")
            raw_text += "\n"
    return raw_text


def extract_chunk_from_pdf(pdf_path, start_page=0, max_pages_per_run=10):
    """
    Bóc tách PDF:
    - PDF có text (kể cả text ẩn) → gửi text cho Gemini.
    - PDF scan ảnh thuần → gửi PDF cho Gemini Vision OCR.
    """
    from ai_client import get_client
    client = get_client()
    if not client:
        return 0, 0, [], 0, "❌ Chưa cấu hình API Key."

    if not os.path.exists(pdf_path):
        return 0, 0, [], 0, f"❌ File không tồn tại: {pdf_path}"

    try:
        doc = pymupdf.open(pdf_path)
        total_pages = len(doc)
        if start_page >= total_pages:
            doc.close()
            return 0, 0, [], total_pages, "Đã xử lý xong file."
        
        end_page = min(start_page + max_pages_per_run, total_pages)
        
        # --- BƯỚC 1: Trích xuất text ---
        chunk_text = ""
        for i in range(start_page, end_page):
            chunk_text += _extract_text_from_page(doc[i]) + "\n"
            
        pages_this_run = end_page - start_page
        is_scanned = len(chunk_text.strip()) < 50
        
        # --- BƯỚC 2: Gọi AI theo loại file ---
        if is_scanned:
            st.info(f"📷 PDF scan ảnh thuần — OCR {pages_this_run} trang bằng Gemini Vision (có thể chậm)...")
            # Cắt PDF gửi Vision
            sub_doc = pymupdf.open()
            sub_doc.insert_pdf(doc, from_page=start_page, to_page=end_page - 1)
            pdf_bytes = sub_doc.tobytes()
            sub_doc.close()
            doc.close()
            
            prompt_text = f"""Bạn là chuyên gia pháp chế Việt Nam. Đây là {pages_this_run} trang ảnh scan của văn bản pháp luật.
Hãy đọc kỹ và trích xuất thành MẢNG JSON.
Mỗi quy định có:
- "dieu_khoan": Số điều khoản
- "noi_dung": Nội dung quy định
- "muc_chi": Mức chi (nếu có, null nếu không)
CHỈ trả về mảng JSON, KHÔNG bọc markdown."""
            
            try:
                resp = client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=[
                        types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                        types.Part.from_text(text=prompt_text),
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW)
                    )
                )
            except Exception as e:
                return 0, pages_this_run, [], total_pages, f"❌ Lỗi gọi AI (Vision): {e}"
        else:
            st.info(f"📄 PDF có text (hoặc text ẩn) — Trích xuất {pages_this_run} trang...")
            doc.close()
            prompt_text = f"""Bạn là chuyên gia pháp chế. Trích xuất các quy định thành MẢNG JSON.
Mỗi quy định có: "dieu_khoan", "noi_dung", "muc_chi" (null nếu không có).
CHỈ trả về mảng JSON, KHÔNG bọc markdown.

Văn bản:
\"\"\"
{chunk_text}
\"\"\"
"""
            try:
                resp = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt_text,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
                    )
                )
            except Exception as e:
                return 0, pages_this_run, [], total_pages, f"❌ Lỗi gọi AI (Text): {e}"

        # --- BƯỚC 3: Xử lý kết quả ---
        tokens_used = 0
        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            tokens_used = resp.usage_metadata.total_token_count

        raw_response = resp.text or ""
        st.caption(f"🤖 AI trả về {len(raw_response)} ký tự ({tokens_used:,} tokens)")

        rules = []
        try:
            raw = raw_response.strip()
            if raw.startswith("```json"): raw = raw[7:]
            if raw.startswith("```"): raw = raw[3:]
            if raw.endswith("```"): raw = raw[:-3]
            raw = raw.strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rules = parsed
            elif isinstance(parsed, dict):
                for key in ("rules", "quy_dinh", "data", "items"):
                    if key in parsed and isinstance(parsed[key], list):
                        rules = parsed[key]
                        break
                else:
                    rules = [parsed]
            
            st.caption(f"✅ Parse được {len(rules)} quy định")
        except Exception as e:
            st.error(f"❌ Lỗi parse JSON: {e}")
            st.code(raw_response[:500])
            return tokens_used, pages_this_run, [], total_pages, f"❌ Parse lỗi: {e}"

        return tokens_used, pages_this_run, rules, total_pages, "OK"

    except Exception as e:
        import traceback
        st.error(f"❌ Lỗi:\n{traceback.format_exc()}")
        return 0, 0, [], 0, f"❌ {e}"