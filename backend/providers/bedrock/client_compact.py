"""
client_compact.py — Amazon Bedrock compaction client
"""

import json
import os
import time
from typing import TYPE_CHECKING

import boto3

from prompts.compact_prompt import COMPACT_SYSTEM_PROMPT

if TYPE_CHECKING:
    from models import PreviousMessage

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_NAME = os.environ.get("BEDROCK_MODEL", "anthropic.claude-sonnet-4-20250514-v1:0")
MAX_TOKENS = 4096

_client = None


def _get_client():
    global _client
    if _client is None:
        session = boto3.Session(
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
        )
        _client = session.client("bedrock-runtime", region_name=AWS_REGION)
    return _client


def compact(messages: list["PreviousMessage"]) -> str:
    api_messages = _build_messages(messages)

    start = time.time()
    resp = _get_client().converse(
        modelId=MODEL_NAME,
        system=[{"text": COMPACT_SYSTEM_PROMPT}],
        messages=api_messages,
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    elapsed_ms = int((time.time() - start) * 1000)

    output = resp.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])
    summary = ""
    for block in content_blocks:
        if "text" in block:
            summary += block["text"]

    print(f"[compact/bedrock] Summarised in {elapsed_ms}ms  ({len(summary)} chars)")
    return summary


def _build_messages(messages: list["PreviousMessage"]) -> list[dict]:
    from models import MessageRole

    raw: list[dict] = []
    for pm in messages:
        if pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": [{"text": pm.content or ""}]})
        elif pm.role == MessageRole.user:
            raw.append({"role": "user", "content": [{"text": pm.content or ""}]})
    return raw
