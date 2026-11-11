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
DOB_FIELDS = ("ngay_sinh", "ngay_thang_nam_sinh", "dob",
              "date_of_birth", "birth_date")


def detect_name_from_data(d):
    if not d:
        return None
    for f in NAME_FIELDS:
        if d.get(f):
            return str(d[f]).strip()
    return None


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