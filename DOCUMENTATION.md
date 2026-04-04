# Emulation Agent (v0.1) — Documentation

> Technical reference for architecture, design decisions, performance findings, and development patterns.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure](#3-project-structure)
4. [Architecture](#4-architecture)
5. [IPC Action Pattern](#5-ipc-action-pattern)
6. [Persistent Shell Process](#6-persistent-shell-process)
7. [Performance Findings](#7-performance-findings)
8. [Backend](#8-backend)
9. [Frontend](#9-frontend)
10. [Action Reference](#10-action-reference)
11. [Key Design Decisions & Problems Solved](#11-key-design-decisions--problems-solved)
12. [Running the App](#12-running-the-app)
13. [Planned Work](#13-planned-work)

---

## 1. Project Overview

A desktop application that uses computer vision and LLM reasoning to emulate human interaction with any desktop UI. The user describes a task in natural language; the agent breaks it into atomic steps and executes them via simulated mouse and keyboard actions.

**Core Philosophy:** The agent behaves like a human operator — observe the screen, reason about state, act, verify, and adapt.

---

## 2. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend shell | Electron 40.6.1 | Cross-platform desktop, CommonJS |
| Backend | Python (FastAPI) | REST server, log + persistence layer |
| Package manager | `uv` | **All** Python packages must use `uv`. No pip/poetry/conda. |
| Primary model | OpenAI API (GPT-4o) | Vision + reasoning — not yet integrated |
| Screen capture | Electron `desktopCapturer` | Avoids X display limit in backend by running capture in Node |
| Mouse/keyboard | PowerShell Win32 API | Single persistent PowerShell process, managed by Node |
| IPC | Electron `ipcMain` / `ipcRenderer` | `invoke`/`handle` async pattern |
| WebSocket (planned) | FastAPI WebSocket | For real-time agent → frontend command streaming |

---

## 3. Project Structure

```
emulation-agent/
│
├── main.js                          # Electron main process — lifecycle + IPC boot
├── package.json                     # npm config (electron only)
├── preload.js                       # Electron preload (currently minimal)
│
├── frontend/
│   ├── index.html                   # App shell
│   ├── app.js                       # Renderer entry — chat UI + keyword dispatch
│   ├── styles.css                   # App styles
│   │
│   ├── process/
│   │   └── psProcess.js             # Persistent PowerShell process manager
│   │
│   ├── actions/
│   │   ├── index.js                 # Barrel: exports all actions + registerAll()
│   │   ├── screenshot.js            # Screen capture action
│   │   ├── navigate.js              # Mouse move action
│   │   ├── leftClick.js             # Single left click action
│   │   ├── leftClickOpen.js         # Double-click (open file/folder) action
│   │   ├── rightClick.js            # Right click action
│   │   └── window.js                # App window management actions
│   │
│   └── components/
│       ├── index.js
│       ├── Message.js
│       ├── ChatInput.js
│       ├── Button.js
│       └── Sidebar.js
│
└── backend/
    ├── main.py                      # FastAPI app
    ├── pyproject.toml               # uv project config
    ├── README.md
    └── emulation_screen_shots/      # Auto-created, stores received screenshots
```

---

## 4. Architecture

```
┌──────────────────────────────────────────────────┐
│                  Electron App                     │
│                                                   │
│  ┌────────────────┐    ┌────────────────────────┐ │
│  │  Renderer      │    │  Main Process          │ │
│  │  (app.js)      │◄──►│  (main.js)             │ │
│  │                │IPC │                        │ │
│  │  Chat UI       │    │  registerAll()         │ │
│  │  Keyword       │    │  psProcess.start()     │ │
│  │  dispatch      │    │  createWindow()        │ │
│  └────────────────┘    └──────────┬─────────────┘ │
│                                   │               │
│                        ┌──────────▼─────────────┐ │
│                        │  psProcess.js          │ │
│                        │  (persistent shell)    │ │
│                        │  stdin/stdout pipe     │ │
│                        └────────────────────────┘ │
└────────────────────────────┬─────────────────────┘
                             │ HTTP (fetch)
┌────────────────────────────▼─────────────────────┐
│              FastAPI Backend (Python)             │
│                                                   │
│  POST /screenshot   — receive + save PNG          │
│  POST /move/...     — log mouse move              │
│  POST /click/...    — log click events            │
│                                                   │
│  (Future: WebSocket /ws for agent→frontend cmds)  │
└───────────────────────────────────────────────────┘
```

### Data flow for a single action

```
User types command in chat
        │
        ▼
app.js respond()  →  keyword match  →  calls action fn (renderer side)
        │
        ▼
ipcRenderer.invoke('mouse:left-click', { x, y })
        │
        ▼ (crosses process boundary)
ipcMain.handle in leftClick.js
        │
        ▼
psProcess.run('[W.U32]::mouse_event(2,0,0,0,0); ...')   ← stdin pipe, ~3ms
        │
        ▼
Win32 mouse_event fires the click on the OS
        │
        ├──► fetch POST /click/left/...  (fire-and-forget log to backend)
        │
        └──► return { success: true, x, y }
        │
        ▼
Renderer receives result, updates chat message
```

---

## 5. IPC Action Pattern

Every action lives in `frontend/actions/<name>.js` and exports exactly two things:

```javascript
// Renderer-side function — called from app.js
async function leftClick(x, y) {
    return await ipcRenderer.invoke('mouse:left-click', { x, y });
}

// Main-process IPC handler — registered once at startup
function register(ipcMain, BACKEND_URL) {
    ipcMain.handle('mouse:left-click', async (_event, { x, y }) => {
        // ... OS action + backend log
        return { success: true, x, y };
    });
}

module.exports = { leftClick, register };
```

**`frontend/actions/index.js`** is the barrel that collects all actions and exposes `registerAll()`:

```javascript
registerAll(ipcMain, deps) {
    screenshot.register(ipcMain, deps);
    navigate.register(ipcMain, deps.BACKEND_URL);
    leftClick.register(ipcMain, deps.BACKEND_URL);
    leftClickOpen.register(ipcMain, deps.BACKEND_URL);
    rightClick.register(ipcMain, deps.BACKEND_URL);
    window_.register(ipcMain, deps.getMainWindow);
}
```

**`main.js`** calls it once:

```javascript
const { registerAll } = require('./frontend/actions');
registerAll(ipcMain, { BACKEND_URL, desktopCapturer, screen, getMainWindow: () => mainWindow });
```

**Rule:** When adding a new action, always follow this pattern:
1. Create `frontend/actions/actionName.js` with both the renderer fn and `register()`
2. Add it to `index.js` barrel + `registerAll()`
3. Add a log endpoint in `backend/main.py`
4. Add keyword detection in `frontend/app.js` `respond()`

---

## 6. Persistent Shell Process

**File:** `frontend/process/psProcess.js`

### Why

Every `spawnSync` or `execSync` call pays the full process creation cost:

| Phase | Time |
|---|---|
| `CreateProcess()` / `fork()` | ~50ms |
| shell startup parsing | ~100–200ms |
| **Total per action** | **~150–250ms** |

For an agent loop running 20–50 steps, this is several seconds of pure overhead.

### Solution

One `powershell.exe` process started at app launch, kept alive for the duration of the session. Commands are piped via stdin (base64-encoded to avoid syntax errors); output is read from stdout using a sentinel string `##PS_DONE##` to detect completion. Win32 assemblies (System.Windows.Forms, user32.dll P/Invoke, GDI) are pre-loaded at startup.

```
App start → psProcess.start()
                │
                ▼
         spawn('powershell', ['-NoProfile', '-NonInteractive', '-Command', '-'])
                │
         Ready. Per-action cost: ~2–8ms (stdin write + stdout read)
```

### API

```javascript
const { start, run, stop } = require('./frontend/process/psProcess');

start();               // called once in app.whenReady()
await run('...');      // sends command, resolves with stdout output
stop();                // called in app 'will-quit'
```

### Command queue

If two actions fire simultaneously, `psProcess` serialises them internally through a `cmdQueue` array — the second command waits for the first's sentinel before being written to stdin. No race conditions.

### Lifecycle hooks in `main.js`

```javascript
app.whenReady().then(() => {
    psProcess.start();   // assemblies load in background
    createWindow();
});

app.on('will-quit', () => {
    psProcess.stop();    // clean stdin close
});
```

---

## 7. Performance Findings

### Per-action latency (renderer → IPC → OS action → IPC reply)

| Action | Old (new process per call) | New (persistent process) |
|---|---|---|
| `mouse:move` | ~400ms | ~3–6ms |
| `mouse:left-click` | ~450ms | ~2–5ms |
| `mouse:right-click` | ~450ms | ~2–5ms |
| `mouse:double-click` | ~500ms | ~55–65ms* |

\* Double-click has specialized handling to stay within the OS double-click time window. This is OS-inherent, not process overhead.

### Agent loop impact

```
20-step task, old:  20 × 450ms = 9000ms spawn overhead alone
20-step task, new:  20 ×   4ms =   80ms overhead
```

### Why the old double-click didn't work

The OS sees two isolated clicks, not a double-click. It interprets the first click as "select" and the second as "rename" on desktop icons.

**Fix:** Both click pairs in one `psProcess.run()` call via Win32 `mouse_event` to click natively without process spawning gaps.

---

## 8. Backend

**File:** `backend/main.py`  
**Start:** `uv run uvicorn main:app --reload --port 8000` (run from `backend/` in WSL)

The backend is currently a **log and persistence layer only**. All OS actions (mouse, keyboard) run on the Electron side. The backend receives action data for:
- Saving screenshots to disk
- Logging action events (for future agent memory/replay)

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `GET` | `/health` | Health check |
| `POST` | `/screenshot` | Receive base64 PNG, decode, save timestamped file to `emulation_screen_shots/` |
| `POST` | `/move/x={x},y={y}` | Log mouse move event |
| `POST` | `/click/left/x={x},y={y}` | Log left click event |
| `POST` | `/click/double/x={x},y={y}` | Log double click event |
| `POST` | `/click/right/x={x},y={y}` | Log right click event |

### Screenshot flow

```
Electron desktopCapturer.getSources()
    │ toDataURL() → strip "data:image/png;base64," prefix
    ▼
POST /screenshot  { image: "<base64>", width: N, height: N }
    │ base64.b64decode → PIL.Image.open → img.save(PNG)
    ▼
emulation_screen_shots/screenshot_YYYYMMDD_HHMMSS_fff.png
```

### Why not capture screenshots in the backend

`mss` and `pyautogui` both require a standard display to be active. Screenshots are captured entirely in Electron and sent to the backend as base64.

### Dependencies (`pyproject.toml`)

```toml
[project]
dependencies = [
    "fastapi",
    "pillow",
    "uvicorn[standard]"
]
```

`mss` and `pyautogui` were intentionally removed.

---

## 9. Frontend

### `main.js` — Main process

Minimal by design. Only responsibilities:
1. Import and call `registerAll()` to wire up all IPC handlers
2. Start and stop `psProcess`
3. `createWindow()` and Electron app lifecycle

### `frontend/app.js` — Renderer

- Builds the chat UI (vanilla JS, no framework)
- `sendMessage()` captures a screenshot then calls `respond()`
- `respond()` currently uses **keyword matching** to dispatch actions (LLM integration pending)
- Keyword priority order matters — `left-click-open` is checked before `left-click` to avoid partial match

### `frontend/process/psProcess.js`

See [Section 6](#6-persistent-shell-process).

### `frontend/actions/`

See [Section 5](#5-ipc-action-pattern) and [Section 10](#10-action-reference).

---

## 10. Action Reference

### `screenshot`
- **IPC channel:** `screenshot:capture`
- **Renderer fn:** `captureScreenshot()`
- **What it does:** Captures the primary display via `desktopCapturer`, converts to base64, POSTs to `/screenshot`
- **Returns:** `{ success, filename, width, height }`

### `navigate` (mouse move)
- **IPC channel:** `mouse:move`
- **Renderer fn:** `navigateMouse(x, y)`
- **What it does:** Sets mouse cursor position via `psProcess.run()`
- **Returns:** `{ success, x, y }`

### `leftClick`
- **IPC channel:** `mouse:left-click`
- **Renderer fn:** `leftClick(x, y)`
- **What it does:** Fires `mouse_event(0x02)` (DOWN) + `mouse_event(0x04)` (UP) via `psProcess.run()`
- **Note:** Move cursor to coordinates with `navigateMouse` first
- **Returns:** `{ success, x, y }`

### `leftClickOpen` (double-click)
- **IPC channel:** `mouse:double-click`
- **Renderer fn:** `leftClickOpen(x, y)`
- **What it does:** Fires two DOWN+UP pairs with `Start-Sleep -Milliseconds 50` between them, all in one `psProcess.run()` call
- **Returns:** `{ success, x, y }`

### `rightClick`
- **IPC channel:** `mouse:right-click`
- **Renderer fn:** `rightClick(x, y)`
- **What it does:** Fires `mouse_event(0x08)` (DOWN) + `mouse_event(0x10)` (UP) via `psProcess.run()`
- **Returns:** `{ success, x, y }`

### `window` actions
- **IPC channels:** `window:side-panel`, `window:centered`, `window:blur`
- **Renderer fns:** `moveToSidePanel()`, `moveToCentered()`, `blurWindow()`
- **What it does:** Repositions the Electron window — side panel snaps to right edge (400px wide, full height), centered restores original bounds
- **Used by:** `app.js` automatically moves to side panel when a task is sent

### Win32 mouse_event flags reference

| Flag | Hex | Decimal | Meaning |
|---|---|---|---|
| `MOUSEEVENTF_LEFTDOWN` | `0x02` | 2 | Left button press |
| `MOUSEEVENTF_LEFTUP` | `0x04` | 4 | Left button release |
| `MOUSEEVENTF_RIGHTDOWN` | `0x08` | 8 | Right button press |
| `MOUSEEVENTF_RIGHTUP` | `0x10` | 16 | Right button release |
| `MOUSEEVENTF_WHEEL` | `0x0800` | 2048 | Scroll wheel (not yet implemented) |

---

## 11. Key Design Decisions & Problems Solved

### Decision: All OS actions in Electron, not Python backend

Moving all mouse/keyboard/screenshot actions to the Electron main process eliminates Python library environment setup issues entirely.

### Decision: `desktopCapturer` over `mss`

`desktopCapturer` is Electron's built-in API, captures any screen with proper HiDPI/scaling awareness, and returns a `NativeImage` directly.

### Decision: Single persistent shell process

See [Section 6](#6-persistent-shell-process) and [Section 7](#7-performance-findings) for the full analysis. TL;DR: spawn overhead per action was high; persistent process drops it to 2–8ms.

### Decision: IPC co-located with action files

Initially IPC handlers lived in a separate `ipc/` folder. This was refactored so each action file owns both its renderer function and its `register()` IPC handler. Benefits: the handler and its logic are always in the same file, easier to trace, easier to delete/add actions atomically.

### Problem: Double-click not registering

**Root cause:** Two separate `spawnSync` calls took too long, missing the OS double-click time window. The gap left no room for the OS to recognise the pair as a double-click.

**Fix:** Both click pairs in one `psProcess.run()` call. Since the process is already running, both clicks fire within a single stdin write, separated only by `Start-Sleep -Milliseconds 50`.

### Problem: Duplicate `app.whenReady()` blocks

After the IPC refactor, `main.js` had leftover inline IPC handlers and a second `app.whenReady()` / `app.on('window-all-closed')` block from the old code. Cleaned up to a single lifecycle block.

---

## 12. Running the App

### Prerequisites

- Node.js + npm
- Python 3.12+ with `uv` installed
- Windows 10/11 (actions use PowerShell Win32 API)

### Backend

```bash
# In WSL terminal, from project root:
cd backend
uv run uvicorn main:app --reload --port 8000
```

### Frontend (Electron)

```bash
# In a separate terminal, from project root:
npm start

# Dev mode (opens DevTools):
npm run dev
```

### Environment variables

```
OPENAI_API_KEY=sk-...    # Required when LLM integration is added
BACKEND_PORT=8000        # Default, hardcoded in main.js as BACKEND_URL
```

---

## 13. Planned Work

| Feature | Notes |
|---|---|
| **LLM integration** | Replace keyword matching in `respond()` with OpenAI API call, pass screenshot base64 + chat history |
| **WebSocket streaming** | FastAPI `/ws` endpoint for real-time agent → frontend command streaming; frontend WS client dispatches to action functions |
| **`typeText` action** | `type` command via `psProcess.run()` |
| **`scroll` action** | scroll commands via `psProcess.run()` |
| **`hotkey` action** | key combo triggers via `psProcess.run()` |
| **`drag` action** | Move + LEFT_DOWN + move + LEFT_UP sequence |
| **Agent orchestrator** | Planning LLM call → step list → execution loop with post-action screenshot verification |
| **Multi-monitor support** | Coordinate normalisation across displays |
| **HiDPI handling** | Scale factor normalisation for Retina/4K displays |
| **Confirmation step** | User prompt before destructive actions (file delete, form submit) |
| **Max steps guard** | Default cap of 50 steps per task to prevent runaway loops |
| **Open model support** | Abstract `BaseModel` interface in backend for swapping GPT-4o → Qwen-VL / InternVL |
