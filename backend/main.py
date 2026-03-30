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
from workspace import (
    ensure_session_dir,
    write_session_plan,
    read_session_plan,
    append_session_notes,
)

# ── Inference backend ────────────────────────────────────────────────────────
from providers.registry import load_provider, load_compact_provider
from context_manager.context import USE_OMNI_PARSER

call_model, is_ready, ensure_ready, _provider_name = load_provider()
compact_model = load_compact_provider()

print(f"[config] OmniParser: {'ENABLED' if USE_OMNI_PARSER else 'DISABLED (direct screenshots)'}")

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


# ── WebSocket connection manager ─────────────────────────────────────────────

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


# ── Agent tool handlers ──────────────────────────────────────────────────────

async def handle_compact_context(session_id: str, focus: str = "") -> str:
    """Handle the model's compact_context tool call."""
    chain_len = context_manager.chain_length(session_id)
    if chain_len <= 4:
        return "Context is already short — no compaction needed."

    await manager.send(session_id, {
        "type": "status",
        "message": "Compacting context as requested...",
    })

    try:
        compact_messages = context_manager.get_compact_messages(session_id)
        summary = compact_model(compact_messages)
        old_len = chain_len
        context_manager.reset_with_summary(session_id, summary)
        new_len = context_manager.chain_length(session_id)
        msg = f"Context compacted: {old_len} → {new_len} messages."
        if focus:
            msg += f" Focused on: {focus}"
        print(f"[compact] Model-initiated. {old_len} → {new_len} messages")
        await manager.send(session_id, {"type": "status", "message": msg})
        return msg
    except Exception as e:
        print(f"[compact] Failed: {e}")
        return f"Compaction failed: {e}. Continue without it."


def handle_read_plan(session_id: str) -> str:
    """Handle the model's read_plan tool call."""
    plan = read_session_plan(session_id)
    if plan:
        return f"[YOUR PLAN]\n{plan}"
    else:
        return "No plan.md found for this session. You may need to create one."


def handle_update_plan(session_id: str, content: str) -> str:
    """Handle the model's update_plan tool call."""
    if not content:
        return "No content provided for plan update."
    write_session_plan(session_id, content)
    return "Plan updated successfully."


def handle_write_memory(session_id: str, content: str, target: str = "daily_log") -> str:
    """Handle the model's write_memory tool call."""
    if not content:
        return "No content provided for memory write."

    _backend_dir = Path(__file__).parent
    _project_root = _backend_dir.parent
    _emu_dir = _project_root / ".emu"

    try:
        if target == "daily_log":
            today = datetime.now().strftime("%Y-%m-%d")
            time_now = datetime.now().strftime("%H:%M")
            memory_dir = _emu_dir / "workspace" / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            daily_path = memory_dir / f"{today}.md"
            with open(daily_path, "a", encoding="utf-8") as f:
                f.write(f"\n### {time_now}\n{content}\n")
            return f"Written to daily log ({today})."

        elif target == "long_term":
            memory_path = _emu_dir / "workspace" / "MEMORY.md"
            with open(memory_path, "a", encoding="utf-8") as f:
                f.write(f"\n{content}\n")
            return "Written to long-term memory (MEMORY.md)."

        elif target == "preferences":
            prefs_path = _emu_dir / "global" / "preferences.md"
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            with open(prefs_path, "a", encoding="utf-8") as f:
                f.write(f"\n{content}\n")
            return "Written to preferences."

        else:
            return f"Unknown memory target: {target}. Use daily_log, long_term, or preferences."

    except Exception as e:
        return f"Memory write failed: {e}"


# ── Endpoints ────────────────────────────────────────────────────────────────

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

    Handles:
    1. Text tasks / screenshot inputs → model call
    2. Action validation (runtime, not prompt rules)
    3. Agent tool dispatch (compact_context, read_plan, update_plan, write_memory)
    4. Safety-net auto-compaction
    """
    session_id = req.session_id or str(uuid.uuid4())
    has_screenshot = bool(req.base64_screenshot)
    has_text = bool(req.user_message.strip())

    # ── Add to context ──────────────────────────────────────────────────────
    if has_screenshot:
        context_manager.add_screenshot_turn(session_id, req.base64_screenshot)
    if has_text:
        context_manager.add_user_message(session_id, req.user_message)

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

    print(f"[agent/step] Model responded in {response.inference_time_ms}ms")
    print(f"  action     : {response.action.type.value}")
    print(f"  done       : {response.done}")
    print(f"  confidence : {response.confidence}")

    action_type = response.action.type.value
    action_payload = response.action.model_dump(exclude_none=True)

    # ── Handle agent tools (executed server-side, not sent to frontend) ────
    agent_tool_types = {"compact_context", "read_plan", "update_plan", "write_memory"}

    if action_type in agent_tool_types:
        tool_result = ""

        if action_type == "compact_context":
            tool_result = await handle_compact_context(
                session_id,
                focus=response.action.focus or ""
            )
        elif action_type == "read_plan":
            tool_result = handle_read_plan(session_id)
        elif action_type == "update_plan":
            tool_result = handle_update_plan(session_id, response.action.text or "")
        elif action_type == "write_memory":
            tool_result = handle_write_memory(
                session_id,
                content=response.action.text or "",
                target=response.action.target or "daily_log",
            )

        print(f"[agent-tool] {action_type} → {tool_result[:200]}")

        # Record assistant turn and inject tool result, then re-call model
        response_json = response.model_dump_json(exclude_none=True)
        context_manager.add_assistant_turn(session_id, response_json)
        context_manager.add_user_message(session_id, f"[{action_type} result]\n{tool_result}")

        await manager.send(session_id, {
            "type": "status",
            "message": f"Tool: {action_type} completed. Continuing...",
        })

        return {
            "session_id": session_id,
            "status": "tool_executed",
            "action": action_payload,
            "tool_result": tool_result,
            "done": False,
        }

    # ── Action validation (runtime guardrails) ─────────────────────────────
    is_valid, error_msg = context_manager.action_validator.validate(
        session_id, action_payload
    )

    if not is_valid:
        print(f"[validator] REJECTED: {error_msg}")
        # Inject error as feedback — model learns from this
        rejection_json = response.model_dump_json(exclude_none=True)
        context_manager.add_assistant_turn(session_id, rejection_json)
        context_manager.add_user_message(
            session_id,
            f"[ACTION REJECTED] {error_msg}\nChoose a different action."
        )

        await manager.send(session_id, {
            "type": "status",
            "message": f"Action rejected: {error_msg}",
        })

        return {
            "session_id": session_id,
            "status": "action_rejected",
            "error": error_msg,
            "done": False,
        }

    # ── Valid action — persist and route to frontend ───────────────────────
    response_json = response.model_dump_json(exclude_none=True)
    context_manager.add_assistant_turn(session_id, response_json)

    # Safety-net auto-compaction (high threshold — model should self-compact before this)
    needs_compact = context_manager.needs_compaction(session_id)
    if needs_compact:
        chain_len = context_manager.chain_length(session_id)
        token_est = context_manager.estimate_token_count(session_id)
        print(f"[auto-compact] Safety net triggered at {chain_len} messages (~{token_est} tokens)")

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

    # Safety-net auto-compact
    if needs_compact and not response.done:
        print(f"[auto-compact] Running safety-net compaction...")
        await manager.send(session_id, {
            "type": "status",
            "message": "Context getting large — auto-compacting...",
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
                "message": f"Auto-compacted: {old_len} → {new_len} messages.",
            })
        except Exception as e:
            print(f"[auto-compact] Failed (non-fatal): {e}")

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


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await manager.connect(session_id, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)
