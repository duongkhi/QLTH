# form_prompts.py
"""
Prompt templates theo loại biểu mẫu. Giúp AI hiểu context và tối ưu điền.
Admin có thể override bằng cách set form_templates.fill_prompt.
"""

CATEGORIES = {
    "cv":           "📄 CV / Resume",
    "ly_lich":      "📋 Sơ yếu lý lịch",
    "don_xin_viec": "✉️ Đơn xin việc",
    "don_de_nghi":  "📝 Đơn đề nghị",
    "bang_khai":    "🗂️ Bản khai",
    "hop_dong":     "📃 Hợp đồng",
    "other":        "🔖 Khác",
}

# Prompt mặc định theo category (chỉ phần rule bổ sung)
CATEGORY_RULES = {
    "cv": """Đây là CV. Quy tắc điền:
- Thông tin cá nhân: họ tên, DOB, địa chỉ, email, sđt
- Học vấn: trường, chuyên ngành, năm bắt đầu/kết thúc
- Kinh nghiệm: công ty, vị trí, thời gian, mô tả
- Kỹ năng, chứng chỉ, ngoại ngữ
- KHÔNG bịa thông tin không có trong hồ sơ.""",

    "ly_lich": """Đây là sơ yếu lý lịch. Quy tắc điền:
- Thông tin bản thân: họ tên, ngày sinh, giới tính, quê quán, hộ khẩu
- CCCD/CMND: số, ngày cấp, nơi cấp
- Gia đình: cha, mẹ, vợ/chồng, con (họ tên + năm sinh + nghề nghiệp)
- Quá trình công tác, khen thưởng, kỷ luật
- KHÔNG bịa thông tin gia đình không có.""",

    "don_xin_viec": """Đây là đơn xin việc. Quy tắc điền:
- Kính gửi: tên công ty/người nhận (nếu có)
- Họ tên, ngày sinh, địa chỉ, sđt, email
- Vị trí ứng tuyển (nếu có trong file, giữ nguyên; nếu không bỏ trống)
- Ngày ký = ngày hiện tại
- Văn phong trang trọng, không dùng từ thân mật.""",

    "don_de_nghi": """Đây là đơn đề nghị. Quy tắc điền:
- Kính gửi
- Họ tên, đơn vị công tác, chức vụ
- Nội dung đề nghị: giữ nguyên nếu có, bỏ trống nếu không
- Ngày ký = ngày hiện tại.""",

    "bang_khai": """Đây là bản khai. Quy tắc điền:
- Thông tin cá nhân đầy đủ
- Nội dung khai báo: điền chính xác theo hồ sơ
- Ngày khai = ngày hiện tại.""",

    "hop_dong": """Đây là hợp đồng. Quy tắc điền:
- Bên A/B: chỉ điền bên có thông tin trong hồ sơ
- Ngày ký, thời hạn hợp đồng
- KHÔNG tự thêm điều khoản.""",

    "other": """Điền thông tin từ hồ sơ vào các trường có sẵn.
Không bịa, không thêm trường mới.""",
}

# Prompt gốc (dùng chung, ghép với CATEGORY_RULES)
BASE_FILL_PROMPT = """Bạn là trợ lý điền biểu mẫu hành chính chính xác cao.

HỒ SƠ:
{profile_json}

BIỂU MẪU (markdown):
{template_markdown}

YÊU CẦU:
- Điền các chỗ trống (dạng `...`, `___`, `[ ]`, `( )`, hoặc sau dấu `:`).
- Giữ nguyên TOÀN BỘ cấu trúc markdown gốc.
- Chỉ thay các giá trị cần điền; giữ nhãn, heading, bullet.
- Trường không có dữ liệu → giữ nguyên dấu chấm (`...`).
- KHÔNG bịa, KHÔNG thêm ghi chú ngoài.

{category_rule}

TRẢ VỀ: DUY NHẤT JSON object:
{{
  "filled_markdown": "<markdown đã điền>",
  "filled_fields": ["Họ và tên", "Ngày sinh", ...]
}}
"""


def build_fill_prompt(profile_data, template_markdown, category,
                      custom_prompt=None):
    """Ghép prompt gốc + rule category (hoặc custom_prompt nếu có)."""
    rule = custom_prompt or CATEGORY_RULES.get(category, CATEGORY_RULES["other"])
    return BASE_FILL_PROMPT.format(
        profile_json=profile_data,
        template_markdown=template_markdown,
        category_rule=rule,
    )


def detect_category_from_title(title: str) -> str:
    """Đoán category từ title."""
    import unicodedata
    s = str(title or "").lower()
    s = s.replace("đ", "d")
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    rules = [
        ("cv",           ["cv", "resume", "curriculum"]),
        ("ly_lich",      ["ly lich", "so yeu"]),
        ("don_xin_viec", ["don xin viec", "xin viec", "ung tuyen"]),
        ("don_de_nghi",  ["don de nghi", "de nghi"]),
        ("bang_khai",    ["ban khai", "khai"]),
        ("hop_dong",     ["hop dong"]),
    ]
    for cat, kws in rules:
        if any(kw in s for kw in kws):
            return cat
    return "other"