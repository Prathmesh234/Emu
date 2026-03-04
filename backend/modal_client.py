"""
modal_client.py

HTTP client for calling the deployed Qwen3.5 VLM on Modal.
Converts AgentRequest → OpenAI chat payload → Modal → AgentResponse.
"""

import json
import re
import time
from typing import Optional

import requests

from models import (
    Action,
    AgentRequest,
    AgentResponse,
    MessageRole,
)
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

MODAL_URL = "https://ppbhatt500--qwen35-35b-a3b-vlm-qwen35vlm.us-east.modal.direct"
MODEL_NAME = "Qwen/Qwen3.5-35B-A3B"
MAX_TOKENS = 1024
TEMPERATURE = 0.6
REQUEST_TIMEOUT = 300  # seconds

# Prefix that marks a user message as a screenshot (data URI)
SCREENSHOT_PREFIX = "data:image/"


# ── Public API ───────────────────────────────────────────────────────────────

def call_modal(agent_req: AgentRequest) -> AgentResponse:
    """
    Send an agent step to the Modal VLM and return a parsed AgentResponse.

    Builds an OpenAI-compatible chat/completions payload from the AgentRequest:
      - System prompt
      - User text messages rendered as text
      - User screenshot messages rendered as multimodal image_url
      - Assistant messages rendered as text
    """
    messages = _build_messages(agent_req)

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
    }

    start = time.time()
    data = _post_with_retry(payload)
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(data, elapsed_ms)


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> list[dict]:
    """
    Convert AgentRequest.previous_messages into OpenAI chat format.

    Detection logic:
      - system messages  → {"role": "system", "content": text}
      - assistant msgs   → {"role": "assistant", "content": text}
      - user msgs starting with "data:image/" → multimodal image
      - user msgs (anything else) → plain text
    """
    messages: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            messages.append({"role": "system", "content": pm.content})

        elif pm.role == MessageRole.assistant:
            messages.append({"role": "assistant", "content": pm.content})

        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                # Screenshot turn → multimodal image
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": pm.content}},
                    ],
                })
            else:
                # Text turn
                messages.append({"role": "user", "content": pm.content})

    return messages


# ── HTTP call with retry ─────────────────────────────────────────────────────

def _post_with_retry(
    payload: dict,
    max_retries: int = 5,
) -> dict:
    """POST to Modal endpoint with retry on transient errors."""
    url = f"{MODAL_URL}/v1/chat/completions"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
        ):
            if attempt == max_retries:
                raise
            _backoff(attempt, "connection error (container may be starting)")
        except requests.exceptions.HTTPError:
            if resp.status_code in (500, 502, 503, 504) and attempt < max_retries:
                _backoff(attempt, f"HTTP {resp.status_code}")
            else:
                print(f"[modal_client] FAILED ({resp.status_code}): {resp.text[:300]}")
                raise

    raise RuntimeError("Unreachable")


def _backoff(attempt: int, reason: str):
    wait = min(5 * attempt, 30)
    print(f"[modal_client] attempt {attempt} — {reason}, retrying in {wait}s")
    time.sleep(wait)


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(data: dict, elapsed_ms: int) -> AgentResponse:
    """
    Parse the OpenAI-compatible response from Modal into an AgentResponse.

    The VLM returns JSON in the message content. We extract:
      - reasoning_content (thinking/CoT)
      - content (the action JSON)
    """
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    reasoning = message.get("reasoning_content") or ""
    content = message.get("content") or ""

    # Parse the action JSON from content
    action_data = _extract_action_json(content)

    action = Action(**action_data.get("action", {"type": "done"}))
    done = action_data.get("done", False)
    final_message = action_data.get("final_message")
    confidence = action_data.get("confidence", 1.0)

    return AgentResponse(
        action=action,
        done=done,
        final_message=final_message,
        confidence=confidence,
        reasoning_content=reasoning if reasoning else None,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _extract_action_json(content: str) -> dict:
    """
    Extract the JSON action object from the model's text response.
    The model may wrap JSON in markdown code fences, include extra text,
    or produce slightly malformed JSON (missing quotes on keys, trailing
    commas, etc.).  We try progressively more aggressive repairs before
    giving up.
    """
    text = content.strip()

    # Strip markdown code fences
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    # Isolate the outermost { … }
    if not text.startswith("{"):
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start : brace_end + 1]

    # ── Attempt 1: strict parse ──────────────────────────────────────────
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Attempt 2: repair common issues ──────────────────────────────────
    repaired = _repair_json(text)
    try:
        result = json.loads(repaired)
        print(f"[modal_client] JSON repaired successfully")
        return result
    except json.JSONDecodeError:
        pass

    # ── Give up — ask the model to try again (screenshot, not done) ──────
    print(f"[modal_client] WARNING: Could not parse action JSON from model output:")
    print(f"  {content[:300]}")
    return {
        "action": {"type": "screenshot"},
        "done": False,
        "confidence": 0.5,
    }


def _repair_json(text: str) -> str:
    """
    Best-effort repairs for common VLM JSON mistakes:
      1. Unquoted keys:           { x: 1 }            → { "x": 1 }
      2. Missing opening quote:   { x": 1 }           → { "x": 1 }
      3. Single-quoted strings:   { 'key': 'val' }    → { "key": "val" }
      4. Trailing commas:         [1, 2, ]             → [1, 2]
      5. True/False/None:         True                 → true
    """
    s = text

    # Fix unquoted or half-quoted keys:  ,  key": val  or  { key": val
    # Matches: start-of-obj/comma, optional whitespace, word chars, then ":
    # and ensures "key" gets proper opening quote
    s = re.sub(
        r'([{,]\s*)([a-zA-Z_]\w*)"(\s*:)',
        r'\1"\2"\3',
        s,
    )

    # Fix fully unquoted keys:  { key : val }
    s = re.sub(
        r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)',
        r'\1"\2"\3',
        s,
    )

    # Single quotes → double quotes (naive but effective for simple cases)
    s = s.replace("'", '"')

    # Trailing commas before } or ]
    s = re.sub(r',\s*([}\]])', r'\1', s)

    # Python-style booleans / None
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)

    return s
