import io
import time
from datetime import datetime
import pandas as pd

from storage import load_json_from_db, save_json_to_db

KEY_PROJECTS = "finance_projects"
KEY_DISBURSEMENTS = "finance_disbursements"
KEY_TRANSACTIONS = "finance_transactions"

FILE_NAME_REQUIRED = "danh sách đề tài đang thực hiện iop.xlsx"

EDITABLE_FIELDS = {
    "name", "pi", "group", "task_type", "unit", "duration",
    "total_budget", "allocated_budget", "actual_budget",
}


# =============================================================
# CRUD CƠ BẢN
# =============================================================
def load_finance_data():
    projects = load_json_from_db(KEY_PROJECTS) or {}
    disbursements = load_json_from_db(KEY_DISBURSEMENTS) or {}
    transactions = load_json_from_db(KEY_TRANSACTIONS) or []
    return projects, disbursements, transactions


def save_finance_data(projects=None, disbursements=None, transactions=None):
    if projects is not None:
        save_json_to_db(KEY_PROJECTS, projects)
    if disbursements is not None:
        save_json_to_db(KEY_DISBURSEMENTS, disbursements)
    if transactions is not None:
        save_json_to_db(KEY_TRANSACTIONS, transactions)


def format_currency(amount):
    if not amount:
        return "0 đ"
    return f"{amount:,.0f} đ".replace(",", ".")


def get_project_metrics(pid, project, disb):
    total_budget = project.get("total_budget", 0)
    actual_budget = project.get("actual_budget", 0)
    cum_dict = disb.get("cumulative", {})
    current_cum = max(cum_dict.values()) if cum_dict else disb.get("settled_before_2025", 0)
    rate = (current_cum / actual_budget * 100) if actual_budget > 0 else 0
    return {
        "total_budget": total_budget,
        "actual_budget": actual_budget,
        "current_cum": current_cum,
        "rate": rate,
    }


# =============================================================
# PARSE HELPERS (dùng khi import Excel)
# =============================================================
def _parse_currency(val):
    if pd.isna(val):
        return 0
    if isinstance(val, (int, float)):
        try:
            return int(val)
        except Exception:
            return 0
    s = str(val).replace(",", "").replace(".", "").replace(" ", "").strip()
    if not s or s.startswith("=") or s.lower() == "nan":
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def _format_date(val):
    if pd.isna(val):
        return ""
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return ""
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(s, fmt).strftime("%d/%m/%Y")
            except Exception:
                pass
        return s
    try:
        return val.strftime("%d/%m/%Y")
    except Exception:
        return str(val).strip()


def _find_col(df, *kws):
    for col in df.columns:
        c = str(col).lower()
        for kw in kws:
            if kw.lower() in c:
                return col
    return None


def _read_sheet(xls, sheet_name):
    for h in range(0, 6):
        try:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=h)
            df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]
            if len(df) > 0 and len(df.columns) > 3:
                return df
        except Exception:
            continue
    return None


# =============================================================
# IMPORT EXCEL (GHI ĐÈ)
# =============================================================
def validate_and_import_excel(file_bytes, filename):
    if filename.strip().lower() != FILE_NAME_REQUIRED:
        return False, "Tên file không đúng! Yêu cầu: 'Danh sách đề tài đang thực hiện IOP.xlsx'"

    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
    except Exception as e:
        return False, f"Không đọc được file Excel: {e}"

    if "Danh muc de tai" not in xls.sheet_names:
        return False, "Thiếu sheet 'Danh muc de tai'."
    if "Giai ngan 2026" not in xls.sheet_names:
        return False, "Thiếu sheet 'Giai ngan 2026'."

    try:
        df_dm = _read_sheet(xls, "Danh muc de tai")
        df_gn = _read_sheet(xls, "Giai ngan 2026")
        if df_dm is None:
            return False, "Không đọc được sheet 'Danh muc de tai'."
        if df_gn is None:
            return False, "Không đọc được sheet 'Giai ngan 2026'."

        col_pid = _find_col(df_dm, "ma de tai")
        if not col_pid:
            return False, "Sheet 'Danh muc de tai' không có cột 'Ma de tai'."

        c_name   = _find_col(df_dm, "ten de tai")
        c_pi     = _find_col(df_dm, "chu nhiem")
        c_group  = _find_col(df_dm, "nhom")
        c_task   = _find_col(df_dm, "loai nhiem vu")
        c_unit   = _find_col(df_dm, "don vi")
        c_dur    = _find_col(df_dm, "thoi gian")
        c_total  = _find_col(df_dm, "tong kinh phi de tai")
        c_alloc  = _find_col(df_dm, "giao du toan")
        c_actual = _find_col(df_dm, "su dung thuc te")

        cum_cols = {}
        for m in range(1, 13):
            cum_cols[m] = _find_col(df_gn, f"luy ke kinh phi giai ngan den het thang {m} ")

        c_before  = _find_col(df_gn, "kinh phi da giai ngan den het thang 12/2025")
        c_saving  = _find_col(df_gn, "kinh phi tiet kiem nam 2026")
        c_settled = _find_col(df_gn, "kinh phi quyet toan tu thang 1/2026")
        c_date    = _find_col(df_gn, "ngay cap nhat quyet toan")

        projects = {}
        disbursements = {}

        for i, (_, row) in enumerate(df_dm.iterrows()):
            pid_raw = row.get(col_pid)
            if pd.isna(pid_raw):
                continue
            pid = str(pid_raw).strip()
            if not pid or pid.startswith("="):
                continue

            row_gn = df_gn.iloc[i] if i < len(df_gn) else pd.Series(dtype=object)

            projects[pid] = {
                "id": pid,
                "group": str(row.get(c_group, "") or "").strip() if c_group else "",
                "task_type": str(row.get(c_task, "") or "").strip() if c_task else "",
                "name": str(row.get(c_name, "") or "").strip() if c_name else "",
                "pi": str(row.get(c_pi, "") or "").strip() if c_pi else "",
                "unit": str(row.get(c_unit, "") or "").strip() if c_unit else "Viện Vật lý",
                "duration": str(row.get(c_dur, "") or "").strip() if c_dur else "",
                "total_budget": _parse_currency(row.get(c_total)) if c_total else 0,
                "allocated_budget": _parse_currency(row.get(c_alloc)) if c_alloc else 0,
                "actual_budget": _parse_currency(row.get(c_actual)) if c_actual else 0,
            }

            cumulative = {}
            for m in range(1, 13):
                col = cum_cols.get(m)
                if col:
                    cumulative[str(m)] = _parse_currency(row_gn.get(col))

            disbursements[pid] = {
                "settled_before_2025": _parse_currency(row_gn.get(c_before)) if c_before else 0,
                "saving_2026": _parse_currency(row_gn.get(c_saving)) if c_saving else 0,
                "cumulative": cumulative,
                "settled_2026": _parse_currency(row_gn.get(c_settled)) if c_settled else 0,
                "last_settlement_date": _format_date(row_gn.get(c_date)) if c_date else "",
            }

        if not projects:
            return False, "Không tìm thấy đề tài nào trong file Excel."

        save_finance_data(projects=projects, disbursements=disbursements)
        return True, f"✅ Đã ghi đè thành công {len(projects)} đề tài!"

    except Exception as e:
        return False, f"Lỗi xử lý file: {e}"


# =============================================================
# CRUD ĐỀ TÀI
# =============================================================
def add_single_project(pid, name, pi, group, budget):
    projects, disbs, _ = load_finance_data()
    if pid in projects:
        return False, "Mã đề tài đã tồn tại."
    projects[pid] = {
        "id": pid, "name": name, "pi": pi, "group": group,
        "actual_budget": budget, "total_budget": budget, "allocated_budget": 0,
        "duration": "", "task_type": "", "unit": "Viện Vật lý",
    }
    disbs[pid] = {
        "settled_before_2025": 0, "saving_2026": 0,
        "cumulative": {}, "settled_2026": 0, "last_settlement_date": "",
    }
    save_finance_data(projects=projects, disbursements=disbs)
    return True, "Đã thêm đề tài."


def delete_single_project(pid):
    projects, disbs, _ = load_finance_data()
    if pid in projects:
        del projects[pid]
        if pid in disbs:
            del disbs[pid]
        save_finance_data(projects=projects, disbursements=disbs)
        return True
    return False


def update_single_project(pid, patch: dict):
    """
    Cập nhật 1 đề tài với dict patch.
    Chỉ các field trong EDITABLE_FIELDS được áp dụng.
    Trả về (ok, msg).
    """
    projects, disbs, _ = load_finance_data()
    if pid not in projects:
        return False, "Không tìm thấy đề tài."

    changed = False
    for k in EDITABLE_FIELDS:
        if k not in patch:
            continue
        v = patch[k]
        if k in ("total_budget", "allocated_budget", "actual_budget"):
            try:
                v = int(v) if v not in (None, "") else 0
            except Exception:
                v = 0
        else:
            v = str(v or "").strip()

        if projects[pid].get(k) != v:
            projects[pid][k] = v
            changed = True

    if changed:
        save_finance_data(projects=projects, disbursements=disbs)
        return True, "✅ Đã cập nhật đề tài."
    return True, "ℹ️ Không có thay đổi nào."


# =============================================================
# CRUD CHỨNG TỪ
# =============================================================
def add_transaction(tx_data):
    _, _, transactions = load_finance_data()
    tx_data["id"] = f"TX_{int(time.time())}"
    transactions.append(tx_data)
    save_finance_data(transactions=transactions)
    return True, "Đã lưu chứng từ."


def delete_transaction(tx_id):
    _, _, transactions = load_finance_data()
    new_txs = [tx for tx in transactions if tx["id"] != tx_id]
    save_finance_data(transactions=new_txs)
    return True


def get_transactions_by_project(project_id):
    _, _, transactions = load_finance_data()
    if not project_id:
        return transactions
    return [tx for tx in transactions if tx["project_id"] == project_id]