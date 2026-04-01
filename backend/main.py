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

import json

from models import (
    Action,
    ActionType,
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
    write_session_file,
    read_session_file,
    list_session_files,
    read_memory,
    read_daily_memory,
)
from skills import get_skill_body

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


def handle_read_memory(target: str = "long_term") -> str:
    """Handle the model's read_memory tool call."""
    try:
        if target == "long_term":
            content = read_memory()
            if content:
                return f"[MEMORY.md]\n{content}"
            return "MEMORY.md is empty or does not exist yet."
        elif target == "preferences":
            from pathlib import Path
            _backend_dir = Path(__file__).parent
            _project_root = _backend_dir.parent
            prefs_path = _project_root / ".emu" / "global" / "preferences.md"
            if prefs_path.exists():
                content = prefs_path.read_text(encoding="utf-8").strip()
                if content:
                    return f"[preferences.md]\n{content}"
            return "preferences.md is empty or does not exist yet."
        elif target == "daily_log":
            content = read_daily_memory()
            if content:
                return f"[Today's daily log]\n{content}"
            return "No daily log for today yet."
        else:
            return f"Unknown memory target: {target}. Use long_term, preferences, or daily_log."
    except Exception as e:
        return f"Memory read failed: {e}"


def handle_use_skill(skill_name: str) -> str:
    """Handle the model's use_skill tool call — load full skill body on demand."""
    from skills import load_skills
    available = [s.name for s in load_skills()]
    available_str = ", ".join(available) if available else "(none)"

    if not skill_name or skill_name.strip() in ("", ":", ": "):
        return (
            f"No valid skill name provided. "
            f"Available skills: {available_str}. "
            f"Call use_skill with one of these exact names."
        )
    body = get_skill_body(skill_name)
    if body:
        return f"[SKILL: {skill_name}]\n\n{body}"
    else:
        return (
            f"Skill '{skill_name}' not found. "
            f"Available skills: {available_str}. "
            f"Use one of these exact names."
        )


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

    # ── 1. Add input to context ──────────────────────────────────────────────
    if has_screenshot:
        context_manager.add_screenshot_turn(session_id, req.base64_screenshot)
    if has_text:
        context_manager.add_user_message(session_id, req.user_message)

    # ── Log ──────────────────────────────────────────────────────────────────
    history = context_manager._history.get(session_id, [])
    print(f"\n{'=' * 60}")
    print(f"[agent/step] session={session_id}  mode={'screenshot' if has_screenshot else 'text'}  chain={len(history)}")
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
        # Call model
        try:
            agent_req = context_manager.build_request(session_id)
            response = call_model(agent_req)
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
                    "a desktop action (mouse_move, left_click, type_text, key_press, etc.)."
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

                result = await _execute_agent_tool(session_id, tc.name, args)
                context_manager.add_tool_result_turn(session_id, tc.id, tc.name, result)
                print(f"[tool] {tc.name}({json.dumps(args)[:80]}) → {result[:150]}")

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

    # Safety-net auto-compaction
    needs_compact = context_manager.needs_compaction(session_id)
    if needs_compact:
        print(f"[auto-compact] Safety net triggered at {context_manager.chain_length(session_id)} messages")

    needs_confirm = action_type == "shell_exec" and not response.done

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
        await _auto_compact(session_id)

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


# ── Agent tool dispatcher ───────────────────────────────────────────────────

async def _execute_agent_tool(session_id: str, name: str, args: dict) -> str:
    """Execute an agent tool by name and return the result string."""
    if name == "update_plan":
        plan_content = args.get("content", "")
        result = handle_update_plan(session_id, plan_content)
        # Plan review is handled by the agent loop gate — no tool_event needed
        return result
    elif name == "read_plan":
        return handle_read_plan(session_id)
    elif name == "use_skill":
        return handle_use_skill(args.get("skill_name", ""))
    elif name == "write_memory":
        return handle_write_memory(
            session_id,
            content=args.get("content", ""),
            target=args.get("target", "daily_log"),
        )
    elif name == "read_memory":
        return handle_read_memory(target=args.get("target", "long_term"))
    elif name == "write_session_file":
        filename = args.get("filename", "")
        # Determine if this is a create or edit
        existing = read_session_file(session_id, filename) is not None
        result = write_session_file(session_id, filename, args.get("content", ""))
        # Notify frontend with file card
        if "written" in result:
            sanitized = filename.strip().replace("/", "").replace("\\", "")
            if not sanitized.endswith(".md"):
                sanitized += ".md"
            await manager.send(session_id, {
                "type": "tool_event",
                "event": "file_written",
                "filename": sanitized,
                "action": "edited" if existing else "created",
            })
        return result
    elif name == "read_session_file":
        result = read_session_file(session_id, args.get("filename", ""))
        return result if result is not None else f"File '{args.get('filename')}' not found."
    elif name == "list_session_files":
        files = list_session_files(session_id)
        if not files:
            return "No files in current session. (plan.md and notes.md are considered system files)"
        return "Session files: " + ", ".join(files)
    elif name == "compact_context":
        return await handle_compact_context(session_id, focus=args.get("focus", ""))
    else:
        args_str = json.dumps(args, ensure_ascii=False)
        return (
            f"ERROR: Unknown function tool '{name}' called with arguments: {args_str}\n\n"
            f"If '{name}' is a desktop action (like shell_exec or mouse_move), "
            f"you MUST return it as a plain JSON text response (e.g. {{\"action\": {{\"type\": \"{name}\", ...}}}}), "
            f"NOT as a function tool call. Please try again using the proper format."
        )


async def _auto_compact(session_id: str):
    """Safety-net auto-compaction."""
    print(f"[auto-compact] Running...")
    await manager.send(session_id, {"type": "status", "message": "Auto-compacting context..."})
    try:
        compact_messages = context_manager.get_compact_messages(session_id)
        summary = compact_model(compact_messages)
        old_len = context_manager.chain_length(session_id)
        context_manager.reset_with_summary(session_id, summary)
        new_len = context_manager.chain_length(session_id)
        print(f"[auto-compact] Done. {old_len} → {new_len} messages")
        await manager.send(session_id, {"type": "status", "message": f"Compacted: {old_len} → {new_len}"})
    except Exception as e:
        print(f"[auto-compact] Failed (non-fatal): {e}")


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
