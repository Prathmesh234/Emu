# Emu Setup Guide

This guide is the practical setup path for running Emu locally.

## Prerequisites

- Node.js 18+
- Python 3.12+
- `uv` package manager

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS-only dependencies:

```bash
brew install cliclick
```

Then grant permissions:

- Accessibility
- Screen Recording

For the packaged `.dmg` app flow and exact System Settings paths, see `MACOS_PERMISSIONS.md`.

## Quick start

Open two terminals at repo root.

```bash
# Terminal 1
./backend.sh

# Terminal 2
./frontend.sh
```

## What startup scripts do

## `backend.sh`

- Loads `backend/.env` if present.
- Creates `.venv` with `uv venv` when needed.
- Runs `uv sync`.
- Detects provider from env vars.
- Deploys Modal model automatically when provider resolves to `modal`.
- Deploys OmniParser when `USE_OMNI_PARSER` is enabled.
- Starts FastAPI at `127.0.0.1:8000`.
- On macOS, prompts one-time memory daemon install via `daemon.install_macos`.

## `frontend.sh`

- Installs npm dependencies if missing.
- Runs Electron (`npm start`).

## Provider setup

Create `backend/.env` (or export vars in shell) and set one provider key.

Examples:

```bash
# Claude
ANTHROPIC_API_KEY=...

# OpenAI
OPENAI_API_KEY=...

# OpenRouter
OPENROUTER_API_KEY=...

# Gemini
GOOGLE_API_KEY=...

# Azure OpenAI
AZURE_OPENAI_ENDPOINT=...
AZURE_OPENAI_API_KEY=...

# OpenAI-compatible endpoint (vLLM/SGLang/Ollama)
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_API_KEY=none
```

Optional overrides:

```bash
EMU_PROVIDER=claude
EMU_MODEL_TIMEOUT_SECS=60
EMU_MODEL_TIMEOUT_RETRIES=1
USE_OMNI_PARSER=1
EMU_DEV=1
```

For OpenRouter, `OPENROUTER_REQUEST_TIMEOUT_SECS=60` keeps the SDK request
timeout aligned with Emu's model-call timeout instead of the longer SDK default.

## Memory daemon setup (macOS)

The daemon runs as a per-user LaunchAgent and does not need sudo, Screen Recording, Accessibility, or Full Disk Access. The desktop app itself needs Screen Recording and Accessibility for screenshots and control.

If you skipped the backend prompt or want manual control:

```bash
python3 -m daemon.install_macos install
```

Check it:

```bash
python3 -m daemon.install_macos status
```

Force a tick:

```bash
python3 -m daemon.install_macos run-now
```

Remove it:

```bash
python3 -m daemon.install_macos uninstall
```

## Manual launch commands (without scripts)

```bash
# Backend
cd backend
uv venv
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8000

# Frontend
cd ..
npm install
npm start
```

## Troubleshooting

## `uv` not found

- Reinstall `uv`.
- Restart terminal session.

## API calls failing with 401

- Backend enforces auth token in `X-Emu-Token`.
- Ensure frontend is using `.emu/.auth_token` from current backend run.

## Frontend starts but no backend response

- Verify backend logs show server listening at `127.0.0.1:8000`.
- Verify no stale backend process is writing a different auth token.

## Modal issues

```bash
cd backend
uv run modal setup
```

Then rerun `./backend.sh`.

## Hermes tool use fails

- Install Hermes if missing (tool guidance is returned automatically).
- Confirm Hermes binary is on PATH.
- Use `check_hermes` polling for long jobs.

## Daemon install refused

Installer blocks transient paths like app translocation or mounted disk images.
Use a stable path (`/Applications` for app bundle or a normal source checkout) and retry.
