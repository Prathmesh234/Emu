import base64
import io
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image

app = FastAPI(title="Emulation Agent API")

# Screenshots folder
SCREENSHOTS_DIR = Path(__file__).parent / "emulation_screen_shots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# CORS for Electron frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Emulation Agent API"}


class ScreenshotRequest(BaseModel):
    image: str        # raw base64 PNG from Electron desktopCapturer
    width: int = 0
    height: int = 0


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/screenshot")
async def receive_screenshot(request: ScreenshotRequest):
    """Accept a base64 PNG from Electron, save to disk, return metadata."""
    try:
        print(f"[screenshot] received base64 string (first 80 chars): {request.image[:80]}...")
        print(f"[screenshot] total base64 length: {len(request.image)} chars | dims: {request.width}x{request.height}")

        img_bytes = base64.b64decode(request.image)
        img = Image.open(io.BytesIO(img_bytes))

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"screenshot_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        img.save(filepath, format="PNG")

        return {
            "success": True,
            "filename": filename,
            "path": str(filepath),
            "width": img.width,
            "height": img.height,
            "image": request.image
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class MoveRequest(BaseModel):
    x: int
    y: int


@app.post("/move/x={x},y={y}")
async def mouse_move_log(x: int, y: int):
    """Log mouse move coordinates sent from Electron after the move is performed."""
    print(f"[mouse:move] cursor moved to ({x}, {y})")
    return {"success": True, "x": x, "y": y}


@app.post("/click/left/x={x},y={y}")
async def left_click_log(x: int, y: int):
    """Log left click coordinates sent from Electron after the click is performed."""
    print(f"[mouse:left-click] left clicked at ({x}, {y})")
    return {"success": True, "x": x, "y": y}


@app.post("/click/double/x={x},y={y}")
async def double_click_log(x: int, y: int):
    """Log double click coordinates sent from Electron after the click is performed."""
    print(f"[mouse:double-click] double clicked at ({x}, {y})")
    return {"success": True, "x": x, "y": y}


@app.post("/click/right/x={x},y={y}")
async def right_click_log(x: int, y: int):
    """Log right click coordinates sent from Electron after the click is performed."""
    print(f"[mouse:right-click] right clicked at ({x}, {y})")
    return {"success": True, "x": x, "y": y}


@app.post("/scroll/x={x},y={y},direction={direction},amount={amount}")
async def scroll_log(x: int, y: int, direction: str, amount: int):
    """Log scroll event sent from Electron after the scroll is performed."""
    print(f"[mouse:scroll] scrolled {direction} x{amount} at ({x}, {y})")
    return {"success": True, "x": x, "y": y, "direction": direction, "amount": amount}
