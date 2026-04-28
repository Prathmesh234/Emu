"""
tools/raise_app.py

`raise_app` — backend function tool that brings a named macOS application
to the foreground via osascript. Used by the agent BEFORE interacting with
any target application so subsequent clicks/keystrokes land on the right
window.

This is a function tool (called via the API's tool-calling channel),
NOT a desktop action JSON.
"""

from __future__ import annotations

import platform
import subprocess


_TIMEOUT_S = 5
_MAX_NAME_LEN = 200


def handle_raise_app(app_name: str) -> str:
    """Activate a macOS application by name. Returns a status string."""
    name = (app_name or "").strip()
    if not name:
        return "ERROR: raise_app requires a non-empty 'app_name'."
    if len(name) > _MAX_NAME_LEN:
        return f"ERROR: raise_app 'app_name' exceeds {_MAX_NAME_LEN} chars."
    # Reject embedded quotes / backslashes that would break the AppleScript literal.
    if '"' in name or "\\" in name:
        return "ERROR: raise_app 'app_name' must not contain quotes or backslashes."

    if platform.system() != "Darwin":
        return f"ERROR: raise_app only works on macOS (detected: {platform.system()})."

    script = f'tell application "{name}" to activate'
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: raise_app timed out after {_TIMEOUT_S}s while raising '{name}'."
    except FileNotFoundError:
        return "ERROR: raise_app could not find 'osascript' (is this macOS?)."
    except Exception as e:
        return f"ERROR: raise_app failed to launch osascript: {e}"

    if proc.returncode == 0:
        return f"Raised: {name}"

    err = (proc.stderr or "").strip() or "(no stderr)"
    return (
        f"ERROR: could not raise '{name}'. osascript exit={proc.returncode}: {err}\n"
        f"Hint: verify the exact app name (e.g. 'Google Chrome', 'Visual Studio Code'). "
        f"If the app is not running, activate will normally launch it; persistent "
        f"failure usually means the name is wrong."
    )
