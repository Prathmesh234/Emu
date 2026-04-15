# Emu Terminal — Setup & Usage Guide

## Overview

Emu Terminal is a Python-based TUI (Terminal User Interface) frontend for the Emu computer-use agent. It replaces the Electron/JavaScript desktop app with a Hermes-inspired terminal interface while reusing the **exact same FastAPI backend**.

```
┌─────────────────────────────────────────────────┐
│  You type a task in the terminal                │
│         ↓                                       │
│  Terminal captures your screen (mss + Pillow)   │
│         ↓                                       │
│  Sends screenshot + message to backend (REST)   │
│         ↓                                       │
│  Backend calls the model, returns an action     │
│         ↓  (via WebSocket)                      │
│  Terminal executes the action (pyautogui)        │
│         ↓                                       │
│  Terminal captures a new screenshot              │
│         ↓                                       │
│  Loop continues until task is done              │
└─────────────────────────────────────────────────┘
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Python** | 3.12+ | https://python.org |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Git** | any | `sudo apt install git` / `brew install git` |

### Platform-specific dependencies

**Linux (X11/Wayland):**
```bash
# pyautogui needs these for mouse/keyboard control
sudo apt install python3-tk python3-dev scrot xdotool
```

**macOS:**
```bash
# Grant Accessibility permissions to your terminal app
# System Settings → Privacy & Security → Accessibility → enable your terminal
```

**Windows:**
```bash
# No extra deps — pyautogui uses Win32 APIs natively
```

---

## Setup

### 1. Clone and switch to the terminal-emu branch

```bash
git clone https://github.com/Prathmesh234/Emu.git
cd Emu
git checkout terminal-emu
```

### 2. Configure your model provider

Copy the example env file into the backend directory and fill in your API key:

```bash
cp .env.example backend/.env
```

Edit `backend/.env` and set **one** of these (pick your provider):

```bash
# Option A: Anthropic Claude (recommended)
ANTHROPIC_API_KEY=sk-ant-...

# Option B: OpenRouter (200+ models)
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=qwen/qwen3.5-397b-a17b

# Option C: OpenAI
OPENAI_API_KEY=sk-...

# Option D: Google Gemini
GOOGLE_API_KEY=AIza...

# Option E: Self-hosted (vLLM / SGLang / Ollama)
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=none

# Option F: Modal GPU (no API key needed, uses Modal)
EMU_PROVIDER=modal
```

### 3. Install backend dependencies

```bash
cd backend
uv venv
uv sync
cd ..
```

### 4. Install terminal UI dependencies

```bash
cd terminal
uv venv
uv sync
cd ..
```

---

## Running

You need **two terminal windows** — one for the backend, one for the TUI.

### Terminal 1: Start the backend

```bash
./backend.sh
```

Or manually:

```bash
cd backend
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Wait until you see:

```
[emu] Emu Backend Starting
  Provider:    openrouter
  URL:         http://127.0.0.1:8000
```

### Terminal 2: Start the terminal UI

```bash
cd terminal
uv run python -m terminal
```

Or with options:

```bash
# Custom backend URL
uv run python -m terminal --backend http://192.168.1.50:8000

# Explicit auth token (normally auto-read from .emu/.auth_token)
uv run python -m terminal --token your_token_here
```

---

## Using the TUI

### Layout

```
┌──────────────────────────────────────────────────┐
│  Emu Terminal | model: claude | chain: 0 | idle  │  ← Status bar
├──────────────────────────────────────────────────┤
│                                                  │
│  (conversation appears here)                     │  ← Scrollable
│                                                  │
├──────────────────────────────────────────────────┤
│  > Type your task here...                        │  ← Input
└──────────────────────────────────────────────────┘
```

### Interaction

1. Type a task and press **Enter** (e.g., `Open Calculator and compute 42 * 17`)
2. The agent will:
   - Capture your screen
   - Reason about what to do
   - Execute mouse/keyboard actions
   - Capture a new screenshot after each action
   - Repeat until done
3. Each step shows: reasoning, action type, coordinates, and confidence

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Enter` | Send message |
| `Ctrl+C` | Stop current generation (press twice to quit) |
| `Ctrl+D` | Quit |

### Slash commands

| Command | Action |
|---------|--------|
| `/compact` | Compress conversation context |
| `/history` | Show past sessions |
| `/plan` | Show current task plan |
| `/verbose` | Cycle display verbosity |
| `/quit` | Exit the TUI |

---

## Architecture

```
terminal/
├── pyproject.toml          # Python dependencies
├── __init__.py
├── __main__.py             # CLI entry point (click)
├── config.py               # Config: auth token, backend URL
├── client.py               # Async HTTP + WebSocket client
├── screenshot.py           # Screen capture (mss → Pillow → WebP base64)
├── executor.py             # Action execution (pyautogui)
├── agent_loop.py           # Core observe → act → observe loop
├── app.py                  # Textual TUI application
├── app.tcss                # Textual CSS styling
├── widgets/
│   ├── status_bar.py       # Top bar: model, chain, confidence, state
│   ├── conversation.py     # Scrollable message history
│   ├── action_card.py      # Styled action display
│   ├── plan_card.py        # Plan review (approve/reject)
│   ├── screenshot_view.py  # Inline screenshot preview
│   └── input_bar.py        # Text input with slash commands
└── utils/
    └── image.py            # Base64 encoding, terminal graphics detection
```

### How it talks to the backend

The terminal client uses the **exact same API** as the Electron frontend:

| What | Endpoint | Purpose |
|------|----------|---------|
| Create session | `POST /agent/session` | Get a session_id |
| Send task | `POST /agent/step` | User message + screenshot |
| Real-time updates | `WS /ws/{session_id}` | Receive step/plan/done/error |
| Report action result | `POST /action/complete` | Tell backend the action finished |
| Stop agent | `POST /agent/stop` | Interrupt current trajectory |
| Compact context | `POST /agent/compact` | Compress long conversations |

Auth token is read from `.emu/.auth_token` (written by the backend on startup).

---

## Troubleshooting

### "Connection refused" when starting the TUI

The backend isn't running. Start it first with `./backend.sh`.

### "Invalid or missing auth token"

The auth token is generated fresh each time the backend starts. Restart the TUI after restarting the backend so it picks up the new token from `.emu/.auth_token`.

### pyautogui can't control the mouse/keyboard

- **Linux**: Install `xdotool` and `scrot` (`sudo apt install xdotool scrot`)
- **macOS**: Grant Accessibility permissions to your terminal
- **Wayland**: pyautogui has limited Wayland support — use X11 or Xwayland

### Screenshots are blank or wrong monitor

By default `mss` captures the primary monitor. Multi-monitor support is handled by selecting `sct.monitors[0]` (entire virtual screen) or `sct.monitors[1]` (primary).

---

## Development

### Implementation order

The scaffolding has `NotImplementedError` stubs. Implement in this order:

1. **`screenshot.py`** — get screen capture working first
2. **`executor.py`** — wire up pyautogui for each action type
3. **`client.py`** — implement REST calls and WebSocket listener
4. **`agent_loop.py`** — connect screenshot → backend → action → loop
5. **`app.py`** + widgets — layer on the Textual TUI
6. **`utils/image.py`** — inline screenshot rendering (sixel/kitty/block)

### Running tests

```bash
cd terminal
uv run python -c "from terminal.screenshot import capture_screenshot; print(capture_screenshot())"
uv run python -c "from terminal.executor import ActionExecutor; e = ActionExecutor(); print('OK')"
```

### Adding new action types

1. Add the handler method in `executor.py`
2. Add the IPC channel mapping in `ACTION_CHANNEL_MAP`
3. Add the label in `widgets/action_card.py` → `ACTION_LABELS`
