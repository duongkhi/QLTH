import streamlit as st, streamlit.components.v1 as components
import json, os, io, time, math, re, unicodedata
from docx import Document
from google import genai
from google.genai import types
from google.genai.errors import APIError
import bcrypt, mammoth
from supabase_adapter import (
    load_json_from_db, save_json_to_db, delete_key_from_db, list_all_keys,
)

DATA_DIR = "./database"
LOG_FILE = os.path.join(DATA_DIR, "system_logs.txt")
MAX_CHARS = 25000
MAX_RETRIES = 2
MODELS_TO_TRY = [
    {"name": "gemini-3.8-flash", "thinking": types.ThinkingLevel.LOW},
    {"name": "gemini-3.5-flash-lite", "thinking": types.ThinkingLevel.MINIMAL},
]
CHAT_MODELS_TO_TRY = ["gemini-3.5-flash-lite", "gemini-3.8-flash"]

st.set_page_config(page_title="AI Agent Hành Chính Bảo Mật", page_icon="🔒", layout="wide")
st.markdown("""<style>
    html, body, [class*="css"] { font-size: 18px; }
    h1 { font-size: 2.4rem !important; } h2 { font-size: 1.9rem !important; }
    h3 { font-size: 1.4rem !important; }
    p, li, label, .stMarkdown p { font-size: 1.1rem !important; line-height: 1.6; }
    input, textarea, select, button { font-size: 1.05rem !important; }
    [data-testid="stChatMessage"] p { font-size: 1.15rem !important; line-height: 1.6; }
    hr { margin: 2rem 0 !important; }
</style>""", unsafe_allow_html=True)


# ============= BẢO MẬT =============
def hash_password(p):
    return bcrypt.hashpw(p.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(p, h):
    try:
        return bcrypt.checkpw(p.encode("utf-8"), h.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ============= MIGRATION =============
def _migrate_user_record(uname, rec):
    if "role" not in rec:
        a = rec.get("allowed_profiles", [])
        rec["role"] = "admin" if "admin" in a else ("manager" if len(a) > 1 else "user")
    role = rec["role"]
    if "own_profile" not in rec:
        if role == "user":
            rec["own_profile"] = uname
        else:
            a = rec.get("allowed_profiles", [])
            rec["own_profile"] = uname if uname in a else None
    if role == "user" and not rec.get("own_profile"):
        rec["own_profile"] = uname
    rec.pop("allowed_profiles", None)
    return rec


# ============= DB WRAPPERS =============
META_KEYS = {"auth_config", "name_mapping"}

def load_auth_config():
    cfg = load_json_from_db("auth_config")
    if not cfg or "users" not in cfg:
        cfg = {"users": {
            "admin": {
                "password_hash": hash_password("adminpassword"),
                "own_profile": None,
                "role": "admin",
            },
        }}
        save_json_to_db("auth_config", cfg)
    for u, r in cfg.get("users", {}).items():
        _migrate_user_record(u, r)
    return cfg

def save_auth_config(cfg):
    save_json_to_db("auth_config", cfg)

def load_user_profile(name):
    if not name:
        return {}
    return load_json_from_db(name) or {}

def save_user_profile(name, data):
    if not name:
        return
    save_json_to_db(name, data)

def load_name_mapping():
    return load_json_from_db("name_mapping") or {}

def save_name_mapping(m):
    save_json_to_db("name_mapping", m)

def get_all_existing_profiles():
    return sorted(k for k in list_all_keys()
                  if k not in META_KEYS and not k.startswith("_"))

def write_system_log(user, action, status):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {user} | {action} | {status}\n")
    except Exception:
        pass


# ============= QUYỀN =============
def compute_allowed_profiles(rec):
    role = rec.get("role", "user")
    own = rec.get("own_profile")
    if role in ("admin", "manager"):
        p = set(get_all_existing_profiles())
        if own:
            p.add(own)
        return sorted(p)
    return [own] if own else []

def get_own_profile(rec, username):
    """Có thể trả về None với admin/manager chưa gán profile."""
    return rec.get("own_profile")


# ============= NORMALIZE =============
def _norm(s):
    return " ".join(str(s or "").strip().lower().split())

def _strip_diacritics(s):
    if not s:
        return ""
    s = str(s).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

def _tokenize(s):
    return set(w for w in _norm(s).split() if len(w) > 1)

def _name_matches_query(name, query):
    if not name or not query:
        return False
    if _norm(name) == _norm(query):
        return True
    q = _tokenize(_strip_diacritics(query))
    n = _tokenize(_strip_diacritics(name))
    return bool(q) and q.issubset(n)


# ============= NAME MAPPING =============
def sync_name_mapping(profiles):
    m = load_name_mapping()
    changed = False
    for k in profiles:
        if not k or k in m:
            continue
        d = load_user_profile(k)
        if not d:
            continue
        for field in ("ho_va_ten", "ho_ten", "full_name", "fullName", "name"):
            if d.get(field):
                m[k] = {"display_name": str(d[field]).strip(), "aliases": []}
                changed = True
                break
    if changed:
        save_name_mapping(m)

def update_name_mapping_from_profile(key, data):
    if not data:
        return
    for field in ("ho_va_ten", "ho_ten", "full_name", "fullName", "name"):
        if data.get(field):
            m = load_name_mapping()
            m.setdefault(key, {})
            m[key]["display_name"] = str(data[field]).strip()
            m[key].setdefault("aliases", [])
            save_name_mapping(m)
            return

def resolve_profile(query, allowed):
    q = str(query or "").strip()
    if not q:
        return None, [], "empty", "Tên rỗng."
    if q in allowed:
        return q, [], None, None
    for k in allowed:
        if k.lower() == q.lower():
            return k, [], None, None
    m = load_name_mapping()
    exact, partial = set(), set()
    for k, info in m.items():
        if k not in allowed:
            continue
        names = [info.get("display_name", "")] + list(info.get("aliases", []))
        for n in names:
            if not n:
                continue
            if _norm(n) == _norm(q):
                exact.add(k)
                break
            if _name_matches_query(n, q):
                partial.add(k)
    if len(exact) == 1:
        return list(exact)[0], [], None, None
    if len(exact) > 1:
        return None, sorted(exact), "ambiguous", f"Nhiều hồ sơ trùng tên '{q}': {sorted(exact)}. Hỏi lại."
    if len(partial) == 1:
        return list(partial)[0], [], None, None
    if len(partial) > 1:
        return None, sorted(partial), "ambiguous", f"Nhiều hồ sơ khớp '{q}': {sorted(partial)}. Hỏi lại."
    qs = _strip_diacritics(q).replace(" ", "").lower()
    for k in allowed:
        if _strip_diacritics(k).replace(" ", "").lower() == qs:
            return k, [], None, None
    avail = {k: v.get("display_name", "") for k, v in m.items() if k in allowed}
    return None, [], "not_found", f"Không tìm thấy hồ sơ khớp '{q}'. Có sẵn: {avail or list(allowed)}."

def find_profile_in_text(text, allowed):
    m = load_name_mapping()
    tn = _norm(text)
    best, blen = None, 0
    for k, info in m.items():
        if k not in allowed:
            continue
        names = [info.get("display_name", "")] + list(info.get("aliases", []))
        for n in names:
            if not n:
                continue
            nn = _norm(n)
            if nn and nn in tn and len(nn) > blen:
                best, blen = k, len(nn)
    return best


# ============= IDENTITY =============
def detect_name_from_data(d):
    if not d:
        return None
    for f in ("ho_va_ten", "ho_ten", "full_name", "fullName", "name"):
        if d.get(f):
            return str(d[f]).strip()
    return None

def detect_dob_from_data(d):
    if not d:
        return None
    for f in ("ngay_sinh", "ngay_thang_nam_sinh", "dob",
              "date_of_birth", "birth_date", "sinh_ngay"):
        if d.get(f):
            return str(d[f]).strip()
    return None

def get_identity(d):
    return detect_name_from_data(d), detect_dob_from_data(d)

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

def identity_matches(a, b):
    an, ad = get_identity(a)
    bn, bd = get_identity(b)
    if not an or not bn:
        return "no"
    if not (_norm(an) == _norm(bn) or _name_matches_query(an, bn) or _name_matches_query(bn, an)):
        return "no"
    dr = _dob_match(ad, bd)
    if dr is None:
        return "weak"
    return "strong" if dr else "no"

def find_identity_matches(new_data, allowed):
    res = []
    for k in allowed:
        e = load_user_profile(k)
        if not e:
            continue
        s = identity_matches(new_data, e)
        if s in ("strong", "weak"):
            res.append((k, s))
    res.sort(key=lambda x: (0 if x[1] == "strong" else 1, x[0]))
    return res

def suggest_profile_key(name):
    if not name:
        return ""
    s = _strip_diacritics(name).strip()
    return "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", s))

def merge_and_save(key, new_data, overwrite=False):
    final = dict(new_data) if overwrite else {**load_user_profile(key), **new_data}
    save_user_profile(key, final)
    update_name_mapping_from_profile(key, final)
    return final

def reset_upload_state():
    for k in ("upload_stage", "upload_extracted",
              "upload_detected_name", "upload_detected_dob"):
        st.session_state[k] = None


# ============= ROLE / USER =============
def get_user_role(rec):
    r = rec.get("role", "user")
    labels = {"admin": "👑 Quản trị", "manager": "📋 Quản lý tổng hợp", "user": "👤 Người dùng"}
    return r, labels.get(r, "👤 Người dùng")

def update_user_password(u, new_pw):
    c = load_auth_config()
    if u not in c["users"]:
        return False
    c["users"][u]["password_hash"] = hash_password(new_pw)
    save_auth_config(c)
    return True

def validate_username(u):
    if not u:
        return False, "Vui lòng nhập tên đăng nhập."
    if len(u) < 3:
        return False, "Tên đăng nhập phải có ít nhất 3 ký tự."
    if len(u) > 30:
        return False, "Tên đăng nhập không được vượt quá 30 ký tự."
    if not re.match(r"^[a-zA-Z0-9_]+$", u):
        return False, "Tên đăng nhập chỉ được chứa chữ, số và gạch dưới."
    return True, ""

def create_user(u, pw):
    """Đăng ký tự do — KHÔNG tạo profile JSON."""
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": u,
        "role": "user",
    }
    save_auth_config(c)
    return True, "Đăng ký thành công! Hãy nạp dữ liệu ở mục 1."

def admin_create_user(u, pw, role):
    """Admin tạo user — KHÔNG tạo profile JSON."""
    c = load_auth_config()
    if u in c["users"]:
        return False, "Tên đăng nhập đã tồn tại."
    c["users"][u] = {
        "password_hash": hash_password(pw),
        "own_profile": u if role == "user" else None,
        "role": role,
    }
    save_auth_config(c)
    # Nếu profile cùng tên user đã tồn tại (admin đã upload trước) → sync mapping
    if role == "user" and load_user_profile(u):
        sync_name_mapping([u])
    return True, f"Đã tạo user '{u}' (role '{role}')."

def admin_update_user(target, new_role, new_own):
    """Cập nhật user — KHÔNG tạo profile JSON."""
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    rec = c["users"][target]
    rec["role"] = new_role
    if new_role == "user":
        rec["own_profile"] = target
    else:
        rec["own_profile"] = new_own if new_own else None
    save_auth_config(c)
    return True, f"Đã cập nhật user '{target}'."

def admin_reset_password(target, new_pw):
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    c["users"][target]["password_hash"] = hash_password(new_pw)
    save_auth_config(c)
    return True, f"Đã reset mật khẩu cho '{target}'."

def admin_delete_user(target, current):
    if target == current:
        return False, "Không thể xóa chính mình."
    c = load_auth_config()
    if target not in c["users"]:
        return False, "Không tìm thấy user."
    del c["users"][target]
    save_auth_config(c)
    return True, f"Đã xóa user '{target}'."


# ============= DOCX =============
def extract_text_from_docx(uf):
    doc = Document(uf)
    parts = []
    for p in doc.paragraphs:
        if p.text.strip():
            parts.append(p.text.strip())
    for t in doc.tables:
        for r in t.rows:
            cells = [c.text.strip() for c in r.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)

@st.cache_data(show_spinner=False)
def cached_extract_docx(b):
    return extract_text_from_docx(io.BytesIO(b))

def smart_truncate(t, m=MAX_CHARS):
    return t if len(t) <= m else t[:m] + f"\n\n[...lược {len(t)-m:,} ký tự...]"

def render_docx_preview(b, height=600):
    try:
        html = mammoth.convert_to_html(io.BytesIO(b)).value
        if not html.strip():
            st.info("File trống.")
            return
        styled = f"""<div style="font-family:'Segoe UI',Arial;font-size:15px;line-height:1.7;padding:20px;background:white;color:#222;">
        <style>table{{border-collapse:collapse;width:100%;margin:8px 0;}}td,th{{border:1px solid #ccc;padding:6px 10px;}}th{{background:#f0f0f0;}}p{{margin:6px 0;}}</style>{html}</div>"""
        components.html(styled, height=height, scrolling=True)
    except Exception as e:
        st.warning(f"Không hiển thị được: {e}")


# ============= AI CALLS =============
def _build_config(thinking, json_mode):
    kw = {"thinking_config": types.ThinkingConfig(thinking_level=thinking)}
    if json_mode:
        kw["response_mime_type"] = "application/json"
    return types.GenerateContentConfig(**kw)

def call_model_json(prompt, progress, start=20, end=95, label="🤖 AI"):
    last_err = None
    for mi in MODELS_TO_TRY:
        mn = mi["name"]
        cfg = _build_config(mi["thinking"], True)
        for att in range(MAX_RETRIES + 1):
            try:
                progress.progress(start, text=f"🤖 {mn}...")
                text = ""
                for ch in client.models.generate_content_stream(model=mn, contents=prompt, config=cfg):
                    if ch.text:
                        text += ch.text
                        ratio = 1 - math.exp(-len(text) / 1500)
                        progress.progress(min(end, int(start + (end - start) * ratio)),
                                          text=f"{label} ({mn})... ({len(text):,})")
                return text
            except APIError as e:
                if e.code in (503, 404):
                    last_err = e
                    if att < MAX_RETRIES:
                        time.sleep(2 ** att)
                        continue
                    break
                raise
    raise RuntimeError(f"Model quá tải. (Lỗi: {last_err.code if last_err else '?'})")

def _generate_with_retry(cfg, contents):
    last_err = None
    for mn in CHAT_MODELS_TO_TRY:
        for att in range(MAX_RETRIES + 1):
            try:
                return client.models.generate_content(model=mn, contents=contents, config=cfg)
            except APIError as e:
                if e.code in (503, 404):
                    last_err = e
                    if att < MAX_RETRIES:
                        time.sleep(2 ** att)
                        continue
                    break
                raise
    raise last_err if last_err else RuntimeError("Không có model.")

def list_accessible_profiles(allowed):
    m = load_name_mapping()
    res = []
    for k in allowed:
        info = m.get(k, {})
        d = load_user_profile(k)
        res.append({
            "profile_key": k,
            "display_name": info.get("display_name", ""),
            "aliases": info.get("aliases", []),
            "has_data": bool(d),
            "n_fields": len(d) if d else 0,
        })
    return res


def chat_with_ai(user_q, allowed, username, user_record, chat_history=None):
    own = get_own_profile(user_record, username)
    role = user_record.get("role", "user")
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_profile_data",
            description="Lấy dữ liệu hồ sơ nhân sự. CHỈ gọi khi user hỏi thông tin CỤ THỂ về nhân sự. KHÔNG gọi cho chào hỏi.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"profile_name": types.Schema(type=types.Type.STRING, description="Key hoặc tên")},
                required=["profile_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_accessible_profiles",
            description="Liệt kê hồ sơ user có quyền.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
    ])]
    own_display = own if own else "(không có — bạn là admin/manager)"
    if own:
        rule_own = (
            f"- User nói 'của tôi', 'tao', 'mình', 'tớ', 'của em/anh/chị' → gọi "
            f"get_profile_data với profile_name='{own}'. TUYỆT ĐỐI không hỏi lại.\n"
        )
    else:
        rule_own = (
            "- User KHÔNG có profile riêng (admin/manager). Nếu user nói 'của tôi' "
            "→ hỏi lại user muốn tra cứu ai.\n"
        )
    sys_msg = (
        f"Bạn là trợ lý hồ sơ hành chính.\nUser: '{username}', vai trò: {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Quyền truy cập {len(allowed)} hồ sơ: "
        f"{', '.join(allowed[:30])}{'...' if len(allowed) > 30 else ''}.\n\n"
        f"Quy tắc:\n- Chào hỏi/cảm ơn → trả lời trực tiếp, KHÔNG gọi tool.\n"
        f"{rule_own}"
        f"- Nhắc TÊN → gọi get_profile_data với tên đó.\n"
        f"- Hỏi 'đang dùng file nào', 'liệt kê' → gọi list_accessible_profiles.\n"
        f"- Nhiều candidates → hỏi lại user.\n- Profile rỗng → báo nạp ở mục 1.\n"
        f"- Không bịa. Tiếng Việt, ngắn gọn."
    )
    contents = []
    if chat_history:
        recent = chat_history[-8:]
        lines = [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in recent]
        if lines:
            contents.append(types.Content(role="user", parts=[types.Part(text="Lịch sử:\n" + "\n".join(lines))]))
            contents.append(types.Content(role="model", parts=[types.Part(text="Đã hiểu.")]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_q)]))
    cfg = types.GenerateContentConfig(
        tools=tools, system_instruction=sys_msg,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
    )
    used, p_used, status = False, None, None
    for _ in range(3):
        resp = _generate_with_retry(cfg, contents)
        if not resp.candidates:
            return "Xin lỗi, không xử lý được.", used, p_used, status
        if resp.function_calls:
            used = True
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in resp.function_calls:
                if fc.name == "list_accessible_profiles":
                    status = "list"
                    result = list_accessible_profiles(allowed)
                elif fc.name == "get_profile_data":
                    req = str((dict(fc.args) if fc.args else {}).get("profile_name", "")).strip()
                    resolved, cands, reason, hint = resolve_profile(req, allowed)
                    if resolved:
                        p_used = resolved
                        d = load_user_profile(resolved)
                        if d:
                            status = "ok"
                            result = {"profile_key": resolved, "data": d}
                        else:
                            status = "no_data"
                            result = {"error": f"Hồ sơ '{resolved}' chưa có dữ liệu.", "profile_key": resolved}
                    elif cands:
                        p_used = ",".join(cands)
                        status = "ambiguous"
                        result = {"error": hint, "candidates": cands, "action": "ask_user_to_choose"}
                    else:
                        p_used = req
                        status = "not_found"
                        m = load_name_mapping()
                        result = {"error": hint,
                                  "known_names": {k: v.get("display_name", "") for k, v in m.items() if k in allowed},
                                  "action": "tell_user_not_found"}
                else:
                    result = {"error": f"Unknown function {fc.name}"}
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            answer = (resp.text or "").strip()
            return answer or "Xin lỗi, tôi chưa có câu trả lời.", used, p_used, status
    return "Chưa hoàn tất. Thử lại.", used, p_used, status


def render_chat_caption(msg):
    if not msg.get("used_data"):
        st.caption("💬 Chat thường")
        return
    s, p = msg.get("tool_status"), msg.get("profile_used")
    if s == "ok":
        st.caption(f"📊 Đã tra cứu **{p}**")
    elif s == "no_data":
        st.caption(f"📭 Hồ sơ **{p}** chưa có dữ liệu — nạp ở mục 1")
    elif s == "not_found":
        st.caption(f"🚫 Không tìm thấy **{p}**")
    elif s == "ambiguous":
        st.caption(f"⚠️ Nhiều hồ sơ khớp: **{p}**")
    elif s == "list":
        st.caption("📋 Đã liệt kê hồ sơ")
    else:
        st.caption("💬 Chat thường")


# ============= SESSION STATE =============
defaults = {
    "logged_in": False, "username": "", "last_username": "", "chat_history": [],
    "show_change_pw": False, "show_manage_users": False,
    "auth_mode": "login", "pending_toast": None,
    "upload_stage": None, "upload_extracted": None,
    "upload_detected_name": None, "upload_detected_dob": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

api_key = st.secrets.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key) if api_key else None


# ============= LOGIN / REGISTER =============
if not st.session_state.logged_in:
    st.title("🔒 Đăng Nhập Hệ Thống Agent")
    st.write("Vui lòng xác thực tài khoản cục bộ.")
    auth_config = load_auth_config()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔑 Đăng nhập", use_container_width=True,
                     type="primary" if st.session_state.auth_mode == "login" else "secondary",
                     key="sw_login"):
            st.session_state.auth_mode = "login"
            st.rerun()
    with c2:
        if st.button("📝 Đăng ký", use_container_width=True,
                     type="primary" if st.session_state.auth_mode == "register" else "secondary",
                     key="sw_register"):
            st.session_state.auth_mode = "register"
            st.rerun()

    st.markdown("---")

    if st.session_state.auth_mode == "login":
        default_u = st.query_params.get("last_user", st.session_state.get("last_username", ""))
        with st.form("login_form"):
            u = st.text_input("Tên đăng nhập", value=default_u, key="login_u")
            p = st.text_input("Mật khẩu", type="password", key="login_p")
            if st.form_submit_button("Đăng nhập", use_container_width=True):
                rec = auth_config["users"].get(u)
                if rec and verify_password(p, rec["password_hash"]):
                    st.session_state.logged_in = True
                    st.session_state.username = u
                    st.session_state.last_username = u
                    st.session_state.chat_history = []
                    st.session_state.auth_mode = "login"
                    st.query_params["last_user"] = u
                    sync_name_mapping(compute_allowed_profiles(rec))
                    write_system_log(u, "Đăng nhập", "OK")
                    st.rerun()
                else:
                    st.session_state.last_username = u
                    write_system_log(u or "Ẩn danh", "Login failed", "Thất bại")
                    st.error("Sai tài khoản hoặc mật khẩu!")
    else:
        st.subheader("📝 Đăng ký tài khoản")
        with st.form("register_form"):
            nu = st.text_input("Tên đăng nhập", key="reg_u", placeholder="3-30 ký tự, chữ/số/gạch dưới")
            npw = st.text_input("Mật khẩu", type="password", key="reg_p", placeholder="≥6 ký tự")
            npw2 = st.text_input("Nhập lại mật khẩu", type="password", key="reg_p2")
            if st.form_submit_button("Đăng ký", use_container_width=True):
                ok_u, msg_u = validate_username(nu)
                if not ok_u:
                    st.error(msg_u)
                elif not npw or len(npw) < 6:
                    st.error("Mật khẩu ≥6 ký tự.")
                elif npw != npw2:
                    st.error("Mật khẩu nhập lại không khớp.")
                else:
                    ok, msg = create_user(nu, npw)
                    if ok:
                        st.session_state.logged_in = True
                        st.session_state.username = nu
                        st.session_state.last_username = nu
                        st.session_state.chat_history = []
                        st.session_state.auth_mode = "login"
                        st.query_params["last_user"] = nu
                        st.session_state.pending_toast = f"🎉 Chào mừng {nu}!"
                        write_system_log(nu, "Đăng ký", "OK")
                        st.rerun()
                    else:
                        st.error(msg)

else:
    # ============= ĐÃ ĐĂNG NHẬP =============
    if st.session_state.get("pending_toast"):
        st.toast(st.session_state.pending_toast, icon="🎉")
        st.session_state.pending_toast = None

    user_record = load_auth_config()["users"].get(st.session_state.username, {})
    role_key = user_record.get("role", "user")
    own_profile = get_own_profile(user_record, st.session_state.username)
    allowed_profiles = compute_allowed_profiles(user_record)

    # ============= SIDEBAR =============
    with st.sidebar:
        role_display = {
            "admin": "👑 Quản trị",
            "manager": "📋 Quản lý tổng hợp",
            "user": "👤 Người dùng",
        }.get(role_key, "👤 Người dùng")

        profile_display = own_profile if own_profile else "(chưa có)"

        st.markdown(f"""
        <div style="padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
                    border-radius:12px;color:white;margin-bottom:16px;">
            <div style="font-size:1.4rem;font-weight:bold;">👤 {st.session_state.username}</div>
            <div style="font-size:1rem;margin-top:6px;opacity:.95;">{role_display}</div>
            <div style="font-size:.9rem;margin-top:4px;opacity:.85;">Profile: {profile_display}</div>
        </div>
        """, unsafe_allow_html=True)

        # ---------- QUẢN LÝ USER (admin) ----------
        if role_key == "admin":
            if st.button(
                "👥 Quản lý user" if not st.session_state.show_manage_users
                else "✖️ Đóng quản lý user",
                use_container_width=True, key="btn_toggle_manage", type="primary",
            ):
                st.session_state.show_manage_users = not st.session_state.show_manage_users
                st.rerun()

            if st.session_state.show_manage_users:
                cfg_now = load_auth_config()
                users_now = cfg_now["users"]

                with st.expander("➕ Thêm user mới", expanded=False):
                    with st.form("admin_add_user", clear_on_submit=True):
                        nu = st.text_input("Tên đăng nhập", key="add_u",
                                           placeholder="3-30 ký tự, chữ/số/gạch dưới")
                        npw = st.text_input("Mật khẩu", type="password", key="add_p",
                                            placeholder="≥6 ký tự")
                        npw2 = st.text_input("Nhập lại mật khẩu", type="password", key="add_p2")
                        role_choice = st.selectbox(
                            "Role", ["user", "manager", "admin"],
                            format_func=lambda x: {
                                "user": "👤 Người dùng",
                                "manager": "📋 Quản lý tổng hợp",
                                "admin": "👑 Quản trị",
                            }[x],
                            key="add_role",
                        )
                        if st.form_submit_button("Tạo user", use_container_width=True):
                            ok_u, msg_u = validate_username(nu)
                            if not ok_u:
                                st.error(msg_u)
                            elif not npw or len(npw) < 6:
                                st.error("Mật khẩu ≥6 ký tự.")
                            elif npw != npw2:
                                st.error("Mật khẩu nhập lại không khớp.")
                            else:
                                ok, msg = admin_create_user(nu, npw, role_choice)
                                if ok:
                                    write_system_log(st.session_state.username,
                                                     f"Tạo user '{nu}' (role={role_choice})", "OK")
                                    st.success(f"✅ {msg}")
                                    st.rerun()
                                else:
                                    st.error(msg)

                st.markdown("**📋 Danh sách user:**")
                for uname, urec in sorted(users_now.items()):
                    is_self = uname == st.session_state.username
                    cur_role = urec.get("role", "user")
                    icon = {"admin": "👑", "manager": "📋", "user": "👤"}.get(cur_role, "👤")
                    label = f"{icon} {uname}" + (" _(bạn)_" if is_self else "")

                    with st.expander(label, expanded=False):
                        prof = urec.get("own_profile") or "(chưa gán)"
                        st.caption(f"Role: `{cur_role}` | Profile: `{prof}`")

                        with st.form(f"edit_{uname}"):
                            new_role = st.selectbox(
                                "Role", ["user", "manager", "admin"],
                                index=["user", "manager", "admin"].index(cur_role),
                                format_func=lambda x: {
                                    "user": "👤 Người dùng",
                                    "manager": "📋 Quản lý tổng hợp",
                                    "admin": "👑 Quản trị",
                                }[x],
                                key=f"r_{uname}",
                                disabled=is_self,
                            )
                            new_own = st.text_input(
                                "Profile riêng (own_profile)",
                                value=urec.get("own_profile") or "",
                                key=f"o_{uname}",
                                disabled=(new_role == "user" or is_self),
                                help="Role 'user' luôn dùng username làm profile. Admin/manager có thể để trống.",
                            )
                            if st.form_submit_button("💾 Lưu", use_container_width=True):
                                if is_self and new_role != cur_role:
                                    st.error("Không thể tự đổi role.")
                                else:
                                    eff_role = cur_role if is_self else new_role
                                    eff_own = uname if eff_role == "user" else new_own.strip()
                                    if eff_own and not re.match(r"^[a-zA-Z0-9_]+$", eff_own):
                                        st.error("Profile chỉ chứa chữ, số, gạch dưới.")
                                    else:
                                        ok, msg = admin_update_user(uname, eff_role, eff_own)
                                        if ok:
                                            write_system_log(
                                                st.session_state.username,
                                                f"Sửa user '{uname}'",
                                                f"OK (role={eff_role}, profile={eff_own})",
                                            )
                                            st.success(msg)
                                            st.rerun()
                                        else:
                                            st.error(msg)

                        with st.form(f"reset_{uname}"):
                            new_pw = st.text_input("Mật khẩu mới", type="password",
                                                    key=f"np_{uname}")
                            if st.form_submit_button("🔑 Reset mật khẩu", use_container_width=True):
                                if not new_pw or len(new_pw) < 6:
                                    st.error("Mật khẩu ≥6 ký tự.")
                                else:
                                    ok, msg = admin_reset_password(uname, new_pw)
                                    if ok:
                                        write_system_log(st.session_state.username,
                                                         f"Reset pass '{uname}'", "OK")
                                        st.success(msg)
                                    else:
                                        st.error(msg)

                        if not is_self:
                            if st.button("🗑️ Xóa user", key=f"d_{uname}",
                                          use_container_width=True):
                                ok, msg = admin_delete_user(uname, st.session_state.username)
                                if ok:
                                    write_system_log(st.session_state.username,
                                                     f"Xóa user '{uname}'", "OK")
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                        else:
                            st.caption("_(không thể xóa chính mình)_")

            st.markdown("---")

        # ---------- ĐỔI MẬT KHẨU ----------
        if st.button(
            "🔑 Đổi mật khẩu" if not st.session_state.show_change_pw
            else "✖️ Hủy đổi mật khẩu",
            use_container_width=True, key="btn_toggle_pw",
        ):
            st.session_state.show_change_pw = not st.session_state.show_change_pw
            st.rerun()

        if st.session_state.show_change_pw:
            with st.form("change_pw_form"):
                new_pw = st.text_input("Mật khẩu mới", type="password", key="cp_new")
                confirm = st.text_input("Nhập lại mật khẩu mới", type="password", key="cp_conf")
                if st.form_submit_button("Xác nhận", use_container_width=True):
                    if not new_pw or not confirm:
                        st.error("Điền đầy đủ cả 2 ô.")
                    elif new_pw != confirm:
                        st.error("Mật khẩu nhập lại không khớp.")
                    elif len(new_pw) < 6:
                        st.error("Mật khẩu ≥6 ký tự.")
                    else:
                        if update_user_password(st.session_state.username, new_pw):
                            write_system_log(st.session_state.username, "Đổi mật khẩu", "OK")
                            st.session_state.pw_change_success = True
                            st.session_state.show_change_pw = False
                            st.rerun()
                        else:
                            st.error("Không tìm thấy user.")

        if st.session_state.get("pw_change_success"):
            st.success("✅ Đã đổi mật khẩu!")
            st.session_state.pw_change_success = False

        # ---------- ÁNH XẠ TÊN ----------
        with st.expander("🗂️ Ánh xạ tên → hồ sơ"):
            mp = load_name_mapping()
            vis = {k: v for k, v in mp.items() if k in allowed_profiles}
            if vis:
                for k, v in sorted(vis.items()):
                    st.markdown(f"**`{k}`** — {v.get('display_name', '(chưa có)')}")
                    if v.get("aliases"):
                        st.caption(f"Alias: {', '.join(v['aliases'])}")
            else:
                st.info("Chưa có ánh xạ.")

            if role_key == "admin":
                st.markdown("**Thêm/sửa alias:**")
                with st.form("alias_form", clear_on_submit=True):
                    tk = st.selectbox("Hồ sơ", allowed_profiles, key="al_tgt")
                    dn = st.text_input(
                        "Display name",
                        value=mp.get(tk, {}).get("display_name", ""),
                        key="al_dn",
                    )
                    na = st.text_input("Alias mới", key="al_new",
                                        placeholder="vd: 'Vũ Dương', 'anh Dương'")
                    if st.form_submit_button("Lưu", use_container_width=True):
                        mp.setdefault(tk, {"display_name": "", "aliases": []})
                        if dn:
                            mp[tk]["display_name"] = dn.strip()
                        if na and na.strip() not in mp[tk]["aliases"]:
                            mp[tk]["aliases"].append(na.strip())
                        save_name_mapping(mp)
                        st.success(f"✅ Đã lưu cho `{tk}`.")
                        st.rerun()

        st.markdown("---")

        if st.button("🚪 Đăng xuất", use_container_width=True, key="btn_logout"):
            write_system_log(st.session_state.username, "Đăng xuất", "OK")
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.chat_history = []
            st.session_state.show_change_pw = False
            st.session_state.show_manage_users = False
            reset_upload_state()
            st.rerun()

    # ============= MAIN UI =============
    st.title("🤖 AI Agent Quản Lý Hành Chính")
    st.caption("Nạp hồ sơ · Điền biểu mẫu · Hỏi đáp trực tiếp")

    if not client:
        st.error("⚠️ Chưa cấu hình `GEMINI_API_KEY` trong `st.secrets`.")
        st.stop()

    # ============================================================
    # KHU VỰC 1: NẠP DỮ LIỆU (2 bước)
    # ============================================================
    st.markdown("---")
    st.subheader("📄 1. Nạp dữ liệu hồ sơ")

    is_power = role_key in ("admin", "manager")

    if is_power:
        st.caption(
            "Upload file Word. AI sẽ trích xuất và **tự động so khớp họ tên + ngày sinh** "
            "với hồ sơ có sẵn. Nếu chưa có, tạo hồ sơ mới theo tên."
        )
    else:
        if not own_profile:
            st.error("⚠️ Tài khoản của bạn chưa có profile. Liên hệ admin.")
            st.stop()
        st.caption(f"Upload file hồ sơ của bạn (hồ sơ **{own_profile}**).")

    # ---------- Stage 1: Upload ----------
    if st.session_state.get("upload_stage") is None:
        upf = st.file_uploader("File hồ sơ thô (.docx)", type=["docx"],
                                key="uploader_profile")
        if upf and st.button("🔍 Phân tích file", use_container_width=True,
                              key="btn_analyze"):
            progress = st.progress(5, text="📄 Đang đọc file...")
            try:
                raw = cached_extract_docx(upf.getvalue())
                raw = smart_truncate(raw)
                progress.progress(15, text=f"📤 Đọc {len(raw):,} ký tự, gửi AI...")
                prompt = f"""
Bạn là AI Agent quản lý hồ sơ nhân sự. Trích xuất TOÀN BỘ thông tin
từ văn bản thô sau thành JSON phẳng.

Văn bản:
\"\"\"
{raw}
\"\"\"

Yêu cầu:
- Trả về MỘT đối tượng JSON (key-value).
- Key tiếng Anh, viết thường, gạch dưới.
- BẮT BUỘC có 'ho_va_ten' (họ tên đầy đủ) nếu tìm được.
- BẮT BUỘC có 'ngay_sinh' (DD/MM/YYYY) nếu tìm được.
- Trường khác: gioi_tinh, que_quan, dia_chi_thuong_tru, so_dien_thoai,
  email, so_cccd, ngay_cap_cccd, noi_cap_cccd, trinh_do_hoc_van,
  chuc_vu, don_vi_cong_tac, ...
"""
                jt = call_model_json(prompt, progress, 20, 95, label="🤖 Đang trích xuất")
                extracted = json.loads(jt)
                progress.progress(100, text="✅ Xong")
                st.session_state.upload_extracted = extracted
                st.session_state.upload_detected_name = detect_name_from_data(extracted)
                st.session_state.upload_detected_dob = detect_dob_from_data(extracted)
                st.session_state.upload_stage = "review"
                time.sleep(0.3)
                st.rerun()
            except Exception as e:
                progress.empty()
                st.error(f"Lỗi: {e}")

    # ---------- Stage 2: Review ----------
    else:
        extracted = st.session_state.upload_extracted
        det_name = st.session_state.upload_detected_name
        det_dob = st.session_state.upload_detected_dob

        st.success(f"✅ Đã trích xuất **{len(extracted)} trường**.")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Họ tên:** {det_name or '⚠️ không xác định'}")
        with c2:
            st.markdown(f"**Ngày sinh:** {det_dob or '⚠️ không xác định'}")

        with st.expander("👁️ Xem dữ liệu trích xuất"):
            st.json(extracted)

        # ================ ADMIN / MANAGER ================
        if is_power:
            if not det_name:
                st.error("⚠️ Không phát hiện họ tên trong file — không thể so khớp.")
            else:
                matches = find_identity_matches(extracted, allowed_profiles)

                if matches:
                    st.markdown("### 🔍 Hồ sơ trùng khớp")
                    for mk, strength in matches:
                        existing = load_user_profile(mk)
                        en, ed = get_identity(existing)
                        tag = ("🟢 Khớp đầy đủ (họ tên + ngày sinh)"
                               if strength == "strong"
                               else "🟡 Chỉ khớp họ tên (thiếu ngày sinh để đối chiếu)")
                        with st.container(border=True):
                            st.markdown(f"**`{mk}`** — {en or '?'} — {ed or '?'}")
                            st.caption(tag)
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if st.button("🔄 Gộp thêm", key=f"mg_{mk}",
                                              use_container_width=True, type="primary"):
                                    merged = merge_and_save(mk, extracted)
                                    write_system_log(st.session_state.username,
                                                     f"Gộp vào {mk}", f"OK ({len(merged)})")
                                    st.success(f"✅ Đã gộp vào `{mk}` ({len(merged)} trường).")
                                    reset_upload_state()
                                    time.sleep(0.5)
                                    st.rerun()
                            with cc2:
                                if st.button("♻️ Ghi đè", key=f"ow_{mk}",
                                              use_container_width=True):
                                    merged = merge_and_save(mk, extracted, overwrite=True)
                                    write_system_log(st.session_state.username,
                                                     f"Ghi đè {mk}", f"OK ({len(merged)})")
                                    st.success(f"✅ Đã ghi đè `{mk}` ({len(merged)} trường).")
                                    reset_upload_state()
                                    time.sleep(0.5)
                                    st.rerun()
                else:
                    st.info("🔍 Không có hồ sơ trùng họ tên + ngày sinh → sẽ tạo hồ sơ mới.")

                st.markdown("### 🆕 Tạo hồ sơ mới")
                sk = suggest_profile_key(det_name)
                new_key = st.text_input("Key profile mới (tên file JSON):",
                                         value=sk, key="new_key",
                                         help="Chỉ chữ, số, gạch dưới. VD: VuDuong")
                if new_key:
                    if not re.match(r"^[a-zA-Z0-9_]+$", new_key):
                        st.error("Key chỉ chứa chữ, số, gạch dưới.")
                    elif load_user_profile(new_key):
                        st.warning(f"⚠️ Profile `{new_key}` đã tồn tại. Tiếp tục sẽ GHI ĐÈ.")
                        if st.button(f"⚠️ Ghi đè `{new_key}`",
                                      use_container_width=True, key="btn_new_ow"):
                            merged = merge_and_save(new_key, extracted, overwrite=True)
                            write_system_log(st.session_state.username,
                                             f"Ghi đè {new_key}", f"OK ({len(merged)})")
                            st.success(f"✅ Đã ghi đè `{new_key}`.")
                            reset_upload_state()
                            time.sleep(0.5)
                            st.rerun()
                    else:
                        if st.button("🆕 Tạo hồ sơ mới", type="primary",
                                      use_container_width=True, key="btn_new_mk"):
                            merged = merge_and_save(new_key, extracted)
                            write_system_log(st.session_state.username,
                                             f"Tạo mới {new_key}", f"OK ({len(merged)})")
                            st.success(f"✅ Đã tạo `{new_key}` ({len(merged)} trường).")
                            reset_upload_state()
                            time.sleep(0.5)
                            st.rerun()

        # ================ USER CÁ NHÂN ================
        else:
            existing = load_user_profile(own_profile)

            if not existing:
                st.info(
                    f"📁 Hồ sơ **{own_profile}** chưa có dữ liệu. "
                    f"Đây sẽ là lần nạp đầu tiên — dữ liệu sẽ được lưu vào `{own_profile}`."
                )
                if st.button("💾 Lưu vào hồ sơ của tôi", type="primary",
                              use_container_width=True, key="u_first"):
                    merged = merge_and_save(own_profile, extracted)
                    write_system_log(st.session_state.username,
                                     f"Nạp lần đầu vào {own_profile}",
                                     f"OK ({len(merged)})")
                    st.success(f"✅ Đã nạp {len(merged)} trường vào `{own_profile}`.")
                    reset_upload_state()
                    time.sleep(0.5)
                    st.rerun()
            else:
                en, ed = get_identity(existing)
                result = identity_matches(extracted, existing)

                if result == "no":
                    st.error(
                        f"🚫 **Không thể ghi.** File chứa **{det_name}** "
                        f"(DOB: {det_dob or '?'}), nhưng hồ sơ của bạn là "
                        f"**{en or '?'}** (DOB: {ed or '?'}). "
                        f"Đây không phải dữ liệu của bạn."
                    )
                else:
                    if result == "strong":
                        st.success(f"✅ Khớp hồ sơ **{en}** — {ed}.")
                    else:
                        st.warning(
                            f"⚠️ Khớp họ tên **{det_name}**, nhưng thiếu ngày sinh "
                            f"để đối chiếu chắc chắn."
                        )
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if st.button("🔄 Gộp thêm", key="u_merge",
                                      use_container_width=True, type="primary"):
                            merged = merge_and_save(own_profile, extracted)
                            write_system_log(st.session_state.username,
                                             f"Gộp vào {own_profile}", f"OK ({len(merged)})")
                            st.success(f"✅ Đã gộp vào `{own_profile}`.")
                            reset_upload_state()
                            time.sleep(0.5)
                            st.rerun()
                    with cc2:
                        if st.button("♻️ Ghi đè", key="u_ow", use_container_width=True):
                            merged = merge_and_save(own_profile, extracted, overwrite=True)
                            write_system_log(st.session_state.username,
                                             f"Ghi đè {own_profile}", f"OK ({len(merged)})")
                            st.success(f"✅ Đã ghi đè `{own_profile}`.")
                            reset_upload_state()
                            time.sleep(0.5)
                            st.rerun()

        st.markdown("---")
        if st.button("❌ Hủy, upload lại", use_container_width=True, key="u_cancel"):
            reset_upload_state()
            st.rerun()

    # ============================================================
    # KHU VỰC 2: ĐIỀN BIỂU MẪU
    # ============================================================
    st.markdown("---")
    st.subheader("📝 2. Điền biểu mẫu")

    if is_power:
        st.caption(
            "Tải file Word biểu mẫu. AI sẽ điền từ hồ sơ được nhắc trong yêu cầu, "
            "hoặc hồ sơ riêng của bạn nếu để trống."
        )
        form_prompt = st.text_input(
            "Yêu cầu (không bắt buộc)",
            placeholder="VD: điền thông tin Vũ Dương vào form / để trống = hồ sơ riêng",
            key="form_prompt",
        )
    else:
        if own_profile:
            st.caption(f"AI sẽ điền từ hồ sơ của bạn: **{own_profile}**")
        else:
            st.warning("Tài khoản chưa có profile. Liên hệ admin.")
        form_prompt = ""

    tf = st.file_uploader("File biểu mẫu trống (.docx)", type=["docx"],
                           key="uploader_template")

    if tf and st.button("✍️ Điền biểu mẫu", use_container_width=True, key="btn_fill"):
        progress = st.progress(5, text="📄 Đang đọc biểu mẫu...")
        target = None
        try:
            if is_power and form_prompt.strip():
                found = find_profile_in_text(form_prompt, allowed_profiles)
                if found:
                    target = found
                else:
                    resolved, _, _, _ = resolve_profile(form_prompt, allowed_profiles)
                    target = resolved
            if not target:
                target = own_profile
            if not target:
                progress.empty()
                st.error("Không xác định được hồ sơ.")
                st.stop()

            if target not in allowed_profiles:
                progress.empty()
                write_system_log(st.session_state.username,
                                 f"Truy cập {target} qua form", "BỊ CHẶN")
                st.error(f"❌ Không có quyền truy cập **[{target}]**.")
                st.stop()

            tdata = load_user_profile(target)
            if not tdata:
                progress.empty()
                st.warning(f"⚠️ Hồ sơ **[{target}]** chưa có dữ liệu. Nạp ở mục 1 trước.")
                st.stop()

            doc = Document(tf)
            placeholders = [p.text for p in doc.paragraphs
                            if ":" in p.text or "..." in p.text]
            progress.progress(15, text=f"🧠 Phân tích {len(placeholders)} trường...")

            m_prompt = f"""
Bạn là trợ lý hành chính. Lấy thông tin từ dữ liệu của [{target}]:
{json.dumps(tdata, ensure_ascii=False)}

Điền chính xác vào các dòng tương ứng sau của biểu mẫu:
{placeholders}

Yêu cầu: giữ nguyên định dạng tiền tố. Trả về DUY NHẤT một JSON ánh xạ
{{dòng_gốc: dòng_đã_điền}}.
"""
            jt = call_model_json(m_prompt, progress, 20, 85, label="🤖 Đang ánh xạ")
            progress.progress(88, text="✍️ Đang ghi...")
            filled = json.loads(jt)

            for p in doc.paragraphs:
                for o, d in filled.items():
                    if p.text.strip() == o.strip():
                        p.text = d
            for t in doc.tables:
                for r in t.rows:
                    for cell in r.cells:
                        for p in cell.paragraphs:
                            for o, d in filled.items():
                                if p.text.strip() == o.strip():
                                    p.text = d

            bio = io.BytesIO()
            doc.save(bio)
            docx_bytes = bio.getvalue()

            progress.progress(100, text="✅ Xong")
            st.success(f"✅ Đã điền xong cho **[{target}]**.")
            write_system_log(st.session_state.username,
                             f"Điền form cho {target}", "OK")

            st.markdown("#### 👁️ Xem trước")
            render_docx_preview(docx_bytes, height=600)

            st.download_button(
                label=f"📥 Tải file Word của {target}",
                data=docx_bytes,
                file_name=f"{target}_bieumau_hoanthanh.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True, key="btn_dl_filled",
            )
        except Exception as e:
            progress.empty()
            write_system_log(st.session_state.username,
                             f"Điền form cho {target or '?'}", f"Lỗi ({e})")
            st.error(f"Lỗi: {e}")

    # ============================================================
    # KHU VỰC 3: CHAT
    # ============================================================
    st.markdown("---")
    st.subheader("💬 3. Hỏi đáp trực tiếp")
    st.caption(
        "Ví dụ: *'Chào bạn'*, *'Hộ khẩu của tôi'*, "
        "*'Vũ Dương là nam hay nữ'*, *'Liệt kê hồ sơ'*"
    )

    if st.button("🗑️ Xóa lịch sử chat", key="btn_clear_chat"):
        st.session_state.chat_history = []
        st.rerun()

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_chat_caption(msg)

    user_q = st.chat_input("Nhập câu hỏi...", key="main_chat_input")

    if user_q:
        hist = list(st.session_state.chat_history)
        with st.chat_message("user"):
            st.markdown(user_q)
        st.session_state.chat_history.append({"role": "user", "content": user_q})

        with st.chat_message("assistant"):
            with st.spinner("Đang suy nghĩ..."):
                try:
                    answer, used, p_used, status = chat_with_ai(
                        user_q=user_q,
                        allowed=allowed_profiles,
                        username=st.session_state.username,
                        user_record=user_record,
                        chat_history=hist,
                    )
                    st.markdown(answer)
                    render_chat_caption({
                        "used_data": used,
                        "profile_used": p_used,
                        "tool_status": status,
                    })
                except Exception as e:
                    answer = f"❌ Lỗi: {e}"
                    used, p_used, status = False, None, None
                    st.markdown(answer)
                    write_system_log(st.session_state.username, "Chat", f"Lỗi ({e})")

        st.session_state.chat_history.append({
            "role": "assistant", "content": answer,
            "used_data": used, "profile_used": p_used, "tool_status": status,
        })
        write_system_log(
            st.session_state.username, "Chat",
            f"OK (data={'yes:' + str(p_used) if used else 'no'}, status={status})",
        )