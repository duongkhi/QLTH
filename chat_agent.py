import json

import streamlit as st
from google.genai import types

from ai_client import _generate_with_retry
from config import META_KEYS
from security import detect_name_from_data
from storage import load_user_profile, load_name_mapping
from profile_service import resolve_profile
from user_service import get_own_profile
from supabase_adapter import filter_profiles_in_db


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


# ---------- Main chat ----------
def chat_with_ai(user_q, allowed, username, user_record, chat_history=None):
    own = get_own_profile(user_record, username)
    role = user_record.get("role", "user")

    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_profile_data",
            description=("Lấy dữ liệu hồ sơ nhân sự. CHỈ gọi khi user hỏi "
                         "thông tin CỤ THỂ về nhân sự. KHÔNG gọi cho chào hỏi."),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "profile_name": types.Schema(
                        type=types.Type.STRING,
                        description="Key hoặc tên")},
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
            description=("Tìm kiếm/lọc hồ sơ theo MỘT trường bất kỳ. "
                         "Dùng cho câu hỏi thống kê."),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(
                        type=types.Type.STRING,
                        description="Tên trường (vd: 'ngay_sinh')."),
                    "operator": types.Schema(
                        type=types.Type.STRING,
                        enum=["eq", "neq", "gt", "gte", "lt", "lte",
                              "like", "ilike", "in"],
                        description=("'lt' cho nhỏ hơn, 'gt' cho lớn hơn, "
                                     "'ilike' cho tìm gần đúng.")),
                    "value": types.Schema(
                        type=types.Type.STRING,
                        description=("Giá trị so sánh. Với 'in', dùng "
                                     "mảng JSON.")),
                },
                required=["field", "operator", "value"],
            ),
        ),
    ])]

    own_display = own if own else "(không có — bạn là admin/manager)"
    rule_own = (
        f"- User nói 'của tôi', 'tao', 'mình' → gọi get_profile_data "
        f"với profile_name='{own}'.\n"
        if own else
        "- User KHÔNG có profile riêng. Nếu nói 'của tôi' → hỏi lại user.\n"
    )

    sys_msg = (
        f"Bạn là trợ lý hồ sơ hành chính.\n"
        f"User: '{username}', vai trò: {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Quyền truy cập {len(allowed)} hồ sơ.\n\n"
        f"Quy tắc:\n"
        f"- Chào hỏi/cảm ơn → trả lời trực tiếp, KHÔNG gọi tool.\n"
        f"{rule_own}"
        f"- Nhắc TÊN → gọi get_profile_data.\n"
        f"- Hỏi 'liệt kê' → gọi list_accessible_profiles.\n"
        f"- Câu hỏi thống kê → BẮT BUỘC gọi search_profiles. "
        f"TUYỆT ĐỐI không gọi get_profile_data cho từng người.\n"
        f"- Nhiều candidates → hỏi lại user.\n"
        f"- Không bịa. Tiếng Việt, ngắn gọn."
    )

    contents = []
    if chat_history:
        recent = chat_history[-8:]
        lines = [
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in recent]
        if lines:
            contents.append(types.Content(role="user", parts=[
                types.Part(text="Lịch sử:\n" + "\n".join(lines))]))
            contents.append(types.Content(role="model", parts=[
                types.Part(text="Đã hiểu.")]))
    contents.append(types.Content(role="user", parts=[
        types.Part(text=user_q)]))

    cfg = types.GenerateContentConfig(
        tools=tools,
        system_instruction=sys_msg,
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MINIMAL),
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
                    req = str((dict(fc.args) if fc.args else {}).get(
                        "profile_name", "")).strip()
                    resolved, cands, reason, hint = resolve_profile(
                        req, allowed)
                    if resolved:
                        p_used = resolved
                        d = load_user_profile(resolved)
                        if d:
                            status = "ok"
                            result = {"profile_key": resolved, "data": d}
                        else:
                            status = "no_data"
                            result = {
                                "error": f"Hồ sơ '{resolved}' chưa có dữ liệu.",
                                "profile_key": resolved,
                            }
                    elif cands:
                        p_used = ",".join(cands)
                        status = "ambiguous"
                        result = {
                            "error": hint, "candidates": cands,
                            "action": "ask_user_to_choose",
                        }
                    else:
                        p_used = req
                        status = "not_found"
                        result = {
                            "error": hint,
                            "action": "tell_user_not_found",
                        }
                elif fc.name == "search_profiles":
                    field = str(fc.args.get("field", ""))
                    operator = str(fc.args.get("operator", "eq"))
                    value_raw = fc.args.get("value", "")
                    if operator == "in" and isinstance(value_raw, str):
                        try:
                            value = json.loads(value_raw)
                        except Exception:
                            value = [v.strip() for v in value_raw.split(",")]
                    else:
                        value = value_raw
                    status = "search"
                    result = search_profiles_dynamic(
                        operator, field, value, allowed)
                else:
                    result = {"error": "Unknown"}
                parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            answer = (resp.text or "").strip()
            return answer or "Xin lỗi.", used, p_used, status
    return "Chưa hoàn tất.", used, p_used, status