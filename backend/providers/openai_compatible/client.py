"""
client.py — OpenAI-compatible endpoint client (vLLM, SGLang, Ollama, etc.)

For self-hosted GPU inference. Connects to any server that implements the
OpenAI /v1/chat/completions API. Uses Chat Completions (not Responses API)
since that's the standard implemented by open-source serving frameworks.

Tested with:
  - vLLM (https://docs.vllm.ai/en/stable/serving/openai_compatible_server/)
    Start: vllm serve <model> --port 8000
    Set:   OPENAI_BASE_URL=http://localhost:8000/v1

  - SGLang (https://docs.sglang.io/basic_usage/openai_api_completions.html)
    Start: sglang serve <model> --port 30000
    Set:   OPENAI_BASE_URL=http://localhost:30000/v1

  - Ollama (https://github.com/ollama/ollama/blob/main/docs/openai.md)
    Start: ollama serve
    Set:   OPENAI_BASE_URL=http://localhost:11434/v1

Both vLLM and SGLang implement /v1/chat/completions, /v1/completions,
and /v1/models. They auto-apply HuggingFace chat templates and support
vision models with base64 image input via the image_url content type.

vLLM also supports tool calling (--tool-call-parser) and reasoning
content (--enable-reasoning) for compatible models.

Drop-in replacement for other providers — same public interface:

    call_model(agent_req: AgentRequest) -> AgentResponse
    is_ready() -> bool
    ensure_ready(**kwargs) -> None

Environment:
    OPENAI_BASE_URL     — required (e.g. http://localhost:8000/v1)
    OPENAI_API_KEY      — optional (set to "none" or "sk-dummy" for local servers)
    OPENAI_COMPAT_MODEL — optional (default: auto-detected from /v1/models)
"""

import json
import os
import re
import time

import requests
from openai import OpenAI

from models import Action, AgentRequest, AgentResponse, MessageRole
from prompts import SYSTEM_PROMPT

# ── Configuration ────────────────────────────────────────────────────────────

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8000/v1")
API_KEY = os.environ.get("OPENAI_API_KEY", "none")
MODEL_NAME = os.environ.get("OPENAI_COMPAT_MODEL", "")
MAX_TOKENS = 1024
TEMPERATURE = 0.6

SCREENSHOT_PREFIX = "data:image/"

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# ── State ────────────────────────────────────────────────────────────────────

_ready = False
_resolved_model = MODEL_NAME


# ── Public API (matches provider interface) ──────────────────────────────────

def call_model(agent_req: AgentRequest) -> AgentResponse:
    global _resolved_model
    if not _resolved_model:
        _resolved_model = _detect_model()

    system_prompt, messages = _build_messages(agent_req)

    start = time.time()
    resp = client.chat.completions.create(
        model=_resolved_model,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{"role": "system", "content": system_prompt}] + messages,
    )
    elapsed_ms = int((time.time() - start) * 1000)

    return _parse_response(resp, elapsed_ms)


def is_ready() -> bool:
    return _ready


def ensure_ready(timeout: int = 300, poll_interval: int = 5, **kwargs) -> None:
    """Block until the server is healthy and has at least one model loaded."""
    global _ready, _resolved_model

    if _ready:
        return

    print(f"[openai_compat] Checking server at {BASE_URL}...")
    deadline = time.time() + timeout
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            models_url = BASE_URL.rstrip("/") + "/models"
            resp = requests.get(models_url, timeout=10)
            resp.raise_for_status()
            models = resp.json().get("data", [])

            if models:
                _ready = True
                if not _resolved_model:
                    _resolved_model = models[0].get("id", "unknown")
                model_ids = [m.get("id", "?") for m in models]
                print(f"[openai_compat] Server ready! Models: {model_ids}")
                print(f"[openai_compat] Using model: {_resolved_model}")
                return

            print(f"[openai_compat] attempt {attempt}: server up but no models loaded, retrying...")

        except requests.exceptions.ConnectionError:
            print(f"[openai_compat] attempt {attempt}: connection refused, retrying in {poll_interval}s...")
        except requests.exceptions.Timeout:
            print(f"[openai_compat] attempt {attempt}: timeout, retrying in {poll_interval}s...")
        except Exception as e:
            print(f"[openai_compat] attempt {attempt}: {type(e).__name__}: {e}, retrying...")

        time.sleep(poll_interval)

    raise TimeoutError(
        f"[openai_compat] Server not ready after {timeout}s ({attempt} attempts). "
        f"Is the server running at {BASE_URL}?"
    )


# ── Model detection ──────────────────────────────────────────────────────────

def _detect_model() -> str:
    """Query /v1/models to find the first available model."""
    try:
        models_url = BASE_URL.rstrip("/") + "/models"
        resp = requests.get(models_url, timeout=10)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        if models:
            model_id = models[0].get("id", "unknown")
            print(f"[openai_compat] Auto-detected model: {model_id}")
            return model_id
    except Exception as e:
        print(f"[openai_compat] Model detection failed: {e}")

    return "default"


# ── Message builder ──────────────────────────────────────────────────────────

def _build_messages(req: AgentRequest) -> tuple[str, list[dict]]:
    """Build (system_prompt, messages) in OpenAI Chat Completions format.

    Uses Chat Completions (not Responses API) since vLLM, SGLang, and
    Ollama all implement /v1/chat/completions. Image content is passed
    as type: "image_url" with a data URI, which both vLLM and SGLang
    support for vision models.
    """
    system_prompt = ""
    raw: list[dict] = []

    for pm in req.previous_messages:
        if pm.role == MessageRole.system:
            system_prompt = pm.content
        elif pm.role == MessageRole.assistant:
            raw.append({"role": "assistant", "content": pm.content})
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

    return system_prompt or SYSTEM_PROMPT.strip(), raw


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_response(resp, elapsed_ms: int) -> AgentResponse:
    choice = resp.choices[0] if resp.choices else None
    message = choice.message if choice else None
    content = message.content or "" if message else ""

    # vLLM with --enable-reasoning surfaces reasoning_content on the message
    reasoning = getattr(message, "reasoning_content", None) if message else None

    data = _extract_json(content)

    return AgentResponse(
        action=Action(**data.get("action", {"type": "done"})),
        done=data.get("done", False),
        final_message=data.get("final_message"),
        confidence=data.get("confidence", 1.0),
        reasoning_content=reasoning,
        inference_time_ms=elapsed_ms,
        model_name=_resolved_model,
    )


def _extract_json(content: str) -> dict:
    """Pull the JSON object out of the model's text response."""
    text = content.strip()

    # Strip markdown fences
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Isolate outermost { … }
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start : brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Common VLM JSON repairs
    repaired = _repair_json(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Plain text response — treat as conversational done, not a loop
    print(f"[openai_compat] INFO: plain-text response, wrapping as done:\n  {content[:200]}")
    return {"action": {"type": "done"}, "done": True, "final_message": content.strip(), "confidence": 0.9}


def _repair_json(text: str) -> str:
    """Best-effort repairs for common VLM JSON mistakes."""
    s = text
    # Unquoted keys
    s = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)"(\s*:)', r'\1"\2"\3', s)
    s = re.sub(r'([{,]\s*)([a-zA-Z_]\w*)(\s*:)', r'\1"\2"\3', s)
    # Single quotes → double quotes
    s = s.replace("'", '"')
    # Trailing commas
    s = re.sub(r',\s*([}\]])', r'\1', s)
    # Malformed coordinates: {"x":255,219} → {"x":255,"y":219}
    s = re.sub(r'"x"\s*:\s*(\d+)\s*,\s*(\d+)\s*}', r'"x":\1,"y":\2}', s)
    # Python booleans / None
    s = re.sub(r'\bTrue\b', 'true', s)
    s = re.sub(r'\bFalse\b', 'false', s)
    s = re.sub(r'\bNone\b', 'null', s)
    return s
