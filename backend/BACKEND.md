# Backend Reference

Backend entrypoint: `backend/main.py`.

## Responsibilities

- Session creation and lifecycle.
- Context building and history management.
- Model provider invocation.
- Server-side tool execution.
- Action validation and loop safety.
- WebSocket streaming to frontend.
- Auth-token protection for HTTP endpoints.

## Endpoints

- `GET /health`
- `POST /agent/session`
- `GET /agent/session/{session_id}`
- `POST /agent/step`
- `POST /action/complete`
- `POST /agent/compact`
- `POST /agent/stop`
- `WS /ws/{session_id}`

## Provider subsystem

Location: `backend/providers/`.

Each provider exposes:

- `call_model(agent_req)`
- `is_ready()`
- `ensure_ready(...)`
- compact client (`client_compact.py`)

Registry and auto-detection: `backend/providers/registry.py`.

## Tooling subsystem

Primary files:

- `backend/tools/dispatcher.py`
- `backend/tools/handlers.py`
- `backend/tools/compaction.py`
- `backend/tools/hermes.py`
- `backend/tools/hermes_jobs.py`

Notable tools:

- planning + session files (`update_plan`, `read_plan`, `write_session_file`, `read_session_file`)
- memory + skills (`read_memory`, `use_skill`)
- context maintenance (`compact_context`)
- Hermes async delegation (`invoke_hermes`, `check_hermes`, `cancel_hermes`, `list_hermes_jobs`)

## Hermes behavior details

- Hermes is invoked with non-interactive `hermes chat -Q -q`.
- Jobs run in background asyncio subprocesses.
- stdout/stderr are drained concurrently to avoid pipe deadlock.
- Job status includes liveness hints and timeout handling.
- Output is persisted to session markdown artifacts for auditability.

## Security and auth

- Per-launch random token generated in backend startup.
- Token stored at `.emu/.auth_token`.
- Middleware requires `X-Emu-Token` on most HTTP routes.

## Context and validation

- Context manager stores per-session conversation turns.
- Action validator blocks known looping/invalid patterns.
- Tool loop has max-iteration safeguards.
- Schema/validation failures are re-injected as model feedback.

## Startup

Preferred:

```bash
./backend.sh
```

Manual:

```bash
cd backend
uv venv
uv sync
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

## Troubleshooting pointers

- Provider readiness issues: inspect provider `ensure_ready` behavior and env vars.
- Repeated 401 responses: confirm frontend token source.
- Hanging Hermes jobs: check `check_hermes`, timeout, and session result files.
- Context growth issues: verify compaction tool calls and thresholds.
