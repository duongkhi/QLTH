from storage import (load_user_profile, load_name_mapping,
                     save_name_mapping)
from security import _norm, _name_matches_query, _strip_diacritics, _tokenize
from security import NAME_FIELDS


def sync_name_mapping(profiles):
    m = load_name_mapping()
    changed = False
    for k in profiles:
        if not k or k in m:
            continue
        d = load_user_profile(k)
        if not d:
            continue
        for field in NAME_FIELDS:
            if d.get(field):
                m[k] = {"display_name": str(d[field]).strip(),
                        "aliases": []}
                changed = True
                break
    if changed:
        save_name_mapping(m)


def update_name_mapping_from_profile(key, data):
    if not data:
        return
    for field in NAME_FIELDS:
        if data.get(field):
            m = load_name_mapping()
            m.setdefault(key, {})
            m[key]["display_name"] = str(data[field]).strip()
            m[key].setdefault("aliases", [])
            save_name_mapping(m)
            return