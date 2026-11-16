import os
import json
import fitz  # PyMuPDF
from google.genai import types

def extract_chunk_from_pdf(pdf_path, start_page=0, max_pages_per_run=3):
    """Khung cứng: Đọc text, gửi AI bóc tách thô thành JSON."""
    from ai_client import get_client
    client = get_client()
    if not client:
        return 0, 0, [], 0, "Chưa cấu hình API Key."

    if not os.path.exists(pdf_path):
        return 0, 0, [], 0, "File không tồn tại."

    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        if start_page >= total_pages:
            return 0, 0, [], total_pages, "Đã xử lý xong file."

        end_page = min(start_page + max_pages_per_run, total_pages)
        chunk_text = ""
        
        for i in range(start_page, end_page):
            text = doc[i].get_text("text")
            if text:
                chunk_text += text + "\n"
        doc.close()

        if not chunk_text.strip():
            return 0, (end_page - start_page), [], total_pages, "Trang rỗng (bỏ qua)."

        # PROMPT TỐI GIẢN: Bóc tách được là được, không cần phân loại
        prompt = f"""
        Trích xuất các quy định trong đoạn văn bản pháp luật sau thành mảng JSON.
        Mỗi quy định gồm các trường:
        - "dieu_khoan": Số điều (VD: "Điều 5")
        - "noi_dung": Nội dung quy định
        - "muc_chi": Mức chi (nếu có, nếu không thì null)
        
        Văn bản thô:
        \"\"\"
        {chunk_text}
        \"\"\"
        """
        
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
            )
        )
        
        tokens_used = 0
        if hasattr(resp, "usage_metadata") and resp.usage_metadata:
            tokens_used = resp.usage_metadata.total_token_count

        rules = []
        try:
            # Làm sạch markdown và parse an toàn
            raw_text = resp.text.strip()
            if raw_text.startswith("```json"): raw_text = raw_text[7:]
            if raw_text.endswith("```"): raw_text = raw_text[:-3]
            
            parsed = json.loads(raw_text.strip())
            if isinstance(parsed, list):
                rules = parsed
        except Exception:
            pass # Nuốt lỗi, chấp nhận file này không trích được gì
        
        return tokens_used, (end_page - start_page), rules, total_pages, "OK"

    except Exception as e:
        return 0, 0, [], 0, f"Lỗi: {e}"