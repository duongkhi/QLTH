import json
from google.genai import types
from ai_client import _generate_with_retry
from finance_service import load_finance_data, get_project_metrics


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
def chat_with_finance_ai(user_q, chat_history=None,
                          allowed_project_ids=None):
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
    ])]

    sys_msg = (
        "Bạn là Trợ lý Tài chính AI. Bạn có quyền truy cập dữ liệu báo cáo "
        "tổng hợp và sổ chứng từ chi tiết.\n"
        "Quy tắc:\n"
        "1. Hỏi số liệu tổng hợp (VD: 'Tổng kinh phí của TS. Tiến') → gọi tool "
        "'query_finance_data'.\n"
        "2. Hỏi chi tiết chứng từ (VD: 'Đề tài CT01 có hóa đơn nào?') → gọi "
        "'query_transactions'.\n"
        "3. Định dạng tiền tệ VNĐ. Trả lời ngắn gọn, chính xác."
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

    used_tool = False
    for _ in range(3):
        resp = _generate_with_retry(cfg, contents)
        if resp.function_calls:
            used_tool = True
            contents.append(resp.candidates[0].content)
            parts = []
            for fc in resp.function_calls:
                if fc.name == "query_finance_data":
                    res = query_finance_data_tool(
                        field=str(fc.args.get("field", "")),
                        operator=str(fc.args.get("operator", "eq")),
                        value=str(fc.args.get("value", "")),
                        action=str(fc.args.get("action", "list")),
                        allowed_projects=allowed_project_ids,
                    )
                elif fc.name == "query_transactions":
                    res = query_transactions_tool(
                        project_id=str(fc.args.get("project_id", "")),
                        action=str(fc.args.get("action", "list")),
                        allowed_projects=allowed_project_ids,
                    )
                else:
                    res = {"error": "Unknown tool"}
                parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": res}))
            contents.append(types.Content(role="user", parts=parts))
        else:
            return (resp.text or "").strip(), used_tool
    return "Lỗi: AI không phản hồi.", used_tool