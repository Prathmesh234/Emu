"""
client.py — Baseten API client

Uses the OpenAI Chat Completions API format against Baseten's inference endpoint.

Docs: https://docs.baseten.co/api-reference/openai

Environment:
    BASETEN_API_KEY  — required
    BASETEN_MODEL    — optional (default: moonshotai/Kimi-K2.5)
"""

import json
import os
import time
import uuid

from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import AGENT_TOOLS_OPENAI, AGENT_TOOL_NAMES

# -- Configuration -----------------------------------------------------------

API_KEY = os.environ.get("BASETEN_API_KEY", "")
MODEL_NAME = os.environ.get("BASETEN_MODEL", "moonshotai/Kimi-K2.5")
BASE_URL = "https://inference.baseten.co/v1"
MAX_TOKENS = 8000
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
        tools=AGENT_TOOLS_OPENAI,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return bool(API_KEY)


def ensure_ready(**kwargs) -> None:
    if not API_KEY:
        raise RuntimeError(
            "[baseten] BASETEN_API_KEY is not set. "
            "Get one at https://app.baseten.co/settings/api-keys"
        )


# -- Message builder ---------------------------------------------------------

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
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


# -- Response parser ---------------------------------------------------------

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    choice = resp.choices[0] if resp.choices else None
    message = choice.message if choice else None
    content = message.content or "" if message else ""

    reasoning = getattr(message, "reasoning_content", None) if message else None

    if message and message.tool_calls:
        tool_calls = [
            ToolCallInfo(
                id=tc.id,
                name=tc.function.name,
                arguments=tc.function.arguments,
            )
            for tc in message.tool_calls
        ]
        print(f"[baseten] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            reasoning_content=reasoning,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    data = _extract_json(content)
    data = _sanitize_single_action(data)

    raw_action = data.get("action", {"type": "done"})
    if isinstance(raw_action, str):
        raw_action = {"type": raw_action}

    # HACK: Kimi-K2.5 often returns function tools (read_memory, update_plan, etc.)
    # as JSON text actions instead of using the function-calling API.  Intercept and
    # convert them to proper tool calls so main.py routes them correctly.
    # TODO: This workaround should be eliminated after supervised fine-tuning (SFT)
    # on the harness — a post-trained model should learn to use the function-calling
    # API for tools and reserve JSON text responses for desktop actions only.
    action_type = raw_action.get("type", "")
    if action_type in AGENT_TOOL_NAMES:
        args = {k: v for k, v in raw_action.items() if k != "type"}
        for key in ("content", "skill_name", "filename", "target", "date", "focus"):
            if key not in args and key in data:
                args[key] = data[key]
        print(f"[baseten] Rerouting text action '{action_type}' → function tool call")
        return AgentResponse(
            tool_calls=[ToolCallInfo(
                id=f"synth_{uuid.uuid4().hex[:8]}",
                name=action_type,
                arguments=json.dumps(args, ensure_ascii=False),
            )],
            done=False,
            reasoning_content=reasoning,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    return AgentResponse(
        action=Action(**raw_action),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        reasoning_content=reasoning,
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _sanitize_single_action(data: dict) -> dict:
    for key in ("next", "next_action", "actions", "step2", "then"):
        if key in data:
            print(f"[baseten] WARN: stripped batched key '{key}' from response")
            del data[key]
    return data


def _extract_json(content: str) -> dict:
    text = content.strip()

    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    brace_start = text.find("{")
    if brace_start != -1:
        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(text, brace_start)
            return obj
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    print(f"[baseten] INFO: plain-text response, wrapping as done")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 1.0}
