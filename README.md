# Emu Agent

Emu is a desktop automation agent that combines screen understanding, LLM planning, and OS-level action execution.

## What is included now

- Desktop action loop with screenshot -> reason -> act -> verify behavior.
- Provider auto-detection with broad model support.
- Async Hermes Agent delegation for heavy terminal/code tasks.
- macOS memory daemon (launchd) for background memory curation.
- Auth-token protected backend API (`X-Emu-Token`).
- Session artifacts and memory stored under `.emu/`.

## New features called out

### 1. Memory daemon

- Daemon runs out-of-process on macOS via launchd.
- Tick interval is 120 seconds (see `daemon/launchd/com.emu.memory-daemon.plist.template`).
- Command entrypoint is `daemon/launchd/run.sh`.
- Installer CLI: `python3 -m daemon.install_macos <command>`.

Useful commands:

```bash
python3 -m daemon.install_macos install
python3 -m daemon.install_macos status
python3 -m daemon.install_macos run-now
python3 -m daemon.install_macos uninstall
```

### 2. Hermes Agent integration

Backend includes async Hermes job tools:

- `invoke_hermes`
- `check_hermes`
- `cancel_hermes`
- `list_hermes_jobs`

Implementation details:

- Job registry and subprocess draining: `backend/tools/hermes_jobs.py`
- Tool handlers: `backend/tools/hermes.py`
- Results persisted to session `hermes/task_result_XX.md` files.

### 3. Provider expansion

Current detection chain includes:

- Claude
- OpenRouter
- Azure OpenAI
- OpenAI-compatible endpoints
- OpenAI
- Gemini
- Bedrock
- Fireworks
- Together AI
- Baseten
- H Company
- Modal fallback

Reference: `backend/providers/registry.py`.

## Launch commands

Recommended startup uses two terminals.

```bash
# Terminal 1: backend
./backend.sh

# Terminal 2: frontend
./frontend.sh
```

Manual startup:

```bash
# Backend
cd backend
uv venv
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8000

# Frontend (new terminal)
cd ..
npm install
npm start
```

## Environment variables you will likely use

```bash
# Pick one provider key (or use EMU_PROVIDER override)
ANTHROPIC_API_KEY=
OPENROUTER_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=

# Optional
EMU_PROVIDER=
OPENAI_BASE_URL=
USE_OMNI_PARSER=1
EMU_DEV=1
```

Also review `backend/.env.example` for full provider and daemon options.

## Common issues and fixes

### Backend 401 errors

Symptom:

- Frontend calls fail with unauthorized responses.

Cause:

- Missing or mismatched `X-Emu-Token` header.

Fix:

- Ensure frontend is reading `.emu/.auth_token` created by backend startup.
- Restart backend and frontend so both use the same token.

### Frontend cannot connect

Symptom:

- UI starts but no responses.

Fix:

- Confirm backend is running on `http://127.0.0.1:8000`.
- Confirm no firewall or local proxy is intercepting loopback.

### macOS actions fail silently

Fix:

- Grant Accessibility and Screen Recording permissions.
- Restart app after granting permissions.

### Modal deployment fails

Fix:

```bash
cd backend
uv run modal setup
```

Then retry `./backend.sh`.

### Hermes jobs stuck or slow

Fix:

- Poll with `check_hermes`.
- Cancel with `cancel_hermes` if no output for extended periods.
- Review session result files and backend logs for stderr output.

### Daemon not running

Fix:

- Check status with `python3 -m daemon.install_macos status`.
- Reinstall launch agent if needed.
- Ensure app is not running from a transient translocation or mounted image path.

## Repository map

- `backend/`: FastAPI agent harness, providers, tools, prompts.
- `frontend/`: Electron renderer UI, actions, services, store, styles.
- `daemon/`: memory daemon runtime, policy, state, launchd installer.
- `backend.sh` / `frontend.sh`: one-command startup scripts.

## Additional docs

- `SETUP.md`
- `DOCUMENTATION.md`
- `backend/BACKEND.md`
- `frontend/FRONTEND.md`
- `daemon/DESIGN.md`
- `HARNESS_IMPROVEMENTS.md`
- `FRONTEND_REDESIGN.md`
