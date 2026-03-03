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
    Accepts user message + screenshot, orchestrates model call, and streams
    actions + reasoning back to the frontend via WebSocket.
    """
    session_id = req.session_id or str(uuid.uuid4())

    # Build the full context chain for this step
    agent_req = context_manager.build_request(session_id, req.user_message, req.base64_screenshot)

    screenshot_kb = round(len(req.base64_screenshot) * 3 / 4 / 1024, 1) if req.base64_screenshot else 0
    history = context_manager._history.get(session_id, [])

    print("\n" + "=" * 60)
    print("[agent/step] NEW REQUEST")
    print(f"  session_id        : {session_id}")
    print(f"  timestamp         : {req.timestamp}")
    print(f"  user_message      : {req.user_message}")
    print(f"  step_index        : {agent_req.step_index}")
    print(f"  base64_screenshot : {len(req.base64_screenshot)} chars (~{screenshot_kb} KB)")
    if req.base64_screenshot:
        print(f"  screenshot prefix : {req.base64_screenshot[:40]}...")
    print(f"\n  ── context chain ({len(history)} message(s) in history) ──")
    for i, msg in enumerate(history):
        preview = msg.content[:80].replace("\n", " ")
        print(f"    [{i}] {msg.role.value:<10}  {preview}{'...' if len(msg.content) > 80 else ''}")
    print("=" * 60 + "\n")

    # Tell frontend we're thinking
    await manager.send(session_id, {
        "type": "status",
        "message": "Processing your request..."
    })

    # ── Call Modal container ────────────────────────────────────────────────
    # TODO: replace with real Modal HTTP call
    #   response: AgentResponse = await call_modal(agent_req)
    #
    # After Modal responds, send a single 'step' message to the frontend:
    #   response_json = response.model_dump_json(exclude_none=True)
    #   context_manager.add_assistant_turn(session_id, response_json)
    #
    #   await manager.send(session_id, {
    #       "type":          "step",
    #       "screenshot":    req.base64_screenshot,
    #       "reasoning":     "<reasoning from chat template>",
    #       "action":        response.action.model_dump(exclude_none=True),
    #       "done":          response.done,
    #       "confidence":    response.confidence,
    #       "final_message": response.final_message,
    #   })

    await manager.send(session_id, {
        "type": "done",
        "message": "Modal container not yet connected. Context chain built successfully."
    })

    return {"session_id": session_id, "status": "awaiting_modal"}


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
