#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# backend.sh — One-command Emu backend launcher
#
# What it does:
#   1. Creates a Python venv (if needed) and installs dependencies via uv
#   2. Loads .env from backend/ if present
#   3. Detects your model provider (same logic as the Python registry)
#   4. If provider is "modal" → runs `modal deploy` for the Qwen VLM
#   5. If USE_OMNI_PARSER is enabled → runs `modal deploy` for OmniParser
#   6. Starts the FastAPI backend on port 8000
#
# Usage:
#   chmod +x backend.sh
#   ./backend.sh
#
# Environment variables (optional):
#   EMU_PROVIDER        — force a provider: claude|openai|gemini|openai_compatible|modal
#   USE_OMNI_PARSER     — set to 1/true/yes to enable OmniParser
#   ANTHROPIC_API_KEY   — auto-selects Claude
#   OPENROUTER_API_KEY  — auto-selects OpenRouter
#   OPENAI_API_KEY      — auto-selects OpenAI (or OpenAI-compatible if OPENAI_BASE_URL set)
#   GOOGLE_API_KEY      — auto-selects Gemini
#   EMU_DAEMON_AUTO_INSTALL — 1 (default) installs/refreshes the macOS launchd
#                             memory daemon non-interactively; 0 falls back to
#                             an interactive y/N/never prompt.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[emu]${NC} $*"; }
ok()    { echo -e "${GREEN}[emu]${NC} $*"; }
warn()  { echo -e "${YELLOW}[emu]${NC} $*"; }
err()   { echo -e "${RED}[emu]${NC} $*" >&2; }

# ── Pre-flight checks ───────────────────────────────────────────────────────

if ! command -v uv &>/dev/null; then
    err "uv is not installed. Install it first:"
    err "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    err "python3 is not found. Please install Python 3.12+."
    exit 1
fi

# ── Load .env if present ────────────────────────────────────────────────────

if [ -f "$BACKEND_DIR/.env" ]; then
    info "Loading environment from backend/.env"
    set -a
    # shellcheck disable=SC1091
    source "$BACKEND_DIR/.env"
    set +a
fi

# ── Python environment setup ────────────────────────────────────────────────

cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
    info "Creating Python virtual environment..."
    uv venv
    ok "Virtual environment created"
else
    info "Virtual environment already exists"
fi

info "Installing/syncing Python dependencies..."
uv sync
ok "Dependencies installed"

# ── Detect provider ─────────────────────────────────────────────────────────
# Mirrors the detection logic in backend/providers/registry.py

detect_provider() {
    # Trim + lowercase without xargs (xargs can fail in some environments and drop EMU_PROVIDER).
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
info "Detected provider: ${BOLD}${PROVIDER}${NC}"

# ── Check if OmniParser is enabled ──────────────────────────────────────────

omni_enabled() {
    local val="${USE_OMNI_PARSER:-}"
    val="$(echo "$val" | tr '[:upper:]' '[:lower:]')"
    [[ "$val" == "1" || "$val" == "true" || "$val" == "yes" ]]
}

# ── Modal deployments ───────────────────────────────────────────────────────

deploy_modal_model() {
    info "Provider is 'modal' — deploying Qwen VLM on Modal..."
    if ! command -v modal &>/dev/null; then
        warn "modal CLI not found in PATH, trying via uv..."
        uv run modal deploy providers/modal/deploy.py
    else
        modal deploy providers/modal/deploy.py
    fi
    ok "Modal VLM deployment complete"
}

deploy_omni_parser() {
    info "OmniParser is ENABLED — deploying OmniParser V2 on Modal..."
    if ! command -v modal &>/dev/null; then
        warn "modal CLI not found in PATH, trying via uv..."
        uv run modal deploy providers/modal/omni_parser/deploy.py
    else
        modal deploy providers/modal/omni_parser/deploy.py
    fi
    ok "OmniParser V2 deployment complete"
}

# Deploy Modal model if provider is modal
if [ "$PROVIDER" = "modal" ]; then
    deploy_modal_model
fi

# Deploy OmniParser if enabled (works with ANY provider)
if omni_enabled; then
    deploy_omni_parser
else
    info "OmniParser: disabled (set USE_OMNI_PARSER=1 to enable)"
fi

# ── Build uvicorn args ──────────────────────────────────────────────────────

# --reload is only enabled in dev mode (EMU_DEV=1) to prevent auto-executing
# any file write on production user machines. 0.0.0.0 would expose the
# shell-exec-capable backend to the entire LAN — always bind to loopback.
_RELOAD_FLAG=""
if [ "${EMU_DEV:-0}" = "1" ]; then
    _RELOAD_FLAG="--reload"
    warn "DEV MODE: --reload enabled (file changes will restart the server)"
fi
UVICORN_ARGS="main:app ${_RELOAD_FLAG} --host 127.0.0.1 --port 8000"

# ── Memory daemon config ────────────────────────────────────────────────────
# The daemon runs OUT-OF-PROCESS via macOS launchd so it keeps ticking even
# when this backend is shut down. Export the detected provider so
# daemon/llm_client.py picks it up when launchd fires run.sh.

export EMU_DAEMON_PROVIDER="${EMU_DAEMON_PROVIDER:-$PROVIDER}"

# ── Memory daemon install prompt (macOS only, first run) ────────────────────
# Skips silently if:
#   - not macOS
#   - stdin isn't a TTY (CI / nohup)
#   - plist already installed
#   - user previously answered "never"

if [[ "$(uname)" == "Darwin" ]]; then
    # Stdlib only — no need to spin up the backend venv.
    # EMU_DAEMON_AUTO_INSTALL=1 (default) installs/repairs the launchd agent
    # non-interactively. Set to 0 to fall back to the interactive y/N/never
    # prompt (useful if you want the user to opt in explicitly).
    if [[ "${EMU_DAEMON_AUTO_INSTALL:-1}" == "1" ]]; then
        info "Installing/refreshing memory daemon (EMU_DAEMON_AUTO_INSTALL=1)..."
        (cd "$SCRIPT_DIR" && python3 -m daemon.install_macos install) || \
            warn "Memory daemon install failed (continuing without it)"
    else
        (cd "$SCRIPT_DIR" && python3 -m daemon.install_macos prompt-install) || true
    fi
fi

# ── Start the backend ───────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Emu Backend Starting${NC}"
echo -e "  Provider:    ${CYAN}${PROVIDER}${NC}"
echo -e "  OmniParser:  ${CYAN}$(omni_enabled && echo 'enabled' || echo 'disabled')${NC}"
echo -e "  URL:         ${CYAN}http://127.0.0.1:8000${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

exec uv run uvicorn $UVICORN_ARGS
