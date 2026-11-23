"""
Script XÓA HẾT các key danh mục chất lượng trên Supabase.

Xóa toàn bộ key bắt đầu bằng "journal_quality_catalog_" (bao gồm cả key mới và cũ).
Sau khi chạy, kho danh mục sẽ trống rỗng, bạn có thể upload lại file từ đầu.

Chạy local (cần credentials Supabase):
    python delete_all_catalogs.py --yes
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from supabase_adapter import (
    list_all_keys,
    delete_key_from_db,
)

PREFIX = "journal_quality_catalog_"


def main():
    all_keys = list_all_keys()
    catalog_keys = sorted([k for k in all_keys if k.startswith(PREFIX)])

    if not catalog_keys:
        print("Không có key catalog nào trên Supabase để xóa.")
        return

    print(f"Tìm thấy {len(catalog_keys)} key catalog sẽ bị XÓA HOÀN TOÀN:")
    for k in catalog_keys:
        print(f"  - {k}")

    confirm = "yes" if "--yes" in sys.argv else input("\nBạn có chắc muốn xóa HẾT các key này? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Đã hủy.")
        return

    deleted = 0
    failed = 0
    for k in catalog_keys:
        ok = delete_key_from_db(k)
        if ok:
            print(f"  [DEL] {k}")
            deleted += 1
        else:
            print(f"  [LỖI] {k}")
            failed += 1

    print(f"\nKết quả: xóa thành công {deleted}, thất bại {failed}.")
    if deleted > 0:
        print("Kho danh mục chất lượng đã trống. Bạn có thể upload lại file từ đầu.")


if __name__ == "__main__":
    main()
