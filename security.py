import bcrypt
import re
import unicodedata


# ---------- Password ----------
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------- Normalize ----------
def _norm(s) -> str:
    return " ".join(str(s or "").strip().lower().split())


def _strip_diacritics(s) -> str:
    if not s:
        return ""
    s = str(s).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _tokenize(s) -> set:
    return set(w for w in _norm(s).split() if len(w) > 1)


def _name_matches_query(name, query) -> bool:
    if not name or not query:
        return False
    if _norm(name) == _norm(query):
        return True
    q = _tokenize(_strip_diacritics(query))
    n = _tokenize(_strip_diacritics(name))
    return bool(q) and q.issubset(n)


# ---------- Date / DOB ----------
def _extract_date_parts(dob):
    if not dob:
        return None
    s = str(dob)
    m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})", s)
    if m:
        return (int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _dob_match(a, b):
    if not a or not b:
        return None
    pa, pb = _extract_date_parts(a), _extract_date_parts(b)
    if pa and pb:
        return pa == pb
    da = "".join(c for c in str(a) if c.isdigit())
    db = "".join(c for c in str(b) if c.isdigit())
    return da == db if da and db else None


# ---------- Detect ----------
NAME_FIELDS = ("ho_va_ten", "ho_ten", "full_name", "fullName", "name")
NAME_FIELDS_EN = ("ho_va_ten_anh", "ten_tieng_anh", "full_name_en",
                  "name_en", "english_name")
DOB_FIELDS = ("ngay_sinh", "ngay_thang_nam_sinh", "dob",
              "date_of_birth", "birth_date")


def detect_name_from_data(d):
    if not d:
        return None
    for f in NAME_FIELDS:
        if d.get(f):
            return str(d[f]).strip()
    return None


def detect_name_en_from_data(d):
    """Trích xuất tên tiếng Anh từ dữ liệu hồ sơ (nếu có)."""
    if not d:
        return None
    for f in NAME_FIELDS_EN:
        if d.get(f):
            return str(d[f]).strip()
    return None


# ---------- Ánh xạ vai trò tác giả khoa học (VI ↔ EN) ----------
# first author = tác giả chính / tác giả đầu
# corresponding author = tác giả liên hệ
# co-author / đồng tác giả = đồng tác giả
AUTHOR_ROLE_VN_TO_EN = {
    "tac gia chinh": "first author",
    "tác giả chính": "first author",
    "tac gia dau": "first author",
    "tác giả đầu": "first author",
    "first author": "first author",
}
AUTHOR_ROLE_EN_TO_VN = {v: k for k, v in AUTHOR_ROLE_VN_TO_EN.items()}

AUTHOR_ROLE_CORRESPONDING_VN_TO_EN = {
    "tac gia lien he": "corresponding author",
    "tác giả liên hệ": "corresponding author",
    "corresponding author": "corresponding author",
}
AUTHOR_ROLE_CORRESPONDING_EN_TO_VN = {v: k for k, v in AUTHOR_ROLE_CORRESPONDING_VN_TO_EN.items()}

AUTHOR_ROLE_COAUTHOR_VN_TO_EN = {
    "dong tac gia": "co-author",
    "đồng tác giả": "co-author",
    "co-author": "co-author",
}
AUTHOR_ROLE_COAUTHOR_EN_TO_VN = {v: k for k, v in AUTHOR_ROLE_COAUTHOR_VN_TO_EN.items()}


def normalize_author_role(role: str) -> dict:
    """
    Chuẩn hóa vai trò tác giả từ chuỗi tự do thành dict boolean.
    Trả về: {"tac_gia_chinh": bool, "tac_gia_lien_he": bool, "dong_tac_gia": bool, "vai_tro_viet_nam": str}
    Mặc định ưu tiên tiếng Việt khi hiển thị.
    """
    if not role:
        return {"tac_gia_chinh": False, "tac_gia_lien_he": False,
                "dong_tac_gia": True, "vai_tro_viet_nam": "Đồng tác giả"}
    r = str(role).strip()
    rl = r.lower()
    result = {"tac_gia_chinh": False, "tac_gia_lien_he": False,
              "dong_tac_gia": False, "vai_tro_viet_nam": r}

    if any(k in rl for k in AUTHOR_ROLE_VN_TO_EN):
        result["tac_gia_chinh"] = True
        result["vai_tro_viet_nam"] = "Tác giả chính"
        return result
    if any(k in rl for k in AUTHOR_ROLE_CORRESPONDING_VN_TO_EN):
        result["tac_gia_lien_he"] = True
        result["vai_tro_viet_nam"] = "Tác giả liên hệ"
        return result
    if any(k in rl for k in AUTHOR_ROLE_COAUTHOR_VN_TO_EN):
        result["dong_tac_gia"] = True
        result["vai_tro_viet_nam"] = "Đồng tác giả"
        return result
    # fallback: coi là đồng tác giả
    result["dong_tac_gia"] = True
    result["vai_tro_viet_nam"] = "Đồng tác giả"
    return result


def detect_dob_from_data(d):
    if not d:
        return None
    for f in DOB_FIELDS:
        if d.get(f):
            return str(d[f]).strip()
    return None


def get_identity(d):
    return detect_name_from_data(d), detect_dob_from_data(d)


def identity_matches(a, b) -> str:
    """'strong' | 'weak' | 'no'"""
    an, ad = get_identity(a)
    bn, bd = get_identity(b)
    if not an or not bn:
        return "no"
    if not (_norm(an) == _norm(bn)
            or _name_matches_query(an, bn)
            or _name_matches_query(bn, an)):
        return "no"
    dr = _dob_match(ad, bd)
    if dr is None:
        return "weak"
    return "strong" if dr else "no"