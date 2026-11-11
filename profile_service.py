from storage import (load_user_profile, save_user_profile,
                     load_name_mapping)
from security import (_norm, _strip_diacritics, _name_matches_query,
                      identity_matches, _tokenize)
from name_mapping import update_name_mapping_from_profile


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


def merge_and_save(key, new_data, overwrite=False):
    """
    Gộp dữ liệu mới vào hồ sơ hiện tại.
    - overwrite=True: Ghi đè toàn bộ (dùng cho nút "Ghi đè").
    - overwrite=False: 
      + List: Nối thêm phần tử mới (không trùng lặp).
      + Đơn trị: Ghi đè nếu có giá trị mới.
      + Rỗng (None, "", []): Bỏ qua, giữ nguyên giá trị cũ.
    """
    old_data = load_user_profile(key)

    # Nếu ghi đè toàn bộ hoặc chưa có dữ liệu cũ
    if overwrite or not old_data:
        final = {k: v for k, v in new_data.items() if v not in (None, "", [], {})}
        save_user_profile(key, final)
        update_name_mapping_from_profile(key, final)
        return final, {"added": final, "updated": {}, "appended": {}}

    final = dict(old_data)
    changes = {"added": {}, "updated": {}, "appended": {}}

    for k, v in new_data.items():
        # 1. Bỏ qua nếu giá trị mới rỗng
        if v is None or v == "" or v == [] or v == {}:
            continue

        # 2. Nếu là List -> Nối thêm
        if isinstance(v, list):
            if k in final and isinstance(final[k], list):
                # Lọc các phần tử mới chưa có trong mảng cũ
                new_items = [item for item in v if item not in final[k]]
                if new_items:
                    final[k] = final[k] + new_items
                    changes["appended"][k] = new_items
            else:
                # Chưa có hoặc kiểu dữ liệu cũ không phải list -> Ghi đè bằng list mới
                final[k] = v
                changes["added"][k] = v
        
        # 3. Nếu là đơn trị (String, Int, Dict...) -> Ghi đè
        else:
            if k not in final:
                final[k] = v
                changes["added"][k] = v
            elif final[k] != v:
                final[k] = v
                changes["updated"][k] = v

    save_user_profile(key, final)
    update_name_mapping_from_profile(key, final)
    
    return final, changes


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