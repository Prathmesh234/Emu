"""
client_compact.py — Modal compaction client

Uses the same Modal endpoint / model to summarise context chains.
Called by the /compact feature.
Messages are built in the same format as the regular Modal client.
"""

import time
import os
from typing import TYPE_CHECKING

import requests

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

MODAL_URL = os.getenv("MODAL_VLM_URL", "")
MODEL_NAME = "Qwen/Qwen3.5-35B-A3B"
MAX_TOKENS = 4096
TEMPERATURE = 0.6
REQUEST_TIMEOUT = 300


def compact(messages: list["PreviousMessage"]) -> str:
    """Send the context chain to Modal and return the summary."""
    from models import MessageRole

    api_messages = [{"role": "system", "content": COMPACT_SYSTEM_PROMPT}]
    for pm in messages:
        if pm.role == MessageRole.assistant:
            api_messages.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            api_messages.append({"role": "user", "content": pm.content})

    payload = {
        "model": MODEL_NAME,
        "messages": api_messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    start = time.time()
    resp = requests.post(
        f"{MODAL_URL}/v1/chat/completions",
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    elapsed_ms = int((time.time() - start) * 1000)

    choices = data.get("choices", [])
    summary = choices[0]["message"]["content"] if choices else ""
    print(f"[compact/modal] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary
