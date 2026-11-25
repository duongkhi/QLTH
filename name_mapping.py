from storage import (load_user_profile, load_name_mapping,
                     save_name_mapping)
from security import (_norm, _name_matches_query, _strip_diacritics, _tokenize,
                      detect_name_en_from_data)
from security import NAME_FIELDS, NAME_FIELDS_EN


def sync_name_mapping(profiles):
    m = load_name_mapping()
    changed = False
    for k in profiles:
        if not k or k in m:
            continue
        try:
            d = load_user_profile(k)
        except Exception:
            continue
        if not isinstance(d, dict) or not d:
            continue
        # Lấy tên hiển thị (ưu tiên tiếng Việt, fallback tiếng Anh)
        display_name = ""
        for field in NAME_FIELDS:
            if d.get(field):
                display_name = str(d[field]).strip()
                break
        if not display_name:
            for field in NAME_FIELDS_EN:
                if d.get(field):
                    display_name = str(d[field]).strip()
                    break
        if not display_name:
            continue
        display_name_en = ""
        for field in NAME_FIELDS_EN:
            if d.get(field):
                display_name_en = str(d[field]).strip()
                break
        m[k] = {
            "display_name": display_name,
            "display_name_en": display_name_en,
            "aliases": [],
            "aliases_en": [],
        }
        changed = True
    if changed:
        save_name_mapping(m)


def update_name_mapping_from_profile(key, data):
    if not data:
        return
    # Cập nhật tên tiếng Việt (ưu tiên)
    display_name = ""
    for field in NAME_FIELDS:
        if data.get(field):
            display_name = str(data[field]).strip()
            break
    # Cập nhật tên tiếng Anh (nếu có)
    display_name_en = ""
    for field in NAME_FIELDS_EN:
        if data.get(field):
            display_name_en = str(data[field]).strip()
            break
    if not display_name and not display_name_en:
        return
    m = load_name_mapping()
    m.setdefault(key, {})
    if display_name:
        m[key]["display_name"] = display_name
    if display_name_en:
        m[key]["display_name_en"] = display_name_en
    m[key].setdefault("aliases", [])
    m[key].setdefault("aliases_en", [])
    save_name_mapping(m)


def get_display_name(key, mapping=None):
    """Lấy tên hiển thị của một key, ưu tiên tiếng Việt, fallback tiếng Anh."""
    if mapping is None:
        mapping = load_name_mapping()
    info = mapping.get(key, {}) if isinstance(mapping, dict) else {}
    if not isinstance(info, dict):
        info = {}
    name_vn = info.get("display_name", "") or ""
    name_en = info.get("display_name_en", "") or ""
    if name_vn:
        return name_vn
    return name_en or key