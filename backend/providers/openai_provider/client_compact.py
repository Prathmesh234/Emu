"""
client_compact.py — OpenAI compaction client

Uses the same model as the main provider to summarise bloated context
chains. Called by the /compact feature.
Messages are built in the same format as the regular OpenAI client.
"""

import os
import time
from typing import TYPE_CHECKING

from openai import OpenAI

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5.4")
MAX_TOKENS = 4096

client = OpenAI()


def compact(messages: list["PreviousMessage"]) -> str:
    """Send the context chain and return the summary."""
    api_messages = _build_messages(messages)

    start = time.time()
    resp = client.responses.create(
        model=MODEL_NAME,
        instructions=COMPACT_SYSTEM_PROMPT,
        input=api_messages,
        max_output_tokens=MAX_TOKENS,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = resp.output_text or ""
    print(f"[compact/openai] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_messages(messages: list["PreviousMessage"]) -> list[dict]:
    """Build OpenAI Responses API format messages."""
    from models import MessageRole

    raw: list[dict] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": [
                {"type": "output_text", "text": pm.content},
            ]})
        elif pm.role == MessageRole.user:
            raw.append({"role": "user", "content": [
                {"type": "input_text", "text": pm.content},
            ]})
    return raw
