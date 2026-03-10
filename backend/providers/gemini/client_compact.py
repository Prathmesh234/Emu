"""
client_compact.py — Gemini compaction client

Uses the same model as the main provider to summarise bloated context
chains. Called by the /compact feature.
Messages are built in the same format as the regular Gemini client.
"""

import os
import time
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_TOKENS = 4096

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))


def compact(messages: list["PreviousMessage"]) -> str:
    """Send the context chain and return the summary."""
    contents = _build_contents(messages)

    start = time.time()
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=COMPACT_SYSTEM_PROMPT,
            max_output_tokens=MAX_TOKENS,
        ),
    )
    elapsed_ms = int((time.time() - start) * 1000)

    summary = resp.text or ""
    print(f"[compact/gemini] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_contents(messages: list["PreviousMessage"]) -> list[types.Content]:
    """Build Gemini-format contents from PreviousMessage list."""
    from models import MessageRole

    contents: list[types.Content] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            contents.append(types.Content(
                role="model",
                parts=[types.Part(text=pm.content)],
            ))
        elif pm.role == MessageRole.user:
            contents.append(types.Content(
                role="user",
                parts=[types.Part(text=pm.content)],
            ))

    # Merge consecutive same-role turns (Gemini requires alternating)
    merged: list[types.Content] = []
    for item in contents:
        if merged and merged[-1].role == item.role:
            merged[-1].parts.extend(item.parts)
        else:
            merged.append(item)
    return merged
