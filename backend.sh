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
    local explicit="${EMU_PROVIDER:-}"
    explicit="$(echo "$explicit" | tr '[:upper:]' '[:lower:]' | xargs)"

    if [ -n "$explicit" ]; then
        echo "$explicit"
        return
    fi

    if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
        echo "claude"
    elif [ -n "${OPENROUTER_API_KEY:-}" ]; then
        echo "openrouter"
    elif [ -n "${OPENAI_BASE_URL:-}" ] && [ -n "${OPENAI_API_KEY:-}" ]; then
        echo "openai_compatible"
    elif [ -n "${OPENAI_API_KEY:-}" ]; then
        echo "openai"
    elif [ -n "${GOOGLE_API_KEY:-}" ]; then
        echo "gemini"
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

UVICORN_ARGS="main:app --reload --host 0.0.0.0 --port 8000"

if omni_enabled; then
    UVICORN_ARGS="$UVICORN_ARGS --use-omni-parser"
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
