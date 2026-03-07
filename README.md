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
| Vision + reasoning | Claude, OpenAI, Gemini, or self-hosted (see Providers) |
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
├── .emu/                          # Persistent agent memory (see Memory section)
│   ├── manifest.json
│   ├── workspace/
│   ├── sessions/
│   └── global/
│
├── frontend/
│   ├── index.html                 # App shell
│   ├── app.js                     # Mounts Chat page
│   ├── styles.css
│   │
│   ├── pages/
│   │   └── Chat.js                # Main chat page (WS routing, agent loop)
│   │
│   ├── components/                # UI components
│   │   ├── index.js               # Barrel exports
│   │   ├── Header.js              # 🦤 Emu title bar + window controls
│   │   ├── EmptyState.js          # Welcome screen
│   │   ├── StatusIndicator.js     # Pulsing dot + status text
│   │   ├── Message.js             # Chat bubble (user / assistant)
│   │   ├── ChatInput.js           # Textarea + send/stop button
│   │   ├── StepCard.js            # Step card, DoneCard, ErrorCard
│   │   ├── Button.js              # Button factory + SVG icons
│   │   ├── Sidebar.js             # Chat history sidebar
│   │   └── Tooltip.js             # Tooltip wrapper
│   │
│   ├── actions/                   # IPC-backed action modules
│   │   ├── index.js               # Barrel — registerAll()
│   │   ├── actionProxy.js         # Maps backend actions → IPC dispatch
│   │   ├── screenshot.js          # Capture screen (panel included)
│   │   ├── fullCapture.js         # Capture screen (panel excluded)
│   │   ├── exec.js                # shell_exec — run PowerShell commands
│   │   ├── navigate.js            # Move mouse cursor
│   │   ├── leftClick.js           # Left click
│   │   ├── leftClickOpen.js       # Double-click / open
│   │   ├── rightClick.js          # Right click
│   │   ├── scroll.js              # Scroll wheel
│   │   ├── keyboard.js            # Type text / key press
│   │   └── window.js              # Side-panel / centered toggle
│   │
│   ├── process/
│   │   └── psProcess.js           # Persistent PowerShell process (~2–8 ms/action)
│   │
│   ├── emu/                       # .emu/ folder management
│   │   ├── init.js                # initEmu() — idempotent scaffold
│   │   ├── defaults.js            # Default file contents
│   │   └── index.js               # Barrel exports
│   │
│   ├── services/
│   │   ├── api.js                 # HTTP client (session, step, stop)
│   │   └── websocket.js           # WebSocket client
│   │
│   └── state/
│       └── store.js               # Centralized app state
│
└── backend/
    ├── main.py                    # FastAPI entry point
    ├── pyproject.toml             # uv dependencies
    ├── context_manager/
    │   └── context.py             # Session history chain
    ├── workspace/
    │   └── reader.py              # .emu/ file reader + context builder
    ├── prompts/
    │   └── system_prompt.py       # Dynamic system prompt builder
    ├── providers/
    │   ├── registry.py            # Auto-detect provider from env vars
    │   ├── claude/
    │   │   └── client.py          # Claude API (Anthropic)
    │   ├── openai_provider/
    │   │   └── client.py          # OpenAI API (GPT-4o / GPT-4.1)
    │   ├── gemini/
    │   │   └── client.py          # Google Gemini API
    │   ├── openai_compatible/
    │   │   └── client.py          # Any OpenAI-compat server (vLLM, SGLang, Ollama)
    │   └── modal/
    │       └── client.py          # Modal GPU inference
    ├── models/
    │   ├── actions.py             # Action types enum
    │   ├── request.py             # AgentRequest model
    │   └── response.py            # AgentResponse model
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

Set **one** API key and Emu auto-detects the provider. Create a `.env` in `backend/` or export in your shell:

```bash
# Pick ONE — Emu uses whichever key it finds (checked in this order):
export ANTHROPIC_API_KEY=sk-ant-...       # → Claude (Anthropic)
export OPENAI_API_KEY=sk-...              # → OpenAI (GPT-4o / GPT-4.1)
export GOOGLE_API_KEY=AIza...             # → Google Gemini

# Self-hosted GPU (vLLM, SGLang, Ollama, etc.):
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=none                # most local servers don't need a real key

# Force a specific provider (overrides auto-detection):
export EMU_PROVIDER=claude                # claude | openai | gemini | openai_compatible | modal
```

See the **Providers** section below for full details.

### Run

```bash
# Terminal 1 — FastAPI backend
cd backend
uv run uvicorn main:app --reload --port 8000

# Terminal 2 — Electron app
npm start
```

---

## Providers

Emu is backend-agnostic — it works with any vision-language model. All providers share the same system prompt, context chain, and response format. Just export the right API key and go.

### Supported Providers

| Provider | Env Var | Default Model | API | Notes |
|---|---|---|---|---|
| **Claude** (Anthropic) | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` | Messages API | Best quality. Recommended for most users. |
| **OpenAI** | `OPENAI_API_KEY` | `gpt-5.4` | [Responses API](https://platform.openai.com/docs/api-reference/responses) | Set `OPENAI_MODEL` to override. Uses the latest Responses API (not Chat Completions). |
| **Google Gemini** | `GOOGLE_API_KEY` | `gemini-3-flash-preview` | [Gemini 3 API](https://ai.google.dev/gemini-api/docs/gemini-3) | Set `GEMINI_MODEL` to override. Uses google-genai SDK with typed Parts. |
| **OpenAI-compatible** | `OPENAI_BASE_URL` + `OPENAI_API_KEY` | Auto-detected from `/v1/models` | [Chat Completions](https://docs.vllm.ai/en/stable/serving/openai_compatible_server/) | Works with vLLM, SGLang, Ollama, and any OpenAI-compat server. |
| **Modal** (GPU) | *(none needed)* | `Qwen/Qwen3.5-35B-A3B` | OpenAI-compat | Remote GPU inference via Modal. |

### Auto-Detection

The backend checks environment variables in this order and loads the first match:

1. `EMU_PROVIDER` — explicit override (e.g. `EMU_PROVIDER=openai`)
2. `ANTHROPIC_API_KEY` → Claude
3. `OPENAI_BASE_URL` + `OPENAI_API_KEY` → OpenAI-compatible (self-hosted)
4. `OPENAI_API_KEY` → OpenAI
5. `GOOGLE_API_KEY` → Gemini
6. Fallback → Modal

### Self-Hosted GPU Setup (vLLM / SGLang / Ollama)

Run any vision-language model on your own hardware via the OpenAI-compatible provider.
Uses the standard `/v1/chat/completions` endpoint that all major serving frameworks implement.

- [vLLM docs](https://docs.vllm.ai/en/stable/serving/openai_compatible_server/)
- [SGLang docs](https://docs.sglang.io/basic_usage/openai_api_completions.html)
- [Ollama OpenAI compat](https://github.com/ollama/ollama/blob/main/docs/openai.md)

```bash
# vLLM (recommended entrypoint)
vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8000

# SGLang (recommended entrypoint)
sglang serve Qwen/Qwen2.5-VL-72B-Instruct --port 30000

# Ollama
ollama serve  # default port 11434
ollama pull llava
```

Then point Emu at it:

```bash
# vLLM
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=none

# SGLang
export OPENAI_BASE_URL=http://localhost:30000/v1
export OPENAI_API_KEY=none

# Ollama
export OPENAI_BASE_URL=http://localhost:11434/v1
export OPENAI_API_KEY=none

# Optional: specify the model name if auto-detection doesn't work
export OPENAI_COMPAT_MODEL=Qwen/Qwen2.5-VL-72B-Instruct
```

The backend will poll `/v1/models` until the server is ready, then auto-detect the model name.

### Adding a New Provider

All providers implement the same three-function interface:

```python
def call_model(agent_req: AgentRequest) -> AgentResponse: ...
def is_ready() -> bool: ...
def ensure_ready(**kwargs) -> None: ...
```

1. Create `backend/providers/your_provider/client.py` implementing those functions
2. Create `__init__.py` re-exporting them
3. Add an entry to `_PROVIDER_MAP` in `backend/providers/registry.py`
4. Add auto-detection logic in `_detect_provider()`

---

## Safety Features

### Shell Command Confirmation

Every `shell_exec` action requires explicit user approval before execution. When the model wants to run a command:

1. The command is displayed in a scrollable preview with dark-themed monospace formatting
2. **Allow** / **Deny** buttons appear below the command
3. If denied, the model receives feedback: `"DENIED — user has denied this command. Try a different approach."`
4. The model then adapts and tries an alternative strategy

### File Locks

Protected workspace files (`SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`) are enforced at the harness level — not just in the prompt. Any `shell_exec` command that attempts to write, delete, or rename these files is automatically blocked before execution.

### Command Timeout

All PowerShell commands have a 30-second timeout. If a command hangs (e.g. from an accidental recursive search), it's automatically killed and returns an error. This prevents the persistent PowerShell process from locking up.

---

## Agent Memory System (`.emu/`)

The agent has a persistent, structured memory that lives in a `.emu/` directory at the project root. This folder is created automatically on first launch and survives across sessions. It gives the agent continuity — knowledge about who the user is, what happened in past sessions, and how the user prefers to work.

### Directory Structure

```
.emu/
├── manifest.json                  # System metadata + bootstrap flag
│
├── workspace/                     # Agent's working memory
│   ├── SOUL.md                    # Core personality (firmware)
│   ├── AGENTS.md                  # Boot order & SOP (firmware)
│   ├── USER.md                    # User identity (firmware)
│   ├── IDENTITY.md                # Agent capabilities & voice (firmware)
│   ├── MEMORY.md                  # Curated long-term memory (conditional)
│   ├── BOOTSTRAP.md               # First-launch interview script
│   └── memory/                    # Daily session logs
│       ├── 2026-03-05.md
│       ├── 2026-03-06.md
│       └── ...
│
├── sessions/                      # Per-session working data
│   └── <session-id>/
│       ├── plan.md                # Task plan (mandatory first action)
│       ├── notes.md               # Scratch notes during execution
│       └── screenshots/           # Session-specific screenshots
│
└── global/                        # Cross-session preferences
    └── preferences.md             # Inferred user preferences
```

### Injection Tiers

Not all files are loaded into every request. The agent's memory is organized into three tiers that balance context richness against token cost:

| Tier | When Injected | Files | Purpose |
|---|---|---|---|
| **Firmware** | Every request, always | `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `preferences.md` | Core identity — who the agent is, who the user is, how to behave |
| **Conditional** | Session start, gated | `MEMORY.md`, `memory/today.md`, `memory/yesterday.md` | Long-term facts + recent context. `MEMORY.md` truncated at ~3k tokens |
| **Tool-accessible** | On demand via `shell_exec` | `memory/*.md` (older), `sessions/<id>/*` | Historical data the agent reads only when needed |

```
             ┌─────────────────────────────────────────────┐
             │           System Prompt                      │
             │                                              │
 Firmware ──►│  SOUL.md ─ AGENTS.md ─ USER.md              │  ← Always present
             │  IDENTITY.md ─ preferences.md                │
             │                                              │
 Conditional►│  MEMORY.md (≤3k tokens)                     │  ← Session start
             │  memory/today.md + memory/yesterday.md       │
             │                                              │
             └─────────────────────────────────────────────┘

 Tool-access  memory/2026-02-*.md                             ← Agent reads via
              sessions/<old-id>/plan.md                          shell_exec
```

### File Descriptions

#### Firmware Files (always injected)

| File | Owner | Purpose |
|---|---|---|
| `SOUL.md` | **User only** | Core personality, ethical boundaries, communication rules. The agent NEVER modifies this. Changing it changes the agent's fundamental character. |
| `AGENTS.md` | **User only** | Boot sequence order and standard operating procedures. Think of it as `docker-compose.yml` for the agent's brain. |
| `USER.md` | **User only** | User's self-declared identity — name, role, timezone, editor, tech stack, communication preferences. Populated during bootstrap. Agent never auto-modifies. |
| `IDENTITY.md` | **User only** | Agent's name, role, capabilities, limitations, and voice definition. Adjusted during bootstrap to match user's preferred tone. |
| `preferences.md` | **Agent writes** | Inferred patterns from observing the user across sessions. Gradually populated — e.g., "User prefers keyboard shortcuts over mouse," "User always uses dark mode." |

#### Conditional Files (session start)

| File | Owner | Purpose |
|---|---|---|
| `MEMORY.md` | **Agent curates** | A personal wiki of important facts distilled from daily logs. Not a log — entries are updated, merged, and pruned to stay compact. Injected every session but truncated if it exceeds ~3k tokens. |
| `memory/YYYY-MM-DD.md` | **Agent appends** | Daily session log. Append-only entries with timestamps: what was done, key decisions, anything to remember. Today + yesterday are auto-injected; older files are accessible via `shell_exec`. |

#### Session Files (per-session working data)

| File | Owner | Purpose |
|---|---|---|
| `sessions/<id>/plan.md` | **Agent writes** | Mandatory. The agent's FIRST action every session (before any desktop interaction) is writing a plan: Task, Steps, Expected Outcome. A living document — updated mid-session if strategy changes. |
| `sessions/<id>/notes.md` | **Agent writes** | Scratch space for observations, blockers, or decisions during execution. |
| `sessions/<id>/screenshots/` | **System** | Session-specific screenshot storage. |

#### System Files

| File | Owner | Purpose |
|---|---|---|
| `manifest.json` | **System** | Schema version, creation date, app version, `bootstrap_complete` flag, session counters, active provider, platform info. Written once at init, updated for bootstrap completion. |
| `BOOTSTRAP.md` | **System** | First-launch interview script. Defines the questions the agent asks to populate `USER.md` and `IDENTITY.md`. Can be deleted after bootstrap. |

### File Lifecycle

```
                    Created at              Written by         Modified by           Read every
                    ──────────              ──────────         ───────────           ──────────
manifest.json       npm start (first)       initEmu()          bootstrap complete    backend (startup)
SOUL.md             npm start (first)       initEmu()          user (manually)       every request
AGENTS.md           npm start (first)       initEmu()          user (manually)       every request
USER.md             npm start (first)       initEmu()          bootstrap interview   every request
IDENTITY.md         npm start (first)       initEmu()          bootstrap interview   every request
BOOTSTRAP.md        npm start (first)       initEmu()          never                 bootstrap only
preferences.md      npm start (first)       initEmu()          agent (gradual)       every request
MEMORY.md           npm start (first)       initEmu()          agent (curates)       session start
memory/YYYY-MM-DD   end of session          agent              agent (append-only)   today+yesterday
plan.md             first action            agent              agent (updates)       agent (on demand)
notes.md            during session          agent              agent (appends)       agent (on demand)
```

### Bootstrap Flow

On the very first launch, `manifest.json` has `bootstrap_complete: false`. The backend detects this and injects the bootstrap prompt block instead of the normal plan-first mandate.

```
First Launch
    │
    ▼
manifest.json → bootstrap_complete: false
    │
    ▼
Backend injects BOOTSTRAP_BLOCK into system prompt
    │
    ▼
Agent greets user, conducts conversational interview
  (2-4 exchanges — name, role, timezone, editor, tech stack, comm style)
    │
    ▼
Agent writes USER.md and IDENTITY.md via shell_exec
    │
    ▼
Agent sets manifest.json → bootstrap_complete: true
    │
    ▼
All future sessions skip bootstrap, use normal plan-first mode
```

### Context Chain (per request)

Every API request to the model carries a conversation history built by the `ContextManager`:

```
[0] system      System prompt + workspace context (firmware + conditional files)
[1] user        "Open Notepad and type hello world"
[2] assistant   { action: shell_exec, command: "Set-Content plan.md ..." }
[3] user        [SCREENSHOT]
[4] assistant   { action: mouse_move, coordinates: { x: 50, y: 680 } }
[5] user        [SCREENSHOT]
[6] assistant   { action: left_click }
...
```

Older screenshots in the chain are replaced with `[A screenshot was taken here and reviewed by you]` to save tokens. Only the most recent screenshot is sent as an actual image.

### Memory Curation Rules

The agent follows specific rules for writing to memory files:

1. **Session plan** (`plan.md`) — mandatory first action, before any desktop interaction
2. **Daily log** (`memory/YYYY-MM-DD.md`) — appended at end of each task with summary
3. **Long-term memory** (`MEMORY.md`) — after writing a daily log, agent promotes important facts. This is a wiki: update outdated entries, remove stale info, keep it compact
4. **Preferences** (`preferences.md`) — agent adds entries only when confident about a pattern across multiple sessions
5. **Protected files** — agent NEVER modifies `SOUL.md`, `USER.md`, `IDENTITY.md`, or `AGENTS.md`

---

## Actions

| Action | Type | Description |
|---|---|---|
| `screenshot` | vision | Capture current screen state |
| `mouse_move` | mouse | Move cursor to (x, y) |
| `left_click` | mouse | Left-click at cursor position |
| `double_click` | mouse | Double-click at cursor position |
| `right_click` | mouse | Right-click at cursor position |
| `scroll` | mouse | Scroll up/down N notches |
| `type_text` | keyboard | Type a string at current focus |
| `key_press` | keyboard | Press a key combo (e.g., `ctrl+c`) |
| `shell_exec` | system | Run a PowerShell command, get stdout |
| `wait` | system | Pause N milliseconds |
| `done` | control | Task complete |

Screenshots are saved to `backend/emulation_screen_shots/`.

---

## Architecture Notes

### Persistent PowerShell Process

All mouse, keyboard, and shell_exec actions go through a single long-running PowerShell process (`frontend/process/psProcess.js`).

Commands are Base64-encoded before piping to prevent unclosed quotes, here-strings, or multi-line content from interfering with the sentinel marker that signals command completion.

| Approach | Latency |
|---|---|
| Old — `spawnSync` per action | ~350–650 ms |
| New — persistent stdin/stdout | ~2–8 ms |

Win32 `user32.dll` (`mouse_event`, `keybd_event`) is P/Invoked once at startup and reused for every action.

### Window Modes

- **Centered** — default 800×600, centered on screen, `alwaysOnTop: false`. Used for chat/bootstrap.
- **Side panel** — snaps to right edge, full display height, `alwaysOnTop: 'screen-saver'`. Activated only when a vision/action step arrives (not for conversational messages).

### Full Capture (panel-excluded)

Moves the Electron window off-screen (`x: -9999`) with `setBounds(false)` (no animation), waits 80 ms for the OS compositor to render without the window, captures, then restores bounds.

---

## Planned Work

- [ ] Multi-monitor support
- [x] Confirmation step for destructive actions (shell_exec Allow/Deny)
- [x] Open model support (OpenAI, Gemini, vLLM, SGLang, Ollama)
- [ ] Electron packaging / distribution
- [ ] Vector retrieval for old memory chunks
- [ ] `drag` action
