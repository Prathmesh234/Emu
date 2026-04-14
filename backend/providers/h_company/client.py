"""
client.py — H Company (Holo) API client

Uses H Company's OpenAI-compatible endpoint for the Holo family of models.
Sends agent tools via native function calling when supported.

Environment:
    H_COMPANY_API_KEY  — required
    H_COMPANY_MODEL    — optional (default: holo3-35b-a3b)
"""

import json
import os
import re
import time

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import AGENT_TOOLS_OPENAI

# ── Configuration ────────────────────────────────────────────────────────────

API_KEY = os.environ.get("H_COMPANY_API_KEY", "")
MODEL_NAME = os.environ.get("H_COMPANY_MODEL", "holo3-35b-a3b")
BASE_URL = "https://api.hcompany.ai/v1/"
MAX_TOKENS = 8000
TEMPERATURE = 0.6

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# ── State ────────────────────────────────────────────────────────────────────

_ready = False
_tools_supported = True  # optimistic; set to False on first failure


# ── Public API ───────────────────────────────────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    global _tools_supported

    system_prompt, messages = _build_messages(agent_req)

    kwargs = dict(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )

    # Send tools if backend supports them
    if _tools_supported:
        kwargs["tools"] = AGENT_TOOLS_OPENAI

    start = time.time()
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        # If tools caused the error, retry without them
        if _tools_supported and "tool" in str(e).lower():
            print(f"[h_company] tools not supported, disabling: {e}")
            _tools_supported = False
            kwargs.pop("tools", None)
            resp = client.chat.completions.create(**kwargs)
        else:
            raise
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return _ready


def ensure_ready(timeout: int = 30, poll_interval: int = 5, **kwargs) -> None:
    """Mark ready immediately — H Company is a managed API, no warm-up needed."""
    global _ready
    if _ready:
        return
    _ready = True
    print(f"[h_company] Using model: {MODEL_NAME} at {BASE_URL}")


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in OpenAI Chat Completions format."""
    system_prompt = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content

        elif pm.role == MessageRole.assistant:
            msg = {"role": "assistant"}
            if pm.tool_calls:
                msg["tool_calls"] = pm.tool_calls
                msg["content"] = pm.content if pm.content else None
            else:
                msg["content"] = pm.content
            raw.append(msg)

        elif pm.role == MessageRole.tool:
            msg = {
                "role": "tool",
                "tool_call_id": pm.tool_call_id or "",
                "content": pm.content,
            }
            if pm.tool_name:
                msg["name"] = pm.tool_name
            raw.append(msg)

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

    return system_prompt or "", raw


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    choice = resp.choices[0] if resp.choices else None
    message = choice.message if choice else None
    content = message.content or "" if message else ""

    reasoning = getattr(message, "reasoning_content", None) if message else None

    # ── Tool calls? ──────────────────────────────────────────────────────────
    if message and message.tool_calls:
        tool_calls = [
            ToolCallInfo(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in message.tool_calls
        ]
        print(f"[h_company] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=reasoning,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    # ── No tool calls — parse JSON action from text ──────────────────────────
    data = _extract_json(content)
    data = _sanitize_action(data)

    raw_action = data.get("action", {"type": "done"})
    if isinstance(raw_action, str):
        raw_action = {"type": raw_action}

    return AgentResponse(
        action=Action(**raw_action),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        reasoning_content=reasoning,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _extract_json(content: str) -> dict:
    """Pull the JSON object out of the model's text response."""
    text = content.strip()

    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

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
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    print(f"[h_company] INFO: plain-text response, wrapping as unknown:\n  {content[:200]}")
    return {"action": {"type": "unknown"}, "done": False, "final_message": content.strip(), "confidence": 0.0}


def _sanitize_action(data: dict) -> dict:
    """Enforce one-action-per-response; strip batched keys and unwrap nested actions."""
    for key in ("next", "next_action", "actions", "step2", "then", "followup"):
        if key in data:
            print(f"[h_company] WARN: stripped batched key '{key}' from response")
            del data[key]

    fm = data.get("final_message")
    if isinstance(fm, str) and fm.strip().startswith("{"):
        try:
            inner = json.loads(fm)
            if isinstance(inner, dict) and "action" in inner:
                print(f"[h_company] WARN: final_message contained nested action — extracting")
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
    s = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', s)
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)
    return s
