# Emu Agent (v0.1)

A desktop automation agent that uses computer vision + LLM reasoning to control any desktop UI. Describe a task in plain language — Emu observes your screen, plans steps, and executes them via simulated mouse, keyboard, and shell input.

---

## How It Works

```
User Prompt
    │
    ▼
[Planning Phase]  — LLM + screenshot → structured step list
    │
    ▼
[Execution Loop]
    ├── Capture screenshot
    ├── LLM selects next action + arguments
    ├── Execute action (mouse / keyboard / shell)
    ├── Capture post-action screenshot
    ├── LLM verifies result / detects errors
    └── Repeat until done or max steps reached
    │
    ▼
[Report to User]  — Stream results back via WebSocket
```

---

## Quick Start

```bash
# Terminal 1 — backend
./backend.sh

# Terminal 2 — frontend
./frontend.sh
```

Set your API key before running (or Emu falls back to Modal GPU):

```bash
# Create backend/.env or export in your shell — pick ONE:
export ANTHROPIC_API_KEY=your-api-key       # Claude (recommended)
export OPENAI_API_KEY=your-api-key          # OpenAI
export GOOGLE_API_KEY=your-api-key          # Google Gemini
export OPENROUTER_API_KEY=your-api-key      # OpenRouter (200+ models)
export EMU_PROVIDER=modal                   # Modal GPU (no key needed)
```

`backend.sh` handles everything: Python venv, dependency install, optional Modal deployment, and server startup.

### Prerequisites

- [Node.js](https://nodejs.org/) v18+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Linux**: `sudo apt install scrot imagemagick xdotool xclip`
- **macOS**: `brew install cliclick`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Desktop shell | Electron 40 |
| Backend | Python + FastAPI |
| Package manager | `uv` |
| Vision + reasoning | Claude / OpenAI / Gemini / Modal / Self-hosted |
| Action execution | `xdotool` (Linux), `cliclick` + AppleScript (macOS) |
| Screen capture | `scrot` (Linux), `screencapture` (macOS) |
| IPC | Electron `ipcMain` / `ipcRenderer` |

---

## Providers

Auto-detected from environment variables in this order:

1. `EMU_PROVIDER` — explicit override
2. `ANTHROPIC_API_KEY` → Claude
3. `OPENAI_BASE_URL` + `OPENAI_API_KEY` → OpenAI-compatible (self-hosted)
4. `OPENAI_API_KEY` → OpenAI
5. `GOOGLE_API_KEY` → Gemini
6. Fallback → Modal GPU

| Provider | Env Var | Default Model |
|---|---|---|
| Claude | `ANTHROPIC_API_KEY` | `claude-sonnet-4-6` |
| OpenAI | `OPENAI_API_KEY` | `gpt-5.4` |
| Gemini | `GOOGLE_API_KEY` | `gemini-3-flash-preview` |
| OpenAI-compatible | `OPENAI_BASE_URL` + `OPENAI_API_KEY` | Auto-detected |
| Modal GPU | *(none)* | `Qwen/Qwen3.5-35B-A3B` |

### Self-Hosted (vLLM / SGLang / Ollama)

```bash
vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8000

export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=none
```

### Adding a New Provider

All providers implement three functions:

```python
def call_model(agent_req: AgentRequest) -> AgentResponse: ...
def is_ready() -> bool: ...
def ensure_ready(**kwargs) -> None: ...
```

1. Create `backend/providers/your_provider/client.py`
2. Add `__init__.py` re-exporting those three functions
3. Register in `_PROVIDER_MAP` in `backend/providers/registry.py`
4. Add detection logic in `_detect_provider()`

---

## Skills

Skills extend the agent with named capabilities injected into the system prompt. They are plain Markdown files — no code required.

### Bundled Skills

| Skill | Purpose |
|---|---|
| `web-search` | Search web, open URLs in browser |
| `summarize` | Summarize text content |
| `system-info` | Query system information |
| `app-launcher` | Launch desktop applications |
| `file-manager` | File system operations |

### Creating a Skill

1. Create a folder under `backend/skills/bundled/your-skill/`
2. Add a `SKILL.md` file with this structure:

```markdown
---
name: your-skill
description: "One-line description of when to use this skill."
---

## Your Skill Name

Explain what the skill does and when the agent should use it.

### How to use

Step-by-step instructions the agent follows.

### Tips

- Any relevant tips, edge cases, or strategies.
```

The loader at `backend/skills/loader.py` auto-discovers all `SKILL.md` files in `bundled/` and injects them into the system prompt.

---

## Agent Memory (`.emu/`)

Persistent memory lives in `.emu/` at the project root, created automatically on first launch.

```
.emu/
├── manifest.json              # System metadata + bootstrap flag
├── workspace/
│   ├── SOUL.md                # Core personality (user-editable, never agent-modified)
│   ├── AGENTS.md              # Boot order + SOPs
│   ├── USER.md                # User identity (populated during bootstrap)
│   ├── IDENTITY.md            # Agent name, role, voice
│   ├── MEMORY.md              # Curated long-term facts (agent-maintained wiki)
│   ├── BOOTSTRAP.md           # First-launch interview script
│   └── memory/                # Daily session logs (YYYY-MM-DD.md)
├── sessions/<id>/
│   ├── plan.md                # Task plan (mandatory first action each session)
│   ├── notes.md               # Scratch notes during execution
│   └── screenshots/
└── global/
    └── preferences.md         # Inferred user preferences (agent writes)
```

### Injection Tiers

| Tier | When | Files |
|---|---|---|
| **Firmware** | Every request | `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md`, `preferences.md` |
| **Conditional** | Session start | `MEMORY.md` (≤3k tokens), `memory/today.md`, `memory/yesterday.md` |
| **Tool-accessible** | On demand via `shell_exec` | Older `memory/*.md`, session files |

### SOUL.md

`SOUL.md` is the agent's core personality file. It defines ethical boundaries, communication style, and behavioral rules. **Only the user should edit this file — the agent never modifies it.** Changing it changes the agent's fundamental character.

### Bootstrap

On first launch, the agent runs a short interview (2–4 exchanges) to populate `USER.md` and `IDENTITY.md`. All future sessions skip this and go straight to plan-first mode.

---

## Safety Features

| Feature | Behavior |
|---|---|
| **Shell confirmation** | Every `shell_exec` shows Allow / Deny before running |
| **File locks** | `SOUL.md`, `AGENTS.md`, `USER.md`, `IDENTITY.md` are write-protected at harness level |
| **Command timeout** | All shell commands killed after 30 seconds |

---

## Actions

| Action | Type | Description |
|---|---|---|
| `screenshot` | vision | Capture current screen |
| `mouse_move` | mouse | Move cursor to (x, y) |
| `left_click` | mouse | Left-click at cursor |
| `double_click` | mouse | Double-click at cursor |
| `right_click` | mouse | Right-click at cursor |
| `scroll` | mouse | Scroll N notches |
| `type_text` | keyboard | Type a string |
| `key_press` | keyboard | Press key combo (e.g. `ctrl+c`) |
| `shell_exec` | system | Run shell command, get stdout |
| `wait` | system | Pause N milliseconds |
| `done` | control | Signal task complete |

---

## Project Structure

```
Emu/
├── main.js                    # Electron main process + IPC
├── backend.sh                 # Start backend (one command)
├── frontend.sh                # Start frontend (one command)
│
├── backend/
│   ├── main.py                # FastAPI entry point
│   ├── pyproject.toml         # uv dependencies
│   ├── context_manager/       # Token-budgeted conversation history
│   ├── prompts/               # System prompt, plan, compact, bootstrap
│   ├── providers/             # Claude, OpenAI, Gemini, Modal, OpenAI-compat
│   ├── models/                # Pydantic request/response models
│   ├── skills/
│   │   ├── loader.py          # Auto-discovers and injects skills
│   │   └── bundled/           # Built-in skills (each with SKILL.md)
│   └── workspace/             # .emu/ file reader + context builder
│
└── frontend/
    ├── index.html
    ├── app.js
    ├── pages/Chat.js          # Main chat page (WS routing, agent loop)
    ├── components/            # Header, Message, StepCard, ChatInput, Sidebar…
    ├── actions/               # IPC action handlers (screenshot, click, type…)
    ├── process/psProcess.js   # Persistent shell (~2–8 ms/action)
    ├── services/              # HTTP + WebSocket clients
    ├── emu/                   # .emu/ folder init + defaults
    └── state/store.js         # Centralized app state
```

---

## Further Reading

| Document | Purpose |
|---|---|
| [SETUP.md](SETUP.md) | Full setup guide, all providers, OmniParser, troubleshooting |
| [DOCUMENTATION.md](DOCUMENTATION.md) | IPC patterns, persistent shell, performance |
| [BACKEND.md](backend/BACKEND.md) | Backend architecture, Modal GPU, agent loop |
| [FRONTEND.md](frontend/FRONTEND.md) | Component architecture, services, state |
| [CONTEXT_CHAIN.md](CONTEXT_CHAIN.md) | Context management design and limitations |
| [LEARNINGS.md](LEARNINGS.md) | Engineering decisions: OmniParser, cursor capture |
