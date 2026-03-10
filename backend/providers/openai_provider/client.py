"""
client.py — OpenAI Responses API client (GPT-5.4)

Uses the Responses API (client.responses.create) which is OpenAI's latest
and recommended API primitive — replaces Chat Completions with better
caching, multi-turn support, and built-in tool primitives.

Docs: https://platform.openai.com/docs/api-reference/responses

Drop-in replacement for other providers — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    OPENAI_API_KEY  — required
    OPENAI_MODEL    — optional (default: gpt-5.4)
"""

import json
import os
import re
import time

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5.4")
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI()  # reads OPENAI_API_KEY from env


# ── Public API (matches provider interface) ──────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    instructions, input_messages = _build_input(agent_req)

    start = time.time()
    resp = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_messages,
        max_output_tokens=MAX_TOKENS,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return True


def ensure_ready(**kwargs) -> None:
    pass


# ── Message builder ──────────────────────────────────────────────────────────

def _build_input(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (instructions, input) for the Responses API.

    The Responses API uses:
      - `instructions` param for system/developer instructions
      - `input` array with role: "user" / "assistant" messages
      - Image content uses type: "input_image" with image_url
      - Text content uses type: "input_text" with text
    """
    instructions = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            instructions = pm.content
        elif pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": [
                {"type": "output_text", "text": pm.content},
            ]})
        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                raw.append({
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": pm.content},
                    ],
                })
            else:
                raw.append({
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": pm.content},
                    ],
                })

    return instructions or SYSTEM_PROMPT.strip(), raw


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    # output_text is a convenience property that aggregates all text output
    content = resp.output_text or ""

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

    # Trailing commas fix
    repaired = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Plain text response — treat as conversational done, not a loop
    print(f"[openai] INFO: plain-text response, wrapping as done:\n  {content[:200]}")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 0.9}
