# finance_agent.py
import json
from google.genai import types
from ai_client import _generate_with_retry
from finance_service import load_finance_data, get_project_metrics
from supabase_adapter import get_ai_settings, load_json_from_db, list_keys_with_prefix, load_many
import unicodedata

# =============================================================
# KNOWLEDGE BASE
# =============================================================
def _strip_vn(s: str) -> str:
    s = str(s).replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()

def search_knowledge_base(query, module="finance"):
    if module == "admin":
        manual_key = "admin_rules"
        prefix = "kb_admin_"
    else:
        manual_key = "finance_rules"
        prefix = "kb_finance_"
    
    kb_keys = list_keys_with_prefix(prefix)
    if manual_key not in kb_keys:
        kb_keys.append(manual_key)
    
    all_data = load_many(kb_keys)
    all_rules = []
    
    for key, data in all_data.items():
        if not data: continue
        if "content" in data and data["content"]:
            all_rules.append({"dieu_khoan": data.get("document_name", "Quy định chung"), "noi_dung": data["content"], "muc_chi": None, "doi_tuong": None, "tu_khoa": [], "_source": "Quy định nhập tay"})
        if "rules" in data and isinstance(data["rules"], list):
            for r in data["rules"]:
                r["_source"] = data.get("document_name", key)
                all_rules.append(r)
    
    if not all_rules:
        return "Hệ thống chưa có tri thức nền cho phân hệ này."
    
    query_clean = _strip_vn(query)
    query_words = [w for w in query_clean.split() if len(w) > 1]
    
    scored = []
    for rule in all_rules:
        search_text = (
            _strip_vn(rule.get("noi_dung", "")) + " " +
            _strip_vn(rule.get("dieu_khoan", "")) + " " +
            _strip_vn(rule.get("_source", "")) + " " +
            " ".join([_strip_vn(k) for k in rule.get("tu_khoa", [])])
        )
        score = sum(1 for w in query_words if w in search_text)
        for w in query_words:
            if w.isdigit() and w in search_text: score += 5
        if score > 0: scored.append((score, rule))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    top_results = [r[1] for r in scored[:5]]
    
    if not top_results:
        top_results = all_rules[:5]
        note = "(Lưu ý: Không tìm thấy từ khóa trực tiếp, dưới đây là 5 quy định đầu tiên trong tài liệu để tham khảo)\n\n"
    else:
        note = ""

    output = note + "Các quy định trích xuất từ tài liệu:\n\n"
    for r in top_results:
        src = f" (Nguồn: {r['_source']})" if r.get("_source") else ""
        output += f"- **{r.get('dieu_khoan', '')}**{src}\n"
        output += f"  {r.get('noi_dung', '')[:500]}\n"
        if r.get("muc_chi"): output += f"  • Mức chi: {r['muc_chi']}\n"
        output += "\n"
    
    return output

# =============================================================
# TOOLS
# =============================================================
def query_finance_data_tool(field, operator, value, action, allowed_projects=None):
    projects, disbursements, _ = load_finance_data()
    results = []

    for pid, p in projects.items():
        if allowed_projects is not None and pid not in allowed_projects:
            continue

        d = disbursements.get(pid, {})
        m = get_project_metrics(pid, p, d)
        flat = {**p, **m, **d, "project_id": pid}

        # SỬA LỖI: Xử lý trường hợp lấy toàn bộ (all) hoặc không có field
        if operator == "all" or not field or field == "all":
            match = True
        else:
            val = flat.get(field, "")
            match = False
            if operator == "eq" and str(val).lower() == str(value).lower(): match = True
            elif operator == "contains" and str(value).lower() in str(val).lower(): match = True
            elif operator == "gt":
                try: match = float(val or 0) > float(value)
                except: pass
            elif operator == "lt":
                try: match = float(val or 0) < float(value)
                except: pass

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
            return {"total_sum": sum(float(r.get(field) or 0) for r in results), "count": len(results)}
        return {"count": len(results)}

    if action == "count":
        return {"count": len(results)}

    return results


def query_transactions_tool(project_id="", action="list", allowed_projects=None):
    _, _, transactions = load_finance_data()
    res = []
    for tx in transactions:
        if allowed_projects is not None and tx.get("project_id") not in allowed_projects:
            continue
        if project_id and project_id not in tx.get("project_id", ""):
            continue
        res.append(tx)

    if action == "sum":
        return {"total_sum": sum(t.get("amount", 0) for t in res), "count": len(res)}
    if action == "count":
        return {"count": len(res)}
    return res


# =============================================================
# CHAT
# =============================================================
def chat_with_finance_ai(user_q, chat_history=None, allowed_project_ids=None):
    ai_cfg = get_ai_settings()
    db_prompt = ai_cfg.get("chat_system_prompt", "")

    # Khai báo Tools (Đã nới lỏng required)
    func_declarations = [
        types.FunctionDeclaration(
            name="query_finance_data",
            description="Truy vấn danh sách đề tài, số liệu kinh phí, giải ngân. Hỗ trợ lấy toàn bộ danh sách hoặc lọc.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "field": types.Schema(type=types.Type.STRING, description="Trường cần lọc: 'pi', 'group', 'actual_budget'. Để trống nếu lấy toàn bộ."),
                    "operator": types.Schema(type=types.Type.STRING, enum=["eq", "contains", "gt", "lt", "all"], description="Dùng 'all' nếu muốn lấy toàn bộ danh sách."),
                    "value": types.Schema(type=types.Type.STRING, description="Giá trị lọc (VD: 'Phạm Hồng Minh'). Để trống nếu lấy toàn bộ."),
                    "action": types.Schema(type=types.Type.STRING, enum=["list", "sum", "count"], description="Hành động: 'list', 'sum', 'count'."),
                },
                required=["action"], # Chỉ bắt buộc action
            ),
        ),
        types.FunctionDeclaration(
            name="query_transactions",
            description="Truy vấn sổ chứng từ chi tiết.",
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
            description="Tìm kiếm quy chế, định mức chi tiêu NỘI BỘ.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(type=types.Type.STRING)},
                required=["query"],
            ),
        ),
    ]

    tools = [types.Tool(function_declarations=func_declarations)]

    sys_msg = (
        f"{db_prompt}\n"
        "Bạn là Trợ lý Tài chính AI. Bạn được cung cấp dữ liệu nội bộ và kiến thức pháp luật chung.\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Hỏi số liệu đề tài -> gọi 'query_finance_data'.\n"
        "2. Hỏi danh sách toàn bộ đề tài -> gọi 'query_finance_data' với operator='all', action='list'.\n"
        "3. Hỏi chứng từ -> gọi 'query_transactions'.\n"
        "4. Hỏi về quy định, định mức -> ĐẦU TIÊN phải gọi 'search_knowledge'.\n"
        "5. Nếu không tìm thấy trong nội bộ, HÃY DÙNG KIẾN THỨC CỦA BẠN để trả lời.\n"
        "6. Định dạng tiền tệ VNĐ. Trả lời ngắn gọn, chính xác."
    )

    if allowed_project_ids is not None:
        sys_msg += f"\n⚠️ QUAN TRỌNG: User chỉ được xem {len(allowed_project_ids)} đề tài. Nếu hỏi đề tài khác, báo không có quyền."

    contents = []
    if chat_history:
        recent = chat_history[-6:]
        lines = [f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in recent]
        if lines:
            contents.append(types.Content(role="user", parts=[types.Part(text="Lịch sử:\n" + "\n".join(lines))]))
            contents.append(types.Content(role="model", parts=[types.Part(text="Đã hiểu.")]))

    contents.append(types.Content(role="user", parts=[types.Part(text=user_q)]))

    cfg = types.GenerateContentConfig(
        tools=tools,
        system_instruction=sys_msg,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)
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
                        operator=str(fc.args.get("operator", "all")),
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
                parts.append(types.Part.from_function_response(name=fc.name, response={"result": res}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            return (resp.text or "").strip(), status
            
    return "Lỗi: AI không phản hồi.", status