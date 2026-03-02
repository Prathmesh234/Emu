# AGENTS.md — Human Emulation Desktop Agent

> **Living document.** Update this file as the project evolves — architecture decisions, tool additions, progress notes, and blockers all belong here.

---

## Project Overview

A desktop application that uses computer vision + LLM reasoning to emulate human interaction with any desktop UI. The user describes a task in natural language; the agent breaks it into atomic steps and executes them via simulated mouse/keyboard actions.

**Core Philosophy:** The agent should behave like a human operator — observe the screen, reason about state, act, verify, and adapt.

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Electron | Cross-platform desktop shell |
| Backend | Python (FastAPI) | REST + WebSocket server |
| Package Manager | `uv` | **All** Python packages must use `uv`. No pip/poetry/conda. |
| Primary Model | OpenAI API (GPT-4o) | Vision + reasoning |
| Future Models | Open models (e.g. Qwen-VL, InternVL) | To be integrated |
| Screen Capture | `mss` or `pyautogui` | Low-latency screenshots |
| Action Execution | `pyautogui` + `pynput` | Mouse/keyboard control |
| IPC | WebSocket (FastAPI → Electron) | Real-time step streaming |

---

## Architecture

```
┌─────────────────────────────────────────────┐
│                Electron App                  │
│  ┌──────────────┐    ┌─────────────────────┐│
│  │  Chat UI     │◄──►│  IPC / WS Client    ││
│  └──────────────┘    └────────┬────────────┘│
└───────────────────────────────┼─────────────┘
                                │ WebSocket
┌───────────────────────────────▼─────────────┐
│              FastAPI Server (Python)         │
│  ┌──────────────────────────────────────┐   │
│  │           Agent Orchestrator         │   │
│  │  1. Task → Planning LLM call         │   │
│  │  2. Steps → Tool dispatch loop       │   │
│  │  3. After each action → verify state │   │
│  └──────────────────────────────────────┘   │
│  ┌─────────────┐  ┌───────────────────────┐ │
│  │  Tool Layer │  │   Vision / OCR Layer  │ │
│  └─────────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## Agent Loop

```
User Prompt
    │
    ▼
[Planning Phase]  ── LLM call with screenshot + prompt → structured step list
    │
    ▼
[Execution Loop]
    ├── Capture screenshot
    ├── LLM selects next tool + arguments
    ├── Execute tool action
    ├── Capture post-action screenshot
    ├── LLM verifies success / detects error
    └── Repeat until task complete or max_steps reached
    │
    ▼
[Report to User]  ── Stream step results back via WebSocket
```

---

## Tool Registry

Each tool is a Python function registered with the agent. The LLM selects tools via function/tool calling.

| Tool | Description | Key Params |
|---|---|---|
| `screenshot` | Capture current screen state | `region?: Rect` |
| `click` | Left-click at coordinates | `x, y, button?` |
| `double_click` | Double-click at coordinates | `x, y` |
| `right_click` | Right-click at coordinates | `x, y` |
| `type_text` | Type a string at current focus | `text, interval?` |
| `press_key` | Press a keyboard key/combo | `key` (e.g. `"ctrl+c"`) |
| `scroll` | Scroll at position | `x, y, direction, amount` |
| `drag` | Click-drag from A to B | `x1, y1, x2, y2` |
| `find_element` | Locate UI element by description | `query: str` → `Rect` |
| `wait` | Pause execution | `ms: int` |
| `write_file` | Write content to a `.md` file | `path, content` |
| `read_clipboard` | Read current clipboard content | — |
| `set_clipboard` | Set clipboard content | `text` |
| `get_screen_text` | OCR the current screen | `region?: Rect` |

> **Adding tools:** Add the Python function to `tools/` with a docstring matching the OpenAI tool schema format. Register in `tool_registry.py`.

---

## Project Structure

```
/
├── electron/                  # Electron frontend
│   ├── main.js                # Main process
│   ├── preload.js
│   └── renderer/              # Chat UI (HTML/CSS/JS or React)
│
├── backend/                   # Python FastAPI server
│   ├── main.py                # FastAPI app entrypoint
│   ├── agent/
│   │   ├── orchestrator.py    # Agent loop
│   │   ├── planner.py         # Task → steps via LLM
│   │   └── verifier.py        # Post-action state check
│   ├── tools/
│   │   ├── tool_registry.py   # Tool registration
│   │   ├── mouse.py
│   │   ├── keyboard.py
│   │   ├── screen.py
│   │   └── filesystem.py
│   ├── models/
│   │   ├── openai_client.py   # OpenAI integration
│   │   └── base.py            # Abstract model interface (for open model swap)
│   └── pyproject.toml         # uv project config
│
├── AGENTS.md                  # This file
└── README.md
```

---

## Setup

```bash
# Backend
cd backend
uv venv
uv sync

# Run server
uv run uvicorn main:app --reload --port 8000

# Frontend
cd electron
npm install
npm start
```

**Required env vars:**
```
OPENAI_API_KEY=sk-...
BACKEND_PORT=8000
```

---

## Model Interface (Abstraction Layer)

All model calls go through `models/base.py` — a simple abstract class with `plan()` and `act()` methods. `openai_client.py` implements this. When open models are added, they implement the same interface.

```python
class BaseModel(ABC):
    @abstractmethod
    def plan(self, prompt: str, screenshot: bytes) -> list[Step]: ...
    
    @abstractmethod
    def act(self, screenshot: bytes, steps: list[Step], history: list) -> ToolCall: ...
```

---

## Progress Log

| Date | Milestone | Status |
|---|---|---|
| — | Project kickoff, AGENTS.md created | ✅ |
| — | Electron shell + FastAPI server scaffold | ⬜ |
| — | Tool layer (mouse, keyboard, screen) | ⬜ |
| — | Agent orchestrator loop | ⬜ |
| — | Planning + verification LLM calls | ⬜ |
| — | WebSocket streaming to Electron UI | ⬜ |
| — | End-to-end demo (simple task) | ⬜ |
| — | Open model integration | ⬜ |

---

## Known Constraints & Decisions

- **macOS accessibility permissions** required for `pyautogui`/`pynput`. Electron app must prompt user.
- **Coordinate space:** Screenshots must account for display scaling (Retina/HiDPI). Normalize before passing to model.
- **Rate limits:** OpenAI vision calls are expensive. Capture screenshots only when needed, not on a timer.
- **Security:** The agent has full desktop control. Implement a confirmation step for destructive actions (file deletion, form submission, etc.).
- **Max steps guard:** Default cap of 50 steps per task to prevent runaway loops.

---

## Open Questions

- [ ] How do we handle multi-monitor setups?
- [ ] Should planning be a separate LLM call or combined with execution?
- [ ] OCR engine choice: Tesseract vs. pass raw image to vision model?
- [ ] How to package Python backend inside Electron for distribution?