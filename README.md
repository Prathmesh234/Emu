# Emulation Agent

A desktop application that uses computer vision + LLM reasoning to emulate human interaction with any desktop UI. Describe a task in natural language — the agent observes the screen, plans a sequence of actions, and executes them via simulated mouse and keyboard input.

---

## How It Works

```
User Prompt
    │
    ▼
[Planning Phase]  — LLM call with screenshot + prompt → structured step list
    │
    ▼
[Execution Loop]
    ├── Capture screenshot
    ├── LLM selects next action + arguments
    ├── Execute action (mouse / keyboard / screen)
    ├── Capture post-action screenshot
    ├── LLM verifies success / detects error
    └── Repeat until task complete or max steps reached
    │
    ▼
[Report to User]  — Stream results back via WebSocket
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | Electron 40 |
| Backend server | Python + FastAPI |
| Python packages | `uv` (no pip/poetry/conda) |
| Vision + reasoning | OpenAI GPT-4o |
| Action execution | Win32 `user32.dll` via persistent PowerShell |
| Screen capture | Electron `desktopCapturer` |
| IPC | Electron `ipcMain`/`ipcRenderer` |

---

## Project Structure

```
emulation-agent/
│
├── main.js                        # Electron main process + app lifecycle
├── package.json
│
├── frontend/
│   ├── index.html                 # App shell
│   ├── app.js                     # Chat UI logic + action dispatch
│   ├── styles.css
│   │
│   ├── actions/                   # IPC-backed action modules
│   │   ├── index.js               # Barrel — registerAll()
│   │   ├── screenshot.js          # Capture screen (panel included)
│   │   ├── fullCapture.js         # Capture screen (panel excluded)
│   │   ├── navigate.js            # Move mouse cursor
│   │   ├── leftClick.js           # Left click
│   │   ├── leftClickOpen.js       # Double-click / open
│   │   ├── rightClick.js          # Right click
│   │   ├── scroll.js              # Scroll wheel
│   │   └── window.js              # Side-panel / centered window toggle
│   │
│   ├── process/
│   │   └── psProcess.js           # Persistent PowerShell process (~2–8 ms/action)
│   │
│   └── components/                # UI components
│       ├── index.js
│       ├── Message.js
│       ├── ChatInput.js
│       ├── Button.js
│       └── Sidebar.js
│
└── backend/
    ├── main.py                    # FastAPI entry point
    ├── pyproject.toml             # uv dependencies
    └── emulation_screen_shots/    # Screenshot output folder
```

---

## Setup

### Prerequisites

- [Node.js](https://nodejs.org/) (v18+)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python package management
- Python 3.12+
- Windows (Win32 APIs used for mouse/keyboard actions)

### Install

```bash
# Frontend
npm install

# Backend
cd backend
uv venv
uv sync
```

### Environment variables

Create a `.env` file or set these in your shell:

```
OPENAI_API_KEY=sk-...
```

### Run

```bash
# Terminal 1 — Electron app
npm start

# Terminal 2 — FastAPI backend
cd backend
uv run uvicorn main:app --reload --port 8000
```

---

## Actions

| Action | Keyword trigger | Description |
|---|---|---|
| `captureScreenshot` | *(automatic on every message)* | Full-screen capture, panel included |
| `fullCapture` | `full capture` | Full-screen capture, panel excluded (moves window off-screen) |
| `navigateMouse` | `move` | Move cursor to (x, y) |
| `leftClick` | `left-click` | Left-click at (x, y) |
| `leftClickOpen` | `left-click-open` | Double-click / open at (x, y) |
| `rightClick` | `right-click` | Right-click at (x, y) |
| `scroll` | `scroll` | Scroll up/down N notches at (x, y) |

Screenshots are saved to `backend/emulation_screen_shots/`.

---

## Architecture Notes

### Persistent PowerShell Process

All mouse and keyboard actions go through a single long-running PowerShell process (`frontend/process/psProcess.js`) instead of spawning a new process per action.

| Approach | Latency |
|---|---|
| Old — `spawnSync` per action | ~350–650 ms |
| New — persistent stdin/stdout | ~2–8 ms |

Win32 `user32.dll` (`mouse_event`, `keybd_event`) is P/Invoked once at startup and reused for every action.

### Window Modes

- **Centered** — default 800×600, centered on screen, `alwaysOnTop: false`
- **Side panel** — snaps to right edge, full display height, `alwaysOnTop: 'screen-saver'`

### Full Capture (panel-excluded)

Moves the Electron window off-screen (`x: -9999`) with `setBounds(false)` (no animation), waits 80 ms for the OS compositor to render without the window, captures, then restores bounds.

---

## Planned Work

- [ ] LLM integration (GPT-4o vision + tool calling)
- [ ] WebSocket streaming of agent steps to frontend
- [ ] `typeText` action
- [ ] `hotkey` action (e.g. `Ctrl+C`, `Alt+Tab`)
- [ ] `drag` action
- [ ] Multi-monitor support
- [ ] Confirmation step for destructive actions
- [ ] Open model support (Qwen-VL, InternVL)
- [ ] Electron packaging / distribution
