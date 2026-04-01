"""
client.py — OpenAI Responses API client

Uses the Responses API with native tool calling for agent tools.
Desktop actions are returned as JSON text responses.

Docs: https://platform.openai.com/docs/api-reference/responses

Environment:
    OPENAI_API_KEY  — required
    OPENAI_MODEL    — optional (default: gpt-5.4)
"""

import json
import os
import re
import time

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import AGENT_TOOLS_OPENAI

# ── Configuration ────────────────────────────────────────────────────────────

MODEL_NAME = os.environ.get("OPENAI_MODEL", "gpt-5.4")
MAX_TOKENS = 1024

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI()  # reads OPENAI_API_KEY from env

# Convert OpenAI Chat Completions tool format to Responses API format
RESPONSE_API_TOOLS = [
    {
        "type": "function",
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "parameters": t["function"]["parameters"],
    }
    for t in AGENT_TOOLS_OPENAI
]


# ── Public API ───────────────────────────────────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    instructions, input_messages = _build_input(agent_req)

    start = time.time()
    resp = client.responses.create(
        model=MODEL_NAME,
        instructions=instructions,
        input=input_messages,
        tools=RESPONSE_API_TOOLS,
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
    """Build (instructions, input) for the Responses API."""
    instructions = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            instructions = pm.content

        elif pm.role == MessageRole.assistant:
            if pm.tool_calls:
                # Responses API: function_call output items
                for tc in pm.tool_calls:
                    fn = tc.get("function", {})
                    raw.append({
                        "type": "function_call",
                        "call_id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "arguments": fn.get("arguments", "{}"),
                    })
            else:
                raw.append({"role": "assistant", "content": [
                    {"type": "output_text", "text": pm.content},
                ]})

        elif pm.role == MessageRole.tool:
            # Responses API: function_call_output
            raw.append({
                "type": "function_call_output",
                "call_id": pm.tool_call_id or "",
                "output": pm.content,
            })

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

    return instructions or "", raw


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    # Check for function_call outputs (tool calls)
    tool_calls = []
    text_parts = []

    for item in resp.output:
        if item.type == "function_call":
            tool_calls.append(ToolCallInfo(
                id=item.call_id,
                name=item.name,
                arguments=item.arguments,
            ))
        elif item.type == "message":
            for block in item.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)

    if tool_calls:
        print(f"[openai] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=None,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    # No tool calls — parse JSON desktop action from text
    content = "".join(text_parts) or resp.output_text or ""
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

    print(f"[openai] INFO: plain-text response, wrapping as unknown:\n  {content[:200]}")
    return {"action": {"type": "unknown"}, "done": False, "final_message": content.strip(), "confidence": 0.0}
