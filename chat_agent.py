# chat_agent.py
import json
import streamlit as st
from google.genai import types

from ai_client import _generate_with_retry
from config import META_KEYS
from security import detect_name_from_data
from storage import load_user_profile, load_name_mapping, get_all_existing_profiles
from profile_service import resolve_profile, suggest_profile_key
from user_service import get_own_profile
from supabase_adapter import get_ai_settings, filter_profiles_in_db, load_json_from_db, save_json_to_db, load_many
from finance_agent import query_finance_data_tool, query_transactions_tool, search_knowledge_base
from finance_service import load_finance_data, get_visible_project_ids
from tool_registry import TOOL_REGISTRY

DEFAULT_PUBLIC_FIELDS = {
    "ho_va_ten", "ho_ten", "full_name", "hoc_ham", "hoc_vi",
    "chuc_vu", "don_vi", "don_vi_cong_tac", "email",
    "huong_nghien_cuu", "linh_vuc", "de_tai", "cong_bo", "giai_thuong",
}


# ==========================================
# QUẢN LÝ BỘ NHỚ (MEMORY)
# ==========================================
def load_chat_history(username):
    if not username:
        return []
    data = load_json_from_db(f"chat_history_{username}")
    return data.get("history", [])


def save_chat_history(username, history):
    if not username:
        return
    trimmed = history[-20:] if len(history) > 20 else history
    save_json_to_db(f"chat_history_{username}", {"history": trimmed})


# ==========================================
# TOOLS IMPLEMENTATION
# ==========================================
def list_accessible_profiles(allowed):
    """Lấy thông tin tóm tắt các hồ sơ có quyền truy cập.

    Dùng load_many để tải toàn bộ hồ sơ cần thiết trong một query Supabase
    thay vì gọi lẻ từng hồ sơ, giúp giảm thời gian chờ trên Streamlit Cloud.
    """
    m = load_name_mapping()
    profiles = load_many(list(allowed)) if allowed else {}
    return [
        {
            "profile_key": k,
            "display_name": m.get(k, {}).get("display_name", ""),
            "has_data": bool(profiles.get(k)),
        }
        for k in allowed
    ]


def search_profiles_dynamic(operator, field, value, allowed_profiles):
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


def _filter_public_only(profile_data: dict) -> dict:
    configured = profile_data.get("_public_fields")
    allowed = set(configured) if isinstance(configured, list) else DEFAULT_PUBLIC_FIELDS
    return {
        k: v for k, v in profile_data.items()
        if not k.startswith("_") and (k in allowed or k in DEFAULT_PUBLIC_FIELDS) and v
    }


def _build_registry_ctx(allowed_profiles):
    m = load_name_mapping()
    return {
        "load_profile": load_user_profile,
        "allowed_profiles": allowed_profiles,
        "get_name": lambda k: m.get(k, {}).get("display_name") or detect_name_from_data(load_user_profile(k)) or k,
    }


# ==========================================
# MAIN CHAT ENGINE
# ==========================================
def chat_with_ai(user_q, allowed_profiles, username, user_record, chat_history=None, viewing_profile=None):
    role = user_record.get("role", "guest") if username else "guest"
    own_profile = get_own_profile(user_record, username) if username else None
    allowed_tools = user_record.get("allowed_tools", []) if username else []
    can_finance = role in ("admin", "manager") or ("finance" in allowed_tools)

    ai_cfg = get_ai_settings()
    db_prompt = ai_cfg.get("chat_system_prompt", "")

    # 1. Khai báo Tools cơ bản
    all_tools = [
        types.FunctionDeclaration(
            name="get_profile_data",
            description="Lấy dữ liệu hồ sơ nhân sự.",
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
            description="Tìm kiếm/lọc hồ sơ theo trường.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(type=types.Type.STRING),
                    "operator": types.Schema(
                        type=types.Type.STRING,
                        enum=["eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike", "in", "contains"],
                    ),
                    "value": types.Schema(type=types.Type.STRING),
                },
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
                properties={
                    "project_id": types.Schema(type=types.Type.STRING),
                    "action": types.Schema(type=types.Type.STRING, enum=["list", "sum", "count"]),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_knowledge",
            description="Tìm kiếm quy chế, định mức trong tài liệu.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(type=types.Type.STRING)},
                required=["query"],
            ),
        ),
    ]

    # Nạp thêm các tool từ TOOL_REGISTRY (lương, lũy kế, xuất Excel) nếu có quyền
    if can_finance:
        for item in TOOL_REGISTRY.values():
            all_tools.append(item["schema"])

    # 2. Cấu hình Prompt
    own_display = own_profile if own_profile else "(chưa đăng nhập / chưa có)"
    view_display = viewing_profile if viewing_profile else "(không rõ)"
    sys_msg = (
        f"{db_prompt}\n"
        f"--- BỐI CẢNH ---\n"
        f"User: '{username or 'Khách'}', vai trò: {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Trang hồ sơ công khai đang mở trên màn hình: '{view_display}'.\n"
        f"Quyền truy cập chi tiết: {len(allowed_profiles)} hồ sơ.\n\n"
        f"--- QUY TẮC SUY LUẬN & TÌM KIẾM CHÉO (BẮT BUỘC) ---\n"
        f"1. Chào hỏi/cảm ơn → trả lời trực tiếp, KHÔNG gọi tool.\n"
        f"2. Khi hỏi 'người này' hoặc thông tin trang đang mở → gọi 'get_profile_data' với profile_name='{view_display}'.\n"
        f"3. Khi hỏi thông tin chung về một cá nhân cụ thể:\n"
        f"   - Bước 1: Gọi 'get_profile_data' (hoặc 'search_profiles' nếu tìm theo điều kiện).\n"
        f"   - Bước 2: Nếu có dữ liệu hồ sơ → CHỈ tóm tắt ngắn gọn thông tin cơ bản (Họ tên, Học hàm/học vị, Chức vụ, Đơn vị công tác, Hướng nghiên cứu chính) trong 3–4 dòng. KHÔNG liệt kê dài dòng quá trình công tác hay toàn bộ đề tài (trừ khi user hỏi đích danh một mục cụ thể).\n"
        f"   - Bước 3: Nếu không có hồ sơ trong hệ thống → gọi 'query_finance_data' (field='pi', operator='contains', value='Tên') để tìm chéo xem người đó có chủ nhiệm đề tài nào không.\n"
        f"4. Khi hỏi 'danh sách đề tài' → gọi 'query_finance_data' (operator='all', action='list').\n"
        f"5. Khi hỏi 'của tôi' → gọi 'get_profile_data' với profile_name='{own_profile}'.\n"
        f"6. Hỏi về quy định, định mức → gọi 'search_knowledge'.\n"
        f"7. BẢO MẬT: Nếu kết quả trả về có trường 'note' (cảnh báo bị giới hạn quyền), bạn PHẢI tuân thủ: Trả lời dựa trên dữ liệu đang có và thông báo thông tin riêng tư đã bị ẩn do chính sách bảo mật. KHÔNG ĐƯỢC bịa số liệu.\n"
        f"8. QUY TẮC DỪNG: Nếu một công cụ trả về 'Không tìm thấy' hoặc danh sách rỗng, ĐỪNG GỌI LẠI CÔNG CỤ ĐÓ NỮA.\n"
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
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
    )

    used, p_used, status = False, None, None
    all_existing = get_all_existing_profiles()

    for _ in range(3):
        resp = _generate_with_retry(cfg, contents)
        if not resp.candidates:
            return "Xin lỗi, không xử lý được.", used, p_used, status

        if resp.function_calls:
            used = True
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in resp.function_calls:
                if fc.name == "get_profile_data":
                    req = str(fc.args.get("profile_name", "")).strip()
                    resolved, _, _, _ = resolve_profile(req, all_existing)
                    if not resolved:
                        req_low = req.lower().replace(" ", "")
                        safe_k = suggest_profile_key(req).lower()
                        for k in all_existing:
                            if k.lower() == req_low or k.lower() == safe_k:
                                resolved = k
                                break

                    if resolved:
                        p_used = resolved
                        d = load_user_profile(resolved)
                        if d:
                            status = "ok"
                            if role in ("admin", "manager") or (own_profile and resolved == own_profile):
                                result = {"data": d}
                            else:
                                safe_data = _filter_public_only(d)
                                result = {
                                    "data": safe_data,
                                    "note": "Chỉ hiển thị các thông tin được cá nhân công khai (Public). Thông tin riêng tư đã bị ẩn.",
                                }
                        else:
                            status = "no_data"
                            result = {"error": f"Hồ sơ '{resolved}' chưa có dữ liệu."}
                    else:
                        status = "not_found"
                        result = {
                            "error": "Không tìm thấy hồ sơ này trong hệ thống.",
                            "note": "Hãy thử gọi query_finance_data để tìm kiếm chéo.",
                        }

                elif fc.name == "query_finance_data":
                    status = "data"
                    field = str(fc.args.get("field", ""))
                    operator = str(fc.args.get("operator", "all"))
                    value = str(fc.args.get("value", ""))
                    action = str(fc.args.get("action", "list"))

                    projects_raw, _, _ = load_finance_data()

                    if not can_finance:
                        res = query_finance_data_tool(field, operator, value, action, allowed_projects=None)
                        if action == "list" and isinstance(res, list):
                            safe_res = [{"project_id": r.get("id"), "name": r.get("name"), "pi": r.get("pi")} for r in res]
                            result = {
                                "projects": safe_res,
                                "note": "Số liệu kinh phí chi tiết đã bị ẩn do giới hạn quyền hạn.",
                            }
                        else:
                            result = {"error": "Bạn không có quyền xem thống kê tài chính chi tiết."}
                    else:
                        visible_pids = None if role in ("admin", "manager") else get_visible_project_ids(
                            type("Obj", (), {"role": "user", "own_profile": own_profile})(), projects_raw
                        )
                        result = query_finance_data_tool(field, operator, value, action, allowed_projects=visible_pids)

                elif fc.name == "list_accessible_profiles":
                    status = "list"
                    target_list = allowed_profiles if allowed_profiles else all_existing
                    result = list_accessible_profiles(target_list)

                elif fc.name == "search_profiles":
                    status = "search"
                    target_list = allowed_profiles if allowed_profiles else all_existing
                    result = search_profiles_dynamic(
                        str(fc.args.get("operator", "eq")),
                        str(fc.args.get("field", "")),
                        str(fc.args.get("value", "")),
                        target_list,
                    )

                elif fc.name == "query_transactions":
                    if not can_finance:
                        result = {"error": "Bạn không có quyền truy cập sổ chứng từ."}
                    else:
                        status = "transaction"
                        projects_raw, _, _ = load_finance_data()
                        visible_pids = None if role in ("admin", "manager") else get_visible_project_ids(
                            type("Obj", (), {"role": "user", "own_profile": own_profile})(), projects_raw
                        )
                        result = query_transactions_tool(
                            project_id=str(fc.args.get("project_id", "")),
                            action=str(fc.args.get("action", "list")),
                            allowed_projects=visible_pids,
                        )

                elif fc.name == "search_knowledge":
                    status = "knowledge"
                    result = search_knowledge_base(str(fc.args.get("query", "")), module="finance")

                elif fc.name in TOOL_REGISTRY:
                    if not can_finance:
                        result = {"error": "Bạn không có quyền sử dụng công cụ tính lương/tài chính."}
                    else:
                        status = "data"
                        reg_ctx = _build_registry_ctx(allowed_profiles)
                        raw_res = TOOL_REGISTRY[fc.name]["func"](dict(fc.args), reg_ctx)
                        if isinstance(raw_res, dict) and "_excel_bytes" in raw_res:
                            st.session_state["_chat_excel_download"] = {
                                "bytes": raw_res.pop("_excel_bytes"),
                                "filename": f"{raw_res.get('download_token', 'bang_luong')}.xlsx",
                            }
                        result = raw_res
                else:
                    result = {"error": "Unknown tool"}

                parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            answer = (resp.text or "").strip()
            return answer or "Xin lỗi.", used, p_used, status

    return "Tôi đã thử tìm kiếm nhưng không có kết quả phù hợp. Bạn có thể hỏi rõ hơn được không?", used, p_used, status