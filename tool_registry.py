# tools_registry.py
from google.genai import types
import json

def _calc_salary_impl(args, ctx):
    """Tính lương một nhân sự cho 1 tháng. Math 100% bằng Python."""
    profile_key = args["profile_key"]
    month = args["month"]  # "2024-11"
    
    profile = ctx["load_profile"](profile_key)
    if not profile:
        return {"error": f"Không có hồ sơ '{profile_key}'"}
    
    base = float(profile.get("luong_co_ban", 0))
    days = float(profile.get("ngay_cong", 0))
    allowance = float(profile.get("phu_cap", 0))
    insurance_rate = 0.105  # BHXH+BHYT+BHTN
    tax_threshold = 11_000_000
    
    gross = (base / 26) * days + allowance
    insurance = gross * insurance_rate
    taxable = max(0, gross - insurance - tax_threshold)
    tax = taxable * 0.05  # giả định 5% bậc 1
    net = gross - insurance - tax
    
    return {
        "profile_key": profile_key,
        "month": month,
        "gross": round(gross),
        "insurance": round(insurance),
        "tax": round(tax),
        "net": round(net),
        "breakdown": {
            "base": base, "days": days, "allowance": allowance,
        },
    }

def _aggregate_payroll_impl(args, ctx):
    """Tổng lương toàn bộ nhân sự trong 1 tháng."""
    month = args["month"]
    total_gross = total_net = 0
    details = []
    for key in ctx["allowed_profiles"]:
        r = _calc_salary_impl({"profile_key": key, "month": month}, ctx)
        if "error" in r:
            continue
        total_gross += r["gross"]
        total_net += r["net"]
        details.append({"name": ctx["get_name"](key), "net": r["net"]})
    return {
        "month": month,
        "total_gross": total_gross,
        "total_net": total_net,
        "count": len(details),
        "top5": sorted(details, key=lambda x: x["net"], reverse=True)[:5],
    }

def _extract_cumulative_impl(args, ctx):
    """Lũy kế chi phí đề tài theo năm."""
    project_key = args["project_key"]
    year = int(args["year"])
    data = ctx["load_profile"](project_key) or {}
    ledger = data.get("chi_tieu", [])  # list [{date, amount, note}]
    total = 0
    monthly = {m: 0 for m in range(1, 13)}
    for entry in ledger:
        if str(year) in entry.get("date", ""):
            total += float(entry.get("amount", 0))
            try:
                m = int(entry["date"].split("/")[1])
                monthly[m] += float(entry["amount"])
            except Exception:
                pass
    return {
        "project_key": project_key,
        "year": year,
        "total": total,
        "monthly_breakdown": monthly,
    }

def _export_payroll_excel_impl(args, ctx):
    """Xuất Excel bảng lương tháng. Dùng openpyxl/pandas."""
    import pandas as pd
    import io
    from supabase_adapter import load_json_from_db
    
    month = args["month"]
    rows = []
    for key in ctx["allowed_profiles"]:
        r = _calc_salary_impl({"profile_key": key, "month": month}, ctx)
        if "error" in r:
            continue
        rows.append({
            "Mã NV": key,
            "Họ tên": ctx["get_name"](key),
            "Lương gộp": r["gross"],
            "Bảo hiểm": r["insurance"],
            "Thuế": r["tax"],
            "Thực lĩnh": r["net"],
        })
    df = pd.DataFrame(rows)
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=f"Luong_{month}")
    bio.seek(0)
    return {
        "status": "ready",
        "download_token": f"payroll_{month}",  # Lưu vào session_state để download
        "_excel_bytes": bio.getvalue(),  # caller sẽ pop và lưu
    }


# ============ SCHEMAS cho AI ============
TOOL_REGISTRY = {
    "calculate_salary": {
        "func": _calc_salary_impl,
        "schema": types.FunctionDeclaration(
            name="calculate_salary",
            description=(
                "Tính lương chi tiết 1 nhân sự cho 1 tháng. "
                "Trả về gross, bảo hiểm, thuế, thực lĩnh. "
                "BẮT BUỘC dùng khi user hỏi về lương của ai đó."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "profile_key": types.Schema(type=types.Type.STRING,
                                                 description="Mã nhân sự (vd 'NguyenVanA')"),
                    "month": types.Schema(type=types.Type.STRING,
                                          description="Tháng dạng YYYY-MM (vd '2024-11')"),
                },
                required=["profile_key", "month"],
            ),
        ),
    },
    "aggregate_payroll": {
        "func": _aggregate_payroll_impl,
        "schema": types.FunctionDeclaration(
            name="aggregate_payroll",
            description="Tổng hợp lương toàn bộ nhân sự trong 1 tháng.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"month": types.Schema(type=types.Type.STRING)},
                required=["month"],
            ),
        ),
    },
    "extract_cumulative": {
        "func": _extract_cumulative_impl,
        "schema": types.FunctionDeclaration(
            name="extract_cumulative",
            description="Tính lũy kế chi tiêu của đề tài theo năm.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "project_key": types.Schema(type=types.Type.STRING),
                    "year": types.Schema(type=types.Type.INTEGER),
                },
                required=["project_key", "year"],
            ),
        ),
    },
    "export_payroll_excel": {
        "func": _export_payroll_excel_impl,
        "schema": types.FunctionDeclaration(
            name="export_payroll_excel",
            description="Xuất file Excel bảng lương tháng. Gọi khi user muốn tải file.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"month": types.Schema(type=types.Type.STRING)},
                required=["month"],
            ),
        ),
    },
}