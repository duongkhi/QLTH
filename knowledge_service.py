import os
import json
import pdfplumber
from google.genai import types
from ai_client import get_client

def extract_chunk_from_pdf(pdf_path, start_page=0, max_pages_per_run=3):
    """
    Trích xuất max_pages_per_run trang bắt đầu từ start_page.
    Trả về: (tokens_used, pages_processed_this_time, rules_extracted, total_pages, msg)
    """
    client = get_client()
    if not client:
        return 0, 0, [], 0, "Chưa cấu hình API Key."

    if not os.path.exists(pdf_path):
        return 0, 0, [], 0, "File không tồn tại."

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            if start_page >= total_pages:
                return 0, 0, [], total_pages, "Đã xử lý xong file."

            end_page = min(start_page + max_pages_per_run, total_pages)
            chunk_text = ""
            
            for i in range(start_page, end_page):
                text = pdf.pages[i].extract_text()
                if text:
                    chunk_text += text + "\n"
            
            if not chunk_text.strip():
                return 0, (end_page - start_page), [], total_pages, "Trang rỗng (bỏ qua)."

            prompt = f"""
Bạn là chuyên gia pháp chế. Trích xuất các quy định, định mức chi tiêu từ văn bản thô sau thành mảng JSON.
Yêu cầu mỗi phần tử có:
- "dieu_khoan": Số điều, khoản (VD: "Điều 5, Khoản 2")
- "noi_dung": Nội dung tóm tắt (ngắn gọn)
- "muc_chi": Mức chi cụ thể (VD: "1.500.000đ/ngày", hoặc null)
- "doi_tuong": Đối tượng áp dụng (VD: "Chuyên gia", "Cán bộ")
- "tu_khoa": Mảng từ khóa tìm kiếm (VD: ["công tác phí", "chuyên gia"])

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
                parsed = json.loads(resp.text)
                if isinstance(parsed, list):
                    rules = parsed
            except Exception:
                pass
            
            return tokens_used, (end_page - start_page), rules, total_pages, "OK"

    except Exception as e:
        return 0, 0, [], 0, f"Lỗi: {e}"