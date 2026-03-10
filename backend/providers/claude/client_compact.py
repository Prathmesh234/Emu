"""
client_compact.py — Claude compaction client (Haiku)

Lightweight client that sends the full context chain to Claude Haiku
for summarisation. Used by the /compact feature to reduce token bloat.

Same Anthropic SDK, different model (haiku-4-6) and system prompt.
Messages are built in the same format as the regular Claude client.
"""

import time
from typing import TYPE_CHECKING

import anthropic

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

MODEL_NAME = "claude-haiku-4-5"
MAX_TOKENS = 8192

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


def compact(messages: list["PreviousMessage"]) -> str:
    """Send the context chain to Haiku and return the summary."""
    from models import MessageRole

    api_messages = _build_messages(messages)

    start = time.time()
    resp = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=COMPACT_SYSTEM_PROMPT,
        messages=api_messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = "".join(b.text for b in resp.content if b.type == "text")
    print(f"[compact/claude] Haiku summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_messages(messages: list["PreviousMessage"]) -> list[dict]:
    """Build Anthropic-format messages from PreviousMessage list."""
    from models import MessageRole

    raw: list[dict] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            raw.append({"role": "user", "content": pm.content})

    # Merge consecutive same-role messages (Anthropic requires alternating)
    merged: list[dict] = []
    for msg in raw:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            new = msg["content"]
            if isinstance(prev, str) and isinstance(new, str):
                merged[-1]["content"] = prev + "\n" + new
            else:
                if isinstance(prev, str):
                    prev = [{"type": "text", "text": prev}]
                if isinstance(new, str):
                    new = [{"type": "text", "text": new}]
                merged[-1]["content"] = prev + new
        else:
            merged.append(msg)
    return merged
