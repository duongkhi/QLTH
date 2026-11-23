# profile_service.py
from storage import (load_user_profile, save_user_profile,
                     load_name_mapping, load_json_from_db, save_json_to_db)
from security import (_norm, _strip_diacritics, _name_matches_query,
                      identity_matches, _tokenize)
from name_mapping import update_name_mapping_from_profile
from journal_service import load_journal_catalog

PUBLICATIONS_INDEX_KEY = "publications_index"


def _normalize_text(s):
    """Chuẩn hóa văn bản: chữ thường, bỏ dấu, xóa khoảng trắng thừa."""
    if not s:
        return ""
    return _strip_diacritics(str(s)).strip().lower()


def _compute_pub_key(pub):
    """Tính khóa định danh duy nhất cho một bài báo."""
    doi = str(pub.get("doi", "")).strip()
    if doi:
        return f"doi:{_normalize_text(doi)}"
    title = _normalize_text(pub.get("title", ""))
    year = str(pub.get("year", "")).strip()
    if title and year:
        return f"title:{title}_{year}"
    if title:
        return f"title:{title}"
    return None


def sync_publications_index(profile_key, profile_data):
    """
    Cập nhật chỉ mục bài báo khoa học (publications_index) trên Supabase
    dựa trên dữ liệu hồ sơ của một cán bộ.
    - Chuẩn hóa từng bài báo theo cấu trúc Scopus.
    - Khóa duy nhất: doi (nếu có) hoặc title_normalized + "_" + year.
    - Nếu bài báo đã tồn tại: nối thêm profile_key vào internal_authors,
      và đơn vị công tác vào units (không tạo trùng).
    """
    if not profile_key or not profile_data:
        return

    index = load_json_from_db(PUBLICATIONS_INDEX_KEY) or {}

    # Lấy danh sách bài báo từ các trường có thể có trong hồ sơ
    pubs = profile_data.get("bai_bao_chuan_scopus", [])
    if not isinstance(pubs, list):
        pubs = profile_data.get("cong_bo", [])
    if not isinstance(pubs, list):
        pubs = profile_data.get("bai_bao", [])
    if not isinstance(pubs, list):
        pubs = []

    don_vi = str(profile_data.get("don_vi_cong_tac", "") or profile_data.get("don_vi", "") or "").strip()

    for p in pubs:
        if not isinstance(p, dict):
            continue

        pub_key = _compute_pub_key(p)
        if not pub_key:
            continue

        title = str(p.get("title", "")).strip()
        authors = str(p.get("authors", "")).strip()
        source_title = str(p.get("source_title", "")).strip()
        year = str(p.get("year", "")).strip()
        doi = str(p.get("doi", "")).strip()
        issn = str(p.get("issn", "")).strip()
        index_type = str(p.get("index_type", "")).strip()
        quartile = str(p.get("quartile", "")).strip()
        doc_type = str(p.get("document_type", "")).strip()

        entry = {
            "title": title,
            "authors": authors,
            "source_title": source_title,
            "year": year,
            "doi": doi,
            "issn": issn,
            "index_type": index_type,
            "quartile": quartile,
            "document_type": doc_type,
            "internal_authors": [],
            "units": [],
        }

        if pub_key in index:
            existing = index[pub_key]
            # Nối thêm profile_key nếu chưa có
            auth_list = existing.get("internal_authors", [])
            if profile_key not in auth_list:
                auth_list.append(profile_key)
                existing["internal_authors"] = auth_list
            # Nối thêm đơn vị nếu chưa có
            unit_list = existing.get("units", [])
            if don_vi and don_vi not in unit_list:
                unit_list.append(don_vi)
                existing["units"] = unit_list
            # Cập nhật thông tin chi tiết nếu bản mới đầy đủ hơn
            for field in ("title", "authors", "source_title", "doi", "issn",
                          "index_type", "quartile", "document_type"):
                if not existing.get(field) and p.get(field):
                    existing[field] = str(p.get(field, "")).strip()
            if not existing.get("year") and p.get("year"):
                existing["year"] = str(p.get("year", "")).strip()
            index[pub_key] = existing
        else:
            entry["internal_authors"] = [profile_key]
            if don_vi:
                entry["units"] = [don_vi]
            index[pub_key] = entry

    save_json_to_db(PUBLICATIONS_INDEX_KEY, index)




# ============================================================
# Chuẩn hóa dữ liệu bài báo về trường bai_bao_cong_bo
# ============================================================

def _classify_publication(loai_cong_trinh, noi_cong_bo, ten_cong_trinh):
    """Phân loại bài báo: Scopus/ISI/SCI/SCI-EE (Q1-Q4) hoặc loại trong nước/quốc tế."""
    text = f"{loai_cong_trinh or ''} {noi_cong_bo or ''} {ten_cong_trinh or ''}".lower()
    if "scopus" in text:
        if "q1" in text: return "Scopus Q1"
        if "q2" in text: return "Scopus Q2"
        if "q3" in text: return "Scopus Q3"
        if "q4" in text: return "Scopus Q4"
        return "Scopus"
    if "isi" in text or "sci-ee" in text or "scie" in text:
        if "q1" in text: return "ISI/SCI-EE Q1"
        if "q2" in text: return "ISI/SCI-EE Q2"
        if "q3" in text: return "ISI/SCI-EE Q3"
        if "q4" in text: return "ISI/SCI-EE Q4"
        return "ISI/SCI-EE"
    if "sci" in text:
        if "q1" in text: return "SCI Q1"
        if "q2" in text: return "SCI Q2"
        if "q3" in text: return "SCI Q3"
        if "q4" in text: return "SCI Q4"
        return "SCI"
    lt = (loai_cong_trinh or "").strip().lower()
    if "hội nghị quốc tế" in lt or "conference international" in lt:
        return "Hội nghị quốc tế"
    if "hội nghị trong nước" in lt or "conference national" in lt:
        return "Hội nghị trong nước"
    if "tạp chí quốc tế" in lt or "journal international" in lt:
        return "Tạp chí quốc tế"
    if "tạp chí trong nước" in lt or "journal national" in lt:
        return "Tạp chí trong nước"
    if "hội nghị" in lt:
        return "Hội nghị"
    if "tạp chí" in lt or "journal" in lt:
        return "Tạp chí"
    return "Khác"


def _lookup_phan_loai_from_catalog(ten_cong_trinh, noi_cong_bo, doi, issn):
    """
    Tra cứu kho danh mục SCImago 2025 để gán phân loại chất lượng (Scopus Q1-Q4, ...).
    Tìm theo ưu tiên: doi -> issn -> tên tạp chí (journal_name / source_title).
    """
    try:
        catalog = load_journal_catalog()
    except Exception:
        return ""
    if not catalog:
        return ""

    doi_n = _norm(doi)
    issn_n = _norm(issn)
    name_n = _norm(noi_cong_bo or ten_cong_trinh)

    matched = None
    for key, entry in catalog.items():
        if doi_n and _norm(entry.get("doi")) == doi_n:
            matched = entry
            break
        if issn_n and _norm(entry.get("issn")) == issn_n:
            matched = entry
            break
        if name_n and _norm(entry.get("journal_name")) == name_n:
            matched = entry
            break

    if not matched:
        return ""

    quartile = str(matched.get("quartile", "")).strip().upper()
    index_type = str(matched.get("index_type", "")).strip()

    if quartile in ("Q1", "Q2", "Q3", "Q4"):
        it_low = index_type.lower()
        if "scopus" in it_low:
            return f"Scopus {quartile}"
        if "isi" in it_low or "sci" in it_low:
            return f"ISI/SCI-EE {quartile}"
        return quartile
    return ""


def _normalize_one_publication(entry):
    """Chuẩn hóa 1 bài báo thô thành dict chuẩn cho bai_bao_cong_bo."""
    if not isinstance(entry, dict):
        return None

    ten_cong_trinh = str(entry.get("ten_cong_trinh", "") or entry.get("title", "") or "").strip()
    nam_cong_bo = str(entry.get("nam_cong_bo", "") or entry.get("year", "") or "").strip()
    noi_cong_bo = str(entry.get("noi_cong_bo", "") or entry.get("source_title", "") or "").strip()
    loai_cong_trinh = str(entry.get("loai_cong_trinh", "") or entry.get("document_type", "") or "").strip()
    vai_tro = str(entry.get("vai_tro", "") or "").strip()
    doi = str(entry.get("doi", "") or "").strip()
    issn = str(entry.get("issn", "") or "").strip()

    if not ten_cong_trinh:
        return None

    # Ưu tiên giá trị đã có từ Gemini (nếu file đính kèm đã qua trích xuất AI)
    tac_gia_dau = bool(entry.get("tac_gia_dau", False))
    tac_gia_lien_he = bool(entry.get("tac_gia_lien_he", False))
    dong_tac_gia = bool(entry.get("dong_tac_gia", False))
    if not (tac_gia_dau or tac_gia_lien_he or dong_tac_gia):
        vt = vai_tro.lower()
        if "tác giả đầu" in vt or "tac gia dau" in vt or "first author" in vt:
            tac_gia_dau = True
        elif "tác giả liên hệ" in vt or "tac gia lien he" in vt or "corresponding" in vt:
            tac_gia_lien_he = True
        elif "đồng tác giả" in vt or "dong tac gia" in vt or "co-author" in vt:
            dong_tac_gia = True
        else:
            dong_tac_gia = True

    # Ưu tiên phan_loai từ Gemini nếu đã có
    phan_loai_existing = str(entry.get("phan_loai", "")).strip()
    if phan_loai_existing:
        phan_loai = phan_loai_existing
    else:
        # Thử tra cứu catalog SCImago theo tên tạp chí / DOI / ISSN
        phan_loai = _lookup_phan_loai_from_catalog(
            ten_cong_trinh, noi_cong_bo, doi, issn
        )
        if not phan_loai:
            phan_loai = _classify_publication(
                loai_cong_trinh, noi_cong_bo, ten_cong_trinh
            )

    return {
        "ten_cong_trinh": ten_cong_trinh,
        "nam_cong_bo": nam_cong_bo,
        "noi_cong_bo": noi_cong_bo,
        "loai_cong_trinh": loai_cong_trinh,
        "phan_loai": phan_loai,
        "vai_tro": vai_tro,
        "tac_gia_dau": tac_gia_dau,
        "tac_gia_lien_he": tac_gia_lien_he,
        "dong_tac_gia": dong_tac_gia,
        "doi": doi,
        "issn": issn,
    }


def _collect_raw_publications(profile_data):
    """Thu thập tất cả bài báo thô từ các trường có sẵn trong hồ sơ."""
    raw = []
    if isinstance(profile_data.get("bai_bao_cong_bo"), list):
        for item in profile_data["bai_bao_cong_bo"]:
            if isinstance(item, dict):
                raw.append(item)
    if isinstance(profile_data.get("cac_cong_trinh_kh_cn_chu_yeu"), list):
        raw.extend(profile_data["cac_cong_trinh_kh_cn_chu_yeu"])
    for field in ("bai_bao_chuan_scopus", "cong_bo", "bai_bao", "danh_sach_bai_bao"):
        if isinstance(profile_data.get(field), list):
            raw.extend(profile_data[field])
    return raw


def sync_bai_bao_cong_bo(profile_key, profile_data):
    """
    Chuẩn hóa tất cả bài báo của một hồ sơ về trường bai_bao_cong_bo.
    - Gom dữ liệu từ các trường thô khác.
    - Phân loại (Scopus Q1-Q4, ISI/SCI-EE, SCI, Hội nghị/Tạp chí trong nước/quốc tế, Khác).
    - Xác định vai trò: tác giả đầu, tác giả liên hệ, đồng tác giả.
    - Loại bỏ trùng lặp theo ten_cong_trinh + nam_cong_bo.
    """
    if not profile_key or not profile_data:
        return profile_data

    raw_list = _collect_raw_publications(profile_data)
    if not raw_list:
        if "bai_bao_cong_bo" in profile_data and not profile_data["bai_bao_cong_bo"]:
            profile_data.pop("bai_bao_cong_bo", None)
        return profile_data

    normalized = []
    seen = set()
    for entry in raw_list:
        norm = _normalize_one_publication(entry)
        if not norm:
            continue
        dedup_key = f"{norm['ten_cong_trinh'].lower()}|{norm['nam_cong_bo']}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        normalized.append(norm)

    if normalized:
        profile_data["bai_bao_cong_bo"] = normalized
    else:
        profile_data.pop("bai_bao_cong_bo", None)

    return profile_data


def merge_and_save(key, new_data, overwrite=False):
    """Gộp dữ liệu mới vào hồ sơ hiện tại, bảo toàn cấu hình _public_fields."""
    old_data = load_user_profile(key)
    saved_public = old_data.get("_public_fields") if isinstance(old_data, dict) else None

    if overwrite or not old_data:
        final = {k: v for k, v in new_data.items() if v not in (None, "", [], {})}
        if saved_public is not None and "_public_fields" not in final:
            final["_public_fields"] = saved_public
        final = sync_bai_bao_cong_bo(key, final)
        save_user_profile(key, final)
        update_name_mapping_from_profile(key, final)
        sync_publications_index(key, final)
        return final, {"added": final, "updated": {}, "appended": {}}

    final = dict(old_data)
    changes = {"added": {}, "updated": {}, "appended": {}}

    for k, v in new_data.items():
        if v is None or v == "" or v == [] or v == {}:
            continue

        if isinstance(v, list):
            if k in final and isinstance(final[k], list):
                new_items = [item for item in v if item not in final[k]]
                if new_items:
                    final[k] = final[k] + new_items
                    changes["appended"][k] = new_items
            else:
                final[k] = v
                changes["added"][k] = v
        else:
            if k not in final:
                final[k] = v
                changes["added"][k] = v
            elif final[k] != v:
                final[k] = v
                changes["updated"][k] = v

    final = sync_bai_bao_cong_bo(key, final)
    save_user_profile(key, final)
    update_name_mapping_from_profile(key, final)
    sync_publications_index(key, final)
    return final, changes


def resolve_profile(query, allowed):
    """Trả về (key, candidates, reason, hint)."""
    q = str(query or "").strip()
    if not q:
        return None, [], "empty", "Tên rỗng."
    if q in allowed:
        return q, [], None, None
    for k in allowed:
        if k.lower() == q.lower():
            return k, [], None, None

    m = load_name_mapping()
    exact, partial = set(), set()
    for k, info in m.items():
        if k not in allowed:
            continue
        names = [info.get("display_name", "")] + list(info.get("aliases", []))
        for n in names:
            if not n:
                continue
            if _norm(n) == _norm(q):
                exact.add(k)
                break
            if _name_matches_query(n, q):
                partial.add(k)

    if len(exact) == 1:
        return list(exact)[0], [], None, None
    if len(exact) > 1:
        return None, sorted(exact), "ambiguous", f"Nhiều hồ sơ trùng tên '{q}'."
    if len(partial) == 1:
        return list(partial)[0], [], None, None
    if len(partial) > 1:
        return None, sorted(partial), "ambiguous", f"Nhiều hồ sơ khớp '{q}'."

    qs = _strip_diacritics(q).replace(" ", "").lower()
    for k in allowed:
        if _strip_diacritics(k).replace(" ", "").lower() == qs:
            return k, [], None, None

    # Tìm kiếm gần đúng trực tiếp trong dữ liệu hồ sơ (ho_ten, ho_va_ten, full_name)
    from storage import load_user_profile
    for k in allowed:
        d = load_user_profile(k)
        if not d:
            continue
        for field in ("ho_va_ten", "ho_ten", "full_name", "name"):
            v = d.get(field, "")
            if v and _strip_diacritics(str(v)).replace(" ", "").lower() == qs:
                return k, [], None, None

    return None, [], "not_found", f"Không tìm thấy hồ sơ khớp '{q}'."


def find_profile_in_text(text, allowed):
    """Tìm key profile trong text, dùng word-boundary."""
    m = load_name_mapping()
    tn = _norm(text)
    best, blen = None, 0
    for k, info in m.items():
        if k not in allowed:
            continue
        names = [info.get("display_name", "")] + list(info.get("aliases", []))
        for n in names:
            if not n:
                continue
            nn = _norm(n)
            if not nn:
                continue
            import re
            if re.search(rf"(?<!\w){re.escape(nn)}(?!\w)", tn) and len(nn) > blen:
                best, blen = k, len(nn)
    return best


def suggest_profile_key(name):
    if not name:
        return ""
    s = _strip_diacritics(name).strip()
    import re
    return "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", s))


def find_identity_matches(new_data, allowed):
    res = []
    for k in allowed:
        e = load_user_profile(k)
        if not e:
            continue
        s = identity_matches(new_data, e)
        if s in ("strong", "weak"):
            res.append((k, s))
    res.sort(key=lambda x: (0 if x[1] == "strong" else 1, x[0]))
    return res