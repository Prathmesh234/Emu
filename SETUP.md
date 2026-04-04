# Emu (v0.1) — Setup Guide

Everything you need to get Emu running, from zero to working desktop agent.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| **Node.js** | v18+ | [nodejs.org](https://nodejs.org/) |
| **Python** | 3.12+ | [python.org](https://www.python.org/downloads/) |
| **uv** | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### Platform dependencies

**Windows** — no extra installs needed:
- PowerShell 5.1+ (included with Windows 10/11)
- System.Windows.Forms and GDI assemblies (loaded automatically)

---

## Quick Start (two terminals)

```bash
# Terminal 1 — backend
./backend.sh

# Terminal 2 — frontend
./frontend.sh
```

That's it. Both scripts handle dependency installation, Modal deployments, and startup automatically.

---

## What the scripts do

### `backend.sh`

1. Creates a Python virtual environment via `uv venv` (skips if `.venv/` exists)
2. Installs all Python dependencies via `uv sync`
3. Loads `backend/.env` if present
4. Auto-detects your model provider from environment variables
5. **If provider is `modal`** — runs `modal deploy` for the Qwen VLM automatically
6. **If `USE_OMNI_PARSER=1`** — runs `modal deploy` for OmniParser V2 automatically
7. Starts the FastAPI server on `http://127.0.0.1:8000`

### `frontend.sh`

1. Runs `npm install` (skips if `node_modules/` exists)
2. Launches the Electron desktop app

---

## Choosing a model provider

Emu auto-detects your provider from environment variables. Set **one** API key and go.

### Option 1: Create a `backend/.env` file

```bash
# backend/.env — pick ONE provider

# Claude (recommended)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
# OPENAI_API_KEY=sk-...

# Google Gemini
# GOOGLE_API_KEY=AIza...

# OpenRouter (200+ models)
# OPENROUTER_API_KEY=sk-or-...

# Self-hosted (vLLM, SGLang, Ollama)
# OPENAI_BASE_URL=http://localhost:8000/v1
# OPENAI_API_KEY=none

# Force a specific provider (overrides auto-detection)
# EMU_PROVIDER=claude
```

### Option 2: Export in your shell

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./backend.sh
```

### Auto-detection order

If multiple keys are set, Emu picks the first match:

| Priority | Env var | Provider |
|----------|---------|----------|
| 1 | `EMU_PROVIDER` | Explicit override |
| 2 | `ANTHROPIC_API_KEY` | Claude (Anthropic) |
| 3 | `OPENROUTER_API_KEY` | OpenRouter |
| 4 | `OPENAI_BASE_URL` + `OPENAI_API_KEY` | OpenAI-compatible (self-hosted) |
| 5 | `OPENAI_API_KEY` | OpenAI |
| 6 | `GOOGLE_API_KEY` | Google Gemini |
| 7 | *(none)* | Modal (free GPU fallback) |

---

## Modal deployment (automatic)

If no API keys are set, Emu falls back to **Modal** — running Qwen3.5 on remote GPUs. `backend.sh` handles the deployment automatically:

```
./backend.sh
# [emu] Detected provider: modal
# [emu] Provider is 'modal' — deploying Qwen VLM on Modal...
# [emu] Modal VLM deployment complete
# [emu] Emu Backend Starting
```

### First-time Modal setup

If you haven't used Modal before:

```bash
# Install is handled by uv sync, but you need to authenticate:
uv run modal setup
```

This opens a browser to link your Modal account. You only need to do this once.

---

## OmniParser (optional)

OmniParser V2 adds UI element detection — it annotates screenshots with bounding boxes and labels so the model sees precise coordinates instead of guessing from raw pixels.

### Enable it

```bash
# Option A: environment variable
export USE_OMNI_PARSER=1
./backend.sh

# Option B: add to backend/.env
USE_OMNI_PARSER=1
```

When enabled, `backend.sh` automatically deploys OmniParser to Modal (A10G GPU) before starting the server. This works with **any** provider — Claude, OpenAI, Gemini, or Modal.

### What happens under the hood

1. `backend.sh` detects `USE_OMNI_PARSER=1`
2. Runs `modal deploy providers/modal/omni_parser/deploy.py`
3. OmniParser deploys on an A10G GPU (YOLO + EasyOCR)
4. Every screenshot the agent takes is routed through OmniParser
5. The model receives an annotated image + structured element list

### Performance

| Metric | Value |
|--------|-------|
| Warm latency | ~1.5s per screenshot |
| Cold start | ~15s (first request after idle) |
| GPU | NVIDIA A10G |

---

## Self-hosted models (vLLM / SGLang / Ollama)

Run any vision-language model on your own hardware:

```bash
# Terminal 1 — start your model server
vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8080

# Terminal 2 — point Emu at it
export OPENAI_BASE_URL=http://localhost:8080/v1
export OPENAI_API_KEY=none
./backend.sh
```

Works with any OpenAI-compatible server. The backend polls `/v1/models` to auto-detect the model name.

### Server examples

```bash
# vLLM
vllm serve Qwen/Qwen2.5-VL-72B-Instruct --port 8080

# SGLang
python -m sglang.launch_server --model Qwen/Qwen2.5-VL-72B-Instruct --port 30000

# Ollama
ollama serve
ollama pull llava
# Then: OPENAI_BASE_URL=http://localhost:11434/v1
```

---

## Manual setup (without scripts)

If you prefer running commands yourself:

```bash
# Backend
cd backend
uv venv
uv sync

# (Optional) Deploy Modal model
uv run modal deploy providers/modal/deploy.py

# (Optional) Deploy OmniParser
uv run modal deploy providers/modal/omni_parser/deploy.py

# Start server
uv run uvicorn main:app --reload --port 8000
# Add --use-omni-parser flag if you want OmniParser enabled

# Frontend (separate terminal)
cd ..
npm install
npm start
```

---

## Troubleshooting

### `uv: command not found`
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# Then restart your terminal or: source ~/.bashrc
```

### `modal: command not found` (when using Modal provider)
The modal CLI is installed as a Python dependency. `backend.sh` handles this by running `uv run modal deploy ...` which uses the venv's modal. If running manually:
```bash
cd backend
uv run modal setup    # authenticate (first time only)
uv run modal deploy providers/modal/deploy.py
```

### Backend starts but frontend can't connect
Make sure the backend is running on port 8000 before starting the frontend. The Electron app connects to `http://127.0.0.1:8000`.

### OmniParser cold start is slow
First request after the Modal container idles takes ~15s. Subsequent requests are ~1.5s. The container stays warm for 5 minutes after the last request.

### PowerShell execution policy errors
If you get execution policy errors, run PowerShell as admin and execute:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
