# chat_agent.py
import json
import streamlit as st
from google.genai import types

from ai_client import _generate_with_retry
from config import META_KEYS
from security import detect_name_from_data
from storage import load_user_profile, load_name_mapping
from profile_service import resolve_profile
from user_service import get_own_profile

# ⚠️ ĐÃ SỬA: list_keys_with_prefix (thêm chữ s)
from supabase_adapter import (
    filter_profiles_in_db, 
    load_json_from_db, 
    get_ai_settings,
    list_keys_with_prefix, 
    load_many
)
from agent_profiles import DEFAULT_PROFILES

# ---------- Tool implementations ----------
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

@st.cache_data(ttl=60, show_spinner=False)
def _collect_all_fields_cached(allowed_tuple):
    fields = set()
    for k in allowed_tuple:
        d = load_user_profile(k)
        if d:
            fields.update(d.keys())
    return fields

def search_profiles_dynamic(operator, field, value, allowed_profiles):
    known = _collect_all_fields_cached(tuple(allowed_profiles))
    if field not in known:
        return []
    raw_results = filter_profiles_in_db(operator, f"data->>{field}", value)
    results = []
    for row in raw_results:
        key = row["key"]
        if key in allowed_profiles and key not in META_KEYS:
            data = row["data"]
            results.append({
                "profile_key": key,
                "ho_va_ten": detect_name_from_data(data) or key,
                "matched_value": data.get(field),
            })
    return results

# ⚠️ ĐÃ SỬA: Đặt mặc định là "admin"
def search_knowledge_base(query, module="admin"):
    """
    Tra cứu tri thức: gộp cả văn bản nhập tay (key 'admin_rules') 
    và các văn bản PDF đã xử lý (key 'kb_admin_*').
    """
    if module == "admin":
        manual_key = "admin_rules"
        prefix = "kb_admin_"
    else:
        manual_key = "finance_rules"
        prefix = "kb_finance_"
    
    # 1. Gom tất cả key cần đọc
    kb_keys = list_keys_with_prefix(prefix)
    if manual_key not in kb_keys:
        kb_keys.append(manual_key)  # Luôn thử đọc key nhập tay
    
    # 2. Load 1 lần (tối ưu)
    all_data = load_many(kb_keys)
    
    # 3. Trích xuất rules từ mọi nguồn
    all_rules = []
    for key, data in all_data.items():
        if not data:
            continue
        # Loại 1: Text nhập tay → coi là 1 "rule" duy nhất
        if "content" in data and data["content"]:
            all_rules.append({
                "dieu_khoan": data.get("document_name", "Quy định"),
                "noi_dung": data["content"],
                "muc_chi": None,
                "doi_tuong": None,
                "tu_khoa": data["content"][:100].split(),
            })
        # Loại 2: Mảng rules từ PDF
        if "rules" in data and isinstance(data["rules"], list):
            for r in data["rules"]:
                r["_source"] = data.get("document_name", key)
                all_rules.append(r)
    
    if not all_rules:
        return "Hệ thống chưa có tri thức nền cho phân hệ này."
    
    # 4. Chấm điểm & lấy top 3
    query_lower = str(query).lower()
    query_words = [w for w in query_lower.split() if len(w) > 1]
    
    scored = []
    for rule in all_rules:
        text = (
            str(rule.get("noi_dung", "")) + " " +
            " ".join(rule.get("tu_khoa", [])) + " " +
            str(rule.get("doi_tuong", ""))
        ).lower()
        
        score = sum(1 for w in query_words if w in text)
        if score > 0:
            scored.append((score, rule))
    
    if not scored:
        return "Không tìm thấy quy định nào liên quan trong tài liệu."
    
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [r[1] for r in scored[:3]]
    
    # 5. Format kết quả đẹp cho LLM
    output = "Các quy định tìm thấy:\n\n"
    for r in top:
        src = f" (Nguồn: {r['_source']})" if r.get("_source") else ""
        output += f"- **{r.get('dieu_khoan', '')}**{src}\n"
        output += f"  {r.get('noi_dung', '')}\n"
        if r.get("doi_tuong"):
            output += f"  • Đối tượng: {r['doi_tuong']}\n"
        if r.get("muc_chi"):
            output += f"  • Mức chi: {r['muc_chi']}\n"
        output += "\n"
    
    return output

# ---------- Main chat ----------
def chat_with_ai(user_q, allowed, username, user_record, module="admin", chat_history=None):
    own = get_own_profile(user_record, username)
    role = user_record.get("role", "user")
    
    # 1. Lấy cấu hình AI động từ Database
    ai_cfg = get_ai_settings()
    db_prompt = ai_cfg.get("chat_system_prompt", "")
    
    # 2. Lấy profile của module hiện tại
    profile = DEFAULT_PROFILES.get(module, DEFAULT_PROFILES.get("admin", {}))
    module_prompt = profile.get("system_prompt", "")
    allowed_tools = profile.get("tools", [])

    # 3. Khai báo toàn bộ Tools có thể dùng
    all_tools = [
        types.FunctionDeclaration(
            name="get_profile_data",
            description=("Lấy dữ liệu hồ sơ nhân sự. CHỈ gọi khi user hỏi "
                         "thông tin CỤ THỂ về nhân sự. KHÔNG gọi cho chào hỏi."),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"profile_name": types.Schema(type=types.Type.STRING)},
                required=["profile_name"],
            ),
        ),
        types.FunctionDeclaration(
            name="list_accessible_profiles",
            description="Liệt kê hồ sơ user có quyền.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="search_profiles",
            description="Tìm kiếm/lọc hồ sơ theo trường. Dùng cho câu hỏi thống kê.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(type=types.Type.STRING),
                    "operator": types.Schema(type=types.Type.STRING, enum=["eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in"]),
                    "value": types.Schema(type=types.Type.STRING),
                },
                required=["field", "operator", "value"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_knowledge",
            description="Tìm kiếm quy định, hướng dẫn, quy chế. Dùng khi user hỏi về luật lệ, quy trình, cách tính toán.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(type=types.Type.STRING)},
                required=["query"],
            ),
        ),
    ]
    
    # Lọc lại các tool được phép dùng cho module này
    active_tools = [t for t in all_tools if t.name in allowed_tools]

    own_display = own if own else "(không có — bạn là admin/manager)"
    rule_own = (
        f"- User nói 'của tôi', 'tao', 'mình' → gọi get_profile_data với profile_name='{own}'.\n"
        if own else
        "- User KHÔNG có profile riêng. Nếu nói 'của tôi' → hỏi lại user.\n"
    )

    sys_msg = (
        f"{db_prompt}\n"
        f"{module_prompt}\n\n"
        f"--- BỐI CẢNH ---\n"
        f"User: '{username}', vai trò: {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Quyền truy cập {len(allowed)} hồ sơ.\n\n"
        f"--- QUY TẮC ---\n"
        f"- Chào hỏi/cảm ơn → trả lời trực tiếp, KHÔNG gọi tool.\n"
        f"{rule_own}"
        f"- Nhắc TÊN → gọi get_profile_data.\n"
        f"- Hỏi 'liệt kê' → gọi list_accessible_profiles.\n"
        f"- Câu hỏi thống kê → BẮT BUỘC gọi search_profiles.\n"
        f"- Hỏi về quy định, luật lệ → gọi search_knowledge.\n"
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
        tools=[types.Tool(function_declarations=active_tools)] if active_tools else [],
        system_instruction=sys_msg,
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
                        result = {"error": hint, "action": "tell_user_not_found"}
                elif fc.name == "search_profiles":
                    field = str(fc.args.get("field", ""))
                    operator = str(fc.args.get("operator", "eq"))
                    value_raw = fc.args.get("value", "")
                    if operator == "in" and isinstance(value_raw, str):
                        try: value = json.loads(value_raw)
                        except Exception: value = [v.strip() for v in value_raw.split(",")]
                    else: value = value_raw
                    status = "search"
                    result = search_profiles_dynamic(operator, field, value, allowed)
                elif fc.name == "search_knowledge":
                    q = str(fc.args.get("query", ""))
                    status = "knowledge"
                    result = search_knowledge_base(q, module)
                else:
                    result = {"error": "Unknown"}
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            answer = (resp.text or "").strip()
            return answer or "Xin lỗi.", used, p_used, status
    return "Chưa hoàn tất.", used, p_used, status