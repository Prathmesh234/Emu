"""
client.py — OpenAI API client (GPT-4o / GPT-4.1)

Drop-in replacement for other providers — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    OPENAI_API_KEY  — required
    OPENAI_MODEL    — optional (default: gpt-4.1)
"""

import json
import os
import re
import time

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-4.1")
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI()  # reads OPENAI_API_KEY from env


# ── Public API (matches provider interface) ──────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, messages = _build_messages(agent_req)

    start = time.time()
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return True


def ensure_ready(**kwargs) -> None:
    pass


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in OpenAI chat format."""
    system_prompt = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content
        elif pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                raw.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": pm.content}},
                    ],
                })
            else:
                raw.append({"role": "user", "content": pm.content})

    return system_prompt or SYSTEM_PROMPT.strip(), raw


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    choice = resp.choices[0] if resp.choices else None
    content = choice.message.content or "" if choice else ""

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

    print(f"[openai] WARNING: unparseable response:\n  {content[:300]}")
    return {"action": {"type": "screenshot"}, "done": False, "confidence": 0.5}
