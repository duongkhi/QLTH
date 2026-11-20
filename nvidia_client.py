# nvidia_client.py
# Gọi API NVIDIA (Nemotron) dùng cho Hermes.
# Đọc NVIDIA_API_KEY từ st.secrets hoặc biến môi trường (đã có trong secrets.toml).

import os
import json
import urllib.request
import urllib.error

import streamlit as st


def _get_nvidia_api_key() -> str | None:
    """Lấy NVIDIA_API_KEY từ st.secrets hoặc biến môi trường."""
    try:
        key = st.secrets.get("NVIDIA_API_KEY", "")
    except Exception:
        key = ""
    if not key:
        key = os.environ.get("NVIDIA_API_KEY", "")
    return key or None


def call_nvidia(prompt: str, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
                temperature: float = 0.3, max_tokens: int = 1024) -> str | None:
    """
    Gọi NVIDIA API (Nemotron) để sinh văn bản.

    Returns:
        Chuỗi văn bản trả về, hoặc None nếu lỗi (không trả chuỗi '❌...' nữa).
    """
    api_key = _get_nvidia_api_key()
    if not api_key:
        return None

    url = "https://integrate.api.nvidia.com/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body)
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return None
    except urllib.error.HTTPError:
        return None
    except Exception:
        return None


def call_ai_with_fallback(prompt: str) -> str | None:
    """
    Ưu tiên gọi Gemini trước. Nếu hết quota / lỗi (None), tự động đổi sang NVIDIA.
    Trả về văn bản phản hồi từ AI đầu tiên thành công, hoặc None nếu cả hai đều lỗi.
    """
    try:
        from ai_client import generate_gemini_text
    except Exception:
        generate_gemini_text = None

    if generate_gemini_text:
        text = generate_gemini_text(prompt)
        if text:
            return text

    # Fallback sang NVIDIA khi Gemini lỗi/hết quota
    return call_nvidia(prompt)
