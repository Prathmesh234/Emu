# Modal Provider Notes

This document explains how Emu uses Modal for hosted model execution.

## Where Modal code lives

- Provider client: `backend/providers/modal/client.py`
- Compaction client: `backend/providers/modal/client_compact.py`
- Deployment script: `backend/providers/modal/deploy.py`
- Health checks: `backend/providers/modal/health.py`
- OmniParser deploy: `backend/providers/modal/omni_parser/`

## When Modal is used

Modal is selected when:

- no higher-priority provider credentials are detected, or
- `EMU_PROVIDER=modal` is explicitly set.

Detection logic is in `backend/providers/registry.py`.

## Automatic deploy behavior

`backend.sh` handles Modal deployment:

- If provider is Modal, it deploys the model app.
- If `USE_OMNI_PARSER=1`, it deploys OmniParser as well.

## Manual Modal commands

```bash
cd backend
uv run modal setup
uv run modal deploy providers/modal/deploy.py
```

Optional OmniParser deployment:

```bash
uv run modal deploy providers/modal/omni_parser/deploy.py
```

## Typical issues

## `modal` command missing

Use `uv run modal ...` so the project venv CLI is used.

## Auth/setup failures

Run `uv run modal setup` once to authenticate.

## Slow first response

This is often cold-start latency from remote containers.

## OmniParser increases latency

Enabling OmniParser adds processing overhead per screenshot; expect slower but more structured vision context.
