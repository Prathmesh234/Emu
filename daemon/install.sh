#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install.sh — Install/refresh the Emu Memory Daemon launchd agent on macOS.
#
# Idempotent. Safe to call from backend.sh on every boot, or by hand:
#   ./daemon/install.sh                # install/repair (default)
#   ./daemon/install.sh prompt         # interactive y/N/never prompt
#   ./daemon/install.sh uninstall      # remove the launchd agent
#   ./daemon/install.sh status         # show install status
#
# Honors EMU_DAEMON_AUTO_INSTALL=0 to skip non-interactive install.
# Skips silently on non-macOS hosts.
# ──────────────────────────────────────────────────────────────────────────────

set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-install}"

# Only meaningful on macOS — silently no-op elsewhere so cross-platform
# callers (CI / Linux dev) don't have to special-case.
if [[ "$(uname)" != "Darwin" ]]; then
    exit 0
fi

# Source daemon/.env so EMU_DAEMON_PROVIDER and friends are visible to
# install_macos.py when it stamps the plist template.
for env_file in "$REPO_DIR/daemon/.env" "$REPO_DIR/backend/.env"; do
    if [ -f "$env_file" ]; then
        set -a
        # shellcheck disable=SC1091
        source "$env_file"
        set +a
    fi
done

case "$ACTION" in
    install)
        if [[ "${EMU_DAEMON_AUTO_INSTALL:-1}" != "1" ]]; then
            # Fall back to interactive prompt path.
            exec "$0" prompt
        fi
        echo "[daemon/install.sh] installing/refreshing memory daemon..."
        cd "$REPO_DIR" && exec python3 -m daemon.install_macos install
        ;;
    prompt)
        cd "$REPO_DIR" && exec python3 -m daemon.install_macos prompt-install
        ;;
    uninstall|status|run-now)
        cd "$REPO_DIR" && exec python3 -m daemon.install_macos "$ACTION"
        ;;
    *)
        echo "usage: $0 {install|prompt|uninstall|status|run-now}" >&2
        exit 2
        ;;
esac
