"""
Script khắc phục: tạo lại danh sách tên file đã upload (uploaded_catalog_files)
dựa trên các key catalog đã có trên Supabase.

Chạy local:
    python autofix_uploaded_files.py --yes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase_adapter import list_all_keys, load_json_from_db, save_json_to_db


def main():
    all_keys = list_all_keys()
    catalog_keys = sorted([
        k for k in all_keys
        if k.startswith("journal_quality_catalog_")
    ])

    if not catalog_keys:
        print("Không tìm thấy key catalog nào trên Supabase.")
        return

    print("Tìm thấy các key catalog:")
    for ck in catalog_keys:
        data = load_json_from_db(ck) or {}
        print(f"  {ck} — {len(data)} mục")

    # Tạo danh sách tên file từ các key catalog
    uploaded_files = []
    for ck in catalog_keys:
        if ck.endswith("_index"):
            continue
        suffix = ck[len("journal_quality_catalog_"):]
        parts = suffix.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            name_part = parts[0]
        else:
            name_part = suffix
        file_name = name_part.replace("_", " ") + ".csv"
        if file_name not in uploaded_files:
            uploaded_files.append(file_name)

    uploaded_files.sort()
    print("\nDanh sách tên file sẽ lưu:")
    for f in uploaded_files:
        print(f"  • {f}")

    confirm = "yes" if "--yes" in sys.argv else input("\nLưu danh sách này vào Supabase? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Đã hủy.")
        return

    ok = save_json_to_db("uploaded_catalog_files", uploaded_files)
    if ok:
        print(f"\n✅ Đã lưu {len(uploaded_files)} tên file vào key 'uploaded_catalog_files'")
    else:
        print("\n❌ Không lưu được.")


if __name__ == "__main__":
    main()
