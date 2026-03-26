import base64
import io
import os
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from models import (
    AgentRequest,
    AgentResponse,
    ActionCompleteRequest,
    CompactRequest,
    ScreenshotRequest,
    StopRequest,
)
from context_manager import ContextManager
from workspace import ensure_session_dir

# ── Inference backend ────────────────────────────────────────────────────────
# Auto-detects provider from environment variables.
# Override with EMU_PROVIDER=claude|openai|gemini|openai_compatible|modal
#
from providers.registry import load_provider, load_compact_provider

call_model, is_ready, ensure_ready, _provider_name = load_provider()
compact_model = load_compact_provider()

# ── OmniParser mode ──────────────────────────────────────────────────────────
_use_omni = os.environ.get("USE_OMNI_PARSER", "").strip() in ("1", "true", "yes")
print(f"[config] OmniParser: {'ENABLED' if _use_omni else 'DISABLED (direct screenshot mode)'}")
if not _use_omni:
    print(f"[config] To enable OmniParser, set USE_OMNI_PARSER=1")

app = FastAPI(title="Emulation Agent API")

SCREENSHOTS_DIR = Path(__file__).parent / "emulation_screen_shots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket connection manager ─────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._sockets: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._sockets[session_id] = ws
        print(f"[ws] connected  session={session_id}")

    def disconnect(self, session_id: str):
        self._sockets.pop(session_id, None)
        print(f"[ws] disconnected session={session_id}")

    async def send(self, session_id: str, message: dict):
        ws = self._sockets.get(session_id)
        if ws:
            await ws.send_json(message)

manager = ConnectionManager()
context_manager = ContextManager()


# ── Endpoints ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/screenshot")
async def receive_screenshot(req: ScreenshotRequest):
    """Accept a base64 PNG from Electron, decode and save to disk."""
    try:
        img_bytes = base64.b64decode(req.image)
        img = Image.open(io.BytesIO(img_bytes))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"screenshot_{ts}.png"
        filepath = SCREENSHOTS_DIR / filename
        img.save(filepath, format="PNG")
        print(f"[screenshot] saved {filename} ({img.width}×{img.height})")
        return {"success": True, "filename": filename, "width": img.width, "height": img.height}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/agent/session")
async def create_session():
    """Create a new agent session, scaffold its .emu/sessions/<id>/ directory."""
    session_id = str(uuid.uuid4())
    session_dir = ensure_session_dir(session_id)
    print(f"[session] created {session_id}  dir={session_dir}")
    return {"session_id": session_id}


@app.get("/agent/session/{session_id}")
async def get_session(session_id: str):
    """Return current session state."""
    # Placeholder until full session management is implemented
    return {"session_id": session_id, "status": "active"}


@app.post("/agent/step")
async def agent_step(req: AgentRequest):
    """
    Main agent loop entry point.

    Two modes of invocation:
      1. New task:   user_message is set, base64_screenshot is empty.
                     Adds the user text to context, calls the model.
                     Model will likely respond with a screenshot action.

      2. Screenshot: base64_screenshot is set (after frontend captures).
                     Adds the screenshot to context, calls the model.
                     Model sees the screen and decides the next action.
    """
    session_id = req.session_id or str(uuid.uuid4())
    has_screenshot = bool(req.base64_screenshot)
    has_text = bool(req.user_message.strip())

    # ── Add to context ──────────────────────────────────────────────────────
    if has_screenshot:
        context_manager.add_screenshot_turn(session_id, req.base64_screenshot)
    if has_text:
        context_manager.add_user_message(session_id, req.user_message)

    # Build the request from accumulated history
    agent_req = context_manager.build_request(session_id)

    # ── Log ──────────────────────────────────────────────────────────────────
    history = context_manager._history.get(session_id, [])
    screenshot_kb = round(len(req.base64_screenshot) * 3 / 4 / 1024, 1) if has_screenshot else 0

    print("\n" + "=" * 60)
    print("[agent/step] NEW REQUEST")
    print(f"  session_id  : {session_id}")
    print(f"  mode        : {'screenshot' if has_screenshot else 'text'}")
    print(f"  step_index  : {agent_req.step_index}")
    if has_text:
        print(f"  user_message: {req.user_message}")
    if has_screenshot:
        print(f"  screenshot  : {screenshot_kb} KB")
    print(f"\n  ── context chain ({len(history)} messages) ──")
    for i, msg in enumerate(history):
        if msg.content.startswith("data:image/"):
            print(f"    [{i}] {msg.role.value:<10}  [SCREENSHOT]")
        else:
            preview = msg.content[:80].replace("\n", " ")
            print(f"    [{i}] {msg.role.value:<10}  {preview}{'...' if len(msg.content) > 80 else ''}")
    print("=" * 60 + "\n")

    # Tell frontend we're thinking
    await manager.send(session_id, {
        "type": "status",
        "message": "Processing your request..."
    })

    # ── Ensure inference backend is ready ───────────────────────────────────
    if not is_ready():
        await manager.send(session_id, {
            "type": "status",
            "message": "Warming up inference server... (first request may take a moment)"
        })

    try:
        ensure_ready(timeout=300, poll_interval=5)
    except TimeoutError as e:
        print(f"[agent/step] Container not ready: {e}")
        await manager.send(session_id, {
            "type": "error",
            "message": "Inference server is not responding. Please try again in a minute.",
        })
        return {"session_id": session_id, "status": "error", "error": str(e)}


    # ── Call inference backend ──────────────────────────────────────────────
    try:
        response: AgentResponse = call_model(agent_req)
    except Exception as e:
        print(f"[agent/step] Inference call failed: {e}")
        await manager.send(session_id, {
            "type": "error",
            "message": f"Inference failed: {e}",
        })
        return {"session_id": session_id, "status": "error", "error": str(e)}

    # Persist the model's response in conversation history
    response_json = response.model_dump_json(exclude_none=True)
    context_manager.add_assistant_turn(session_id, response_json)

    print(f"[agent/step] Model responded in {response.inference_time_ms}ms")
    print(f"  action     : {response.action.type.value}")
    print(f"  done       : {response.done}")
    print(f"  confidence : {response.confidence}")

    # Check if auto-compaction is needed after this turn
    needs_compact = context_manager.needs_compaction(session_id)
    if needs_compact:
        chain_len = context_manager.chain_length(session_id)
        token_est = context_manager.estimate_token_count(session_id)
        print(f"[auto-compact] Chain at {chain_len} messages (~{token_est} tokens) — compaction recommended")

    # Route action to frontend via WebSocket
    action_payload = response.action.model_dump(exclude_none=True)

    # shell_exec commands require user confirmation before execution
    needs_confirm = (
        response.action.type.value == "shell_exec"
        and not response.done
    )

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

    # Auto-compact if threshold exceeded and task is still in progress
    if needs_compact and not response.done:
        print(f"[auto-compact] Triggering automatic context compaction...")
        await manager.send(session_id, {
            "type": "status",
            "message": "Context getting large — auto-compacting to stay sharp...",
        })
        try:
            compact_messages = context_manager.get_compact_messages(session_id)
            summary = compact_model(compact_messages)
            old_len = context_manager.chain_length(session_id)
            context_manager.reset_with_summary(session_id, summary)
            new_len = context_manager.chain_length(session_id)
            print(f"[auto-compact] Done. {old_len} → {new_len} messages")
            await manager.send(session_id, {
                "type": "status",
                "message": f"Context auto-compacted: {old_len} → {new_len} messages. Continuing seamlessly.",
            })
        except Exception as e:
            print(f"[auto-compact] Failed (non-fatal): {e}")
            # Non-fatal: the middle-trim fallback in build_request() will handle it

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

    # Inject shell_exec output (or error) into the context chain so the model
    # can see what a command returned.  This goes in as a user message right
    # before the next screenshot.
    if req.output or req.error:
        text_parts = []
        if req.output:
            text_parts.append(f"[shell_exec output]\n{req.output}")
        if req.error and not req.success:
            text_parts.append(f"[shell_exec error]\n{req.error}")
        context_manager.add_user_message(req.session_id, "\n".join(text_parts))
        print(f"[action/complete] injected shell output ({len(req.output or '')} chars) into context")

    return {"acknowledged": True}


@app.post("/agent/stop")
async def agent_stop(req: StopRequest):
    """
    User interrupted the agent flow.
    Append a STOP user message to the context chain so the model is
    aware the user halted execution. The chain is preserved — the user
    can continue the conversation afterwards.
    """
    session_id = req.session_id
    context_manager.add_user_message(session_id, "STOP")
    print(f"[agent/stop] session={session_id} — user interrupted, STOP added to chain")

    await manager.send(session_id, {
        "type": "stopped",
        "message": "Agent stopped by user.",
    })

    return {"session_id": session_id, "status": "stopped"}


@app.post("/agent/compact")
async def compact_context(req: CompactRequest):
    """
    Compact a bloated context chain.

    Serialises the full chain (minus screenshots and system prompt),
    sends it to a lightweight model for summarisation, then resets
    the chain to: system prompt + compressed summary.
    """
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

    # Get the message chain (screenshots → placeholders, system prompt stripped)
    compact_messages = context_manager.get_compact_messages(session_id)

    # Log what we're sending to the compact model
    print(f"[compact] Sending {len(compact_messages)} messages to compact model")
    for i, m in enumerate(compact_messages):
        preview = m.content[:200].replace('\n', ' ')
        print(f"[compact]   [{i}] {m.role.value}: {preview}...")

    await manager.send(session_id, {
        "type": "status",
        "message": "Compacting context — summarising conversation history...",
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

    # Reset the chain: system prompt + summary
    context_manager.reset_with_summary(session_id, summary)
    new_len = context_manager.chain_length(session_id)

    print(f"[compact] Done. {chain_len} messages → {new_len} messages")
    print(f"[compact] ═══ COMPACTED SUMMARY START ═══")
    print(summary)
    print(f"[compact] ═══ COMPACTED SUMMARY END ═══")

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


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await manager.connect(session_id, ws)
    try:
        while True:
            # Keep the connection alive; all messages are pushed from HTTP handlers
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)
