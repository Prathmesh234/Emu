import asyncio
import os
import secrets
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# Ensure the repo root is importable so `from daemon import run` resolves.
# main.py lives at <repo>/backend/main.py; the daemon package is at <repo>/daemon.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import json

from models import (
    Action,
    ActionType,
    AgentRequest,
    AgentResponse,
    ActionCompleteRequest,
    CompactRequest,
    ContinueSessionRequest,
    ProviderSettingsRequest,
    StopRequest,
)
from context_manager import ContextManager
from workspace import ensure_session_dir
from utilities import ConnectionManager, log_entry, log_and_send, ipc_to_action_label, interpret_action_error
from tools import execute_agent_tool, auto_compact

# ── Inference backend ────────────────────────────────────────────────────────
from providers.registry import load_provider, load_compact_provider
from context_manager.context import USE_OMNI_PARSER
from utilities.paths import get_emu_path

call_model, is_ready, ensure_ready, _provider_name = load_provider()
compact_model = load_compact_provider()

print(f"[config] OmniParser: {'ENABLED' if USE_OMNI_PARSER else 'DISABLED (direct screenshots)'}")

# ── Per-launch auth token ────────────────────────────────────────────────────
# Shared with the Electron frontend via .emu/.auth_token file.
AUTH_TOKEN = os.environ.get("EMU_AUTH_TOKEN") or secrets.token_hex(32)
_token_path = get_emu_path() / ".auth_token"
_token_path.parent.mkdir(parents=True, exist_ok=True)
_token_path.write_text(AUTH_TOKEN)
try:
    os.chmod(_token_path, 0o600)  # owner-only read/write
except OSError:
    pass  # Fallback if chmod not supported on this platform
print(f"[security] Auth token written to {_token_path}")


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject HTTP requests that don't carry a valid X-Emu-Token header."""

    async def dispatch(self, request, call_next):
        # CORS preflight and health checks are exempt
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        # NOTE: Do NOT exempt requests based on an `Upgrade: websocket` header —
        # FastAPI routes by path, not by the upgrade header, so a plain HTTP
        # POST that sets `Upgrade: websocket` would otherwise bypass auth on
        # normal HTTP routes (e.g. /agent/step, which can run shell_exec).
        # Real WebSocket upgrades are dispatched on the separate ASGI `websocket`
        # scope that never passes through HTTP middleware, and the endpoint
        # validates the token from the query param itself.
        token = request.headers.get("x-emu-token", "")
        if not token or not secrets.compare_digest(token, AUTH_TOKEN):
            print(f"[security] 401 on {request.method} {request.url.path} — token present={bool(token)}")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing auth token"},
            )
        return await call_next(request)


# ── Memory daemon ───────────────────────────────────────────────────────────
# The memory daemon is driven by macOS launchd (see daemon/launchd/ and
# daemon/install_macos.py), NOT by this process. That way it keeps ticking
# every 2 minutes even when uvicorn is shut down. The backend shares the
# same .emu/ directory with the daemon — no IPC between them.


app = FastAPI(title="Emulation Agent API")

# Middleware execution order in Starlette: LAST added = OUTERMOST.
# We need CORS to be outermost so its headers appear on ALL responses
# (including 401s from TokenAuth). So add CORS LAST.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(null|http://(127\.0\.0\.1|localhost)(:\d+)?)$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Emu-Token"],
)
app.add_middleware(TokenAuthMiddleware)

manager = ConnectionManager()
context_manager = ContextManager()


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer, got {raw!r}") from exc

    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer, got {raw!r}")

    return value


MODEL_TIMEOUT_SECS = _positive_int_env("EMU_MODEL_TIMEOUT_SECS", 60)
MAX_TIMEOUT_RETRIES = _positive_int_env("EMU_MODEL_TIMEOUT_RETRIES", 1)
print(f"[config] Model timeout: {MODEL_TIMEOUT_SECS}s, retries: {MAX_TIMEOUT_RETRIES}")


# ── Provider settings config ─────────────────────────────────────────────────
# Maps each short provider name → the env vars used for its API key and model.

_PROVIDER_SETTINGS: dict[str, dict] = {
    "claude":       {"key_env": "ANTHROPIC_API_KEY",  "model_env": "ANTHROPIC_MODEL",    "default_model": "claude-sonnet-4-5"},
    "openai":       {"key_env": "OPENAI_API_KEY",      "model_env": "OPENAI_MODEL",        "default_model": "gpt-5.4"},
    "openrouter":   {"key_env": "OPENROUTER_API_KEY",  "model_env": "OPENROUTER_MODEL",    "default_model": "anthropic/claude-sonnet-4"},
    "gemini":       {"key_env": "GOOGLE_API_KEY",      "model_env": "GEMINI_MODEL",        "default_model": "gemini-3-flash-preview"},
    "fireworks":    {"key_env": "FIREWORKS_API_KEY",   "model_env": "FIREWORKS_MODEL",     "default_model": "accounts/fireworks/models/llama4-maverick-instruct-basic"},
    "together_ai":  {"key_env": "TOGETHER_API_KEY",    "model_env": "TOGETHER_MODEL",      "default_model": "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8"},
    "baseten":      {"key_env": "BASETEN_API_KEY",     "model_env": "BASETEN_MODEL",       "default_model": "moonshotai/Kimi-K2.5"},
    "h_company":    {"key_env": "H_COMPANY_API_KEY",   "model_env": "H_COMPANY_MODEL",     "default_model": "holo3-35b-a3b"},
    "modal":        {"key_env": None,                  "model_env": None,                  "default_model": ""},
}


def _update_env_file(updates: dict) -> None:
    """Write key=value pairs into backend/.env, adding missing keys at the end."""
    env_path = Path(__file__).resolve().parent / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []

    written: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in written:
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/settings/provider")
async def get_provider_settings():
    """Return current provider/model configuration (API key is masked)."""
    provider = os.environ.get("EMU_PROVIDER", _provider_name)
    cfg = _PROVIDER_SETTINGS.get(provider, {})
    key_env = cfg.get("key_env")
    model_env = cfg.get("model_env")

    api_key = os.environ.get(key_env, "") if key_env else ""
    model = (
        os.environ.get(model_env, cfg.get("default_model", ""))
        if model_env
        else cfg.get("default_model", "")
    )

    masked = (
        ("*" * max(0, len(api_key) - 4) + api_key[-4:]) if len(api_key) > 4 else "*" * len(api_key)
    )

    return {
        "provider": provider,
        "model": model,
        "api_key_set": bool(api_key),
        "api_key_preview": masked,
        "providers": list(_PROVIDER_SETTINGS.keys()),
        "default_models": {k: v["default_model"] for k, v in _PROVIDER_SETTINGS.items()},
    }


@app.post("/settings/provider")
async def save_provider_settings(req: ProviderSettingsRequest):
    """Persist new provider/model/API key to .env and hot-reload the provider."""
    import importlib

    global call_model, is_ready, ensure_ready, _provider_name, compact_model

    provider = req.provider.strip().lower()
    if provider not in _PROVIDER_SETTINGS:
        return JSONResponse(status_code=400, content={"detail": f"Unknown provider: {provider}"})

    cfg = _PROVIDER_SETTINGS[provider]
    model = req.model.strip() or cfg["default_model"]
    api_key = req.api_key.strip()

    # Update environment in-process
    env_updates: dict[str, str] = {"EMU_PROVIDER": provider}
    os.environ["EMU_PROVIDER"] = provider
    if cfg["key_env"] and api_key:
        os.environ[cfg["key_env"]] = api_key
        env_updates[cfg["key_env"]] = api_key
    if cfg["model_env"] and model:
        os.environ[cfg["model_env"]] = model
        env_updates[cfg["model_env"]] = model

    # Persist to .env
    _update_env_file(env_updates)

    # Hot-reload provider module so the new env vars take effect
    try:
        from providers.registry import _PROVIDER_MAP
        module_path = _PROVIDER_MAP[provider]
        mod = importlib.import_module(module_path)
        importlib.reload(mod)

        try:
            compact_mod = importlib.import_module(f"{module_path}.client_compact")
            importlib.reload(compact_mod)
            compact_model = compact_mod.compact
        except Exception:
            pass

        call_model = mod.call_model
        is_ready = mod.is_ready
        ensure_ready = mod.ensure_ready
        _provider_name = provider
        print(f"[settings] Provider reloaded: {provider}  model={model}")
    except Exception as e:
        print(f"[settings] Reload failed: {e}")
        return JSONResponse(status_code=500, content={"detail": f"Provider reload failed: {e}"})

    return {"status": "ok", "provider": provider, "model": model}


@app.post("/agent/session")
async def create_session():
    """Create a new agent session."""
    session_id = str(uuid.uuid4())
    session_dir = ensure_session_dir(session_id)
    print(f"[session] created {session_id}  dir={session_dir}")
    return {"session_id": session_id}


@app.get("/agent/session/{session_id}")
async def get_session(session_id: str):
    """Return current session state."""
    return {"session_id": session_id, "status": "active"}


@app.post("/agent/step")
async def agent_step(req: AgentRequest):
    """
    Main agent loop entry point.

    Simple loop:
      1. Add user input to context
      2. Call model
      3. If tool_calls → execute tools, add results to context, re-call model (repeat)
      4. If desktop action → validate, dispatch to frontend
      5. If done → send final message
    """
    session_id = req.session_id or str(uuid.uuid4())
    has_screenshot = bool(req.base64_screenshot)
    has_text = bool(req.user_message.strip())
    context_manager.set_agent_mode(session_id, req.agent_mode)

    # ── 1. Add input to context ──────────────────────────────────────────────
    if has_screenshot:
        context_manager.add_screenshot_turn(session_id, req.base64_screenshot)
        log_entry(session_id, "[user] <screenshot>")
    if has_text:
        context_manager.add_user_message(session_id, req.user_message)
        await log_and_send(session_id, f"[user] {req.user_message}", manager)

    # ── Log ──────────────────────────────────────────────────────────────────
    history = context_manager._history.get(session_id, [])
    print(f"\n{'=' * 60}")
    print(f"[agent/step] session={session_id}  mode={'screenshot' if has_screenshot else 'text'}  agent_mode={req.agent_mode}  chain={len(history)}")
    if has_text:
        print(f"  message: {req.user_message[:120]}")
    print(f"{'=' * 60}\n")

    await manager.send(session_id, {"type": "status", "message": "Processing..."})

    # ── Ensure backend ready ─────────────────────────────────────────────────
    if not is_ready():
        await manager.send(session_id, {"type": "status", "message": "Warming up..."})
    try:
        ensure_ready(timeout=300, poll_interval=5)
    except TimeoutError as e:
        await manager.send(session_id, {"type": "error", "message": str(e)})
        return {"session_id": session_id, "status": "error", "error": str(e)}

    # ── 2. Model loop — tool calls resolved server-side, actions go to frontend
    MAX_TOOL_LOOPS = 10
    response: AgentResponse | None = None
    plan_pending_review: str | None = None  # set when update_plan is called

    for loop_i in range(MAX_TOOL_LOOPS + 1):
        # Call model (with timeout + retry)
        try:
            for timeout_attempt in range(MAX_TIMEOUT_RETRIES + 1):
                try:
                    agent_req = context_manager.build_request(session_id)
                    response = await asyncio.wait_for(
                        asyncio.to_thread(call_model, agent_req),
                        timeout=MODEL_TIMEOUT_SECS,
                    )
                    break  # success
                except asyncio.TimeoutError:
                    if timeout_attempt < MAX_TIMEOUT_RETRIES:
                        print(f"[agent/step] Model call timed out after {MODEL_TIMEOUT_SECS}s — retrying ({timeout_attempt + 1}/{MAX_TIMEOUT_RETRIES})")
                        await manager.send(session_id, {
                            "type": "status",
                            "message": f"Model response timed out, retrying... ({timeout_attempt + 1}/{MAX_TIMEOUT_RETRIES})",
                        })
                    else:
                        raise TimeoutError(
                            f"Model did not respond after {MAX_TIMEOUT_RETRIES} retries "
                            f"(timeout={MODEL_TIMEOUT_SECS}s each)"
                        )
        except Exception as e:
            from pydantic import ValidationError
            if isinstance(e, ValidationError):
                print(f"[agent/step] Pydantic Validation failed: {e}")
                # Inject the exact error into the context so the model can fix its own JSON schema violation
                context_manager.add_user_message(
                    session_id,
                    f"[SCHEMA VALIDATION FAILED] The JSON you returned was invalid or violated the schema limits:\n{e}\n\nPlease fix your formatting and try again."
                )
                await manager.send(session_id, {"type": "status", "message": "Pydantic schema validation error, returning to model to fix..."})
                
                if loop_i >= MAX_TOOL_LOOPS:
                    return {"session_id": session_id, "status": "action_rejected", "error": str(e), "done": False}
                    
                continue  # Re-call the model internally

            print(f"[agent/step] Inference failed: {e}")
            await manager.send(session_id, {"type": "error", "message": f"Inference failed: {e}"})
            return {"session_id": session_id, "status": "error", "error": str(e)}

        print(f"[agent/step] Response in {response.inference_time_ms}ms"
              f"  tool_calls={bool(response.tool_calls)}"
              f"  action={response.action.type.value if response.action else 'none'}"
              f"  done={response.done}")

        # ── 3. Tool calls? Execute and loop ──────────────────────────────────
        if response.tool_calls:
            if loop_i >= MAX_TOOL_LOOPS:
                print(f"[agent/step] Hit max tool loops ({MAX_TOOL_LOOPS}) — forcing screenshot")
                context_manager.add_user_message(
                    session_id,
                    "[TOOL LOOP LIMIT] You called tools 10 times without taking a desktop action. "
                    "STOP calling tools. Take a screenshot to see the screen and proceed with "
                    "a desktop action (navigate_and_click, mouse_move, type_text, key_press, etc.)."
                )
                response.tool_calls = None
                response.action = Action(type=ActionType.SCREENSHOT)
                response.done = False
                break

            # Store assistant turn with tool calls (OpenAI format for context)
            raw_tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ]
            context_manager.add_tool_call_turn(session_id, raw_tool_calls)

            # Execute each tool and add results
            for tc in response.tool_calls:
                try:
                    args = json.loads(tc.arguments) if tc.arguments else {}
                except json.JSONDecodeError:
                    args = {}

                result = await execute_agent_tool(
                    session_id, tc.name, args, manager, context_manager, compact_model,
                )
                context_manager.add_tool_result_turn(session_id, tc.id, tc.name, result)
                print(f"[tool] {tc.name}({json.dumps(args)[:80]}) → {result[:150]}")
                await log_and_send(
                    session_id,
                    f"[tool] {tc.name}({json.dumps(args, ensure_ascii=False)[:200]}) → {result[:300]}",
                    manager,
                    metadata={"tool_name": tc.name, "args": json.dumps(args, ensure_ascii=False)[:500], "result": result[:500]},
                )

                # If update_plan was called, capture the plan content for review
                if tc.name == "update_plan":
                    plan_content = args.get("content", "")
                    if plan_content:
                        plan_pending_review = plan_content

            # ── Plan review gate: pause loop and wait for user approval ──────
            if plan_pending_review:
                print(f"[plan-review] Plan created — pausing for user approval")
                await manager.send(session_id, {
                    "type": "plan_review",
                    "content": plan_pending_review,
                })
                return {
                    "session_id": session_id,
                    "status": "plan_pending",
                    "done": False,
                }

            await manager.send(session_id, {
                "type": "status",
                "message": f"Tools: {', '.join(tc.name for tc in response.tool_calls)}. Continuing...",
            })
            continue  # re-call model with tool results

        # No tool calls — we have a desktop action or done.

        # ── Safety: ensure we have an action ──────────────────────────────────────
        if not response.action:
            response.action = Action(type=ActionType.SCREENSHOT)
            response.done = False

        # ── Recovery: model returned an unparseable / unknown action.
        # The provider wraps plain-text or malformed-JSON responses as
        # action=unknown. Never promote these to "done" — a garbled action
        # payload is not evidence the task is complete. Instead, nudge the
        # model to re-orient with a fresh screenshot and try again.
        if response.action.type == ActionType.UNKNOWN:
            preview = (response.final_message or "").strip()[:200]
            print(f"[agent/step] unknown action received, requesting retry: {preview!r}")
            context_manager.add_assistant_turn(
                session_id,
                response.model_dump_json(exclude_none=True),
            )
            context_manager.add_user_message(
                session_id,
                "[MALFORMED RESPONSE] Your previous response could not be parsed as a "
                "valid desktop action. Do NOT treat this as task completion. Take a "
                "screenshot to re-orient and then emit a well-formed action JSON.",
            )
            response.action = Action(type=ActionType.SCREENSHOT)
            response.done = False
            response.final_message = None
            await manager.send(session_id, {"type": "status", "message": "Unparseable action, retaking screenshot..."})
            if loop_i < MAX_TOOL_LOOPS:
                continue

        action_type = response.action.type.value
        action_payload = response.action.model_dump(exclude_none=True)

        # ── 4. Action validation ─────────────────────────────────────────────────
        is_valid, error_msg = context_manager.action_validator.validate(
            session_id, action_payload
        )

        if not is_valid:
            print(f"[validator] REJECTED: {error_msg}")
            context_manager.add_assistant_turn(
                session_id,
                response.model_dump_json(exclude_none=True),
            )
            context_manager.add_user_message(
                session_id,
                f"[ACTION REJECTED] {error_msg}\nChoose a different action.",
            )
            await manager.send(session_id, {"type": "status", "message": f"Rejected: {error_msg}. Retrying..."})
            
            # If we hit the loop limit, don't loop again to avoid infinite hangs
            if loop_i >= MAX_TOOL_LOOPS:
                await manager.send(session_id, {"type": "error", "message": f"Validation failed {MAX_TOOL_LOOPS} times. Aborting."})
                return {"session_id": session_id, "status": "action_rejected", "error": error_msg, "done": False}
                
            continue  # Re-call the model internally

        # ── 4b. Catch bogus "done" from truncated action parse ───────────────────
        if response.done and response.action and response.action.type == ActionType.DONE:
            done_ok, done_err = context_manager.action_validator.validate_done_response(
                response.final_message
            )
            if not done_ok:
                print(f"[validator] REJECTED done: {done_err}")
                context_manager.add_user_message(
                    session_id,
                    "[MALFORMED RESPONSE] Your previous response was garbled — it looked like "
                    "a truncated desktop action, not a real completion. Take a screenshot to "
                    "re-orient and then continue with your task."
                )
                response.action = Action(type=ActionType.SCREENSHOT)
                response.done = False
                response.final_message = None
                await manager.send(session_id, {"type": "status", "message": "Truncated response detected, retaking screenshot..."})
                if loop_i < MAX_TOOL_LOOPS:
                    continue

        break  # Valid desktop action or done, dispatch to frontend

    # ── 5. Dispatch action to frontend ────────────────────────────────────────
    if not response or not response.action:
        response = response or AgentResponse(action=Action(type=ActionType.SCREENSHOT), done=False)
        if not response.action:
            response.action = Action(type=ActionType.SCREENSHOT)
            response.done = False

    action_type = response.action.type.value
    action_payload = response.action.model_dump(exclude_none=True)

    response_json = response.model_dump_json(exclude_none=True)
    context_manager.add_assistant_turn(session_id, response_json)

    # Log the assistant's action/response
    reasoning_preview = (response.reasoning_content or "")[:200]
    if response.done:
        await log_and_send(
            session_id,
            f"[assistant] DONE — {response.final_message or 'Task complete.'}",
            manager,
            metadata={"done": True, "final_message": response.final_message or "Task complete."},
        )
    else:
        await log_and_send(
            session_id,
            f"[action] {action_type}  confidence={response.confidence}  reasoning={reasoning_preview}",
            manager,
            metadata={
                "action_type": action_type,
                "confidence": response.confidence,
                "reasoning": (response.reasoning_content or "")[:500],
                "action": action_payload,
            },
        )

    # Safety-net auto-compaction
    needs_compact = context_manager.needs_compaction(session_id)
    if needs_compact:
        print(f"[auto-compact] Safety net triggered at {context_manager.chain_length(session_id)} messages")

    needs_confirm = False

    await manager.send(session_id, {
        "type":                 "step",
        "reasoning":            response_json,
        "reasoning_content":    response.reasoning_content or "",
        "action":               action_payload,
        "done":                 response.done,
        "confidence":           response.confidence,
        "final_message":        response.final_message,
        "requires_confirmation": needs_confirm,
        "chain_length":         context_manager.chain_length(session_id),
        "needs_compaction":     needs_compact,
    })

    # Run auto-compact if needed
    if needs_compact and not response.done:
        await auto_compact(session_id, context_manager, compact_model, manager)

    if response.done:
        await manager.send(session_id, {
            "type": "done",
            "message": response.final_message or "Task complete.",
        })

    return {
        "session_id": session_id,
        "status": "done" if response.done else "action_dispatched",
        "action": action_payload,
        "done": response.done,
        "confidence": response.confidence,
        "final_message": response.final_message,
    }


@app.post("/action/complete")
async def action_complete(req: ActionCompleteRequest):
    """Electron notifies backend that a dispatched action has finished."""
    print(f"[action/complete] session={req.session_id} channel={req.ipc_channel} ok={req.success}")

    text_parts = []

    is_shell = req.ipc_channel in ("shell:exec", "shell_exec")

    if is_shell:
        # Shell exec: always inject stdout; inject stderr on failure
        if req.output:
            text_parts.append(f"[shell_exec output]\n{req.output}")
        if req.error and not req.success:
            text_parts.append(f"[shell_exec error]\n{req.error}")
    elif not req.success and req.error:
        # Non-shell actions: only inject on failure with interpreted guidance
        action_label = ipc_to_action_label(req.ipc_channel)
        text_parts.append(interpret_action_error(req.error, action_label))

    if text_parts:
        context_manager.add_user_message(req.session_id, "\n".join(text_parts))
        print(f"[action/complete] injected feedback into context ({len(' '.join(text_parts))} chars)")

    return {"acknowledged": True}





@app.post("/agent/stop")
async def agent_stop(req: StopRequest):
    """User interrupted the agent flow."""
    session_id = req.session_id
    context_manager.add_user_message(session_id, "STOP")
    print(f"[agent/stop] session={session_id}")

    await manager.send(session_id, {
        "type": "stopped",
        "message": "Agent stopped by user.",
    })

    return {"session_id": session_id, "status": "stopped"}


@app.post("/agent/compact")
async def compact_context(req: CompactRequest):
    """Manual compact endpoint (user-triggered via UI)."""
    session_id = req.session_id
    chain_len = context_manager.chain_length(session_id)
    print(f"[compact] session={session_id}  chain_length={chain_len}")

    if chain_len <= 4:
        return {
            "session_id": session_id,
            "status": "skipped",
            "message": "Context chain is too short to compact.",
            "chain_length": chain_len,
        }

    compact_messages = context_manager.get_compact_messages(session_id)

    await manager.send(session_id, {
        "type": "status",
        "message": "Compacting context...",
    })

    try:
        summary = compact_model(compact_messages)
    except Exception as e:
        print(f"[compact] Failed: {e}")
        await manager.send(session_id, {
            "type": "error",
            "message": f"Context compaction failed: {e}",
        })
        return {"session_id": session_id, "status": "error", "error": str(e)}

    context_manager.reset_with_summary(session_id, summary)
    new_len = context_manager.chain_length(session_id)

    print(f"[compact] Done. {chain_len} → {new_len} messages")

    await manager.send(session_id, {
        "type": "status",
        "message": f"Context compacted: {chain_len} → {new_len} messages.",
    })

    return {
        "session_id": session_id,
        "status": "compacted",
        "previous_length": chain_len,
        "new_length": new_len,
    }


@app.get("/sessions/history")
async def sessions_history():
    """Return all sessions with their first user message for the history sidebar."""
    from workspace import get_sessions_dir
    sessions_dir = get_sessions_dir()
    results = []

    if not sessions_dir.is_dir():
        return {"sessions": []}

    import re as _re
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        # Only process directories with valid session-id names (skip symlinks, junctions)
        if not _re.match(r'^[a-zA-Z0-9_-]+$', session_dir.name) or session_dir.is_symlink():
            continue
        conv_path = session_dir / "logs" / "conversation.json"
        if not conv_path.exists():
            continue
        try:
            with open(conv_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            messages = data.get("messages", [])
            if not messages:
                continue
            # Find the first user message for the preview
            first_user = next((m for m in messages if m.get("role") == "user" and m.get("content", "").strip() and m["content"] != "<screenshot>"), None)
            if not first_user:
                continue
            # Use directory mtime as a rough "last active" timestamp
            mtime = session_dir.stat().st_mtime
            results.append({
                "session_id": session_dir.name,
                "preview": first_user["content"][:80],
                "message_count": len(messages),
                "last_active": mtime,
            })
        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by last_active descending (most recent first)
    results.sort(key=lambda s: s["last_active"], reverse=True)
    return {"sessions": results}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    """Return the full conversation.json for a given session."""
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', session_id):
        return JSONResponse(status_code=400, content={"detail": "Invalid session_id"})
    from workspace import get_sessions_dir
    conv_path = get_sessions_dir() / session_id / "logs" / "conversation.json"
    if not conv_path.exists():
        return {"messages": []}
    try:
        with open(conv_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, KeyError):
        return {"messages": []}


@app.post("/agent/session/continue")
async def continue_session(req: ContinueSessionRequest):
    """
    Create a new session pre-seeded with history from a previous one, then
    delete the old session directory.
    """
    import re
    import shutil

    old_id = req.previous_session_id
    if not re.match(r'^[a-zA-Z0-9_-]+$', old_id):
        return JSONResponse(status_code=400, content={"detail": "Invalid session_id"})

    from workspace import get_sessions_dir
    old_dir = get_sessions_dir() / old_id
    conv_path = old_dir / "logs" / "conversation.json"

    if not conv_path.exists():
        return JSONResponse(status_code=404, content={"detail": "Session not found"})

    try:
        with open(conv_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        old_messages = data.get("messages", [])
    except (json.JSONDecodeError, KeyError):
        return JSONResponse(status_code=400, content={"detail": "Could not read session"})

    new_id = str(uuid.uuid4())
    ensure_session_dir(new_id)
    context_manager.preload_from_conversation(new_id, old_messages)

    try:
        shutil.rmtree(old_dir)
        print(f"[session] deleted {old_id} after continuation")
    except Exception as e:
        print(f"[session] warning: could not delete {old_id}: {e}")

    print(f"[session] continued {old_id} → {new_id}")
    return {"session_id": new_id}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    # Validate auth token from query parameter before accepting
    token = ws.query_params.get("token", "")
    if not secrets.compare_digest(token, AUTH_TOKEN):
        await ws.close(code=4001, reason="Invalid auth token")
        return
    await manager.connect(session_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)
