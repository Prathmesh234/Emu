"""
client_compact.py — Together AI compaction client
"""

import os
import time
from typing import TYPE_CHECKING

from openai import OpenAI

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

API_KEY = os.environ.get("TOGETHER_API_KEY", "")
MODEL_NAME = os.environ.get("TOGETHER_MODEL", "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8")
BASE_URL = "https://api.together.xyz/v1"
MAX_TOKENS = 4096

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def compact(messages: list["PreviousMessage"]) -> str:
    api_messages = _build_messages(messages)

    start = time.time()
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": COMPACT_SYSTEM_PROMPT}] + api_messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = resp.choices[0].message.content or "" if resp.choices else ""
    print(f"[compact/together_ai] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
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
