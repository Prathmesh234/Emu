"""
client.py — Azure OpenAI API client

Uses the OpenAI Python SDK with Azure-specific configuration.
Supports function calling for agent tools and vision (image) inputs.

Docs: https://learn.microsoft.com/en-us/azure/ai-services/openai/

Environment:
    AZURE_OPENAI_API_KEY    — required (or use Azure AD via AZURE_OPENAI_AD_TOKEN)
    AZURE_OPENAI_ENDPOINT   — required (e.g. https://myresource.openai.azure.com)
    AZURE_OPENAI_MODEL      — deployment name (default: gpt-4o)
    AZURE_OPENAI_API_VERSION — API version (default: 2024-12-01-preview)
"""

import json
import os
import re
import time

from openai import AzureOpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo
from providers.agent_tools import AGENT_TOOLS_OPENAI

# -- Configuration -----------------------------------------------------------

API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AD_TOKEN = os.environ.get("AZURE_OPENAI_AD_TOKEN", "")
ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
MODEL_NAME = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o")
API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
MAX_TOKENS = 8000
TEMPERATURE = 0.6

SCREENSHOT_PREFIX = "data:image/"

_client = None


def _get_client():
    global _client
    if _client is None:
        kwargs = {
            "azure_endpoint": ENDPOINT,
            "api_version": API_VERSION,
        }
        if AD_TOKEN:
            kwargs["azure_ad_token"] = AD_TOKEN
        else:
            kwargs["api_key"] = API_KEY
        _client = AzureOpenAI(**kwargs)
    return _client


# -- Public API (matches provider interface) ---------------------------------

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, messages = _build_messages(agent_req)

    start = time.time()
    resp = _get_client().chat.completions.create(
        model=MODEL_NAME,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        tools=AGENT_TOOLS_OPENAI,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return bool(ENDPOINT) and bool(API_KEY or AD_TOKEN)


def ensure_ready(**kwargs) -> None:
    if not ENDPOINT:
        raise RuntimeError(
            "[azure_openai] AZURE_OPENAI_ENDPOINT is not set."
        )
    if not API_KEY and not AD_TOKEN:
        raise RuntimeError(
            "[azure_openai] Set AZURE_OPENAI_API_KEY or AZURE_OPENAI_AD_TOKEN."
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
        print(f"[azure_openai] tool_calls: {[tc.name for tc in tool_calls]}")
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
            print(f"[azure_openai] WARN: stripped batched key '{key}' from response")
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

    print(f"[azure_openai] INFO: plain-text response, wrapping as done")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 1.0}
