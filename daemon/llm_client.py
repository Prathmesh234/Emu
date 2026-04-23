"""
llm_client.py — Agent loop for the memory daemon.

Supports:
  claude           → Anthropic SDK (anthropic)
  openai           → OpenAI SDK (openai)
  openrouter       → OpenAI SDK, base_url=https://openrouter.ai/api/v1
  fireworks        → OpenAI SDK, base_url=https://api.fireworks.ai/inference/v1
  together_ai      → OpenAI SDK, base_url=https://api.together.xyz/v1
  openai_compatible→ OpenAI SDK, base_url=OPENAI_BASE_URL
  baseten          → OpenAI SDK, base_url=BASETEN_API_URL

Provider is selected by EMU_DAEMON_PROVIDER env var (default: claude).
API key comes from EMU_DAEMON_API_KEY env var, then macOS Keychain, then
the provider's own key env var.

Note: bedrock, gemini, h_company, and modal are not yet supported by the
daemon's agent loop. Adding them is a matter of implementing the
_run_loop_* variant for that SDK.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .tools import DispatchState, TOOLS


# ── Provider defaults ─────────────────────────────────────────────────────────

_PROVIDER_DEFAULTS: dict[str, dict] = {
    "claude":            {"model": "claude-sonnet-4-6"},
    "openai":            {"model": "gpt-4o",           "base_url": "https://api.openai.com/v1"},
    "openrouter":        {"model": "anthropic/claude-sonnet-4-6", "base_url": "https://openrouter.ai/api/v1"},
    "fireworks":         {"model": "accounts/fireworks/models/llama-v3p1-70b-instruct", "base_url": "https://api.fireworks.ai/inference/v1"},
    "together_ai":       {"model": "meta-llama/Llama-3.1-70B-Instruct-Turbo", "base_url": "https://api.together.xyz/v1"},
    "openai_compatible": {"model": os.environ.get("OPENAI_MODEL", "default"), "base_url": os.environ.get("OPENAI_BASE_URL", "")},
    "baseten":           {"model": os.environ.get("BASETEN_MODEL", ""), "base_url": os.environ.get("BASETEN_API_URL", "")},
}

_KEY_ENV_MAP: dict[str, str] = {
    "claude":            "ANTHROPIC_API_KEY",
    "openai":            "OPENAI_API_KEY",
    "openrouter":        "OPENROUTER_API_KEY",
    "fireworks":         "FIREWORKS_API_KEY",
    "together_ai":       "TOGETHER_API_KEY",
    "openai_compatible": "OPENAI_API_KEY",
    "baseten":           "BASETEN_API_KEY",
}

_UNSUPPORTED_PROVIDERS = {"bedrock", "gemini", "h_company", "modal"}


@dataclass
class AgentRunResult:
    run_id: str
    turns: int
    tokens_in: int
    tokens_out: int
    written_paths: list[Path]
    policy_violations: int
    finish_summary: str
    status: str  # "ok" | "max_turns" | "max_tokens" | "error"
    error: str = ""


# ── Public entry point ────────────────────────────────────────────────────────

def run_agent_loop(
    system: str,
    user: str,
    tools: list[dict],
    tool_dispatcher: Callable[[str, dict, DispatchState], str],
    max_turns: int,
    max_total_tokens: int,
) -> AgentRunResult:
    run_id = f"tick-{uuid.uuid4().hex[:12]}"
    provider = os.environ.get("EMU_DAEMON_PROVIDER", "claude").strip().lower()

    if provider in _UNSUPPORTED_PROVIDERS:
        raise RuntimeError(
            f"Provider {provider!r} is not supported by the memory daemon. "
            f"Set EMU_DAEMON_PROVIDER to one of: {sorted(_PROVIDER_DEFAULTS)}"
        )

    api_key = _resolve_api_key(provider)

    if provider == "claude":
        return _run_anthropic(
            run_id, api_key, system, user, tools, tool_dispatcher,
            max_turns, max_total_tokens,
        )
    else:
        return _run_openai_compat(
            run_id, provider, api_key, system, user, tools, tool_dispatcher,
            max_turns, max_total_tokens,
        )


# ── API key resolution ────────────────────────────────────────────────────────

def _resolve_api_key(provider: str) -> str:
    # 1. EMU_DAEMON_API_KEY override
    key = os.environ.get("EMU_DAEMON_API_KEY", "").strip()
    if key:
        return key

    # 2. macOS Keychain
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "com.emu.memory-daemon", "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            key = result.stdout.strip()
            if key:
                return key
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 3. Provider-specific env var
    env_var = _KEY_ENV_MAP.get(provider, "")
    if env_var:
        key = os.environ.get(env_var, "").strip()
        if key:
            return key

    raise RuntimeError(
        f"No API key found for provider {provider!r}. "
        f"Set EMU_DAEMON_API_KEY or {_KEY_ENV_MAP.get(provider, '<PROVIDER>_API_KEY')} "
        "in your .env, or store it in Keychain under 'com.emu.memory-daemon'."
    )


# ── Anthropic agent loop ──────────────────────────────────────────────────────

def _run_anthropic(
    run_id: str,
    api_key: str,
    system: str,
    user: str,
    tools: list[dict],
    dispatcher: Callable,
    max_turns: int,
    max_total_tokens: int,
) -> AgentRunResult:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    dispatch_state = DispatchState()

    messages: list[dict] = [{"role": "user", "content": user}]
    tokens_in = 0
    tokens_out = 0
    turns = 0

    # Convert tool defs to Anthropic format (they already match)
    anthropic_tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in tools
    ]

    while turns < max_turns:
        resp = client.messages.create(
            model=_PROVIDER_DEFAULTS["claude"]["model"],
            max_tokens=8192,
            system=system,
            tools=anthropic_tools,
            messages=messages,
        )

        tokens_in += resp.usage.input_tokens
        tokens_out += resp.usage.output_tokens
        turns += 1

        if tokens_in + tokens_out > max_total_tokens:
            return AgentRunResult(
                run_id=run_id, turns=turns,
                tokens_in=tokens_in, tokens_out=tokens_out,
                written_paths=dispatch_state.written_paths,
                policy_violations=dispatch_state.policy_violations,
                finish_summary=dispatch_state.finish_summary,
                status="max_tokens",
            )

        # Collect tool use blocks and text
        tool_calls = [b for b in resp.content if b.type == "tool_use"]
        text_blocks = [b for b in resp.content if b.type == "text"]

        # Build assistant message for history
        assistant_content = []
        for b in text_blocks:
            assistant_content.append({"type": "text", "text": b.text})
        for b in tool_calls:
            assistant_content.append({
                "type": "tool_use",
                "id": b.id,
                "name": b.name,
                "input": b.input,
            })
        messages.append({"role": "assistant", "content": assistant_content})

        if not tool_calls:
            # No tool calls — model is done (or should have called finish)
            break

        # Dispatch all tool calls and collect results
        tool_results = []
        for tc in tool_calls:
            result_text = dispatcher(tc.name, tc.input, dispatch_state)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result_text,
            })
            if dispatch_state.finished:
                break

        messages.append({"role": "user", "content": tool_results})

        if dispatch_state.finished:
            break

    status = "ok" if dispatch_state.finished else ("max_turns" if turns >= max_turns else "ok")
    return AgentRunResult(
        run_id=run_id, turns=turns,
        tokens_in=tokens_in, tokens_out=tokens_out,
        written_paths=dispatch_state.written_paths,
        policy_violations=dispatch_state.policy_violations,
        finish_summary=dispatch_state.finish_summary,
        status=status,
    )


# ── OpenAI-compatible agent loop ─────────────────────────────────────────────

def _run_openai_compat(
    run_id: str,
    provider: str,
    api_key: str,
    system: str,
    user: str,
    tools: list[dict],
    dispatcher: Callable,
    max_turns: int,
    max_total_tokens: int,
) -> AgentRunResult:
    from openai import OpenAI

    defaults = _PROVIDER_DEFAULTS.get(provider, {})
    base_url = defaults.get("base_url") or None
    model = os.environ.get("EMU_DAEMON_MODEL") or defaults.get("model", "gpt-4o")

    client = OpenAI(api_key=api_key, base_url=base_url)
    dispatch_state = DispatchState()

    # Convert tool defs to OpenAI function-calling format
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    tokens_in = 0
    tokens_out = 0
    turns = 0

    # Bounded retry for transient upstream hiccups (OpenRouter occasionally
    # returns a 200 with {"error": {...}} and no choices — we retry rather
    # than failing the whole tick).
    EMPTY_CHOICE_RETRIES = 3
    empty_choice_attempts = 0

    while turns < max_turns:
        resp = client.chat.completions.create(
            model=model,
            tools=openai_tools,
            tool_choice="auto",
            messages=messages,
        )

        usage = resp.usage
        if usage:
            tokens_in += usage.prompt_tokens
            tokens_out += usage.completion_tokens
        turns += 1

        if tokens_in + tokens_out > max_total_tokens:
            return AgentRunResult(
                run_id=run_id, turns=turns,
                tokens_in=tokens_in, tokens_out=tokens_out,
                written_paths=dispatch_state.written_paths,
                policy_violations=dispatch_state.policy_violations,
                finish_summary=dispatch_state.finish_summary,
                status="max_tokens",
            )

        if not resp.choices:
            # Upstream returned an error envelope with no choices; retry a
            # few times before giving up.
            empty_choice_attempts += 1
            err_obj = getattr(resp, "error", None)
            print(
                f"[daemon] empty choices from upstream "
                f"(attempt {empty_choice_attempts}/{EMPTY_CHOICE_RETRIES}) — "
                f"error={err_obj!r}",
                file=sys.stderr,
            )
            if empty_choice_attempts >= EMPTY_CHOICE_RETRIES:
                return AgentRunResult(
                    run_id=run_id, turns=turns,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                    written_paths=dispatch_state.written_paths,
                    policy_violations=dispatch_state.policy_violations,
                    finish_summary=dispatch_state.finish_summary,
                    status="error",
                    error=f"upstream returned no choices after {EMPTY_CHOICE_RETRIES} retries: {err_obj!r}",
                )
            continue  # retry without advancing the conversation

        empty_choice_attempts = 0  # reset after a successful response
        choice = resp.choices[0]
        msg = choice.message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result_text = dispatcher(tc.function.name, args, dispatch_state)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            })
            if dispatch_state.finished:
                break

        if dispatch_state.finished:
            break

        if choice.finish_reason == "stop":
            break

    status = "ok" if dispatch_state.finished else ("max_turns" if turns >= max_turns else "ok")
    return AgentRunResult(
        run_id=run_id, turns=turns,
        tokens_in=tokens_in, tokens_out=tokens_out,
        written_paths=dispatch_state.written_paths,
        policy_violations=dispatch_state.policy_violations,
        finish_summary=dispatch_state.finish_summary,
        status=status,
    )
