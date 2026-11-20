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
    """Xuất file Excel bảng lương tháng. Gọi khi user muốn tải file."""
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
        "download_token": f"payroll_{month}",
        "_excel_bytes": bio.getvalue(),
    }


def _thong_ke_bai_bao_impl(args, ctx):
    """Thống kê bài báo khoa học theo chuẩn Scopus/ISI (Skill Admin)."""
    from_year = args.get("from_year")
    to_year = args.get("to_year")
    unit = str(args.get("unit", "")).strip().lower()
    person = str(args.get("person", "")).strip().lower()
    export_excel = bool(args.get("export_excel", False))

    load_profile = ctx["load_profile"]
    get_name = ctx["get_name"]
    allowed_profiles = ctx.get("allowed_profiles", [])

    rows = []
    for key in allowed_profiles:
        prof = load_profile(key) or {}
        name = get_name(key)

        if person and person not in str(name).lower():
            continue
        don_vi = str(prof.get("don_vi_cong_tac", "") or prof.get("don_vi", "")).lower()
        if unit and unit not in don_vi:
            continue

        pubs = prof.get("bai_bao_chuan_scopus", [])
        if not isinstance(pubs, list):
            pubs = prof.get("cong_bo", [])
        if not isinstance(pubs, list):
            pubs = prof.get("bai_bao", [])
        if not isinstance(pubs, list):
            pubs = []

        for p in pubs:
            if not isinstance(p, dict):
                continue
            try:
                y = int(p.get("year") or 0)
            except Exception:
                y = 0
            if from_year and y < int(from_year):
                continue
            if to_year and y > int(to_year):
                continue

            rows.append({
                "Ma HS": key,
                "Ho ten": name,
                "Ten bai bao": p.get("title", ""),
                "Tac gia": p.get("authors", ""),
                "Vai tro": p.get("author_role", ""),
                "Tap chi": p.get("source_title", ""),
                "Nam": y,
                "Tap": p.get("volume", ""),
                "So": p.get("issue", ""),
                "Trang": p.get("page_range", ""),
                "DOI": p.get("doi", ""),
                "ISSN": p.get("issn", ""),
                "ISBN": p.get("isbn", ""),
                "Loai chi so": p.get("index_type", ""),
                "Quy": p.get("quartile", ""),
                "Loai bai bao": p.get("document_type", ""),
            })

    total = len(rows)
    isi = sum(1 for r in rows if "ISI" in str(r["Loai chi so"]))
    scopus = sum(1 for r in rows if "Scopus" in str(r["Loai chi so"]))
    trong_nuoc = sum(1 for r in rows if "Trong" in str(r["Loai chi so"]))
    q1 = sum(1 for r in rows if str(r["Quy"]) == "Q1")
    q2 = sum(1 for r in rows if str(r["Quy"]) == "Q2")
    q3 = sum(1 for r in rows if str(r["Quy"]) == "Q3")
    q4 = sum(1 for r in rows if str(r["Quy"]) == "Q4")

    summary = {
        "Tong so": total,
        "ISI/SCIE": isi,
        "Scopus": scopus,
        "Trong nuoc": trong_nuoc,
        "Q1": q1,
        "Q2": q2,
        "Q3": q3,
        "Q4": q4,
    }

    result = {
        "summary": summary,
        "rows": rows,
        "filters": {
            "from_year": from_year,
            "to_year": to_year,
            "unit": unit,
            "person": person,
        },
    }

    if export_excel and rows:
        import pandas as pd
        import io
        df = pd.DataFrame(rows)
        bio = io.BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Bai_bao")
        bio.seek(0)
        result["_excel_bytes"] = bio.getvalue()
        result["download_token"] = f"thong_ke_bai_bao_{from_year or ''}_{to_year or ''}"

    return result


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
    "thong_ke_bai_bao_khoa_hoc": {
        "func": _thong_ke_bai_bao_impl,
        "schema": types.FunctionDeclaration(
            name="thong_ke_bai_bao_khoa_hoc",
            description=(
                "Thống kê bài báo khoa học theo chuẩn Scopus/ISI. "
                "Hỗ trợ lọc theo khoảng năm, đơn vị/tập thể và cá nhân. "
                "Trả về bảng chi tiết và tổng hợp theo phân loại. "
                "Dùng khi user hỏi về thống kê công bố khoa học."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "from_year": types.Schema(
                        type=types.Type.INTEGER,
                        description="Năm bắt đầu (ví dụ 2020), để trống nếu không giới hạn.",
                    ),
                    "to_year": types.Schema(
                        type=types.Type.INTEGER,
                        description="Năm kết thúc (ví dụ 2025), để trống nếu không giới hạn.",
                    ),
                    "unit": types.Schema(
                        type=types.Type.STRING,
                        description="Tên đơn vị/tập thể (ví dụ 'Trung tâm Điện tử Lượng tử'), để trống nếu không lọc.",
                    ),
                    "person": types.Schema(
                        type=types.Type.STRING,
                        description="Tên cá nhân, để trống nếu không lọc.",
                    ),
                    "export_excel": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="Có xuất file Excel kèm theo hay không.",
                    ),
                },
                required=[],
            ),
        ),
    },
}