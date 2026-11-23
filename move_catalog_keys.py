"""
Script di chuyển tên key catalog SCImago 2025 trên Supabase.

Chuyển:
  journal_quality_catalog_01  -> journal_quality_catalog_Scinago_2025_01
  ...
  journal_quality_catalog_11  -> journal_quality_catalog_Scinago_2025_11
  journal_quality_catalog_index -> journal_quality_catalog_Scinago_2025_index

Chạy local (cần credentials Supabase):
    python move_catalog_keys.py
"""

import os
import sys

# Đảm bảo import được từ thư mục project
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase_adapter import (
    list_all_keys,
    load_json_from_db,
    save_json_to_db,
    delete_key_from_db,
)

OLD_PREFIX = "journal_quality_catalog_"
NEW_PREFIX = "journal_quality_catalog_Scinago_2025_"

OLD_META_KEY = "journal_quality_catalog_index"
NEW_META_KEY = "journal_quality_catalog_Scinago_2025_index"


def map_key(old_key: str) -> str:
    """Đổi tên key theo quy tắc mới."""
    if old_key == OLD_META_KEY:
        return NEW_META_KEY
    if old_key.startswith(OLD_PREFIX):
        suffix = old_key[len(OLD_PREFIX):]
        return f"{NEW_PREFIX}{suffix}"
    return old_key


def main():
    all_keys = list_all_keys()
    catalog_keys = sorted([
        k for k in all_keys
        if k.startswith(OLD_PREFIX)
    ])

    if not catalog_keys:
        print("Không tìm thấy key catalog nào trên Supabase.")
        return

    print(f"Tìm thấy {len(catalog_keys)} key catalog cần di chuyển:")
    for k in catalog_keys:
        print(f"  {k}  =>  {map_key(k)}")

    confirm = "yes" if "--yes" in sys.argv else input("\nBạn có chắc muốn di chuyển các key này? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Đã hủy.")
        return

    # 1. Copy dữ liệu sang key mới
    new_batch_keys = []
    for old_key in catalog_keys:
        new_key = map_key(old_key)
        data = load_json_from_db(old_key) or {}
        if not data:
            print(f"  [BỎ QUA] {old_key}: dữ liệu trống")
            continue
        ok = save_json_to_db(new_key, data)
        if ok:
            print(f"  [OK] {old_key} -> {new_key} ({len(data)} mục)")
            if old_key != OLD_META_KEY:
                new_batch_keys.append(new_key)
        else:
            print(f"  [LỖI] Không lưu được {new_key}")

    # 2. Cập nhật meta key mới (danh sách batch_keys mới)
    if new_batch_keys:
        meta_ok = save_json_to_db(NEW_META_KEY, {
            "batch_keys": sorted(new_batch_keys),
            "total": sum(len(load_json_from_db(k) or {}) for k in new_batch_keys),
        })
        print(f"  [META] {NEW_META_KEY} đã lưu ({len(new_batch_keys)} batch)")

    # 3. Xóa key cũ
    for old_key in catalog_keys:
        ok = delete_key_from_db(old_key)
        if ok:
            print(f"  [DEL] {old_key} đã xóa")
        else:
            print(f"  [LỖI] Không xóa được {old_key}")

    print("\nHoàn tất di chuyển key.")


if __name__ == "__main__":
    main()
