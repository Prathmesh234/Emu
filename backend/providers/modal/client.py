"""
client.py — Modal GPU inference client

HTTP client for calling the deployed VLM on Modal.
Sends agent tools in the request; handles tool_calls in the response.
Falls back to JSON text parsing for desktop actions.
"""

import json
import os
import re
import time

import requests

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import AGENT_TOOLS_OPENAI

# ── Configuration ────────────────────────────────────────────────────────────

MODAL_URL = os.getenv("MODAL_VLM_URL", "")
MODEL_NAME = "Qwen/Qwen3.5-35B-A3B"
MAX_TOKENS = 8124
TEMPERATURE = 0.8
REQUEST_TIMEOUT = 300  # seconds

SCREENSHOT_PREFIX = "data:image/"


# ── Public API ───────────────────────────────────────────────────────────────

def call_modal(agent_req: AgentRequest) -> AgentResponse:
    messages = _build_messages(agent_req)

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": TEMPERATURE,
        "tools": AGENT_TOOLS_OPENAI,
    }

    start = time.time()
    data = _post_with_retry(payload)
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(data, elapsed_ms)


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> list[dict]:
    """Convert AgentRequest.previous_messages into OpenAI chat format."""
    messages: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            messages.append({"role": "system", "content": pm.content})

        elif pm.role == MessageRole.assistant:
            msg = {"role": "assistant"}
            if pm.tool_calls:
                msg["tool_calls"] = pm.tool_calls
                msg["content"] = pm.content if pm.content else None
            else:
                msg["content"] = pm.content
            messages.append(msg)

        elif pm.role == MessageRole.tool:
            msg = {
                "role": "tool",
                "tool_call_id": pm.tool_call_id or "",
                "content": pm.content,
            }
            if pm.tool_name:
                msg["name"] = pm.tool_name
            messages.append(msg)

        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                messages.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": pm.content}},
                    ],
                })
            else:
                messages.append({"role": "user", "content": pm.content})

    return messages


# ── HTTP call with retry ─────────────────────────────────────────────────────

def _post_with_retry(payload: dict, max_retries: int = 5) -> dict:
    """POST to Modal endpoint with retry on transient errors."""
    url = f"{MODAL_URL}/v1/chat/completions"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
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
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}

    reasoning = message.get("reasoning_content") or ""
    content = message.get("content") or ""

    # ── Tool calls? ──────────────────────────────────────────────────────────
    raw_tool_calls = message.get("tool_calls")
    if raw_tool_calls:
        tool_calls = [
            ToolCallInfo(
                id=tc.get("id", ""),
                name=tc.get("function", {}).get("name", ""),
                arguments=tc.get("function", {}).get("arguments", "{}"),
            )
            for tc in raw_tool_calls
        ]
        print(f"[modal] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=reasoning if reasoning else None,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    # ── No tool calls — parse JSON action from text ──────────────────────────
    action_data = _extract_action_json(content)
    action_data = _sanitize_action(action_data)

    raw_action = action_data.get("action", {"type": "done"})
    if isinstance(raw_action, str):
        raw_action = {"type": raw_action}

    return AgentResponse(
        action=Action(**raw_action),
        done=action_data.get("done", False),
        final_message=action_data.get("final_message"),
        confidence=action_data.get("confidence", 1.0),
        reasoning_content=reasoning if reasoning else None,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _extract_action_json(content: str) -> dict:
    """Extract the JSON action object from the model's text response."""
    text = content.strip()

    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    if not text.startswith("{"):
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    repaired = _repair_json(text)
    try:
        result = json.loads(repaired)
        print(f"[modal] JSON repaired successfully")
        return result
    except json.JSONDecodeError:
        pass

    print(f"[modal] WARNING: Could not parse action JSON:\n  {content[:300]}")
    return {"action": {"type": "screenshot"}, "done": False, "confidence": 0.5}


def _sanitize_action(data: dict) -> dict:
    """Enforce one-action-per-response; strip batched keys and unwrap nested actions."""
    for key in ("next", "next_action", "actions", "step2", "then", "followup"):
        if key in data:
            print(f"[modal] WARN: stripped batched key '{key}' from response")
            del data[key]

    fm = data.get("final_message")
    if isinstance(fm, str) and fm.strip().startswith("{"):
        try:
            inner = json.loads(fm)
            if isinstance(inner, dict) and "action" in inner:
                print(f"[modal] WARN: final_message contained nested action — extracting")
                data["action"] = inner["action"]
                data["done"] = inner.get("done", False)
                data["confidence"] = inner.get("confidence", data.get("confidence", 1.0))
                data["final_message"] = inner.get("final_message")
        except (json.JSONDecodeError, ValueError):
            pass

    return data


def _repair_json(text: str) -> str:
    """Best-effort repairs for common VLM JSON mistakes."""
    s = text
    s = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)"(\s*:)', r'\1"\2"\3', s)
    s = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)', r'\1"\2"\3', s)
    s = s.replace("'", '"')
    s = re.sub(r',\s*([}\]])', r'\1', s)
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)
    return s
