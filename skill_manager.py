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
from storage import load_user_profile, load_name_mapping
from security import detect_name_from_data

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
    """
    Gọi NVIDIA API để sinh JSON skill. Giữ tên _call_gemini_json để tương thích.
    """
    try:
        from nvidia_client import call_nvidia_json
    except Exception:
        return None

    try:
        text = call_nvidia_json(prompt)
        return text
    except Exception:
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
    """Thong ke bai bao khoa hoc tu truong bai_bao_cong_bo cua tung ho so (Skill Admin)."""
    from storage import load_json_from_db
    import pandas as pd
    import io

    from_year = args.get("from_year")
    to_year = args.get("to_year")
    unit = str(args.get("unit", "")).strip().lower()
    person = str(args.get("person", "")).strip().lower()
    export_excel = bool(args.get("export_excel", False))

    allowed_profiles = ctx.get("allowed_profiles", [])
    load_profile = ctx["load_profile"]
    get_name = ctx["get_name"]

    def _norm(s):
        if not s:
            return ""
        import unicodedata
        s = unicodedata.normalize("NFD", str(s))
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
        return s.lower().replace(" ", "").replace("_", "").replace("-", "")

    def _parse_phan_loai(phan_loai):
        pl = str(phan_loai or "").strip()
        pl_upper = pl.upper()
        index_type = ""
        quartile = ""
        if "SCOPUS" in pl_upper:
            index_type = "Scopus"
        elif "ISI" in pl_upper or "SCI" in pl_upper:
            index_type = "ISI/SCI-EE"
        elif "HOI NGHI" in pl_upper or "HỘI NGHỊ" in pl_upper:
            index_type = "Hội nghị"
        elif "TAP CHI TRONG NUOC" in pl_upper or "TẠP CHÍ TRONG NƯỚC" in pl_upper:
            index_type = "Tạp chí trong nước"
        else:
            index_type = "Khác"
        for q in ("Q1", "Q2", "Q3", "Q4"):
            if q in pl_upper:
                quartile = q
                break
        return index_type, quartile

    rows = []
    for key in allowed_profiles:
        prof = load_profile(key) or {}
        name = get_name(key)

        if person and person not in str(name).lower():
            continue
        don_vi = _norm(prof.get("don_vi_cong_tac", "") or prof.get("don_vi", ""))
        don_vi_con = _norm(prof.get("don_vi_cong_tac_con", ""))
        if unit and _norm(unit) not in don_vi and _norm(unit) not in don_vi_con:
            continue

        # Ưu tiên đọc từ bai_bao_cong_bo (đã chuẩn hóa từ file CV)
        pubs_raw = prof.get("bai_bao_cong_bo", [])
        if not isinstance(pubs_raw, list):
            pubs_raw = []
        use_new = bool(pubs_raw)
        if not use_new:
            pubs_raw = prof.get("bai_bao_chuan_scopus", [])
            if not isinstance(pubs_raw, list):
                pubs_raw = prof.get("cong_bo", [])
            if not isinstance(pubs_raw, list):
                pubs_raw = prof.get("bai_bao", [])
            if not isinstance(pubs_raw, list):
                pubs_raw = []

        for p in pubs_raw:
            if not isinstance(p, dict):
                continue
            if use_new:
                phan_loai = str(p.get("phan_loai", "")).strip()
                index_type, quartile = _parse_phan_loai(phan_loai)
                if p.get("tac_gia_dau"):
                    author_role = "Tác giả đầu"
                    authors = "Tác giả đầu"
                elif p.get("tac_gia_lien_he"):
                    author_role = "Tác giả liên hệ"
                    authors = "Tác giả liên hệ"
                elif p.get("dong_tac_gia"):
                    author_role = "Đồng tác giả"
                    authors = "Đồng tác giả"
                else:
                    author_role = str(p.get("vai_tro", "")).strip()
                    authors = author_role
                try:
                    y = int(p.get("nam_cong_bo") or 0)
                except Exception:
                    y = 0
                pub = {
                    "title": str(p.get("ten_cong_trinh", "")).strip(),
                    "authors": authors,
                    "author_role": author_role,
                    "source_title": str(p.get("noi_cong_bo", "")).strip(),
                    "year": str(y),
                    "doi": str(p.get("doi", "")).strip(),
                    "issn": str(p.get("issn", "")).strip(),
                    "index_type": index_type,
                    "quartile": quartile,
                    "document_type": str(p.get("loai_cong_trinh", "")).strip(),
                    "units": [prof.get("don_vi_cong_tac", "") or prof.get("don_vi", "")],
                    "internal_authors": [key],
                }
            else:
                pub = p
                try:
                    y = int(pub.get("year") or 0)
                except Exception:
                    y = 0

            if from_year and y < int(from_year):
                continue
            if to_year and y > int(to_year):
                continue

            rows.append({
                "Ma bai bao": pub.get("title", ""),
                "Ten bai bao": pub.get("title", ""),
                "Ma HS": key,
                "Ho ten": name,
                "Tac gia": pub.get("authors", ""),
                "Vai tro": pub.get("author_role", ""),
                "Tap chi": pub.get("source_title", ""),
                "Nam": y,
                "DOI": pub.get("doi", ""),
                "ISSN": pub.get("issn", ""),
                "Loai chi so": pub.get("index_type", ""),
                "Quy": pub.get("quartile", ""),
                "Loai bai bao": pub.get("document_type", ""),
                "Don vi": "; ".join(pub.get("units", []) or []),
                "So tac gia noi bo": len(pub.get("internal_authors", []) or []),
                "Danh sach tac gia noi bo": "; ".join(pub.get("internal_authors", []) or []),
            })

    rows.sort(key=lambda r: r["Nam"], reverse=True)

    total_unique = len(rows)
    total_contributions = sum(r["So tac gia noi bo"] for r in rows)
    isi = sum(1 for r in rows if "ISI" in str(r["Loai chi so"]))
    scopus = sum(1 for r in rows if "Scopus" in str(r["Loai chi so"]))
    trong_nuoc = sum(1 for r in rows if "Trong" in str(r["Loai chi so"]))
    q1 = sum(1 for r in rows if str(r["Quy"]) == "Q1")
    q2 = sum(1 for r in rows if str(r["Quy"]) == "Q2")
    q3 = sum(1 for r in rows if str(r["Quy"]) == "Q3")
    q4 = sum(1 for r in rows if str(r["Quy"]) == "Q4")

    summary = {
        "Tong so bai duy nhat": total_unique,
        "Tong luot dong hop": total_contributions,
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



# ============================================================
# Skill mac dinh: Quan ly lich lam viec
# ============================================================
QUAN_LY_LICH_LAM_VIEC_CODE = '''
def execute(args, ctx):
    """Quan ly lich lam viec: xem, them, sua, xoa ca lam viec cua mot ho so."""
    from storage import save_user_profile, load_user_profile
    from datetime import datetime

    action = str(args.get("action", "xem")).strip().lower()
    profile_key = str(args.get("profile_key", "")).strip()
    allowed_profiles = ctx.get("allowed_profiles", [])
    load_profile = ctx.get("load_profile")

    if not profile_key:
        return {"error": "Vui long cung cap profile_key (ma ho so nhan vien)."}
    if profile_key not in allowed_profiles:
        return {"error": f"Ban khong co quyen truy cap ho so '{profile_key}'."}

    def _now_id():
        return datetime.now().strftime("%Y%m%d%H%M%S%f")

    def _get_shifts(prof):
        shifts = prof.get("lich_lam_viec", [])
        if not isinstance(shifts, list):
            shifts = []
        return shifts

    def _save(prof, shifts):
        prof["lich_lam_viec"] = shifts
        save_user_profile(profile_key, prof)
        return prof

    if action == "xem":
        prof = load_profile(profile_key) or {}
        shifts = _get_shifts(prof)
        thang = args.get("thang")
        nam = args.get("nam")
        if thang or nam:
            loc = []
            for s in shifts:
                ngay = str(s.get("ngay", ""))
                ok_nam = (not nam) or ngay.startswith(str(nam))
                ok_thang = (not thang) or ngay[5:7] == f"{int(thang):02d}"
                if ok_nam and ok_thang:
                    loc.append(s)
            shifts = loc
        shifts.sort(key=lambda s: str(s.get("ngay", "")))
        return {
            "profile_key": profile_key,
            "tong_so_ca": len(shifts),
            "rows": shifts,
            "filters": {"thang": thang, "nam": nam},
        }

    if action == "them":
        ngay = str(args.get("ngay", "")).strip()
        ca = str(args.get("ca", "")).strip()
        gio_vao = str(args.get("gio_vao", "")).strip()
        gio_ra = str(args.get("gio_ra", "")).strip()
        ghi_chu = str(args.get("ghi_chu", "")).strip()
        if not ngay or not ca:
            return {"error": "Vui long nhap ngay va ca lam viec."}
        try:
            datetime.strptime(ngay, "%Y-%m-%d")
        except Exception:
            return {"error": "Ngay phai co dinh dang YYYY-MM-DD (vi du: 2026-11-23)."}
        prof = load_profile(profile_key) or {}
        shifts = _get_shifts(prof)
        ca_moi = {
            "id": _now_id(),
            "ngay": ngay,
            "ca": ca,
            "gio_vao": gio_vao,
            "gio_ra": gio_ra,
            "ghi_chu": ghi_chu,
        }
        shifts.append(ca_moi)
        _save(prof, shifts)
        return {
            "message": f"Da them ca lam viec vao ngay {ngay} ({ca}).",
            "ca": ca_moi,
            "tong_so_ca": len(shifts),
        }

    if action == "sua":
        ca_id = str(args.get("ca_id", "")).strip()
        if not ca_id:
            return {"error": "Vui long cung ca ca_id (ma ca) de sua."}
        prof = load_profile(profile_key) or {}
        shifts = _get_shifts(prof)
        tim_thay = False
        for s in shifts:
            if str(s.get("id", "")) == ca_id:
                if args.get("ngay"):
                    s["ngay"] = str(args["ngay"]).strip()
                if args.get("ca"):
                    s["ca"] = str(args["ca"]).strip()
                if "gio_vao" in args:
                    s["gio_vao"] = str(args.get("gio_vao") or "").strip()
                if "gio_ra" in args:
                    s["gio_ra"] = str(args.get("gio_ra") or "").strip()
                if "ghi_chu" in args:
                    s["ghi_chu"] = str(args.get("ghi_chu") or "").strip()
                tim_thay = True
                break
        if not tim_thay:
            return {"error": f"Khong tim thay ca lam viec co ma '{ca_id}'."}
        _save(prof, shifts)
        return {"message": f"Da cap nhat ca lam viec ma {ca_id}.", "ca_id": ca_id}

    if action == "xoa":
        ca_id = str(args.get("ca_id", "")).strip()
        if not ca_id:
            return {"error": "Vui long cung ca ca_id (ma ca) de xoa."}
        prof = load_profile(profile_key) or {}
        shifts = _get_shifts(prof)
        moi = [s for s in shifts if str(s.get("id", "")) != ca_id]
        if len(moi) == len(shifts):
            return {"error": f"Khong tim thay ca lam viec co ma '{ca_id}'."}
        _save(prof, moi)
        return {"message": f"Da xoa ca lam viec ma {ca_id}.", "tong_so_ca": len(moi)}

    if action == "thong_ke":
        prof = load_profile(profile_key) or {}
        shifts = _get_shifts(prof)
        nam = args.get("nam")
        thang = args.get("thang")
        theo_ngay = {}
        tong = 0
        for s in shifts:
            ngay = str(s.get("ngay", ""))
            if nam and not ngay.startswith(str(nam)):
                continue
            if thang and ngay[5:7] != f"{int(thang):02d}":
                continue
            tong += 1
            theo_ngay[ngay] = theo_ngay.get(ngay, 0) + 1
        rows = [{"ngay": k, "so_ca": v} for k, v in sorted(theo_ngay.items())]
        return {
            "profile_key": profile_key,
            "tong_so_ca": tong,
            "so_ngay_lam": len(rows),
            "rows": rows,
            "filters": {"nam": nam, "thang": thang},
        }

    return {"error": f"Han dong '{action}' khong duoc ho tro. Dung: xem, them, sua, xoa, thong_ke."}
'''

def ensure_quan_ly_lich_lam_viec_skill() -> bool:
    """Dang ky Skill quan ly lich lam viec vao kho neu chua ton tai."""
    if skill_exists("quan_ly_lich_lam_viec"):
        return True
    return create_skill(
        skill_name="quan_ly_lich_lam_viec",
        creator="system",
        description=(
            "Quan ly lich lam viec: xem, them, sua, xoa ca lam viec cua "
            "mot ho so nhan vien. Luu du lieu vao profile cua nhan vien do. "
            "Chi duoc xem/sua ho so trong danh sach phep duoc cap."
        ),
        code=QUAN_LY_LICH_LAM_VIEC_CODE,
        allowed_users=["admin"],
    )


# ============================================================
# SKILL TREE CONFIG (cay thu muc skill rieng cho moi user)
# ============================================================
SKILL_TREE_PREFIX = "skill_tree_"

def get_skill_tree_config(username: str) -> dict:
    """Lấy cấu hình cây skill của một user. Trả về dict {folder_name: [skill_names]}."""
    if not username:
        return {}
    return load_json_from_db(f"{SKILL_TREE_PREFIX}{username}") or {}

def save_skill_tree_config(username: str, tree: dict) -> bool:
    """Lưu cấu hình cây skill của một user lên Supabase."""
    if not username:
        return False
    return save_json_to_db(f"{SKILL_TREE_PREFIX}{username}", tree)

def add_skill_to_user_tree(username: str, skill_name: str, folder: str = "Khác") -> bool:
    """Thêm một skill vào cây thư mục của user. Mặc định vào folder 'Khác'."""
    if not username or not skill_name:
        return False
    tree = get_skill_tree_config(username)
    if folder not in tree:
        tree[folder] = []
    if skill_name not in tree[folder]:
        tree[folder].append(skill_name)
    return save_skill_tree_config(username, tree)

def remove_skill_from_user_tree(username: str, skill_name: str) -> bool:
    """Xóa skill khỏi cây thư mục của user."""
    if not username or not skill_name:
        return False
    tree = get_skill_tree_config(username)
    for folder, skills in tree.items():
        if skill_name in skills:
            skills.remove(skill_name)
            if not skills:
                del tree[folder]
            break
    return save_skill_tree_config(username, tree)

def get_user_skill_tree(username: str) -> list[dict]:
    """
    Trả về danh sách skill có quyền dùng của user, đã sắp xếp theo cây thư mục.
    Mỗi phần tử: {"folder": str, "skills": [{"name": str, "description": str}]}
    """
    if not username:
        return []
    tree = get_skill_tree_config(username)
    reg = load_skills_registry()
    result = []
    for folder, skill_names in tree.items():
        skills_info = []
        for sn in skill_names:
            skill = reg.get(sn)
            if skill and username in skill.get("allowed_users", []):
                skills_info.append({
                    "name": sn,
                    "description": skill.get("description", ""),
                })
        if skills_info:
            result.append({"folder": folder, "skills": skills_info})
    return result


# ============================================================
# CHẠY SKILL TỪ SIDEBAR
# ============================================================
def run_skill(skill_name: str, args: dict, username: str, allowed_profiles: list) -> dict:
    """
    Chạy một skill với tham số args.
    Trả về dict kết quả (bao gồm _excel_bytes nếu có).
    """
    reg = load_skills_registry()
    skill = reg.get(skill_name)
    if not skill:
        return {"error": f"Không tìm thấy skill '{skill_name}'."}

    if username not in skill.get("allowed_users", []):
        return {"error": f"Bạn không có quyền chạy skill '{skill_name}'."}

    code = skill.get("code", "")
    if not code:
        return {"error": f"Skill '{skill_name}' không có mã thực thi."}

    # Tạo ctx cho skill
    def load_profile(key):
        return load_user_profile(key)

    def get_name(key):
        m = load_name_mapping()
        return m.get(key, {}).get("display_name") or detect_name_from_data(load_user_profile(key)) or key

    ctx = {
        "load_profile": load_profile,
        "get_name": get_name,
        "allowed_profiles": allowed_profiles,
    }

    # Thực thi code skill trong namespace riêng
    namespace = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return {"error": f"Lỗi khi nạp mã skill: {e}"}

    execute_fn = namespace.get("execute")
    if not execute_fn or not callable(execute_fn):
        return {"error": f"Skill '{skill_name}' không có hàm execute(args, ctx)."}

    try:
        result = execute_fn(args, ctx)
        return result if isinstance(result, dict) else {"result": result}
    except Exception as e:
        return {"error": f"Lỗi khi chạy skill: {e}"}
