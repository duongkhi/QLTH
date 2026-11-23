# journal_service.py
# Dịch vụ quản lý danh mục chất lượng bài báo (Scopus/ISI/Trong nước)
# Lưu trên Supabase bảng app_data dưới key "journal_quality_catalog".

import json
import re
import io
import csv
import streamlit as st
import pandas as pd

from supabase_adapter import load_json_from_db, save_json_to_db, list_all_keys, delete_key_from_db

CATALOG_KEY_PREFIX = "journal_quality_catalog_"
CATALOG_META_KEY = "journal_quality_catalog_Scinago_2025_index"
BATCH_SIZE = 3000


# 12 trường chuẩn Scopus cho mỗi bài báo
PUBLICATION_STD_FIELDS = [
    "title", "authors", "author_role", "source_title", "year",
    "volume", "issue", "page_range", "doi", "issn", "isbn",
    "index_type", "quartile", "document_type",
]

INDEX_TYPES = ["ISI", "SCIE", "Scopus", "Trong nước"]
QUARTILES = ["Q1", "Q2", "Q3", "Q4", None]
DOCUMENT_TYPES = [
    "Bài báo khoa học", "Bài-review", "Tạp chí", "Hội nghị",
    "Đề tài", "Sách", "Chương sách", "Khác",
]


# ============================================================
# CRUD kho danh mục chất lượng
# ============================================================
def _load_all_catalog_batches() -> dict:
    """Tải toàn bộ catalog từ các key sharded trên Supabase và gộp lại."""
    meta = load_json_from_db(CATALOG_META_KEY) or {}
    batch_keys = meta.get("batch_keys", [])

    # Nếu chưa có meta, tự quét các key có tiền tố
    if not batch_keys:
        all_keys = list_all_keys()
        batch_keys = sorted([k for k in all_keys if k.startswith(CATALOG_KEY_PREFIX)])

    merged = {}
    for bk in batch_keys:
        data = load_json_from_db(bk) or {}
        merged.update(data)
    return merged


def load_journal_catalog() -> dict:
    """Tải toàn bộ kho danh mục từ Supabase. Trả về {ma_duoc_tao_tu_doi_hoac_issn: entry}."""
    return _load_all_catalog_batches() or {}


def save_journal_catalog(catalog: dict) -> bool:
    """Lưu toàn bộ kho danh mục lên Supabase (chia thành các batch)."""
    import math

    # Xóa các batch cũ
    old_keys = [k for k in list_all_keys() if k.startswith(CATALOG_KEY_PREFIX)]
    for k in old_keys:
        delete_key_from_db(k)

    items = list(catalog.items())
    total_batches = math.ceil(len(items) / BATCH_SIZE)
    batch_keys = []

    for i in range(0, len(items), BATCH_SIZE):
        batch = dict(items[i:i + BATCH_SIZE])
        batch_idx = i // BATCH_SIZE + 1
        key = f"{CATALOG_KEY_PREFIX}{batch_idx:02d}"
        ok = save_json_to_db(key, batch)
        if not ok:
            return False
        batch_keys.append(key)

    # Lưu meta key
    meta_ok = save_json_to_db(CATALOG_META_KEY, {
        "batch_keys": batch_keys,
        "total": len(items),
    })
    return bool(meta_ok)


def list_journals() -> list[dict]:
    """Trả về danh sách các mục danh mục (mỗi phần tử là dict kèm key '_id')."""
    cat = load_journal_catalog()
    return [{**v, "_id": k} for k, v in cat.items()]


def _norm(s) -> str:
    """Chuẩn hóa chuỗi so sánh: lowercase, bỏ khoảng trắng thừa, bỏ dấu câu phổ biến."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[\s\.]+", " ", s)
    return s


def _match_key(entry: dict) -> str | None:
    """
    Tạo khóa khớp ưu tiên: doi -> issn/isbn -> journal_name (chuẩn hóa).
    Trả về None nếu không có đủ thông tin để khớp.
    """
    doi = _norm(entry.get("doi"))
    issn = _norm(entry.get("issn"))
    isbn = _norm(entry.get("isbn"))
    name = _norm(entry.get("journal_name"))

    if doi:
        return f"doi:{doi}"
    if issn:
        return f"issn:{issn}"
    if isbn:
        return f"isbn:{isbn}"
    if name:
        return f"name:{name}"
    return None


def upsert_journal_catalog(entries: list[dict]) -> tuple[int, int]:
    """
    Upsert nhiều mục vào kho danh mục.
    So sánh trùng theo ưu tiên doi -> issn/isbn -> journal_name (chuẩn hóa lowercase).
    Trả về (so_moi_them, so_cap_nhat).
    """
    cat = load_journal_catalog()
    add_cnt = 0
    upd_cnt = 0

    for entry in entries:
        key = _match_key(entry)
        if not key:
            # Không thể xác định khóa duy nhất -> thêm mới với key tự sinh
            key = f"auto_{len(cat) + add_cnt + upd_cnt}"
        if key in cat:
            cat[key].update(entry)
            cat[key]["_id"] = key
            upd_cnt += 1
        else:
            cat[key] = {**entry, "_id": key}
            add_cnt += 1

    ok = save_journal_catalog(cat)
    if not ok:
        return 0, 0
    return add_cnt, upd_cnt


def delete_journal(entry_id: str) -> bool:
    """Xóa một mục khỏi kho danh mục theo _id."""
    cat = load_journal_catalog()
    if entry_id not in cat:
        return False
    del cat[entry_id]
    return save_journal_catalog(cat)


def search_journal_by_doi_issn(doi: str = "", issn: str = "", isbn: str = "", name: str = "") -> dict | None:
    """
    Tìm một mục trong kho theo doi/issn/isbn/name. Trả về entry hoặc None.
    """
    cat = load_journal_catalog()
    doi = _norm(doi)
    issn = _norm(issn)
    isbn = _norm(isbn)
    name = _norm(name)

    for key, entry in cat.items():
        if doi and _norm(entry.get("doi")) == doi:
            return entry
        if issn and _norm(entry.get("issn")) == issn:
            return entry
        if isbn and _norm(entry.get("isbn")) == isbn:
            return entry
        if name and _norm(entry.get("journal_name")) == name:
            return entry
    return None


# ============================================================
# Đọc file upload (.csv, .xlsx, .docx)
# ============================================================
def read_uploaded_file(uploaded) -> pd.DataFrame:
    """
    Đọc file upload (.csv, .xlsx, .docx) thành DataFrame.
    Các cột chuẩn: journal_name, issn, isbn, doi, index_type, quartile, year.
    """
    name = uploaded.name.lower()
    raw = uploaded.getvalue()

    if name.endswith(".csv"):
        # Tự động phát hiện dấu phân cách phù hợp cho từng file CSV
        # (ScimagoJR dùng ';', file CSV thường dùng ',', ...)
        best_df = None
        best_sep = None
        best_score = -1
        for sep in [";", ",", "\t", "|"]:
            try:
                trial = pd.read_csv(
                    io.BytesIO(raw), dtype=str, sep=sep, engine="python",
                    on_bad_lines="skip",
                ).fillna("")
                # Chọn delimiter tạo ra nhiều cột nhất và ổn định nhất
                n_cols = trial.shape[1]
                # Điểm ưu tiên: nhiều cột, và ít dòng có số cột khác nhau hơn
                n_rows = trial.shape[0]
                inconsistent = sum(
                    1
                    for _, row in trial.iterrows()
                    if sum(1 for v in row if str(v).strip() != "") != n_cols
                )
                score = n_cols * 1000 - inconsistent
                if score > best_score:
                    best_score = score
                    best_sep = sep
                    best_df = trial
            except Exception:
                continue
        if best_df is not None:
            df = best_df
        else:
            # Fallback cuối cùng
            df = pd.read_csv(
                io.BytesIO(raw), dtype=str, sep=",", engine="python",
                on_bad_lines="skip",
            ).fillna("")
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw), dtype=str).fillna("")
    elif name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(raw))
        rows = []
        for tbl in doc.tables:
            header = [c.text.strip() for c in tbl.rows[0].cells]
            for row in tbl.rows[1:]:
                vals = [c.text.strip() for c in row.cells]
                rows.append(dict(zip(header, vals)))
        df = pd.DataFrame(rows)
    else:
        raise ValueError("Định dạng file không hỗ trợ (.csv, .xlsx, .docx)")

    # Chuẩn hóa tên cột về lowercase, bỏ khoảng trắng
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # Map các tên cột phổ biến về chuẩn
    col_map = {
        "tạp_chí": "journal_name", "ten_tap_chi": "journal_name", "journal": "journal_name",
        "journal_name": "journal_name", "title": "journal_name",
        "issn": "issn", "isbn": "isbn",
        "doi": "doi", "loai_chỉ_số": "index_type", "index_type": "index_type",
        "chi_so": "index_type", "type": "index_type",
        "quý": "quartile", "quartile": "quartile", "sjr_best_quartile": "quartile",
        "q": "quartile", "nam": "year", "year": "year", "publish_year": "year",
        "coverage": "year",
    }
    df = df.rename(columns=col_map)

    # Đảm bảo có đủ các cột chuẩn
    for c in ["journal_name", "issn", "isbn", "doi", "index_type", "quartile", "year"]:
        if c not in df.columns:
            df[c] = ""

    return df[["journal_name", "issn", "isbn", "doi", "index_type", "quartile", "year"]]


# ============================================================
# Crossref API (bù đắp thiếu DOI/ISSN/Tên tạp chí)
# ============================================================
def query_crossref(title: str) -> dict | None:
    """
    Gọi Crossref API (https://api.crossref.org/works) theo tên bài báo.
    Trả về dict các trường chuẩn hoặc None nếu không tìm thấy / lỗi mạng.
    """
    if not title or not title.strip():
        return None
    try:
        import urllib.request
        import urllib.parse
        import json as _json

        url = "https://api.crossref.org/works?" + urllib.parse.urlencode({
            "query.title": title.strip(),
            "rows": 1,
            "select": "DOI,ISSN,ISBN,container-title,title,author,published,volume,issue,page,type",
        })
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "HermesScopusCatalog/1.0 (mailto:admin@example.com)"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        items = data.get("message", {}).get("items", [])
        if not items:
            return None
        item = items[0]

        def first_str(lst):
            if isinstance(lst, list) and lst:
                return str(lst[0])
            return str(lst) if lst else ""

        authors = item.get("author", [])
        author_list = []
        for a in authors:
            given = a.get("given", "")
            family = a.get("family", "")
            author_list.append(f"{given} {family}".strip())
        published = item.get("published", {})
        date_parts = published.get("date-parts", [[None]])[0]
        year = str(date_parts[0]) if date_parts and date_parts[0] else ""

        container = item.get("container-title", [])
        source = first_str(container)

        return {
            "title": first_str(item.get("title")),
            "authors": "; ".join(author_list),
            "source_title": source,
            "year": year,
            "volume": first_str(item.get("volume")),
            "issue": first_str(item.get("issue")),
            "page_range": first_str(item.get("page")),
            "doi": first_str(item.get("DOI")),
            "issn": first_str(item.get("ISSN")),
            "isbn": first_str(item.get("ISBN")),
            "index_type": "",  # Crossref không nói rõ ISI/Scopus -> để trống, user/admin bổ sung
            "quartile": "",    # để trống
            "document_type": first_str(item.get("type")),
        }
    except Exception:
        return None


# ============================================================
# Chuẩn hóa danh sách bài báo theo 12 trường Scopus
# ============================================================
def normalize_publication(item: dict, catalog: dict) -> dict:
    """
    Chuẩn hóa 1 bài báo về 12 trường Scopus.
    - Đối chiếu với catalog theo doi/issn/isbn/name.
    - Nếu thiếu doi/issn/tên tạp chí, gọi Crossref để bù đắp.
    """
    out = {f: "" for f in PUBLICATION_STD_FIELDS}

    # Sao chép trường có sẵn (chấp nhận tên tiếng Việt phổ biến)
    field_alias = {
        "ten_bai_bao": "title", "title": "title", "ten": "title",
        "tac_gia": "authors", "authors": "authors", "tác_giả": "authors",
        "vai_tro": "author_role", "author_role": "author_role",
        "tap_chi": "source_title", "source_title": "source_title",
        "noi_cong_bo": "source_title", "ten_tap_chi": "source_title",
        "nam": "year", "year": "year",
        "volume": "volume", "so_tap": "volume",
        "issue": "issue", "so": "issue",
        "page_range": "page_range", "trang": "page_range",
        "doi": "doi", "issn": "issn", "isbn": "isbn",
        "index_type": "index_type", "loai_chi_so": "index_type",
        "quartile": "quartile", "quý": "quartile",
        "document_type": "document_type", "loai_bai_bao": "document_type",
    }

    for k, v in item.items():
        kk = str(k).strip().lower().replace(" ", "_")
        if kk in field_alias:
            std = field_alias[kk]
            if v and str(v).strip():
                out[std] = str(v).strip()

    # Chuẩn hóa index_type và quartile
    it = out["index_type"].strip().lower()
    if "isi" in it or "sci" in it or "scie" in it:
        out["index_type"] = "ISI/SCIE"
    elif "scopus" in it:
        out["index_type"] = "Scopus"
    elif "trong nước" in it or "trong nuoc" in it or "nội địa" in it:
        out["index_type"] = "Trong nước"
    else:
        out["index_type"] = out["index_type"] or ""

    q = out["quartile"].strip().upper()
    if q in ("Q1", "Q2", "Q3", "Q4"):
        out["quartile"] = q
    else:
        out["quartile"] = ""

    # Đối chiếu catalog nếu thiếu thông tin quan trọng
    matched = None
    if out.get("doi"):
        matched = search_journal_by_doi_issn(doi=out["doi"])
    if not matched and out.get("issn"):
        matched = search_journal_by_doi_issn(issn=out["issn"])
    if not matched and out.get("isbn"):
        matched = search_journal_by_doi_issn(isbn=out["isbn"])
    if not matched and out.get("source_title"):
        matched = search_journal_by_doi_issn(name=out["source_title"])

    if matched:
        for f in PUBLICATION_STD_FIELDS:
            if not out[f] and matched.get(f):
                out[f] = matched[f]

    # Nếu vẫn thiếu DOI/ISSN/Tên tạp chí -> gọi Crossref
    need_crossref = (
        (not out.get("doi") or not out.get("issn")) and out.get("title")
    )
    if need_crossref:
        cross = query_crossref(out["title"])
        if cross:
            for f in PUBLICATION_STD_FIELDS:
                if not out[f] and cross.get(f):
                    out[f] = cross[f]

    return out


def normalize_publication_list(pubs: list, catalog: dict) -> list[dict]:
    """Chuẩn hóa danh sách bài báo, khử trùng lặp theo doi hoặc title."""
    seen = set()
    result = []
    for p in pubs:
        if not isinstance(p, dict):
            continue
        norm = normalize_publication(p, catalog)
        dedup_key = norm.get("doi") or norm.get("title")
        dedup_key = _norm(dedup_key)
        if dedup_key and dedup_key in seen:
            continue
        if dedup_key:
            seen.add(dedup_key)
        result.append(norm)
    return result


def reclassify_existing_catalog(csv_path="scimagojr 2025.csv"):
    """
    Đọc file SCImago CSV và cập nhật lại phân loại (quartile, index_type, year)
    cho các mục đã có trong kho danh mục Supabase, khớp theo ISSN/ISBN.
    Trả về dict thống kê: {"total": N, "updated": M, "not_found": K} hoặc {"error": ...}
    """
    import re as _re

    issn_map = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                title = (row.get("Title") or "").strip()
                issn_raw = (row.get("Issn") or "").strip()
                quartile = (row.get("SJR Best Quartile") or "").strip()
                coverage = (row.get("Coverage") or "").strip()

                # Lấy ISSN đầu tiên (có thể có nhiều ISSN cách nhau bởi khoảng trắng)
                issns = [x.strip() for x in issn_raw.split() if x.strip()]
                primary_id = issns[0] if issns else ""
                if not primary_id:
                    continue

                # Trích xuất năm cuối từ Coverage (ví dụ "1950-2026" -> 2026)
                year = ""
                m = _re.findall(r"\b(19|20)\d{2}\b", coverage)
                if m:
                    year = m[-1]

                issn_map[primary_id] = {
                    "quartile": quartile,
                    "year": year,
                    "title": title,
                }
    except FileNotFoundError:
        return {"error": f"Không tìm thấy file {csv_path}"}
    except Exception as e:
        return {"error": str(e)}

    cat = load_journal_catalog()
    if not cat:
        return {"error": "Kho danh mục trống hoặc không đọc được từ Supabase"}

    total = 0
    updated = 0
    not_found = 0

    for key, entry in cat.items():
        total += 1
        issn = str(entry.get("issn", "")).strip()
        isbn = str(entry.get("isbn", "")).strip()
        matched = None
        if issn and issn in issn_map:
            matched = issn_map[issn]
        elif isbn and isbn in issn_map:
            matched = issn_map[isbn]

        if matched:
            changed = False
            if matched.get("quartile") and entry.get("quartile") != matched["quartile"]:
                entry["quartile"] = matched["quartile"]
                changed = True
            if not entry.get("index_type"):
                entry["index_type"] = "Scopus"
                changed = True
            if matched.get("year") and entry.get("year") != matched["year"]:
                entry["year"] = matched["year"]
                changed = True
            if changed:
                cat[key] = entry
                updated += 1
        else:
            not_found += 1

    ok = save_journal_catalog(cat)
    if not ok:
        return {"error": "Lưu catalog thất bại"}

    return {"total": total, "updated": updated, "not_found": not_found}
