import os
import json
import time
import toml

from google import genai
from google.genai import types
import pymupdf

# ============================================================
# 1. ĐỌC API KEY TỪ secrets.toml
# ============================================================
SECRETS_PATH = ".streamlit/secrets.toml"
api_key = None

if os.path.exists(SECRETS_PATH):
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        secrets = toml.load(f)
        api_key = secrets.get("GEMINI_API_KEY")
    print(f"✅ Đọc key từ {SECRETS_PATH}: {api_key[:10]}...{api_key[-5:] if api_key else ''}")
else:
    api_key = os.environ.get("GEMINI_API_KEY")
    print(f"⚠️ Không thấy {SECRETS_PATH}, dùng env var")

if not api_key:
    print("❌ KHÔNG TÌM THẤY GEMINI_API_KEY")
    exit(1)

client = genai.Client(api_key=api_key)

# ============================================================
# 2. CẮT 3 TRANG ĐẦU CỦA PDF
# ============================================================
PDF_PATH = "44TT.pdf"

if not os.path.exists(PDF_PATH):
    print(f"❌ Không tìm thấy file {PDF_PATH}")
    exit(1)

print(f"\n📄 Đang cắt 3 trang đầu của {PDF_PATH}...")
doc = pymupdf.open(PDF_PATH)
total = len(doc)
sub = pymupdf.open()
sub.insert_pdf(doc, from_page=0, to_page=2)
pdf_bytes = sub.tobytes()
doc.close()
sub.close()

print(f"✅ Đã cắt 3/{total} trang → {len(pdf_bytes)/1024:.0f} KB")

# ============================================================
# 3. GỬI PDF CHO GEMINI
# ============================================================
print("\n🤖 Gửi PDF cho Gemini Vision...")
t0 = time.time()

try:
    resp = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            types.Part.from_text(text=(
                "Đây là 3 trang của Thông tư pháp luật Việt Nam (có thể là scan). "
                "Hãy đọc và trích xuất 5 quy định đầu tiên thành JSON array. "
                "Mỗi quy định có: dieu_khoan, noi_dung, muc_chi (null nếu không có). "
                "CHỈ trả về JSON, không bọc markdown."
            )),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.LOW
            ),
        ),
    )
except Exception as e:
    print(f"❌ Lỗi gọi AI: {e}")
    exit(1)

elapsed = time.time() - t0
print(f"⏱ Thời gian: {elapsed:.1f} giây")

if resp.usage_metadata:
    print(f"💰 Tokens: {resp.usage_metadata.total_token_count:,}")

# ============================================================
# 4. PARSE KẾT QUẢ
# ============================================================
print(f"\n📝 AI trả về {len(resp.text)} ký tự")
print("=" * 60)

raw = resp.text.strip()
if raw.startswith("```json"): raw = raw[7:]
if raw.startswith("```"): raw = raw[3:]
if raw.endswith("```"): raw = raw[:-3]
raw = raw.strip()

try:
    rules = json.loads(raw)
    print(f"✅ Parse được {len(rules)} quy định\n")
    for i, r in enumerate(rules[:5], 1):
        print(f"{i}. [{r.get('dieu_khoan', '?')}]")
        print(f"   {r.get('noi_dung', '')[:120]}")
        if r.get("muc_chi"):
            print(f"   💰 {r['muc_chi']}")
        print()
except Exception as e:
    print(f"❌ Parse lỗi: {e}")
    print(f"Raw text: {raw[:500]}")

print("=" * 60)
print("✅ HOÀN TẤT")