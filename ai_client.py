import math
import time
import os
from functools import lru_cache

import streamlit as st

from config import MAX_RETRIES

from nvidia_client import call_nvidia_json, call_nvidia_text, call_nvidia_stream, _get_nvidia_api_key

# --- Gemini (giữ lại cho trích xuất CV/tài liệu và fallback khi NVIDIA lỗi) ---
try:
    from google import genai
    from google.genai import types as genai_types
    from google.genai.errors import APIError as GeminiAPIError
    _GEMINI_AVAILABLE = True
except Exception:
    _GEMINI_AVAILABLE = False


@lru_cache(maxsize=1)
def get_client():
    """
    Kiểm tra cấu hình NVIDIA API.
    Trả về dict cấu hình nếu có NVIDIA_API_KEY, ngược lại trả về None.
    """
    api_key = _get_nvidia_api_key()
    return {"api_key": api_key} if api_key else None


def _build_config(thinking, json_mode):
    """Giữ lại để tương thích, không dùng nữa khi chuyển sang NVIDIA."""
    return {"thinking": thinking, "json_mode": json_mode}


def call_model_json(prompt, progress, start=20, end=95, label="🤖 AI"):
    """
    Gọi NVIDIA API để sinh JSON. Nếu NVIDIA lỗi, tự động fallback sang Gemini thật
    (dùng cho trích xuất CV/tài liệu). Giữ tham số progress để không破坏 các giao diện cũ.
    """
    client = get_client()
    if not client:
        # Không có NVIDIA_API_KEY, thử Gemini thật ngay
        real = generate_gemini_text_real(prompt)
        if real:
            return real
        raise RuntimeError("Chưa cấu hình NVIDIA_API_KEY và không có GEMINI_API_KEY.")

    last_err = None
    for att in range(MAX_RETRIES + 1):
        try:
            progress.progress(start, text=f"{label} (NVIDIA)...")
            text = call_nvidia_json(prompt)
            if text:
                return text
            raise RuntimeError("NVIDIA trả về trống.")
        except Exception as e:
            last_err = e
            if att < MAX_RETRIES:
                time.sleep(2 ** att)
                continue
            break

    # Hết lượt thử NVIDIA → fallback Gemini thật
    real = generate_gemini_text_real(prompt)
    if real:
        return real

    raise RuntimeError(f"NVIDIA quá tải hoặc lỗi. Last error: {last_err!r}") from last_err


def generate_gemini_text(prompt: str) -> str | None:
    """
    Gọi NVIDIA API trả về văn bản thuần (mặc định).
    Giữ tên generate_gemini_text để các module cũ import mà không lỗi.
    """
    client = get_client()
    if not client:
        return None

    last_err = None
    for att in range(MAX_RETRIES + 1):
        try:
            text = call_nvidia_text(prompt)
            if text:
                return text
            raise RuntimeError("NVIDIA trả về trống.")
        except Exception as e:
            last_err = e
            if att < MAX_RETRIES:
                time.sleep(2 ** att)
                continue
            break
    return None


def generate_gemini_text_real(prompt: str) -> str | None:
    """
    Gọi Gemini API thật (Google GenAI) để dùng cho trích xuất CV/tài liệu
    hoặc làm nguồn dự phòng khi NVIDIA NIM gặp lỗi.
    Yêu cầu GEMINI_API_KEY trong st.secrets hoặc biến môi trường.
    """
    if not _GEMINI_AVAILABLE:
        print("[DEBUG Gemini] _GEMINI_AVAILABLE = False")
        return None

    api_key = ""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
        print(f"[DEBUG Gemini] st.secrets.get GEMINI_API_KEY: {'tim thay key (do dai {len(api_key)})' if api_key else 'KHONG TIM THAY KEY'}")
    except Exception as e:
        print(f"[DEBUG Gemini] st.secrets loi: {e}")
        pass
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        print(f"[DEBUG Gemini] os.environ.get GEMINI_API_KEY: {'tim thay key' if api_key else 'KHONG TIM THAY KEY'}")
    if not api_key:
        print("[DEBUG Gemini] Khong co GEMINI_API_KEY nao, tra ve None")
        return None

    try:
        client = genai.Client(api_key=api_key)
        for model_name in ("gemini-3.8-flash", "gemini-3.5-flash-lite"):
            try:
                # gemini-3.8-flash khong ho tro ThinkingLevel.MINIMAL -> dung LOW
                thinking = (
                    genai_types.ThinkingLevel.LOW
                    if "3.8" in model_name
                    else genai_types.ThinkingLevel.MINIMAL
                )
                resp = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        thinking_config=genai_types.ThinkingConfig(
                            thinking_level=thinking
                        )
                    ),
                )
                if resp.text:
                    print("[DEBUG Gemini] Goi Gemini thanh cong")
                    return resp.text
            except GeminiAPIError as e:
                if e.code in (429, 503, 404):
                    print(f"[DEBUG Gemini] Model {model_name} loi {e.code}, thu model tiep theo")
                    continue
                raise
    except Exception as e:
        print(f"[DEBUG Gemini] Loi ngoai le: {e}")
        return None
    print("[DEBUG Gemini] Khong co model nao tra ve ket qua")
    return None


def _generate_with_retry(prompt: str, max_retries=1):
    """
    Gọi NVIDIA API với văn bản thuần (thay thế cho Gemini function calling).
    Trả về chuỗi text hoặc None nếu lỗi.

    max_retries=1: chỉ thử lại 1 lần (2 giây) nếu lỗi tạm thời (5xx/timeout).
    Lỗi 400/401/404 (sai key, sai model, sai payload) sẽ không retry để tránh đơ ứng dụng.
    """
    client = get_client()
    if not client:
        raise RuntimeError("Chưa cấu hình NVIDIA_API_KEY.")

    last_err = None
    for att in range(max_retries + 1):
        try:
            text = call_nvidia_text(prompt)
            if text:
                return text
            raise RuntimeError("NVIDIA trả về trống.")
        except Exception as e:
            last_err = e
            msg = str(e)
            # Lỗi 400/401/404 là lỗi cấu hình, không nên retry
            if any(code in msg for code in ("HTTP 400", "HTTP 401", "HTTP 404")):
                break
            if att < max_retries:
                wait_time = 2  # chỉ đợi 2 giây
                print(f"⚠️ Gặp lỗi từ NVIDIA, thử lại sau {wait_time} giây...")
                time.sleep(wait_time)
                continue
            break
    raise last_err if last_err else RuntimeError("NVIDIA quá tải hoặc lỗi.")