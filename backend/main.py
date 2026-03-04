import base64
import io
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from models import (
    AgentRequest,
    AgentResponse,
    ActionCompleteRequest,
    ScreenshotRequest,
)
from context_manager import ContextManager
from modal_client import call_modal
from modal_health import ensure_ready, is_ready

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
    """Create a new agent session and return its ID."""
    session_id = str(uuid.uuid4())
    print(f"[session] created {session_id}")
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
                     Adds the user text to context, calls Modal.
                     Model will likely respond with a screenshot action.

      2. Screenshot: base64_screenshot is set (after frontend captures).
                     Adds the screenshot to context, calls Modal.
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

    # ── Ensure Modal container is warm ──────────────────────────────────────
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

    # ── Call Modal container ────────────────────────────────────────────────
    try:
        response: AgentResponse = call_modal(agent_req)
    except Exception as e:
        print(f"[agent/step] Modal call failed: {e}")
        await manager.send(session_id, {
            "type": "error",
            "message": f"Modal inference failed: {e}",
        })
        return {"session_id": session_id, "status": "error", "error": str(e)}

    # Persist the model's response in conversation history
    response_json = response.model_dump_json(exclude_none=True)
    context_manager.add_assistant_turn(session_id, response_json)

    print(f"[agent/step] Modal responded in {response.inference_time_ms}ms")
    print(f"  action     : {response.action.type.value}")
    print(f"  done       : {response.done}")
    print(f"  confidence : {response.confidence}")

    # Route action to frontend via WebSocket
    action_payload = response.action.model_dump(exclude_none=True)

    await manager.send(session_id, {
        "type":               "step",
        "reasoning":          response_json,
        "reasoning_content":  response.reasoning_content or "",
        "action":             action_payload,
        "done":               response.done,
        "confidence":         response.confidence,
        "final_message":      response.final_message,
    })

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
    return {"acknowledged": True}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str):
    await manager.connect(session_id, ws)
    try:
        while True:
            # Keep the connection alive; all messages are pushed from HTTP handlers
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id)
