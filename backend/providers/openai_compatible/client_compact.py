"""
client_compact.py — OpenAI-compatible compaction client

Uses the same model/endpoint as the main provider to summarise bloated
context chains. Called by the /compact feature.
Messages are built in the same format as the regular OpenAI-compatible client.
"""

import os
import time
from typing import TYPE_CHECKING

from openai import OpenAI

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "none")
MODEL_NAME = os.environ.get("OPENAI_COMPAT_MODEL", "default")
MAX_TOKENS = 4096

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def compact(messages: list["PreviousMessage"]) -> str:
    """Send the context chain and return the summary."""
    api_messages = _build_messages(messages)

    start = time.time()
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": COMPACT_SYSTEM_PROMPT}] + api_messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = resp.choices[0].message.content or "" if resp.choices else ""
    print(f"[compact/openai_compat] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_messages(messages: list["PreviousMessage"]) -> list[dict]:
    """Build Chat Completions format messages."""
    from models import MessageRole

    raw: list[dict] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            raw.append({"role": "user", "content": pm.content})
    return raw
