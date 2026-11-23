# ui/local_session.py
# Quản lý phiên đăng nhập cục bộ trên máy (không lưu trên Supabase).
# Dùng để tự động sign-in lại khi người dùng mở lại Streamlit trên cùng một máy.
import json
import os
from datetime import datetime, timedelta

SESSION_PATH = ".streamlit/local_session.json"
EXPIRY_DAYS = 30  # Lưu đăng nhập tối đa 30 ngày


def save_local_session(username: str | None, password_hash: str) -> None:
    """Lưu thông tin phiên đăng nhập vào file cục bộ."""
    if not username or not password_hash:
        return
    try:
        os.makedirs(os.path.dirname(SESSION_PATH), exist_ok=True)
        data = {
            "username": username,
            "password_hash": password_hash,
            "expiry": (datetime.now() + timedelta(days=EXPIRY_DAYS)).isoformat(),
        }
        with open(SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Bất kỳ lỗi gì (quyền限..., ổ đĩa...) thì bỏ qua, không làm gián đoạn app
        pass


def clear_local_session() -> None:
    """Xóa file phiên cục bộ (dùng khi đăng xuất)."""
    try:
        if os.path.exists(SESSION_PATH):
            os.remove(SESSION_PATH)
    except Exception:
        pass


def load_local_session() -> dict | None:
    """
    Đọc phiên cục bộ nếu còn hợp lệ (chưa hết hạn và đủ thông tin).
    Trả về dict hoặc None.
    """
    try:
        if not os.path.exists(SESSION_PATH):
            return None
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        expiry = data.get("expiry")
        if expiry and datetime.fromisoformat(expiry) < datetime.now():
            return None

        if not data.get("username") or not data.get("password_hash"):
            return None

        return data
    except Exception:
        return None
