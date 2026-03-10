"""
client.py — Google Gemini API client (Gemini 3 Flash)

Uses the google-genai SDK (>= 1.51.0) with client.models.generate_content().
System instructions are passed via GenerateContentConfig.system_instruction.
Images are sent as types.Part with inline_data (types.Blob).

Docs: https://ai.google.dev/gemini-api/docs/gemini-3

Drop-in replacement for other providers — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    GOOGLE_API_KEY  — required
    GEMINI_MODEL    — optional (default: gemini-3-flash-preview)
"""

import base64
import json
import os
import re
import time

from google import genai
from google.genai import types

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))


# ── Public API (matches provider interface) ──────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, contents = _build_contents(agent_req)

    start = time.time()
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_TOKENS,
        ),
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return True


def ensure_ready(**kwargs) -> None:
    pass


# ── Message builder ──────────────────────────────────────────────────────────

def _build_contents(req: AgentRequest) -> tuple[str, list]:
    """Build (system_prompt, contents) using Gemini types.

    Uses types.Content with types.Part for structured content.
    Images are passed as types.Part with inline_data (types.Blob).
    Gemini uses role="model" for assistant turns.
    """
    system_prompt = ""
    contents: list[types.Content] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content
        elif pm.role == MessageRole.assistant:
            contents.append(types.Content(
                role="model",
                parts=[types.Part(text=pm.content)],
            ))
        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                mime_type, b64_data = _parse_data_uri(pm.content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(
                        inline_data=types.Blob(
                            mime_type=mime_type,
                            data=base64.b64decode(b64_data),
                        ),
                    )],
                ))
            else:
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(text=pm.content)],
                ))

    # Gemini requires alternating user/model turns — merge consecutive same-role
    contents = _merge_consecutive(contents)

    return system_prompt or SYSTEM_PROMPT.strip(), contents


def _parse_data_uri(data_uri: str) -> tuple[str, str]:
    """Extract (mime_type, base64_data) from a data URI."""
    if ";base64," in data_uri:
        header, b64 = data_uri.split(";base64,", 1)
        mime = header.replace("data:", "")
        return mime, b64
    return "image/png", data_uri


def _merge_consecutive(contents: list[types.Content]) -> list[types.Content]:
    """Merge consecutive same-role turns (Gemini requires alternating)."""
    merged: list[types.Content] = []
    for item in contents:
        if merged and merged[-1].role == item.role:
            merged[-1].parts.extend(item.parts)
        else:
            merged.append(item)
    return merged


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    content = resp.text or ""

    data = _extract_json(content)

    return AgentResponse(
        action=Action(**data.get("action", {"type": "done"})),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        reasoning_content=None,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _extract_json(content: str) -> dict:
    """Pull the JSON object out of the model's text response."""
    text = content.strip()

    # Strip markdown fences
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Isolate outermost { … }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Common JSON repairs
    repaired = text
    # Trailing commas
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    # Malformed coordinates: {"x":255,219} → {"x":255,"y":219}
    repaired = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', repaired)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Plain text response — treat as conversational done, not a loop
    print(f"[gemini] INFO: plain-text response, wrapping as done:\n  {content[:200]}")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 0.9}
