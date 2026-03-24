"""
client.py — Anthropic Claude API client

Drop-in replacement for the Modal provider — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    ANTHROPIC_API_KEY  — required
"""

import json
import re
import time

import anthropic

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = "claude-sonnet-4-5"
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env


# ── Public API (matches modal provider interface) ────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, messages = _build_messages(agent_req)

    start = time.time()
    resp = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return True


def ensure_ready(**kwargs) -> None:
    pass


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in Anthropic format."""
    system_prompt = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content
        elif pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                base64_data = pm.content
                media_type = "image/png"
                if ";base64," in base64_data:
                    header, base64_data = base64_data.split(";base64,", 1)
                    media_type = header.replace("data:", "")
                raw.append({"role": "user", "content": [{
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": base64_data},
                }]})
            else:
                raw.append({"role": "user", "content": pm.content})

    return system_prompt or SYSTEM_PROMPT.strip(), _merge_consecutive(raw)


def _merge_consecutive(messages: list[dict]) -> list[dict]:
    """Merge consecutive same-role messages (Anthropic requires alternating)."""
    merged: list[dict] = []
    for msg in messages:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]["content"]
            new = msg["content"]
            if isinstance(prev, str):
                prev = [{"type": "text", "text": prev}]
            if isinstance(new, str):
                new = [{"type": "text", "text": new}]
            merged[-1]["content"] = prev + new
        else:
            merged.append(msg)
    return merged


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    content = "".join(b.text for b in resp.content if b.type == "text")
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


def _fix_literal_newlines(text: str) -> str:
    """Escape literal newlines/tabs inside JSON string values (LLMs often emit these)."""
    result = []
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = not in_string
            result.append(ch)
        elif ch == '\n' and in_string:
            result.append('\\n')
        elif ch == '\r' and in_string:
            result.append('\\r')
        elif ch == '\t' and in_string:
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


def _extract_json(content: str) -> dict:
    """Pull the JSON object out of Claude's text response."""
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

    # Repair: escape literal newlines/tabs inside string values
    repaired = _fix_literal_newlines(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Common JSON repairs
    # Trailing commas
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    # Malformed coordinates: {"x":255,219} → {"x":255,"y":219}
    repaired = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', repaired)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Plain text response — treat as conversational done, not a loop
    print(f"[claude] INFO: plain-text response, wrapping as done:\n  {content[:200]}")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 0.9}
