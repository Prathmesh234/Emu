"""
client_compact.py — Azure OpenAI compaction client
"""

import os
import time
from typing import TYPE_CHECKING

from openai import AzureOpenAI

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AD_TOKEN = os.environ.get("AZURE_OPENAI_AD_TOKEN", "")
ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
MODEL_NAME = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
MAX_TOKENS = 4096

_client = None


def _get_client():
    global _client
    if _client is None:
        kwargs = {
            "azure_endpoint": ENDPOINT,
            "api_version": API_VERSION,
        }
        if AD_TOKEN:
            kwargs["azure_ad_token"] = AD_TOKEN
        else:
            kwargs["api_key"] = API_KEY
        _client = AzureOpenAI(**kwargs)
    return _client


def compact(messages: list["PreviousMessage"]) -> str:
    api_messages = _build_messages(messages)

    start = time.time()
    resp = _get_client().chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": COMPACT_SYSTEM_PROMPT}] + api_messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = resp.choices[0].message.content or "" if resp.choices else ""
    print(f"[compact/azure_openai] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_messages(messages: list["PreviousMessage"]) -> list[dict]:
    from models import MessageRole

    raw: list[dict] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            raw.append({"role": "user", "content": pm.content})
    return raw
