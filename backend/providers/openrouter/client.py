"""
client.py — OpenRouter API client

Uses the OpenAI Chat Completions API format against OpenRouter's endpoint.
OpenRouter supports 200+ models from multiple providers (OpenAI, Anthropic,
Google, Meta, Mistral, etc.) through a single API key.

Docs: https://openrouter.ai/docs/quickstart

Drop-in replacement for other providers — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    OPENROUTER_API_KEY  — required
    OPENROUTER_MODEL    — optional (default: anthropic/claude-sonnet-4)
"""

import json
import os
import re
import time

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# -- Configuration -----------------------------------------------------------

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
MODEL_NAME = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
BASE_URL = "https://openrouter.ai/api/v1"
MAX_TOKENS = 1024
TEMPERATURE = 0.6

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


# -- Public API (matches provider interface) ---------------------------------

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, messages = _build_messages(agent_req)

    start = time.time()
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return bool(API_KEY)


def ensure_ready(**kwargs) -> None:
    if not API_KEY:
        raise RuntimeError(
            "[openrouter] OPENROUTER_API_KEY is not set. "
            "Get one at https://openrouter.ai/keys"
        )


# -- Message builder ---------------------------------------------------------

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in OpenAI Chat Completions format."""
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


# -- Response parser ---------------------------------------------------------

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    choice = resp.choices[0] if resp.choices else None
    message = choice.message if choice else None
    content = message.content or "" if message else ""

    reasoning = getattr(message, "reasoning_content", None) if message else None

    data = _extract_json(content)
    data = _sanitize_single_action(data)

    return AgentResponse(
        action=Action(**data.get("action", {"type": "done"})),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        reasoning_content=reasoning,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _sanitize_single_action(data: dict) -> dict:
    """Enforce one-action-per-response. Strip extra actions the model may batch."""
    # Strip rogue keys that look like batched actions
    for key in ("next", "next_action", "actions", "step2", "then"):
        if key in data:
            print(f"[openrouter] WARN: stripped batched key '{key}' from response")
            del data[key]

    # If final_message contains JSON with an "action" key, it's a nested action
    fm = data.get("final_message")
    if isinstance(fm, str) and fm.strip().startswith("{"):
        try:
            inner = json.loads(fm)
            if isinstance(inner, dict) and "action" in inner:
                print(f"[openrouter] WARN: final_message contained nested action — extracting real action")
                # The real action was stuffed inside final_message; promote it
                data["action"] = inner["action"]
                data["done"] = inner.get("done", False)
                data["confidence"] = inner.get("confidence", data.get("confidence", 1.0))
                data["final_message"] = inner.get("final_message")
        except (json.JSONDecodeError, ValueError):
            pass

    return data


def _extract_json(content: str) -> dict:
    """Pull the JSON object out of the model's text response."""
    text = content.strip()

    # Strip markdown fences
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Extract only the FIRST JSON object. Models sometimes concatenate
    # multiple objects (e.g. {...}{...}). json.JSONDecoder.raw_decode
    # stops after the first valid object.
    brace_start = text.find("{")
    if brace_start != -1:
        try:
            decoder = json.JSONDecoder()
            obj, end_idx = decoder.raw_decode(text, brace_start)
            remainder = text[end_idx:].strip()
            if remainder:
                print(f"[openrouter] WARN: model returned multiple objects, using only the first. Discarded: {remainder[:120]}")
            return obj
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Common JSON repairs
    repaired = text
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    repaired = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', repaired)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Plain text response — treat as conversational done
    print(f"[openrouter] INFO: plain-text response, wrapping as done:\n  {content[:200]}")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 0.9}
