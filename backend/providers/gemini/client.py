"""
client.py — Google Gemini API client

Uses native function calling for agent tools (plan, memory, skills, etc.).
Desktop actions are returned as JSON text responses.

Docs: https://ai.google.dev/gemini-api/docs

Environment:
    GOOGLE_API_KEY  — required
    GEMINI_MODEL    — optional (default: gemini-3-flash-preview)
"""

import base64
import json
import os
import re
import time
import uuid

from google import genai
from google.genai import types

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import tools_for_gemini

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY"))
GEMINI_TOOLS = tools_for_gemini()


# ── Public API ───────────────────────────────────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, contents = _build_contents(agent_req)

    start = time.time()
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=MAX_TOKENS,
            tools=GEMINI_TOOLS,
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
    """Build (system_prompt, contents) using Gemini types."""
    system_prompt = ""
    contents: list[types.Content] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content

        elif pm.role == MessageRole.assistant:
            if pm.tool_calls:
                # Gemini: model turn with function_call parts
                parts = []
                if pm.content:
                    parts.append(types.Part(text=pm.content))
                for tc in pm.tool_calls:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    fc_kwargs = {"name": fn.get("name", ""), "args": args}
                    # Pass ID if available (Gemini 3+ requires matching IDs)
                    tc_id = tc.get("id")
                    if tc_id:
                        fc_kwargs["id"] = tc_id
                    parts.append(types.Part(
                        function_call=types.FunctionCall(**fc_kwargs)
                    ))
                contents.append(types.Content(role="model", parts=parts))
            else:
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part(text=pm.content)],
                ))

        elif pm.role == MessageRole.tool:
            # Gemini: function_response as a user turn
            tool_name = pm.tool_name or _find_tool_name(contents, pm.tool_call_id)
            fr_kwargs = {"name": tool_name, "response": {"result": pm.content}}
            # Pass matching ID if available (Gemini 3+ requires it)
            if pm.tool_call_id:
                fr_kwargs["id"] = pm.tool_call_id
            contents.append(types.Content(
                role="user",
                parts=[types.Part(
                    function_response=types.FunctionResponse(**fr_kwargs)
                )],
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

    contents = _merge_consecutive(contents)
    return system_prompt or "", contents


def _find_tool_name(contents: list[types.Content], tool_call_id: str | None) -> str:
    """Find the tool name from the preceding model turn's function_call parts."""
    for content in reversed(contents):
        if content.role == "model":
            for part in content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    return part.function_call.name
    return "unknown"


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
    # Check for function_call parts
    tool_calls = []
    text_parts = []

    candidate = resp.candidates[0] if resp.candidates else None
    if candidate and candidate.content:
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                # Gemini 3+ provides IDs; older models may not
                fc_id = getattr(fc, "id", None) or str(uuid.uuid4())
                tool_calls.append(ToolCallInfo(
                    id=fc_id,
                    name=fc.name,
                    arguments=json.dumps(fc.args) if fc.args else "{}",
                ))
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

    if tool_calls:
        print(f"[gemini] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=None,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    # No tool calls — parse JSON desktop action from text
    content = "".join(text_parts) or (resp.text or "")
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
        reasoning_content=None,
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

    repaired = text
    repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
    repaired = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', repaired)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    print(f"[gemini] INFO: plain-text response, wrapping as unknown:\n  {content[:200]}")
    return {"action": {"type": "unknown"}, "done": False, "final_message": content.strip(), "confidence": 0.0}


def _sanitize_action(data: dict) -> dict:
    """Enforce one-action-per-response; strip batched keys and unwrap nested actions."""
    for key in ("next", "next_action", "actions", "step2", "then", "followup"):
        if key in data:
            print(f"[gemini] WARN: stripped batched key '{key}' from response")
            del data[key]

    fm = data.get("final_message")
    if isinstance(fm, str) and fm.strip().startswith("{"):
        try:
            inner = json.loads(fm)
            if isinstance(inner, dict) and "action" in inner:
                print(f"[gemini] WARN: final_message contained nested action — extracting")
                data["action"] = inner["action"]
                data["done"] = inner.get("done", False)
                data["confidence"] = inner.get("confidence", data.get("confidence", 1.0))
                data["final_message"] = inner.get("final_message")
        except (json.JSONDecodeError, ValueError):
            pass

    return data
