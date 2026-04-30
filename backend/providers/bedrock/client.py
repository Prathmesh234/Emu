"""
client.py — Amazon Bedrock API client

Uses the OpenAI Python SDK against the Bedrock OpenAI-compatible endpoint.
Requires boto3 for SigV4 request signing.

Docs: https://docs.aws.amazon.com/bedrock/latest/userguide/

Environment:
    AWS_ACCESS_KEY_ID       — required
    AWS_SECRET_ACCESS_KEY   — required
    AWS_REGION              — required (default: us-east-1)
    BEDROCK_MODEL           — model ID (default: anthropic.claude-sonnet-4-20250514-v1:0)
"""

import json
import os
import time

import boto3
from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole, ToolCallInfo, safe_build_action
from providers.agent_tools import get_agent_tools_openai

# -- Configuration -----------------------------------------------------------

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_NAME = os.environ.get("BEDROCK_MODEL", "anthropic.claude-sonnet-4-20250514-v1:0")
MAX_TOKENS = 8000
TEMPERATURE = 0.6

SCREENSHOT_PREFIX = "data:image/"

_client = None


def _get_client():
    """Build an OpenAI client that signs requests for Bedrock."""
    global _client
    if _client is None:
        session = boto3.Session(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
        bedrock = session.client("bedrock-runtime", region_name=AWS_REGION)
        base_url = f"https://bedrock-runtime.{AWS_REGION}.amazonaws.com/model/{MODEL_NAME}/converse"

        # Bedrock supports OpenAI-compatible chat completions via the converse stream endpoint
        # Use boto3 converse API directly for full compatibility
        _client = bedrock
    return _client


# -- Public API (matches provider interface) ---------------------------------

def call_model(agent_req: AgentRequest) -> AgentResponse:
    system_prompt, messages = _build_messages(agent_req)

    bedrock = _get_client()

    tool_config = _build_tool_config(agent_req.agent_mode)

    kwargs = {
        "modelId": MODEL_NAME,
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
        },
    }
    if system_prompt:
        kwargs["system"] = [{"text": system_prompt}]
    if tool_config:
        kwargs["toolConfig"] = tool_config

    start = time.time()
    resp = bedrock.converse(**kwargs)
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return bool(AWS_ACCESS_KEY_ID) and bool(AWS_SECRET_ACCESS_KEY)


def ensure_ready(**kwargs) -> None:
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise RuntimeError(
            "[bedrock] AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set."
        )


# -- Tool config builder (Bedrock native format) ----------------------------

def _build_tool_config(agent_mode: str | None = "remote") -> dict:
    """Convert mode-aware OpenAI tool catalogue to Bedrock toolConfig format."""
    tools = []
    for tool in get_agent_tools_openai(agent_mode):
        func = tool["function"]
        spec = {
            "name": func["name"],
            "description": func.get("description", ""),
            "inputSchema": {
                "json": func.get("parameters", {"type": "object", "properties": {}})
            },
        }
        tools.append({"toolSpec": spec})
    return {"tools": tools} if tools else {}


# -- Message builder (Bedrock Converse format) --------------------------------

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in Bedrock Converse format."""
    system_prompt = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content

        elif pm.role == MessageRole.assistant:
            content_blocks = []
            if pm.tool_calls:
                for tc in pm.tool_calls:
                    tc_dict = tc if isinstance(tc, dict) else tc
                    func = tc_dict.get("function", tc_dict)
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    content_blocks.append({
                        "toolUse": {
                            "toolUseId": tc_dict.get("id", ""),
                            "name": func.get("name", ""),
                            "input": args,
                        }
                    })
                if pm.content:
                    content_blocks.insert(0, {"text": pm.content})
            else:
                content_blocks.append({"text": pm.content or ""})
            raw.append({"role": "assistant", "content": content_blocks})

        elif pm.role == MessageRole.tool:
            raw.append({
                "role": "user",
                "content": [{
                    "toolResult": {
                        "toolUseId": pm.tool_call_id or "",
                        "content": [{"text": pm.content or ""}],
                    }
                }],
            })

        elif pm.role == MessageRole.user:
            if pm.content.startswith(SCREENSHOT_PREFIX):
                # Extract base64 and media type from data URI
                media_type, b64_data = _parse_data_uri(pm.content)
                raw.append({
                    "role": "user",
                    "content": [{
                        "image": {
                            "format": _bedrock_image_format(media_type),
                            "source": {"bytes": _b64_to_bytes(b64_data)},
                        }
                    }],
                })
            else:
                raw.append({"role": "user", "content": [{"text": pm.content}]})

    return system_prompt or "", raw


def _parse_data_uri(uri: str) -> tuple[str, str]:
    """Parse 'data:image/webp;base64,AAAA...' into (media_type, base64_data)."""
    header, data = uri.split(",", 1)
    media_type = header.split(":")[1].split(";")[0]
    return media_type, data


def _bedrock_image_format(media_type: str) -> str:
    """Map MIME type to Bedrock image format string."""
    mapping = {
        "image/jpeg": "jpeg",
        "image/png": "png",
        "image/gif": "gif",
        "image/webp": "webp",
    }
    return mapping.get(media_type, "jpeg")


def _b64_to_bytes(b64: str) -> bytes:
    import base64
    return base64.b64decode(b64)


# -- Response parser ---------------------------------------------------------

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    output = resp.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])

    text_parts = []
    tool_calls = []

    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
        elif "toolUse" in block:
            tu = block["toolUse"]
            tool_calls.append(
                ToolCallInfo(
                    id=tu.get("toolUseId", ""),
                    name=tu.get("name", ""),
                    arguments=json.dumps(tu.get("input", {})),
                )
            )

    content = "\n".join(text_parts)

    if tool_calls:
        print(f"[bedrock] tool_calls: {[tc.name for tc in tool_calls]}")
        return AgentResponse(
            tool_calls=tool_calls,
            done=False,
            inference_time_ms=elapsed_ms,
            model_name=MODEL_NAME,
        )

    data = _extract_json(content)
    data = _sanitize_single_action(data)

    raw_action = data.get("action", {"type": "done"})
    if isinstance(raw_action, str):
        raw_action = {"type": raw_action}

    return AgentResponse(
        action=safe_build_action(raw_action, "bedrock"),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        inference_time_ms=elapsed_ms,
        model_name=MODEL_NAME,
    )


def _sanitize_single_action(data: dict) -> dict:
    for key in ("next", "next_action", "actions", "step2", "then"):
        if key in data:
            print(f"[bedrock] WARN: stripped batched key '{key}' from response")
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

    print(f"[bedrock] INFO: plain-text response, wrapping as unknown:\n  {content[:200]}")
    return {"action": {"type": "unknown"}, "done": False, "final_message": content.strip(), "confidence": 0.0}
