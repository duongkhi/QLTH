# chat_agent.py
import json
import streamlit as st
from google.genai import types

from ai_client import _generate_with_retry
from config import META_KEYS
from security import detect_name_from_data
from storage import load_user_profile, load_name_mapping
from profile_service import resolve_profile
from user_service import get_own_profile, load_auth_config
from supabase_adapter import get_ai_settings, list_keys_with_prefix, load_many, filter_profiles_in_db
from finance_agent import query_finance_data_tool, query_transactions_tool, search_knowledge_base
from finance_service import load_finance_data, get_visible_project_ids

# ==========================================
# QUẢN LÝ BỘ NHỚ (MEMORY)
# ==========================================
def load_chat_history(username):
    from supabase_adapter import load_json_from_db
    data = load_json_from_db(f"chat_history_{username}")
    return data.get("history", [])

def save_chat_history(username, history):
    from supabase_adapter import save_json_to_db
    trimmed = history[-20:] if len(history) > 20 else history
    save_json_to_db(f"chat_history_{username}", {"history": trimmed})

# ==========================================
# TOOLS IMPLEMENTATION
# ==========================================
def list_accessible_profiles(allowed):
    m = load_name_mapping()
    return [{"profile_key": k, "display_name": m.get(k, {}).get("display_name", ""), "has_data": bool(load_user_profile(k))} for k in allowed]

def search_profiles_dynamic(operator, field, value, allowed_profiles):
    raw_results = filter_profiles_in_db(operator, f"data->>{field}", value)
    results = []
    for row in raw_results:
        key = row["key"]
        if key in allowed_profiles and key not in META_KEYS:
            data = row["data"]
            results.append({"profile_key": key, "ho_va_ten": detect_name_from_data(data) or key, "matched_value": data.get(field)})
    return results

# ==========================================
# MAIN CHAT ENGINE
# ==========================================
def chat_with_ai(user_q, allowed_profiles, username, user_record, chat_history=None):
    own_profile = get_own_profile(user_record, username)
    role = user_record.get("role", "user")
    
    ai_cfg = get_ai_settings()
    db_prompt = ai_cfg.get("chat_system_prompt", "")

    # 1. Khai báo Tools
    all_tools = [
        types.FunctionDeclaration(
            name="get_profile_data",
            description="Lấy dữ liệu hồ sơ nhân sự.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={"profile_name": types.Schema(type=types.Type.STRING)}, required=["profile_name"]),
        ),
        types.FunctionDeclaration(
            name="list_accessible_profiles",
            description="Liệt kê hồ sơ user có quyền.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="search_profiles",
            description="Tìm kiếm/lọc hồ sơ theo trường.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"field": types.Schema(type=types.Type.STRING), "operator": types.Schema(type=types.Type.STRING, enum=["eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in", "contains"]), "value": types.Schema(type=types.Type.STRING)},
                required=["field", "operator", "value"],
            ),
        ),
        types.FunctionDeclaration(
            name="query_finance_data",
            description="Truy vấn danh sách đề tài, số liệu kinh phí. Dùng để tìm kiếm chéo khi hỏi về một người.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(type=types.Type.STRING, description="Trường cần lọc (VD: 'pi'). Để trống nếu lấy toàn bộ."),
                    "operator": types.Schema(type=types.Type.STRING, enum=["eq", "contains", "gt", "lt", "all"], description="Dùng 'all' nếu lấy toàn bộ."),
                    "value": types.Schema(type=types.Type.STRING, description="Giá trị (VD: 'Phạm Hồng Minh'). Để trống nếu lấy toàn bộ."),
                    "action": types.Schema(type=types.Type.STRING, enum=["list", "sum", "count"]),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="query_transactions",
            description="Truy vấn sổ chứng từ.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"project_id": types.Schema(type=types.Type.STRING), "action": types.Schema(type=types.Type.STRING, enum=["list", "sum", "count"])},
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_knowledge",
            description="Tìm kiếm quy chế, định mức trong tài liệu.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={"query": types.Schema(type=types.Type.STRING)}, required=["query"]),
        ),
    ]

    # 2. Cấu hình Prompt (Bắt buộc Tìm kiếm chéo & Tuân thủ bảo mật)
    own_display = own_profile if own_profile else "(chưa có)"
    sys_msg = (
        f"{db_prompt}\n"
        f"--- BỐI CẢNH ---\n"
        f"User: '{username}', vai trò: {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Quyền truy cập: {len(allowed_profiles)} hồ sơ.\n\n"
        f"--- QUY TẮC SUY LUẬN & TÌM KIẾM CHÉO (BẮT BUỘC) ---\n"
        f"1. Chào hỏi/cảm ơn → trả lời trực tiếp, KHÔNG gọi tool.\n"
        f"2. Khi hỏi về một người cụ thể: Gọi 'search_profiles' hoặc 'get_profile_data'. Nếu không thấy, BẮT BUỘC gọi 'query_finance_data' (field='pi', value='Tên') để tìm chéo.\n"
        f"3. Khi hỏi 'danh sách đề tài': BẮT BUỘC gọi 'query_finance_data' (operator='all', action='list').\n"
        f"4. Khi hỏi 'của tôi': gọi 'get_profile_data' với profile_name='{own_profile}'.\n"
        f"5. Hỏi về quy định: gọi 'search_knowledge'.\n"
        f"6. Chỉ khi TẤT CẢ công cụ trả về rỗng, mới được báo không tìm thấy.\n"
        f"7. BẢO MẬT: Nếu kết quả trả về có chứa trường 'note' (cảnh báo bị giới hạn quyền), bạn PHẢI tuân thủ: Trả lời dựa trên dữ liệu đang có và thông báo cho user biết một số thông tin đã bị ẩn đi do chính sách bảo mật. KHÔNG ĐƯỢC bịa số liệu.\n"
        f"--- Tiếng Việt, ngắn gọn, chính xác ---"
    )

    contents = []
    if chat_history:
        recent = chat_history[-6:]
        lines = [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in recent]
        if lines:
            contents.append(types.Content(role="user", parts=[types.Part(text="Lịch sử:\n" + "\n".join(lines))]))
            contents.append(types.Content(role="model", parts=[types.Part(text="Đã hiểu.")]))
    contents.append(types.Content(role="user", parts=[types.Part(text=user_q)]))

    cfg = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=all_tools)],
        system_instruction=sys_msg,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
    )

    used, p_used, status = False, None, None

    # 3. Vòng lặp xử lý
    for _ in range(3):
        resp = _generate_with_retry(cfg, contents)
        
        if not resp.candidates:
            return "Xin lỗi, không xử lý được.", used, p_used, status
            
        if resp.function_calls:
            used = True
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in resp.function_calls:
                
                # --- XỬ LÝ PROFILE & BẢO MẬT ---
                if fc.name == "get_profile_data":
                    req = str(fc.args.get("profile_name", "")).strip()
                    resolved, cands, _, hint = resolve_profile(req, allowed_profiles)
                    
                    if resolved:
                        p_used = resolved
                        d = load_user_profile(resolved)
                        if d:
                            status = "ok"
                            if role == "user" and resolved != own_profile:
                                target_rec = load_auth_config()["users"].get(resolved, {})
                                public_fields = target_rec.get("public_fields", ["ho_va_ten", "chuc_vu"])
                                safe_data = {k: v for k, v in d.items() if k in public_fields}
                                result = {"data": safe_data, "note": "Dữ liệu bị giới hạn do quyền hạn. Hãy nói rõ thông tin cá nhân chi tiết đã bị ẩn."}
                            else:
                                result = {"data": d}
                        else:
                            status = "no_data"
                            result = {"error": f"Hồ sơ '{resolved}' chưa có dữ liệu."}
                    else:
                        status = "not_found"
                        result = {"error": hint, "note": "Hãy thử gọi query_finance_data để tìm kiếm chéo."}
                
                # --- XỬ LÝ TÀI CHÍNH & BẢO MẬT ---
                elif fc.name == "query_finance_data":
                    status = "data"
                    field = str(fc.args.get("field", ""))
                    operator = str(fc.args.get("operator", "all"))
                    value = str(fc.args.get("value", ""))
                    action = str(fc.args.get("action", "list"))
                    
                    projects_raw, _, _ = load_finance_data()

                    if role == "user":
                        # User thường: Ẩn kinh phí
                        res = query_finance_data_tool(field, operator, value, action, allowed_projects=None)
                        if action == "list" and isinstance(res, list):
                            safe_res = [{"project_id": r.get("id"), "name": r.get("name"), "pi": r.get("pi")} for r in res]
                            result = {"projects": safe_res, "note": "Dữ liệu tài chính đã bị ẩn do quyền hạn. Hãy trả lời dựa trên danh sách này."}
                        else:
                            result = {"error": "Bạn không có quyền xem thống kê tài chính chi tiết."}
                    else:
                        # Admin/Manager: Full quyền
                        visible_pids = get_visible_project_ids(user_record, projects_raw)
                        result = query_finance_data_tool(field, operator, value, action, allowed_projects=visible_pids)
                
                # --- CÁC TOOL KHÁC ---
                elif fc.name == "list_accessible_profiles":
                    status = "list"
                    result = list_accessible_profiles(allowed_profiles)
                    
                elif fc.name == "search_profiles":
                    status = "search"
                    result = search_profiles_dynamic(
                        str(fc.args.get("operator", "eq")), 
                        str(fc.args.get("field", "")), 
                        str(fc.args.get("value", "")), 
                        allowed_profiles
                    )
                    
                elif fc.name == "query_transactions":
                    status = "transaction"
                    projects_raw, _, _ = load_finance_data()
                    visible_pids = get_visible_project_ids(user_record, projects_raw)
                    result = query_transactions_tool(
                        project_id=str(fc.args.get("project_id", "")),
                        action=str(fc.args.get("action", "list")),
                        allowed_projects=visible_pids,
                    )
                    
                elif fc.name == "search_knowledge":
                    status = "knowledge"
                    result = search_knowledge_base(str(fc.args.get("query", "")), module="finance")
                else:
                    result = {"error": "Unknown tool"}
                    
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            answer = (resp.text or "").strip()
            return answer or "Xin lỗi.", used, p_used, status
            
    return "Chưa hoàn tất.", used, p_used, status