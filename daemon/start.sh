#!/usr/bin/env bash
# Long-running launcher for the memory daemon (Ctrl+C to stop).
# `python -m daemon.run` exits after each pass; this script re-invokes it on a
# configurable pause (EMU_DAEMON_INTERVAL_SECONDS, default 300) so idle work does not spin.

set -euo pipefail

DAEMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DAEMON_DIR/.." && pwd)"
BACKEND_DIR="$ROOT/backend"

RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${CYAN}[emu-daemon]${NC} $*"; }
err()  { echo -e "${RED}[emu-daemon]${NC} $*" >&2; }

if ! command -v uv &>/dev/null; then
    err "uv is not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    err "python3 is not found."
    exit 1
fi

if [ -f "$BACKEND_DIR/.env" ]; then
    info "Loading environment from backend/.env"
    set -a
    # shellcheck disable=SC1091
    source "$BACKEND_DIR/.env"
    set +a
fi

detect_provider() {
    local explicit="${EMU_PROVIDER:-}"
    explicit="$(printf '%s' "$explicit" | tr '[:upper:]' '[:lower:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

    if [ -n "$explicit" ]; then
        echo "$explicit"
        return
    fi

    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        echo "claude"
    elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
        echo "openrouter"
    elif [ -n "${AZURE_OPENAI_ENDPOINT:-}" ] && [ -n "${AZURE_OPENAI_API_KEY:-}" ]; then
        echo "azure_openai"
    elif [ -n "${OPENAI_BASE_URL:-}" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
        echo "openai_compatible"
    elif [ -n "${OPENAI_API_KEY:-}" ]; then
        echo "openai"
    elif [ -n "${GOOGLE_API_KEY:-}" ]; then
        echo "gemini"
    elif [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
        echo "bedrock"
    elif [ -n "${FIREWORKS_API_KEY:-}" ]; then
        echo "fireworks"
    elif [ -n "${TOGETHER_API_KEY:-}" ]; then
        echo "together_ai"
    elif [ -n "${BASETEN_API_KEY:-}" ]; then
        echo "baseten"
    elif [ -n "${H_COMPANY_API_KEY:-}" ]; then
        echo "h_company"
    else
        echo "modal"
    fi
}

PROVIDER="$(detect_provider)"
export EMU_DAEMON_PROVIDER="${EMU_DAEMON_PROVIDER:-$PROVIDER}"
export PYTHONPATH="$ROOT"
# EMU_ROOT: optional in backend/.env. Empty/unset → Python uses <repo>/.emu (same as frontend/emu/init.js).
if [ -z "${EMU_ROOT:-}" ]; then unset EMU_ROOT 2>/dev/null || true; fi

cd "$BACKEND_DIR"
if [ ! -d ".venv" ]; then
    info "Creating Python virtual environment..."
    uv venv
fi
info "Installing/syncing Python dependencies..."
uv sync

INTERVAL="${EMU_DAEMON_INTERVAL_SECONDS:-300}"
info "Provider: ${BOLD}${EMU_DAEMON_PROVIDER}${NC}  EMU_ROOT: ${BOLD}${EMU_ROOT:-$ROOT/.emu}${NC} (default: repo .emu/)"
info "Pause between passes: ${BOLD}${INTERVAL}s${NC} (EMU_DAEMON_INTERVAL_SECONDS; Ctrl+C to stop)"

while true; do
    set +e
    ( cd "$ROOT" && PYTHONPATH="$ROOT" uv run --project "$BACKEND_DIR" python -m daemon.run )
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        err "Process exited with status $status; continuing."
    fi
    sleep "$INTERVAL"
done
