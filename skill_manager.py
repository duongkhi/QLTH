# skill_manager.py
# Hệ thống tạo & phân quyền Skill kế toán, lưu toàn bộ kho kỹ năng trên Supabase
# bảng app_data dưới key "hermes_skills_registry".
#
# Cấu trúc mỗi Skill:
#   {
#     "skill_name": str,      # tên hàm viết liền, không dấu (vd: tong_hop_luong_thang)
#     "creator": str,         # tên user tạo skill
#     "description": str,     # mô tả nghiệp vụ bằng tiếng Việt
#     "code": str,            # mã Python thực thi hoàn chỉnh (hàm execute(args, ctx))
#     "allowed_users": [str]  # danh sách user được phép dùng skill này
#   }

import json
import os
import re
import streamlit as st

from supabase_adapter import load_json_from_db, save_json_to_db
from nvidia_client import call_ai_with_fallback

SKILL_REGISTRY_KEY = "hermes_skills_registry"

# Regex kiểm tra tên skill hợp lệ: chỉ chữ cái, số, gạch dưới, bắt đầu bằng chữ cái
_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ============================================================
# CRUD kho kỹ năng
# ============================================================
def load_skills_registry() -> dict:
    """Tải toàn bộ kho kỹ năng từ Supabase. Trả về {skill_name: skill_dict}."""
    return load_json_from_db(SKILL_REGISTRY_KEY) or {}


def save_skills_registry(registry: dict) -> bool:
    """Lưu toàn bộ kho kỹ năng lên Supabase."""
    return save_json_to_db(SKILL_REGISTRY_KEY, registry)


def list_skills() -> list[dict]:
    """Trả về danh sách các skill (mỗi phần tử là dict kèm key skill_name)."""
    reg = load_skills_registry()
    return [{**v, "skill_name": k} for k, v in reg.items()]


def get_skill(skill_name: str) -> dict | None:
    """Lấy chi tiết một skill theo tên."""
    reg = load_skills_registry()
    return reg.get(skill_name)


def skill_exists(skill_name: str) -> bool:
    return skill_name in load_skills_registry()


def create_skill(
    skill_name: str,
    creator: str,
    description: str,
    code: str,
    allowed_users: list[str] | None = None,
) -> bool:
    """Tạo skill mới. Trả False nếu skill_name đã tồn tại hoặc tên không hợp lệ."""
    if not _SKILL_NAME_RE.match(skill_name or ""):
        return False
    reg = load_skills_registry()
    if skill_name in reg:
        return False
    reg[skill_name] = {
        "skill_name": skill_name,
        "creator": creator,
        "description": description,
        "code": code,
        "allowed_users": allowed_users or [creator],
    }
    return save_skills_registry(reg)


def update_skill(skill_name: str, fields: dict) -> bool:
    """Cập nhật một số trường của skill (description, code, allowed_users...)."""
    reg = load_skills_registry()
    if skill_name not in reg:
        return False
    reg[skill_name].update(fields)
    # Đảm bảo skill_name luôn khớp với key
    reg[skill_name]["skill_name"] = skill_name
    return save_skills_registry(reg)


def delete_skill(skill_name: str) -> bool:
    """Xóa một skill khỏi kho."""
    reg = load_skills_registry()
    if skill_name not in reg:
        return False
    del reg[skill_name]
    return save_skills_registry(reg)


def add_allowed_user(skill_name: str, username: str) -> bool:
    """Thêm một user vào danh sách allowed_users của skill."""
    reg = load_skills_registry()
    if skill_name not in reg:
        return False
    users = reg[skill_name].setdefault("allowed_users", [])
    if username not in users:
        users.append(username)
    return save_skills_registry(reg)


def remove_allowed_user(skill_name: str, username: str) -> bool:
    """Bỏ một user khỏi danh sách allowed_users của skill."""
    reg = load_skills_registry()
    if skill_name not in reg:
        return False
    users = reg[skill_name].get("allowed_users", [])
    if username in users:
        users.remove(username)
    return save_skills_registry(reg)


def can_use_skill(skill_name: str, username: str) -> bool:
    """Kiểm tra user có quyền dùng skill hay không."""
    skill = get_skill(skill_name)
    if not skill:
        return False
    return username in skill.get("allowed_users", [])


# ============================================================
# Sinh skill tự động bằng Gemini API
# ============================================================
def _call_gemini_json(prompt: str) -> str | None:
    """Gọi Gemini API để sinh JSON. Trả về chuỗi JSON text hoặc None nếu lỗi."""
    try:
        from google import genai
        from google.genai import types
    except Exception:
        return None

    api_key = ""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return None

    client = genai.Client(api_key=api_key)
    cfg = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        response_mime_type="application/json",
    )
    for model_name in ("gemini-3.8-flash", "gemini-3.5-flash-lite"):
        try:
            resp = client.models.generate_content(
                model=model_name, contents=prompt, config=cfg
            )
            return resp.text
        except Exception:
            continue
    return None


def _clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def generate_skill_from_request(user_request: str) -> dict | None:
    """
    Gọi Gemini API sinh một skill từ yêu cầu tiếng Việt.
    Trả về dict {skill_name, description, code} hoặc None nếu lỗi.
    """
    prompt = f"""
Bạn là trợ lý lập trình chuyên nghiệp, chuyên về hệ thống kế toán và hồ sơ nhân sự.

Yêu cầu của người dùng (tiếng Việt):
"{user_request}"

Hãy tự động thiết kế một kỹ năng (Skill) tự động hóa. Trả về JSON thuần với các trường:
- skill_name: tên hàm viết liền, không dấu, chỉ chữ thường, số và gạch dưới, bắt đầu bằng chữ (ví dụ: tong_hop_luong_thang)
- description: mô tả nghiệp vụ bằng tiếng Việt, ngắn gọn, dễ hiểu
- code: mã Python thực thi hoàn chỉnh. Hàm chính phải tên là execute(args, ctx) và trả về dict.
  * args: dict các tham số đầu vào
  * ctx: dict chứa các hàm hỗ trợ: ctx["load_profile"](key) để đọc hồ sơ, ctx["get_name"](key) để lấy tên, ctx["allowed_profiles"] là danh sách hồ sơ được phép truy cập
  Không import thư viện ngoài ngoài những gì đã có sẵn (json, math, re, datetime...).
  Không được bao hàm markdown, chỉ trả về JSON thuần.

CHỈ trả về JSON, không giải thích thêm, không bao bọc trong ```json ...
"""
    raw = call_ai_with_fallback(prompt)
    if not raw:
        return None

    try:
        data = json.loads(_clean_json_text(raw))
    except Exception:
        return None

    # Chuẩn hóa và làm sạch tên skill
    name = data.get("skill_name", "").strip()
    name = name.lower().replace(" ", "_").replace("-", "_")
    name = re.sub(r"[^a-z0-9_]", "", name)
    if not name or not _SKILL_NAME_RE.match(name):
        name = "skill_moi_tao"

    data["skill_name"] = name
    data.setdefault("description", "")
    data.setdefault("code", "")
    return data


# ============================================================
# Skill mặc định: Thống kê bài báo khoa học
# ============================================================
STATISTICS_SKILL_CODE = '''
def execute(args, ctx):
    """Thống kê bài báo khoa học theo chuẩn Scopus/ISI (Skill Admin)."""
    from_year = args.get("from_year")
    to_year = args.get("to_year")
    unit = str(args.get("unit", "")).strip().lower()
    person = str(args.get("person", "")).strip().lower()
    export_excel = bool(args.get("export_excel", False))

    load_profile = ctx["load_profile"]
    get_name = ctx["get_name"]
    allowed_profiles = ctx.get("allowed_profiles", [])

    rows = []
    for key in allowed_profiles:
        prof = load_profile(key) or {}
        name = get_name(key)

        if person and person not in str(name).lower():
            continue
        don_vi = str(prof.get("don_vi_cong_tac", "") or prof.get("don_vi", "")).lower()
        if unit and unit not in don_vi:
            continue

        pubs = prof.get("bai_bao_chuan_scopus", [])
        if not isinstance(pubs, list):
            pubs = prof.get("cong_bo", [])
        if not isinstance(pubs, list):
            pubs = prof.get("bai_bao", [])
        if not isinstance(pubs, list):
            pubs = []

        for p in pubs:
            if not isinstance(p, dict):
                continue
            try:
                y = int(p.get("year") or 0)
            except Exception:
                y = 0
            if from_year and y < int(from_year):
                continue
            if to_year and y > int(to_year):
                continue

            rows.append({
                "Ma HS": key,
                "Ho ten": name,
                "Ten bai bao": p.get("title", ""),
                "Tac gia": p.get("authors", ""),
                "Vai tro": p.get("author_role", ""),
                "Tap chi": p.get("source_title", ""),
                "Nam": y,
                "Tap": p.get("volume", ""),
                "So": p.get("issue", ""),
                "Trang": p.get("page_range", ""),
                "DOI": p.get("doi", ""),
                "ISSN": p.get("issn", ""),
                "ISBN": p.get("isbn", ""),
                "Loai chi so": p.get("index_type", ""),
                "Quy": p.get("quartile", ""),
                "Loai bai bao": p.get("document_type", ""),
            })

    total = len(rows)
    isi = sum(1 for r in rows if "ISI" in str(r["Loai chi so"]))
    scopus = sum(1 for r in rows if "Scopus" in str(r["Loai chi so"]))
    trong_nuoc = sum(1 for r in rows if "Trong" in str(r["Loai chi so"]))
    q1 = sum(1 for r in rows if str(r["Quy"]) == "Q1")
    q2 = sum(1 for r in rows if str(r["Quy"]) == "Q2")
    q3 = sum(1 for r in rows if str(r["Quy"]) == "Q3")
    q4 = sum(1 for r in rows if str(r["Quy"]) == "Q4")

    summary = {
        "Tong so": total,
        "ISI/SCIE": isi,
        "Scopus": scopus,
        "Trong nuoc": trong_nuoc,
        "Q1": q1,
        "Q2": q2,
        "Q3": q3,
        "Q4": q4,
    }

    result = {
        "summary": summary,
        "rows": rows,
        "filters": {
            "from_year": from_year,
            "to_year": to_year,
            "unit": unit,
            "person": person,
        },
    }

    if export_excel and rows:
        import pandas as pd
        import io
        df = pd.DataFrame(rows)
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Bai_bao")
        bio.seek(0)
        result["_excel_bytes"] = bio.getvalue()
        result["download_token"] = f"thong_ke_bai_bao_{from_year or ''}_{to_year or ''}"

    return result
'''


def ensure_statistics_skill() -> bool:
    """Đăng ký Skill thống kê bài báo vào kho nếu chưa tồn tại."""
    if skill_exists("thong_ke_bai_bao_khoa_hoc"):
        return True
    return create_skill(
        skill_name="thong_ke_bai_bao_khoa_hoc",
        creator="admin",
        description=(
            "Thống kê bài báo khoa học theo chuẩn Scopus/ISI. "
            "Hỗ trợ lọc theo khoảng năm, đơn vị/tập thể và cá nhân, "
            "lập bảng tổng hợp theo phân loại và xuất Excel."
        ),
        code=STATISTICS_SKILL_CODE,
        allowed_users=["admin"],
    )
