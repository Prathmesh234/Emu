# Emu Technical Documentation

This file summarizes the current architecture and runtime behavior.

## System architecture

Emu has three major pieces:

- Electron frontend (`main.js` + `frontend/`)
- FastAPI backend (`backend/main.py`)
- Optional macOS memory daemon (`daemon/` via launchd)

## Request/response loop

1. User sends message in frontend.
2. Frontend captures screenshot when needed.
3. Backend appends input into session context.
4. Backend calls active provider.
5. Provider returns tool calls, desktop action, or `done`.
6. Backend executes server-side tool calls or returns action for frontend execution.
7. Frontend executes action and reports completion.
8. Loop repeats.

## Security model

- Backend generates per-launch auth token.
- Token is written to `.emu/.auth_token`.
- HTTP calls require `X-Emu-Token` (except preflight and health).
- CORS is restricted to localhost/null origins.

## Providers

Provider loader: `backend/providers/registry.py`.

Detection order currently includes:

- explicit `EMU_PROVIDER`
- key-based detection for Claude/OpenRouter/Azure OpenAI/OpenAI-compatible/OpenAI/Gemini/Bedrock/Fireworks/Together/Baseten/H Company
- fallback to Modal

## Tool execution model

- Tool schemas are declared in `backend/providers/agent_tools.py`.
- Tool dispatch routes through `backend/tools/dispatcher.py` and handlers.
- Plan review and compaction hooks run through tool loop controls in `backend/main.py`.

## Hermes architecture

Hermes integration is async and non-blocking:

- `invoke_hermes` starts subprocess job and returns `job_id`.
- `hermes_jobs.py` drains stdout/stderr concurrently to avoid deadlocks.
- `check_hermes` returns status snapshots or final output.
- Results are persisted per session under a `hermes/` subfolder.

## Memory model

Workspace data root: `.emu/`.

Key paths:

- `.emu/workspace/`: firmware and persistent memory files.
- `.emu/sessions/<id>/`: per-session plans, notes, screenshots, Hermes artifacts.
- `.emu/global/`: preferences and daemon logs/state.

## Daemon model

The daemon runs as launchd job on macOS:

- Launcher template: `daemon/launchd/com.emu.memory-daemon.plist.template`
- Entrypoint: `daemon/launchd/run.sh`
- Tick body: `python -m daemon.run`

It is intentionally separate from backend process lifecycle.

## Frontend model

Frontend is split into:

- components (`frontend/components/`)
- page layer (`frontend/pages/`)
- API + WebSocket services (`frontend/services/`)
- centralized store (`frontend/state/store.js`)
- desktop action bridge (`frontend/actions/`)

## Performance notes

- Frontend action execution uses persistent shell process (`frontend/process/psProcess.js`) to reduce repeated process spawn overhead.
- Hermes jobs are background subprocesses with polling rather than blocking model loop.
- Context compaction support exists to keep long sessions manageable.
