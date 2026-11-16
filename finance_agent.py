import json
from google.genai import types
from ai_client import _generate_with_retry
from finance_service import load_finance_data, get_project_metrics
from supabase_adapter import get_ai_settings, load_json_from_db, list_keys_with_prefix, load_many


# =============================================================
# KNOWLEDGE BASE
# =============================================================
def search_knowledge_base(query, module="finance"):
    """
    Tra cứu tri thức: gộp cả văn bản nhập tay (key 'finance_rules') 
    và các văn bản PDF đã xử lý (key 'kb_finance_*').
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
# =============================================================
# TOOLS
# =============================================================
def query_finance_data_tool(field, operator, value, action,
                             allowed_projects=None):
    projects, disbursements, _ = load_finance_data()
    results = []

    for pid, p in projects.items():
        if allowed_projects is not None and pid not in allowed_projects:
            continue

        d = disbursements.get(pid, {})
        m = get_project_metrics(pid, p, d)
        flat = {**p, **m, **d, "project_id": pid}

        val = flat.get(field, "")
        match = False
        if operator == "eq" and str(val).lower() == str(value).lower():
            match = True
        elif operator == "contains" and str(value).lower() in str(val).lower():
            match = True
        elif operator == "gt":
            try: match = float(val or 0) > float(value)
            except Exception: match = False
        elif operator == "lt":
            try: match = float(val or 0) < float(value)
            except Exception: match = False
        elif operator == "all":
            match = True

        if match:
            results.append(flat)

    if action == "list":
        return [{
            "id": r["project_id"],
            "name": r.get("name", ""),
            "pi": r.get("pi", ""),
            "budget": r.get("actual_budget", 0),
            "disbursed": r.get("current_cum", 0),
            "rate": round(r.get("rate", 0), 1),
        } for r in results]

    if action == "sum":
        if field:
            return {
                "total_sum": sum(float(r.get(field) or 0) for r in results),
                "count": len(results),
            }
        return {"count": len(results)}

    if action == "count":
        return {"count": len(results)}

    return results


def query_transactions_tool(project_id="", action="list",
                             allowed_projects=None):
    _, _, transactions = load_finance_data()
    res = []
    for tx in transactions:
        if allowed_projects is not None and \
                tx.get("project_id") not in allowed_projects:
            continue
        if project_id and project_id not in tx.get("project_id", ""):
            continue
        res.append(tx)

    if action == "sum":
        return {
            "total_sum": sum(t.get("amount", 0) for t in res),
            "count": len(res),
        }
    if action == "count":
        return {"count": len(res)}
    return res


# =============================================================
# CHAT
# =============================================================
def chat_with_finance_ai(user_q, chat_history=None, allowed_project_ids=None):
    # 1. Lấy cấu hình AI động
    ai_cfg = get_ai_settings()
    db_prompt = ai_cfg.get("chat_system_prompt", "")

    # 2. Định nghĩa Tools
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="query_finance_data",
            description=(
                "Truy vấn, thống kê, tính tổng kinh phí đề tài. "
                "Dùng khi hỏi về số liệu giao, giải ngân, tỷ lệ %."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(
                        type=types.Type.STRING,
                        description=(
                            "Trường dữ liệu: 'pi' (chủ nhiệm), 'group' (nhóm), "
                            "'actual_budget' (kinh phí), 'current_cum' (đã giải ngân), "
                            "'rate' (tỷ lệ %), 'name' (tên)."
                        ),
                    ),
                    "operator": types.Schema(
                        type=types.Type.STRING,
                        enum=["eq", "contains", "gt", "lt", "all"],
                        description="Toán tử so sánh.",
                    ),
                    "value": types.Schema(
                        type=types.Type.STRING,
                        description="Giá trị so sánh (VD: 'Mở mới', '50').",
                    ),
                    "action": types.Schema(
                        type=types.Type.STRING,
                        enum=["list", "sum", "count"],
                        description="Hành động: list / sum / count.",
                    ),
                },
                required=["field", "operator", "value", "action"],
            ),
        ),
        types.FunctionDeclaration(
            name="query_transactions",
            description=(
                "Truy vấn sổ chứng từ chi tiết. Dùng khi hỏi về hóa đơn, "
                "số chứng từ, nội dung chi, người ký."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "project_id": types.Schema(
                        type=types.Type.STRING,
                        description="Mã đề tài (để trống nếu muốn tất cả).",
                    ),
                    "action": types.Schema(
                        type=types.Type.STRING,
                        enum=["list", "sum", "count"],
                    ),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="search_knowledge",
            description="Tìm kiếm quy chế, định mức chi tiêu, quy trình thanh toán. Dùng khi user hỏi về luật lệ, quy định.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Từ khóa (vd: 'định mức công tác phí')")
                },
                required=["query"],
            ),
        ),
    ])]

    # 3. Xây dựng System Prompt
    sys_msg = (
        f"{db_prompt}\n"
        "Bạn là Trợ lý Tài chính AI. Bạn có quyền truy cập dữ liệu báo cáo "
        "tổng hợp và sổ chứng từ chi tiết.\n"
        "Quy tắc:\n"
        "1. Hỏi số liệu tổng hợp (VD: 'Tổng kinh phí của TS. Tiến') → gọi tool 'query_finance_data'.\n"
        "2. Hỏi chi tiết chứng từ (VD: 'Đề tài CT01 có hóa đơn nào?') → gọi 'query_transactions'.\n"
        "3. Hỏi về quy định, định mức, quy trình → gọi 'search_knowledge'.\n"
        "4. Định dạng tiền tệ VNĐ. Trả lời ngắn gọn, chính xác."
    )

    if allowed_project_ids is not None:
        sys_msg += (
            f"\n\n⚠️ QUAN TRỌNG: User này chỉ được phép xem {len(allowed_project_ids)} "
            "đề tài do chính họ chủ nhiệm. Nếu user hỏi về đề tài khác "
            "(không có trong danh sách được phép), hãy trả lời: "
            "'Bạn không có quyền xem đề tài này. Bạn chỉ có thể xem các đề tài "
            "do mình chủ nhiệm.'"
        )

    contents = []
    if chat_history:
        recent = chat_history[-6:]
        lines = [
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in recent
        ]
        if lines:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text="Lịch sử:\n" + "\n".join(lines))]))
            contents.append(types.Content(
                role="model", parts=[types.Part(text="Đã hiểu.")]))

    contents.append(types.Content(
        role="user", parts=[types.Part(text=user_q)]))

    cfg = types.GenerateContentConfig(
        tools=tools,
        system_instruction=sys_msg,
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel.MINIMAL),
    )

    status = None
    for _ in range(3):
        resp = _generate_with_retry(cfg, contents)
        if resp.function_calls:
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in resp.function_calls:
                if fc.name == "query_finance_data":
                    status = "data"
                    res = query_finance_data_tool(
                        field=str(fc.args.get("field", "")),
                        operator=str(fc.args.get("operator", "eq")),
                        value=str(fc.args.get("value", "")),
                        action=str(fc.args.get("action", "list")),
                        allowed_projects=allowed_project_ids,
                    )
                elif fc.name == "query_transactions":
                    status = "transaction"
                    res = query_transactions_tool(
                        project_id=str(fc.args.get("project_id", "")),
                        action=str(fc.args.get("action", "list")),
                        allowed_projects=allowed_project_ids,
                    )
                elif fc.name == "search_knowledge":
                    status = "knowledge"
                    res = search_knowledge_base(str(fc.args.get("query", "")))
                else:
                    res = {"error": "Unknown tool"}
                parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": res}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            return (resp.text or "").strip(), status
    return "Lỗi: AI không phản hồi.", status