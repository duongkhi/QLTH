"""
Script kiểm tra cấu trúc và nội dung trên Supabase.
Chạy local (cần credentials Supabase):
    python check_supabase.py
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase_adapter import list_all_keys, load_json_from_db


def classify_key(key: str) -> str:
    """Phân loại key thành nhóm."""
    if key.startswith("_"):
        return "Hệ thống (_)"
    if key.startswith("chat_history_"):
        return "Lịch sử chat"
    if key.startswith("finance_"):
        return "Tài chính"
    if key.startswith("kb_"):
        return "Kiến thức"
    if key.startswith("journal_quality_catalog_"):
        return "Catalog chất lượng"
    if key.startswith("_form_template_"):
        return "Biểu mẫu"
    return "Hồ sơ cá nhân / Khác"


def show_profile_structure(key: str, data: dict, max_keys: int = 15):
    """Hiển thị cấu trúc ngắn gọn của một hồ sơ."""
    print(f"\n=== {key} ===")
    print(f"Tổng số trường: {len(data)}")
    keys = list(data.keys())[:max_keys]
    for k in keys:
        v = data[k]
        if isinstance(v, list):
            print(f"  {k}: list[{len(v)} mục]")
            if v and isinstance(v[0], dict):
                print(f"    Ví dụ mục đầu: {list(v[0].keys())[:8]}")
        elif isinstance(v, dict):
            print(f"  {k}: dict[{len(v)} key]")
        else:
            print(f"  {k}: {str(v)[:60]}")
    if len(data) > max_keys:
        print(f"  ... và {len(data) - max_keys} trường khác")


def main():
    all_keys = list_all_keys()
    print(f"Tổng số key trong Supabase: {len(all_keys)}\n")

    # Phân loại
    categories = {}
    for k in all_keys:
        cat = classify_key(k)
        categories.setdefault(cat, []).append(k)

    print("PHÂN LOẠI KEY:")
    for cat, keys in sorted(categories.items()):
        print(f"  {cat}: {len(keys)} key")

    # Hiển thị hồ sơ cá nhân mẫu
    profile_keys = [
        k for k in all_keys
        if not k.startswith("_")
        and not k.startswith("chat_history_")
        and not k.startswith("finance_")
        and not k.startswith("kb_")
        and not k.startswith("journal_quality_catalog_")
        and not k.startswith("_form_template_")
    ]
    profile_keys.sort()

    print(f"\n\nHỒ SƠ CÁ NHÂN ({len(profile_keys)} key):")
    for pk in profile_keys[:5]:  # chỉ hiển thị 5 hồ sơ đầu
        data = load_json_from_db(pk) or {}
        if isinstance(data, dict):
            show_profile_structure(pk, data)

    # Kiểm tra bai_bao_cong_bo trong hồ sơ
    print("\n\nKIỂM TRA TRƯỜNG bai_bao_cong_bo TRONG HỒ SƠ:")
    count_with_pubs = 0
    for pk in profile_keys:
        data = load_json_from_db(pk) or {}
        if isinstance(data, dict) and isinstance(data.get("bai_bao_cong_bo"), list):
            pubs = data["bai_bao_cong_bo"]
            count_with_pubs += 1
            if count_with_pubs <= 3:
                print(f"  {pk}: {len(pubs)} bài báo")
                for p in pubs[:2]:
                    if isinstance(p, dict):
                        print(f"    - {p.get('ten_cong_trinh', '')} ({p.get('nam_cong_bo', '')})")
    if count_with_pubs == 0:
        print("  Không có hồ sơ nào có trường bai_bao_cong_bo")
    else:
        print(f"  Tổng {count_with_pubs} hồ sơ có bài báo")

    # Kiểm tra publications_index
    print("\n\nKIỂM TRA publications_index:")
    pub_index = load_json_from_db("publications_index") or {}
    if pub_index:
        print(f"  Có {len(pub_index)} mục")
        for k, v in list(pub_index.items())[:3]:
            print(f"  {k}: {v.get('title', v.get('Tên bài báo', ''))[:50]}")
    else:
        print("  publications_index trống hoặc không tồn tại")

    # Kiểm tra catalog chất lượng
    print("\n\nKIỂM TRA CATALOG CHẤT LƯỢNG:")
    catalog_keys = sorted([
        k for k in all_keys
        if k.startswith("journal_quality_catalog_")
    ])
    print(f"  Tìm thấy {len(catalog_keys)} key catalog:")
    for ck in catalog_keys:
        data = load_json_from_db(ck) or {}
        print(f"    {ck}: {len(data)} mục")


if __name__ == "__main__":
    main()
