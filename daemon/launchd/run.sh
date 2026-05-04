#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# run.sh — launchd entrypoint for the Emu Memory Daemon.
#
# launchd does NOT inherit your interactive shell env, so we source backend/.env
# here to bring in provider API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
# and EMU_DAEMON_PROVIDER. Then we exec the venv's Python on `daemon.run` —
# a single tick that exits.
#
# This file is invoked by ~/Library/LaunchAgents/com.emu.memory-daemon.plist
# every 2 minutes. WorkingDirectory is set to the repo root by the plist.
# ──────────────────────────────────────────────────────────────────────────────

set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

# Pull provider keys + EMU_DAEMON_PROVIDER from backend/.env if present.
if [ -f "$REPO_DIR/backend/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/backend/.env"
    set +a
fi

# Prefer the backend's uv-managed venv; fall back to system python3.
PYTHON="$REPO_DIR/backend/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3 || true)"
fi

if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    echo "[daemon/run.sh] no python interpreter found" >&2
    exit 127
fi

# Make `from daemon ...` and `from backend ...` (used by daemon/llm_client.py)
# both resolvable.
export PYTHONPATH="$REPO_DIR:$REPO_DIR/backend${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" -m daemon.run
