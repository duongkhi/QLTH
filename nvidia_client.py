# nvidia_client.py
# Gọi API NVIDIA (Nemotron) dùng cho Hermes.
# Đọc NVIDIA_API_KEY từ st.secrets hoặc biến môi trường (đã có trong secrets.toml).
#
# Lưu ý: Dự án đã chuyển hoàn toàn sang NVIDIA, không còn dùng Gemini.
#
# MODEL HIỆN TẠI: nvidia/nemotron-3.5-super-vl-120b-a12b
# Nếu muốn đổi model, hãy sửa tham số model trong các hàm call_nvidia / call_nvidia_stream
# hoặc thay đổi giá trị mặc định ở dòng định nghĩa hàm dưới đây.
# Danh sách model có thể tham khảo: https://build.nvidia.com/nim
#
# KIỂM TRA CẤU HÌNH:
#   - File .streamlit/secrets.toml phải có dòng: NVIDIA_API_KEY = "nvapi-..."
#   - Nếu thiếu, hãy thêm vào secrets.toml hoặc đặt biến môi trường NVIDIA_API_KEY
#
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


def call_nvidia(prompt: str, system: str | None = None, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
                temperature: float = 0.3, max_tokens: int = 1024) -> str | None:
    """
    Gọi NVIDIA API (Nemotron) để sinh văn bản.

    Parameters:
        prompt: Nội dung người dùng (role user).
        system: Hướng dẫn hệ thống (role system), gửi kèm nếu không None.
        model: Model NVIDIA NIM.
        temperature, max_tokens: Tham số sinh văn bản.

    Returns:
        Chuỗi văn bản trả về, hoặc None nếu lỗi.
    """
    api_key = _get_nvidia_api_key()
    if not api_key:
        return None

    url = "https://integrate.api.nvidia.com/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
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
    except urllib.error.HTTPError as e:
        # In mã lỗi HTTP và nội dung chi tiết (ẩn API key) để chẩn đoán nguyên nhân
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:1000]
        except Exception:
            err_body = "<không đọc được nội dung lỗi>"
        print(f"❌ NVIDIA HTTP {e.code}: {err_body}")
        return None
    except Exception as e:
        print(f"❌ NVIDIA lỗi kết nối: {type(e).__name__}: {e}")
        return None


def call_nvidia_json(prompt: str, system: str | None = None, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
                     temperature: float = 0.2, max_tokens: int = 2048) -> str | None:
    """
    Gọi NVIDIA API yêu cầu trả về JSON thuần.

    Hàm này chèn hướng dẫn trả về JSON vào đầu prompt để giảm nguy hiểm AI trả markdown.
    """
    json_instruction = (
        "Trả về CHỈ duy nhất một đối tượng JSON thuần khiết, không được kèm markdown, "
        "không được bọc trong ```json ..., không giải thích thêm.\n\n"
    )
    full_prompt = json_instruction + prompt
    return call_nvidia(full_prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens)


def call_nvidia_text(prompt: str, system: str | None = None, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b",
                     temperature: float = 0.3, max_tokens: int = 1024) -> str | None:
    """
    Alias của call_nvidia, giữ tên để tương thích với mã cũ gọi generate_gemini_text.
    """
    return call_nvidia(prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens)


def call_ai_with_fallback(prompt: str) -> str | None:
    """
    Gọi NVIDIA API (đã là duy nhất sau khi chuyển đổi hoàn toàn).
    Giữ tên hàm để các module cũ vẫn import được.
    """
    return call_nvidia(prompt)


# ==========================================
# STREAM: NVIDIA NIM Lightning (chat thông thường)
# ==========================================
def call_nvidia_stream(
    prompt: str,
    system: str | None = None,
    model: str = "nvidia/nemotron-3.5-lightning-30b-a3b",
    temperature: float = 0.3,
    max_tokens: int = 1024,
):
    """
    Generator gọi NVIDIA NIM với stream=True, yield từng đoạn văn bản ngay khi nhận được.
    Dùng cho khung chat thông thường để người dùng thấy chữ hiện ra ngay lập tức.

    Parameters:
        prompt: Nội dung người dùng (role user).
        system: Hướng dẫn hệ thống (role system), gửi kèm nếu không None.
        model: Model NVIDIA NIM.
        temperature, max_tokens: Tham số sinh văn bản.

    Yields:
        Chuỗi văn bản partial (delta) từ NVIDIA NIM.
    """
    api_key = _get_nvidia_api_key()
    if not api_key:
        return

    url = "https://integrate.api.nvidia.com/v1/chat/completions"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            for raw_line in resp:
                try:
                    line = raw_line.decode("utf-8").strip()
                except Exception:
                    continue
                if not line:
                    continue
                if line.startswith("data: "):
                    content = line[6:]
                    if content == "[DONE]":
                        break
                    try:
                        chunk = json.loads(content)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            yield text
                    except Exception:
                        continue
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8")[:1000]
        except Exception:
            err_body = "<không đọc được nội dung lỗi>"
        print(f"❌ NVIDIA Stream HTTP {e.code}: {err_body}")
        return
    except Exception as e:
        print(f"❌ NVIDIA Stream lỗi kết nối: {type(e).__name__}: {e}")
        return
