# Backend Architecture

> Plan for the Emulation Agent backend services.

---

## Overview

The backend is a FastAPI server that orchestrates desktop automation. It receives tasks from the Electron frontend, uses vision + LLM to understand the screen, and executes mouse/keyboard actions.

---

## Directory Structure

```
backend/
├── main.py                 # FastAPI app entry
├── pyproject.toml          # uv dependencies
│
├── agent/
│   ├── orchestrator.py     # Main agent loop
│   └── state.py            # Task state management
│
├── services/
│   ├── screen.py           # Screenshot capture
│   ├── mouse.py            # Mouse actions (click, drag, scroll)
│   ├── keyboard.py         # Keyboard actions (type, press)
│   └── ocr.py              # Optional OCR utilities
│
├── llm/
│   ├── client.py           # LLM API client (OpenAI)
│   ├── prompts.py          # System prompts
│   └── parser.py           # Parse LLM responses to actions
│
├── tools/
│   ├── registry.py         # Tool registration
│   └── definitions.py      # Tool schemas for LLM
│
└── api/
    ├── routes.py           # REST endpoints
    └── websocket.py        # WebSocket for streaming
```

---

## Services Breakdown

### 1. Screen Service (`services/screen.py`)
Captures screenshots using `mss` (fast) or `pyautogui`.

```python
# Functions
capture_screen() -> bytes          # Full screen
capture_region(x, y, w, h) -> bytes  # Region only
get_screen_size() -> (width, height)
```

### 2. Mouse Service (`services/mouse.py`)
Mouse control using `pyautogui`.

```python
# Functions
click(x, y)
double_click(x, y)
right_click(x, y)
move(x, y)
drag(x1, y1, x2, y2)
scroll(x, y, clicks)  # positive = up, negative = down
```

### 3. Keyboard Service (`services/keyboard.py`)
Keyboard control using `pyautogui`.

```python
# Functions
type_text(text, interval=0.05)
press_key(key)           # e.g., "enter", "tab", "escape"
hotkey(*keys)            # e.g., hotkey("ctrl", "c")
```

### 4. LLM Client (`llm/client.py`)
Communicates with OpenAI GPT-4o (vision model).

```python
# Functions
async analyze_screen(screenshot: bytes, task: str, history: list) -> Action
```

**Input**: Screenshot + task description + action history
**Output**: Next action to take (tool name + parameters)

### 5. Agent Orchestrator (`agent/orchestrator.py`)
Main loop that ties everything together.

```python
# Flow
async run_task(task: str):
    while not done and steps < max_steps:
        screenshot = capture_screen()
        action = await llm.analyze_screen(screenshot, task, history)
        result = execute_action(action)
        history.append(action, result)
        # Stream progress to frontend
```

---

## Agent Loop Flow

```
┌─────────────────────────────────────────────────────┐
│                    User Task                         │
│              "Open notepad and type hello"           │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              1. Capture Screenshot                   │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              2. Send to LLM (GPT-4o)                │
│     - Screenshot (base64)                           │
│     - Task description                              │
│     - Previous actions                              │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              3. LLM Returns Action                  │
│     { "tool": "click", "x": 100, "y": 200 }        │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              4. Execute Action                      │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              5. Verify / Loop                       │
│     - Capture new screenshot                        │
│     - Check if task complete                        │
│     - Repeat or finish                              │
└─────────────────────────────────────────────────────┘
```

---

## Tools (LLM can call)

| Tool | Description | Parameters |
|------|-------------|------------|
| `click` | Left click | `x`, `y` |
| `double_click` | Double click | `x`, `y` |
| `right_click` | Right click | `x`, `y` |
| `type_text` | Type string | `text` |
| `press_key` | Press key | `key` (e.g., "enter") |
| `hotkey` | Key combo | `keys` (e.g., ["ctrl", "v"]) |
| `scroll` | Scroll | `x`, `y`, `clicks` |
| `drag` | Drag | `x1`, `y1`, `x2`, `y2` |
| `wait` | Pause | `seconds` |
| `done` | Task complete | `message` |

---

## API Endpoints

### REST

```
GET  /health              # Health check
POST /task                # Submit new task
GET  /task/{id}           # Get task status
POST /task/{id}/stop      # Stop running task
```

### WebSocket

```
WS /ws                    # Real-time updates
```

**Messages from server:**
```json
{ "type": "step", "action": "click", "x": 100, "y": 200 }
{ "type": "screenshot", "data": "base64..." }
{ "type": "done", "message": "Task completed" }
{ "type": "error", "message": "Failed to..." }
```

---

## Dependencies

All installed via `uv`:

```bash
uv add fastapi uvicorn[standard]  # API server
uv add pyautogui                   # Mouse/keyboard
uv add mss                         # Screenshots
uv add pillow                      # Image processing
uv add openai                      # LLM client
uv add websockets                  # WebSocket support
uv add python-dotenv               # Env vars
```

---

## Environment Variables

```
OPENAI_API_KEY=sk-...
BACKEND_PORT=8000
MAX_STEPS=50
```

---

## Implementation Order

1. **Services** - screen, mouse, keyboard (can test independently)
2. **LLM Client** - connect to OpenAI, test with screenshots
3. **Tool Registry** - define tools LLM can call
4. **Orchestrator** - main loop
5. **API + WebSocket** - connect to frontend

---

## Run

```bash
cd backend
uv run uvicorn main:app --reload --port 8000
```
