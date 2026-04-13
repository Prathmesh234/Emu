"""
client.py — Anthropic Claude API client

Uses native tool calling for agent tools (plan, memory, skills, etc.).
Desktop actions are returned as JSON text responses.

Environment:
    ANTHROPIC_API_KEY  — required
"""

import json
import re
import time

import anthropic

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import tools_for_anthropic

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = "claude-sonnet-4-5"
MAX_TOKENS = 8000
THINKING_BUDGET = 5000  # tokens reserved for extended thinking

SCREENSHOT_PREFIX = "data:image/"

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
ANTHROPIC_TOOLS = tools_for_anthropic()


# ── Public API ───────────────────────────────────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_blocks, messages = _build_messages(agent_req)

    start = time.time()
    resp = client.messages.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        system=system_blocks,
        tools=ANTHROPIC_TOOLS,
        thinking={"type": "enabled", "budget_tokens": THINKING_BUDGET},
        messages=messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return True


def ensure_ready(**kwargs) -> None:
    pass


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> tuple[list[dict], list[dict]]:
    """Build (system_blocks, messages) in Anthropic format.

    Splits the system prompt at the <session> tag so the large static prefix
    gets cache_control and stays cached across turns, while the small
    dynamic session/workspace block changes freely.
    """
    system_text = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_text = pm.content

        elif pm.role == MessageRole.assistant:
            if pm.tool_calls:
                # Anthropic: assistant message with tool_use content blocks
                content = []
                if pm.content:
                    content.append({"type": "text", "text": pm.content})
                for tc in pm.tool_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args,
                    })
                raw.append({"role": "assistant", "content": content})
            else:
                raw.append({"role": "assistant", "content": pm.content})

        elif pm.role == MessageRole.tool:
            # Anthropic: tool results are user messages with tool_result blocks
            raw.append({"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": pm.tool_call_id or "",
                "content": pm.content,
            }]})

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

    if not system_text:
        system_text = ""

    # Split at <session> to separate static (cacheable) from dynamic
    session_marker = "<session>"
    if session_marker in system_text:
        static_part, dynamic_part = system_text.split(session_marker, 1)
        system_blocks = [
            {
                "type": "text",
                "text": static_part.rstrip(),
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": session_marker + dynamic_part,
            },
        ]
    else:
        # Fallback: no session marker — cache the whole thing
        system_blocks = [{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }] if system_text else []

    return system_blocks, _merge_consecutive(raw)


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
    # Check for tool_use blocks first; also collect thinking and text
    tool_calls = []
    text_parts = []
    thinking_parts = []

    for block in resp.content:
        if block.type == "thinking":
            thinking_parts.append(block.thinking)
        elif block.type == "tool_use":
            tool_calls.append(ToolCallInfo(
                id=block.id,
                name=block.name,
                arguments=json.dumps(block.input),
            ))
        elif block.type == "text":
            text_parts.append(block.text)

    reasoning = "".join(thinking_parts) or None
    content = "".join(text_parts)

    if tool_calls:
        print(f"[claude] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=reasoning,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    # No tool calls — parse JSON desktop action from text
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


def _fix_literal_newlines(text: str) -> str:
    """Escape literal newlines/tabs inside JSON string values."""
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

    repaired = _fix_literal_newlines(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    repaired = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', repaired)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    print(f"[claude] INFO: plain-text response, wrapping as unknown:\n  {content[:200]}")
    return {"action": {"type": "unknown"}, "done": False, "final_message": content.strip(), "confidence": 0.0}


def _sanitize_action(data: dict) -> dict:
    """
    Enforce one-action-per-response and fix common model formatting mistakes.

    Strips batched/nested keys the model sometimes adds (next_action, actions[],
    step2, etc.) and unwraps any action accidentally nested inside final_message.
    """
    # Strip extra action keys the model may batch
    for key in ("next", "next_action", "actions", "step2", "then", "followup"):
        if key in data:
            print(f"[claude] WARN: stripped batched key '{key}' from response")
            del data[key]

    # Unwrap action accidentally embedded inside final_message
    fm = data.get("final_message")
    if isinstance(fm, str) and fm.strip().startswith("{"):
        try:
            inner = json.loads(fm)
            if isinstance(inner, dict) and "action" in inner:
                print(f"[claude] WARN: final_message contained nested action — extracting")
                data["action"] = inner["action"]
                data["done"] = inner.get("done", False)
                data["confidence"] = inner.get("confidence", data.get("confidence", 1.0))
                data["final_message"] = inner.get("final_message")
        except (json.JSONDecodeError, ValueError):
            pass

    return data
