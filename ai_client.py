import math
import time
from functools import lru_cache

import streamlit as st
from google import genai
from google.genai import types
from google.genai.errors import APIError

from config import MODELS_TO_TRY, CHAT_MODELS_TO_TRY, MAX_RETRIES


@lru_cache(maxsize=1)
def get_client():
    api_key = st.secrets.get("GEMINI_API_KEY", "")
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
                if e.code in (503, 404):
                    last_err = e
                    if att < MAX_RETRIES:
                        time.sleep(2 ** att)
                        continue
                    break
                raise
    raise RuntimeError(f"Model quá tải. Last error: {last_err!r}") from last_err


def _generate_with_retry(cfg, contents):
    client = get_client()
    if not client:
        raise RuntimeError("Chưa cấu hình GEMINI_API_KEY.")
    last_err = None
    for mn in CHAT_MODELS_TO_TRY:
        for att in range(MAX_RETRIES + 1):
            try:
                return client.models.generate_content(
                    model=mn, contents=contents, config=cfg)
            except APIError as e:
                if e.code in (503, 404):
                    last_err = e
                    if att < MAX_RETRIES:
                        time.sleep(2 ** att)
                        continue
                    break
                raise
    if last_err:
        raise RuntimeError(f"Không có model khả dụng. Last: {last_err!r}") from last_err
    raise RuntimeError("Không có model khả dụng.")