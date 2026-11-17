import math
import time
import os
from functools import lru_cache

import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import MODELS_TO_TRY, CHAT_MODELS_TO_TRY, MAX_RETRIES


@lru_cache(maxsize=1)
def get_client():
    # Ưu tiên đọc từ st.secrets, nếu không có thì đọc từ biến môi trường
    api_key = ""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass
    
    if not api_key:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        
    return genai.Client(api_key=api_key) if api_key else None


def _build_config(thinking, json_mode):
    kw = {"thinking_config": types.ThinkingConfig(thinking_level=thinking)}
    if json_mode:
        kw["response_mime_type"] = "application/json"
    return types.GenerateContentConfig(**kw)


def call_model_json(prompt, progress, start=20, end=95, label="🤖 AI"):
    client = get_client()
    if not client:
        raise RuntimeError("Chưa cấu hình GEMINI_API_KEY.")
        
    last_err = None
    for mi in MODELS_TO_TRY:
        mn = mi["name"]
        cfg = _build_config(mi["thinking"], True)
        for att in range(MAX_RETRIES + 1):
            try:
                progress.progress(start, text=f"🤖 {mn}...")
                text = ""
                for ch in client.models.generate_content_stream(
                        model=mn, contents=prompt, config=cfg):
                    if ch.text:
                        text += ch.text
                        ratio = 1 - math.exp(-len(text) / 1500)
                        progress.progress(
                            min(end, int(start + (end - start) * ratio)),
                            text=f"{label}...")
                return text
            except APIError as e:
                # Bổ sung bắt lỗi 429 (quá tải quota)
                if e.code in (429, 503, 404):
                    last_err = e
                    if att < MAX_RETRIES:
                        time.sleep(2 ** att)
                        continue
                    break
                raise
    raise RuntimeError(f"Model quá tải. Last error: {last_err!r}") from last_err


def _generate_with_retry(cfg, contents, max_retries=3):
    # ⚠️ ĐÂY LÀ DÒNG BỊ THIẾU GÂY RA LỖI
    client = get_client()
    if not client:
        raise RuntimeError("Chưa cấu hình GEMINI_API_KEY.")
        
    last_err = None
    for mn in CHAT_MODELS_TO_TRY:
        for att in range(max_retries + 1):
            try:
                return client.models.generate_content(model=mn, contents=contents, config=cfg)
            except APIError as e:
                # Xử lý lỗi do quá tải hoặc hết quota
                if e.code in (429, 503, 404):
                    last_err = e
                    if att < max_retries:
                        # Nghỉ 5s, 10s, 15s trước khi thử lại 
                        wait_time = 5 * (att + 1) 
                        print(f"⚠️ Gặp lỗi {e.code}, thử lại sau {wait_time} giây...")
                        time.sleep(wait_time)
                        continue
                    break
                raise
    raise last_err if last_err else RuntimeError("Hết lượt gọi API hoặc model quá tải.")