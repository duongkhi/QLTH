# chat_agent.py
import json
import re as _re
import streamlit as st

from ai_client import _generate_with_retry, generate_gemini_text_real
from config import META_KEYS, UserContext
from security import (_norm, _strip_diacritics, detect_name_from_data,
                     detect_dob_from_data)
from storage import (
    load_user_profile, load_name_mapping, get_all_existing_profiles,
)
from name_mapping import get_display_name
from profile_service import (
    resolve_profile, suggest_profile_key, merge_and_save, find_identity_matches,
)
from user_service import get_own_profile, admin_create_user, tra_cuu_luong
from supabase_adapter import (
    get_ai_settings, filter_profiles_in_db, load_json_from_db,
    save_json_to_db, load_many,
)
from finance_agent import (
    query_finance_data_tool, query_transactions_tool, search_knowledge_base,
)
from finance_service import load_finance_data, get_visible_project_ids
from tool_registry import TOOL_REGISTRY
from docx_utils import extract_profile_document, smart_truncate
from form_templates import list_form_templates, get_form_template, get_template_docx_bytes

DEFAULT_PUBLIC_FIELDS = {
    "ho_va_ten", "ho_ten", "full_name", "hoc_ham", "hoc_vi",
    "chuc_vu", "don_vi", "don_vi_cong_tac", "email",
    "huong_nghien_cuu", "linh_vuc", "de_tai", "cong_bo", "giai_thuong",
}

# ============================================================
# BỘ NHỚ / CACHE (giảm gọi Supabase lẻ)
# ============================================================
_profiles_cache: dict = {}


def _load_many_cached(keys: list) -> dict:
    """Tải nhiều hồ sơ cùng 1 query Supabase, cache lại để gọi lại không tốn thêm."""
    if not keys:
        return {}
    missing = [k for k in keys if k not in _profiles_cache]
    if missing:
        fresh = load_many(missing)
        _profiles_cache.update(fresh)
    return {k: _profiles_cache.get(k, {}) for k in keys}


def _clear_profile_cache():
    _profiles_cache.clear()


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
    """Lấy thông tin tóm tắt các hồ sơ có quyền truy cập."""
    m = load_name_mapping()
    profiles = load_many(list(allowed)) if allowed else {}
    return [
        {
            "profile_key": k,
            "display_name": get_display_name(k, m),
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
        "get_name": lambda k: get_display_name(k, m) or detect_name_from_data(load_user_profile(k)) or k,
    }


# ==========================================
# HELPER: XÂY DỰNG PROMPT CHO AI
# ==========================================
def _build_system_prompt(role, own_profile, viewing_profile, allowed_profiles_count, can_finance, db_prompt):
    own_display = own_profile if own_profile else "(chưa đăng nhập / chưa có)"
    view_display = viewing_profile if viewing_profile else "(không rõ)"

    # Rut gon db_prompt neu qua dai de tranh gui khoi van ban lon di lai moi lan hoi du lieu
    business_context = ""
    if db_prompt:
        dp = db_prompt.strip()
        if len(dp) > 400:
            business_context = dp[:300] + "..."
        else:
            business_context = dp

    tool_list = """
Các công cụ có sẵn (bạn YÊU CẦU gọi bằng cách trả về JSON action):
- get_profile_data: lấy dữ liệu hồ sơ một người. Tham số: {"profile_name": "..."}
- get_salary: lấy thông tin lương của một người. Tham số: {"profile_name": "...", "fields": [...], "preset": "all|tao bang luong|bien dong luong|lan len luong gan nhat"}
- list_accessible_profiles: liệt kê hồ sơ user được phép. Tham số: {}
- search_profiles: tìm hồ sơ theo điều kiện. Tham số: {"field": "...", "operator": "eq|like|...", "value": "..."}
- query_finance_data: tra cứu đề tài/kinh phí. Tham số: {"field": "...", "operator": "...", "value": "...", "action": "list|sum|count"}
- query_transactions: tra cứu sổ chứng từ. Tham số: {"project_id": "...", "action": "list|sum|count"}
- search_knowledge: tra cứu quy định. Tham số: {"query": "..."}
"""

    if can_finance:
        tool_list += "\n- Các công cụ từ TOOL_REGISTRY (lương, lũy kế, xuất Excel) nếu có quyền."

    return (
        f"{business_context}\n\n"
        f"--- BỐI CẢNH ---\n"
        f"User: vai trò {role}.\n"
        f"Profile riêng: {own_display}.\n"
        f"Trang hồ sơ đang mở: '{view_display}'.\n"
        f"Số hồ sơ được phép: {allowed_profiles_count}.\n"
        f"{tool_list}\n"
        f"--- QUY TẮC ---\n"
        f"1. Chào hỏi/cảm ơn → trả lời trực tiếp, không gọi công cụ.\n"
        f"2. Hỏi về một người (\"X là ai\", \"thông tin về X\", \"hồ sơ X\") → gọi get_profile_data với profile_name là tên người đó. Nếu không tìm thấy hồ sơ, có thể gọi query_finance_data để tìm đề tài/tài chính của người đó, rồi trả lời ghép.\n"
        f"3. Hỏi về đề tài / chủ nhiệm đề tài / kinh phí → chỉ gọi query_finance_data, không gọi get_profile_data.\n"
        f"4. Hỏi về lương/thu nhập của một người → gọi get_salary với profile_name là tên người đó. Có thể kèm fields (danh sách trường) hoặc preset (\"all\", \"tao bang luong\", \"bien dong luong\", \"lan len luong gan nhat\"). AI sẽ tự tìm theo tên hiển thị hoặc username.\n"
        f"5. Hỏi danh sách đề tài → gọi query_finance_data (action='list').\n"
        f"6. Hỏi quy định → gọi search_knowledge.\n"
        f"5. Trả về CHỈ duy nhất một đối tượng JSON:\n"
        f'   {{"action": "ten_cong_cu", "args": {{...}}}}\n'
        f"   hoặc\n"
        f'   {{"action": "final", "answer": "câu trả lời cuối cùng cho user"}}\n'
        f"6. Không được kèm markdown, không được giải thích thêm ngoài JSON.\n"
        f"--- Tiếng Việt, ngắn gọn, chính xác ---\n"
    )


def _build_intent_prompt(user_q: str) -> str:
    """Phân loại ý định: chat | retrieve | file."""
    return (
        f"Phân loại ý định của câu hỏi sau vào một trong 3 nhãn: chat | retrieve | file\n\n"
        f"- chat: chào hỏi, cảm ơn, hỏi chung về hệ thống, trò chuyện thường ngày, không cần tra cứu dữ liệu cá nhân.\n"
        f"- retrieve: hỏi thông tin về một người cụ thể, danh sách đề tài, kinh phí, quy định, sổ chứng từ... cần tra cứu từ cơ sở dữ liệu.\n"
        f"- file: yêu cầu đọc file CV/PDF/DOCX, trích xuất thông tin từ file, điền mẫu lý lịch, xuất file, xử lý dữ liệu người dùng gửi lên.\n\n"
        f"Câu hỏi: {user_q}\n\n"
        f"Trả về CHỈ một từ: chat, retrieve hoặc file. Không thêm giải thích."
    )
# ============================================================
# LUỒNG 1: CHAT NHANH — không cần dữ liệu
# ============================================================
CHAT_SYSTEM_PROMPT = (
    "Bạn là trợ lý AI thân thiện, trả lời ngắn gọn bằng tiếng Việt. "
    "Không được tra cứu dữ liệu từ hệ thống, không được gọi công cụ nào. "
    "Trả lời tự nhiên, nhẹ nhàng, không cần suy nghĩ phức tạp."
)

def _handle_chat(user_q: str, db_prompt: str, hist_text: str = "") -> str:
    """Trả lời trực tiếp, không gọi Supabase, không gọi công cụ."""
    # Ưu tiên prompt hệ thống nếu admin đã cấu hình và chưa quá dài, ngược lại dùng prompt ngắn gọn
    system = db_prompt.strip() if db_prompt and len(db_prompt) < 800 else CHAT_SYSTEM_PROMPT
    prompt = (
        f"{hist_text}"
        f"Câu hỏi: {user_q}\n\nTrả lời:"
    )
    try:
        ans = _generate_with_retry(prompt, system=system)
        return ans.strip() if ans else "Xin chào! Tôi có thể giúp gì cho bạn?"
    except Exception:
        return "Xin chào! Tôi có thể giúp gì cho bạn?"


# ============================================================
# LUỒNG 2: RETRIEVE — chỉ truy xuất dữ liệu từ Supabase
# ============================================================
def _list_accessible_profiles(allowed: list) -> list:
    m = load_name_mapping()
    profiles = _load_many_cached(list(allowed)) if allowed else {}
    return [
        {
            "profile_key": k,
            "display_name": get_display_name(k, m),
            "has_data": bool(profiles.get(k)),
        }
        for k in allowed
    ]


def _search_profiles_dynamic(operator: str, field: str, value: str,
                             allowed_profiles: list) -> list:
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


def _handle_retrieve(action: str, args: dict, ctx_info: dict,
                     all_existing: list, fallback_query: str = "") -> tuple:
    """Xử lý các tác vụ truy xuất dữ liệu Supabase.
    Trả về (result_dict, status_string)."""
    role = ctx_info["role"]
    own_profile = ctx_info["own_profile"]
    allowed_profiles = ctx_info["allowed_profiles"]
    can_finance = ctx_info["can_finance"]

    result = {}
    status = None

    if action == "get_profile_data":
        req = str(
            args.get("profile_name", "")
            or args.get("name", "")
            or args.get("ho_ten", "")
            or args.get("ho_va_ten", "")
            or ""
        ).strip()

        if not req and fallback_query:
            req = fallback_query.strip()

        resolved, _, _, _ = resolve_profile(req, all_existing)
        if not resolved and req:
            req_low = req.lower().replace(" ", "")
            safe_k = suggest_profile_key(req).lower()
            for k in all_existing:
                if k.lower() == req_low or k.lower() == safe_k:
                    resolved = k
                    break

        if resolved:
            d = load_user_profile(resolved)
            if d:
                status = "ok"
                if role in ("admin", "manager") or (own_profile and resolved == own_profile):
                    result = {"data": d, "profile_used": resolved}
                else:
                    safe_data = _filter_public_only(d)
                    result = {
                        "data": safe_data,
                        "profile_used": resolved,
                        "note": "Chỉ hiển thị các thông tin được cá nhân công khai (Public). Thông tin riêng tư đã bị ẩn.",
                    }
            else:
                status = "no_data"
                result = {"error": f"Hồ sơ '{resolved}' chưa có dữ liệu."}
        else:
            status = "not_found"
            result = {
                "error": f"Không tìm thấy hồ sơ '{req}' trong hệ thống.",
                "note": "Hãy thử gọi query_finance_data để tìm kiếm chéo.",
            }

    elif action == "query_finance_data":
        status = "data"
        field = str(args.get("field", ""))
        operator = str(args.get("operator", "all"))
        value = str(args.get("value", ""))
        action_val = str(args.get("action", "list"))

        projects_raw, _, _ = load_finance_data()

        if not can_finance:
            res = query_finance_data_tool(field, operator, value, action_val, allowed_projects=None)
            if action_val == "list" and isinstance(res, list):
                safe_res = [
                    {"project_id": r.get("id"), "name": r.get("name"), "pi": r.get("pi")}
                    for r in res
                ]
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
            result = query_finance_data_tool(field, operator, value, action_val, allowed_projects=visible_pids)

    elif action == "list_accessible_profiles":
        status = "list"
        target_list = allowed_profiles if allowed_profiles else all_existing
        result = _list_accessible_profiles(target_list)

    elif action == "search_profiles":
        status = "search"
        target_list = allowed_profiles if allowed_profiles else all_existing
        result = _search_profiles_dynamic(
            str(args.get("operator", "eq")),
            str(args.get("field", "")),
            str(args.get("value", "")),
            target_list,
        )

    elif action == "query_transactions":
        if not can_finance:
            result = {"error": "Bạn không có quyền truy cập sổ chứng từ."}
        else:
            status = "transaction"
            projects_raw, _, _ = load_finance_data()
            visible_pids = None if role in ("admin", "manager") else get_visible_project_ids(
                type("Obj", (), {"role": "user", "own_profile": own_profile})(), projects_raw
            )
            result = query_transactions_tool(
                project_id=str(args.get("project_id", "")),
                action=str(args.get("action", "list")),
                allowed_projects=visible_pids,
            )

    elif action == "search_knowledge":
        status = "knowledge"
        result = search_knowledge_base(str(args.get("query", "")), module="finance")

    elif action == "get_salary":
        # Tra cuu luong: user chi xem chinh minh, admin/manager xem tat ca
        target_name = str(args.get("profile_name", "") or args.get("name", "") or "").strip()
        if not target_name and fallback_query:
            target_name = fallback_query.strip()
        if not target_name:
            result = {"error": "Chưa tên người cần tra cứu lương."}
            status = "error"
        else:
            fields = args.get("fields", None)
            preset = args.get("preset", None)
            result = tra_cuu_luong(target_name, username, role, user_record, fields=fields, preset=preset)
            if "error" in result:
                status = "error"
            else:
                status = "salary"

    elif action in TOOL_REGISTRY:
        if not can_finance:
            result = {"error": "Bạn không có quyền sử dụng công cụ tính lương/tài chính."}
        else:
            status = "data"
            reg_ctx = {
                "load_profile": load_user_profile,
                "allowed_profiles": allowed_profiles,
                "get_name": lambda k: (
                    load_name_mapping().get(k, {}).get("display_name")
                    or detect_name_from_data(load_user_profile(k))
                    or k
                ),
            }
            raw_res = TOOL_REGISTRY[action]["func"](dict(args), reg_ctx)
            if isinstance(raw_res, dict) and "_excel_bytes" in raw_res:
                st.session_state["_chat_excel_download"] = {
                    "bytes": raw_res.pop("_excel_bytes"),
                    "filename": f"{raw_res.get('download_token', 'bang_luong')}.xlsx",
                }
            result = raw_res

    else:
        result = {"error": f"Không nhận diện công cụ: {action}"}
        status = "error"

    return result, status


def _synthesize_retrieve_answer(user_q: str, action: str, result: dict,
                                ctx_info: dict, db_prompt: str,
                                hist_text: str = "") -> str:
    """Gọi AI lần thứ 2 để tổng hợp câu trả lời từ kết quả công cụ."""
    role = ctx_info["role"]
    own_profile = ctx_info["own_profile"]
    viewing_profile = ctx_info["viewing_profile"]
    allowed_profiles = ctx_info["allowed_profiles"]
    can_finance = ctx_info["can_finance"]

    sys_prompt = _build_system_prompt(
        role, own_profile, viewing_profile, len(allowed_profiles), can_finance, db_prompt
    )

    follow_up_prompt = (
        f"{hist_text}"
        f"Kết quả từ công cụ '{action}':\n{json.dumps(result, ensure_ascii=False)}\n\n"
        f"Câu hỏi gốc: {user_q}\n\n"
        f"Hãy viết câu trả lời cuối cùng cho user dựa trên kết quả trên. Trả về JSON: "
        f"{json.dumps({'action': 'final', 'answer': '...'})}"
    )

    try:
        final_text = _generate_with_retry(follow_up_prompt, system=sys_prompt)
        if final_text:
            cleaned = final_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            try:
                final_data = json.loads(cleaned)
                final_answer = final_data.get("answer") or (final_data.get("args") or {}).get("answer") or ""
                if final_answer:
                    return final_answer.strip()
            except Exception:
                pass
            # Nếu JSON không lấy được answer, thử trích xuất bằng regex
            m = _re.search(r'"answer"\s*:\s*"([^"]+)"', cleaned or "")
            if m:
                return m.group(1).strip()
            return cleaned
    except Exception:
        pass

    return json.dumps(result, ensure_ascii=False)
# ============================================================
# LUỒNG 3: FILE — xử lý file người dùng gửi (docx/xlsx/pdf)
# ============================================================
def _extract_file_text(file_bytes: bytes, filename: str) -> str:
    """Trích xuất văn bản thô từ file docx hoặc pdf."""
    return extract_profile_document(file_bytes, filename)


def _build_file_extract_prompt(raw_text: str, filename: str) -> str:
    """Prompt yeu cau AI trich xuat thong tin tu file thanh JSON chuan,
    du chi tiet de dong bo truc tiep vao truong bai_bao_cong_bo."""
    parts = []
    parts.append(f"Trich xuat TOAN BO thong tin tu file '{filename}' thanh JSON ")
    parts.append("(key viet thuong, gach duong, tieng Viet khong dau). Truong nao khong co thi de null hoac bo qua.\n\n")
    parts.append("THONG TIN CA NHAN (bat buoc neu co):\n")
    parts.append("- 'ho_va_ten', 'hoc_ham', 'hoc_vi', 'chuc_vu', 'don_vi_cong_tac', 'ngay_sinh' (DD/MM/YYYY)\n")
    parts.append("- 'don_vi_cong_tac_con': don vi con (trung tai/phong ban) neu co\n")
    parts.append("- 'ho_va_ten_anh': ten tieng anh neu co trong file (vi du: 'Vu Duong', 'Nguyen Van A')\n")
    parts.append("- 'huong_nghien_cuu': doan mo tro huong nghien cuu chinh\n\n")
    parts.append("DANH SACH BAI BAO / CONG TRINH KHOA HOC ('cong_bo'):\n")
    parts.append("Moi phan tu la mot dict co cac truong sau:\n")
    parts.append("- 'ten_cong_trinh': ten bai bao/cong trinh\n")
    parts.append("- 'nam_cong_bo': nam cong bo (chi so, vi du 2025)\n")
    parts.append("- 'noi_cong_bo': ten tap chi, hoi nghi, xuat ban\n")
    parts.append("- 'loai_cong_trinh': loai cong trinh (vi du: 'Tap chi quoc te', 'Hoi nghi quoc te', 'Tap chi trong nuoc', 'Hoi nghi trong nuoc')\n")
    parts.append("- 'phan_loai': phan loai chat luong (Scopus Q1/Q2/Q3/Q4, ISI/SCI-EE Q1-Q4, SCI Q1-Q4, Tap chi quoc te, Hoi nghi quoc te, Tap chi trong nuoc, Hoi nghi trong nuoc, Khac)\n")
    parts.append("- 'vai_tro': vai tro tac gia ('Tac gia dau' / 'first author' = tac gia chinh; 'Tac gia lien he' / 'corresponding author' = tac gia lien he; 'Dong tac gia' / 'co-author' = dong tac gia)\n")
    parts.append("- 'doi': ma DOI neu co\n")
    parts.append("- 'issn': ma ISSN neu co\n\n")
    parts.append("DANH SACH DE TAI ('de_tai'):\n")
    parts.append("Moi phan tu la dict {\"ten_de_tai\", \"ma_so\", \"vai_tro\", \"thoi_gian\", \"trang_thai\"}\n\n")
    parts.append("QUY TAC PHAN LOAI (quan trong):\n")
    parts.append("- Neu tap chi co Scopus/ISI/SCI va ghi Q1 -> phan loai 'Scopus Q1' (hoac 'ISI/SCI-EE Q1', 'SCI Q1')\n")
    parts.append("- Q2 -> 'Scopus Q2', Q3 -> 'Scopus Q3', Q4 -> 'Scopus Q4'\n")
    parts.append("- Neu la hoi nghi quoc te khong co chi so -> 'Hoi nghi quoc te'\n")
    parts.append("- Neu la hoi nghi trong nuoc -> 'Hoi nghi trong nuoc'\n")
    parts.append("- Neu la tap chi quoc te khong co chi so -> 'Tap chi quoc te'\n")
    parts.append("- Neu la tap chi trong nuoc -> 'Tap chi trong nuoc'\n\n")
    parts.append("VAN BAN FILE:\n'''" + smart_truncate(raw_text) + "'''\n")
    return "".join(parts)

def _match_profile_to_supabase(extracted: dict, allowed_profiles: list, username: str):
    """So sánh dữ liệu trích xuất từ file với hồ sơ có sẵn trên Supabase."""
    if not allowed_profiles:
        return None, "no_allowed", {}

    matches = find_identity_matches(extracted, allowed_profiles)
    if matches:
        best_key, confidence = matches[0]
        return best_key, confidence, {}

    name = extracted.get("ho_va_ten") or extracted.get("ho_ten") or extracted.get("full_name")
    if name:
        for k in allowed_profiles:
            d = load_user_profile(k)
            if not d:
                continue
            existing_name = detect_name_from_data(d)
            if existing_name and name.lower().strip() == existing_name.lower().strip():
                return k, "weak_name_only", {}

    return None, "no_match", {}


def _handle_file(user_q: str, file_bytes: bytes, filename: str,
                 ctx_info: dict, db_prompt: str) -> tuple:
    """Xử lý file người dùng gửi: trích xuất → so sánh Supabase → cập nhật hồ sơ."""
    username = ctx_info["username"]
    allowed_profiles = ctx_info["allowed_profiles"]
    role = ctx_info["role"]
    own_profile = ctx_info["own_profile"]

    used = True
    p_used = None

    try:
        raw_text = _extract_file_text(file_bytes, filename)
    except Exception as e:
        return (f"❌ Không đọc được file '{filename}': {e}", used, p_used, "error")

    if not raw_text or len(raw_text.strip()) < 10:
        return ("❌ File không có nội dung văn bản hoặc nội dung quá ít.", used, p_used, "error")

    prompt = _build_file_extract_prompt(raw_text, filename)
    try:
        extracted_text = generate_gemini_text_real(prompt)
        if not extracted_text:
            return (
                "⚠️ Đã đính kèm file nhưng hệ thống chưa cấu hình GEMINI_API_KEY, "
                "hoặc Nemotron không hỗ trợ phân tích file đính kèm. "
                "Vui lòng nhập câu hỏi văn bản thay vì đính kèm file, hoặc liên hệ Admin để cấu hình GEMINI_API_KEY.",
                used, p_used, "error",
            )
        cleaned = extracted_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        extracted = json.loads(cleaned)
    except Exception as e:
        return (f"❌ Lỗi phân tích file: {e}", used, p_used, "error")

    if not extracted:
        return ("❌ Không trích xuất được thông tin nào từ file.", used, p_used, "error")

    matched_key, confidence, _ = _match_profile_to_supabase(
        extracted, allowed_profiles, username
    )

    can_write = (
        role in ("admin", "manager")
        or (own_profile and matched_key == own_profile)
    )

    if matched_key and can_write:
        final, changes = merge_and_save(matched_key, extracted, overwrite=False)
        p_used = matched_key
        status = "updated"
        answer = (
            f"✅ Đã phân tích file '{filename}' và cập nhật hồ sơ **{matched_key}**\n"
            f"• Độ tin cậy khớp: {confidence}\n"
            f"• Trường mới thêm: {len(changes.get('added', {}))}\n"
            f"• Trường cập nhật: {len(changes.get('updated', {}))}\n"
            f"• Trường nối thêm: {len(changes.get('appended', {}))}\n\n"
            f"Bạn có thể xem chi tiết hồ sơ này ở trang hồ sơ cá nhân."
        )
        return (answer, used, p_used, status)

    elif matched_key and not can_write:
        p_used = matched_key
        status = "no_permission"
        answer = (
            f"⚠️ File '{filename}' khớp với hồ sơ **{matched_key}**, "
            f"nhưng bạn không có quyền ghi vào hồ sơ này.\n"
            f"Vui lòng liên hệ Admin hoặc Manager để được cập nhật."
        )
        return (answer, used, p_used, status)

    else:
        status = "no_match"
        answer = (
            f"📄 Đã trích xuất được **{len(extracted)} trường** từ file '{filename}'.\n"
            f"Tuy nhiên, không khớp với bất kỳ hồ sơ nào trong hệ thống mà bạn có quyền truy cập.\n\n"
            f"**Dữ liệu trích xuất:**\n"
            f"{json.dumps(extracted, ensure_ascii=False, indent=2)}\n\n"
            f"Nếu bạn là Admin/Manager, có thể tạo hồ sơ mới hoặc liên hệ quản trị để gán dữ liệu này."
        )
        return (answer, used, p_used, status)
# ============================================================
# ĐIỂM VÀO CHÍNH
# ============================================================
def chat_with_ai(user_q, allowed_profiles, username, user_record,
                 chat_history=None, viewing_profile=None,
                 file_bytes=None, filename=None):
    """
    Phân loại ý định rồi điều phối sang luồng xử lý tương ứng.
    Trả về: (answer, used, p_used, status).
    """
    role = user_record.get("role", "user") if user_record else "user"
    own_profile = get_own_profile(user_record or {}, username) if username else None
    can_finance = role in ("admin", "manager") or bool(
        (user_record or {}).get("allowed_tools")
    )
    db_prompt = get_ai_settings().get("chat_system_prompt", "")
    ctx_info = {
        "role": role,
        "own_profile": own_profile,
        "viewing_profile": viewing_profile,
        "allowed_profiles": allowed_profiles or [],
        "can_finance": can_finance,
        "username": username,
    }
    all_existing = get_all_existing_profiles()

    # ====== XỬ LÝ LỆNH ADMIN QUA CHAT ======
    admin_result = _try_admin_command(user_q, role)
    if admin_result is not None:
        return admin_result, True, None, "admin_cmd"

    # ====== LUỒNG 3: XỬ LÝ FILE UPLOAD ======
    if file_bytes and filename:
        return _handle_file(user_q, file_bytes, filename, ctx_info, db_prompt)

    hist_text = ""
    if chat_history:
        recent = chat_history[-6:]
        lines = [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
                 for m in recent]
        if lines:
            hist_text = "Lịch sử gần đây:\n" + "\n".join(lines) + "\n\n"

    try:
        raw_intent = _generate_with_retry(_build_intent_prompt(user_q))
        intent = (raw_intent or "chat").strip().lower()
    except Exception:
        intent = "chat"

    # ====== LUỒNG 1: CHAT THƯỜNG ======
    if "chat" in intent:
        # Nếu câu hỏi nhắc đến tên một người trong hệ thống (có dấu hay không dấu),
        # ép chuyển sang luồng tra cứu thay vì trả lời chào chung.
        q_norm = _strip_diacritics(user_q.lower())
        for k in all_existing:
            k_norm = _strip_diacritics(k.lower())
            if k_norm and (k_norm in q_norm or q_norm in k_norm):
                intent = "retrieve"
                break

        if "chat" in intent:
            ans = _handle_chat(user_q, db_prompt, hist_text)
            return ans, False, None, "chat"

    # ====== LUỒNG 2: RETRIEVE (truy xuất Supabase) ======
    if any(k in intent for k in ("retrieve", "file")):
        sys_prompt = _build_system_prompt(
            role, own_profile, viewing_profile, len(allowed_profiles or []),
            can_finance, db_prompt
        )

        full_prompt = (
            f"{hist_text}"
            f"Câu hỏi hiện tại: {user_q}\n\n"
            f"Trả về JSON action:"
        )

        for _ in range(3):
            try:
                resp_text = _generate_with_retry(full_prompt, system=sys_prompt)
            except Exception:
                return "Xin lỗi, không xử lý được.", False, None, "error"

            if not resp_text:
                return "Xin lỗi, không xử lý được.", False, None, "error"

            action = None
            args = {}
            data = {}
            try:
                cleaned = resp_text.strip()
                if cleaned.startswith("```json"):
                    cleaned = cleaned[7:]
                if cleaned.startswith("```"):
                    cleaned = cleaned[3:]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
                cleaned = cleaned.strip()
                data = json.loads(cleaned)
                action = data.get("action")
                args = data.get("args", {}) or {}
            except Exception:
                # AI có thể trả về text kèm JSON, không phải JSON thuần
                m = _re.search(r'"answer"\s*:\s*"([^"]+)"', resp_text or "")
                if m:
                    return m.group(1).strip(), False, None, "chat"
                return (resp_text or "Xin lỗi.").strip(), False, None, "chat"

            if action == "final":
                ans = data.get("answer") or args.get("answer") or "Xin lỗi."
                return ans.strip(), False, None, "final"

            used = True
            result, status = _handle_retrieve(
                action, args, ctx_info, all_existing, fallback_query=user_q
            )

            final_answer = _synthesize_retrieve_answer(
                user_q, action, result, ctx_info, db_prompt, hist_text
            )
            p_used = None
            if isinstance(result, dict):
                p_used = result.get("profile_used") or (
                    result.get("data", {}).get("profile_key")
                    if isinstance(result.get("data"), dict) else None
                )
            return final_answer, used, p_used, status

    ans = _handle_chat(user_q, db_prompt, hist_text)
    return ans, False, None, "chat"


# ============================================================
# XỬ LÝ LỆNH ADMIN QUA CHAT
# ============================================================
def _try_admin_command(user_q: str, role: str) -> str | None:
    """
    Phát hiện và thực thi lệnh admin từ chat.
    Hỗ trợ mẫu: "thêm user <tên> pass <mật khẩu>"
    """
    q = user_q.strip()

    if role != "admin":
        cmd_patterns = [
            _re.compile(r"thêm\s+user\s+\S+\s+pass\s+\S+", _re.IGNORECASE),
            _re.compile(r"tạo\s+user\s+\S+\s+mật\s+khẩu\s+\S+", _re.IGNORECASE),
            _re.compile(r"add\s+user\s+\S+\s+password\s+\S+", _re.IGNORECASE),
        ]
        for pat in cmd_patterns:
            if pat.search(q):
                return "❌ Bạn không có quyền thực hiện lệnh này. Vui lòng liên hệ Admin."
        return None

    patterns = [
        _re.compile(r"thêm\s+user\s+(\S+)\s+pass\s+(\S+)", _re.IGNORECASE),
        _re.compile(r"tạo\s+user\s+(\S+)\s+mật\s+khẩu\s+(\S+)", _re.IGNORECASE),
        _re.compile(r"add\s+user\s+(\S+)\s+password\s+(\S+)", _re.IGNORECASE),
    ]

    for pat in patterns:
        m = pat.search(q)
        if m:
            new_user = m.group(1)
            new_pw = m.group(2)
            if not _re.match(r"^[a-zA-Z0-9_]+$", new_user):
                return f"❌ Tên user '{new_user}' không hợp lệ. Chỉ được chứa chữ, số và gạch dưới."
            if len(new_user) < 3:
                return f"❌ Tên user '{new_user}' quá ngắn (tối thiểu 3 ký tự)."
            ok, msg = admin_create_user(new_user, new_pw, role="user")
            if ok:
                return f"✅ Đã tạo user '{new_user}' thành công (vai trò: user)."
            else:
                return f"❌ {msg}"

    return None
