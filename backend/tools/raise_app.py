"""
tools/raise_app.py

`raise_app` — backend function tool that brings a named macOS application
to the foreground. Mode-aware (PLAN §5.1):

  * remote / default: existing osascript ``activate`` path.
  * coworker: visible-by-default app work uses the same activation path.
    Use ``cua_launch_app`` instead for explicitly hidden/background launch,
    isolated instances, or URL/file handoff.

This is a function tool (called via the API's tool-calling channel),
NOT a desktop action JSON.
"""

from __future__ import annotations

import platform
import re
import subprocess

_TIMEOUT_S = 5
_MAX_NAME_LEN = 64

# Strict allowlist for macOS application display names. Covers the realistic
# character set ("Google Chrome", "Visual Studio Code", "1Password 7",
# "Adobe Photoshop 2024", "Microsoft 365", "Logic Pro", etc.) while rejecting
# anything that could break out of the AppleScript string we interpolate it
# into (`tell application "<name>" to activate`).
_NAME_RE = re.compile(r"^[A-Za-z0-9 .\-+_/&()'!]+$")

# AppleScript treats every quote variant as a string delimiter; control chars
# (including \n / \r / \t) terminate the current command so newline-separated
# follow-up statements would execute. Reject all of these explicitly even
# before the regex runs, to give a clearer error message.
_FORBIDDEN_CHARS = (
    '"', "\\", "`",
    "\n", "\r", "\t", "\x00", "\x0b", "\x0c",
    "“", "”",  # curly double quotes
    "‘", "’",  # curly single quotes
    "«", "»",  # guillemets
    "ʺ", "ʼ",  # modifier letter quotes
)


def _validate_name(name: str) -> str | None:
    """Return an ERROR string if invalid, else None."""
    if not name:
        return "ERROR: raise_app requires a non-empty 'app_name'."
    if len(name) > _MAX_NAME_LEN:
        return f"ERROR: raise_app 'app_name' exceeds {_MAX_NAME_LEN} chars."
    for ch in _FORBIDDEN_CHARS:
        if ch in name:
            return (
                "ERROR: raise_app 'app_name' contains a forbidden character "
                "(quotes, backslash, backtick, control character, or "
                "non-ASCII quote variant)."
            )
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        return "ERROR: raise_app 'app_name' contains a control character."
    if not _NAME_RE.match(name):
        return (
            "ERROR: raise_app 'app_name' must match "
            "^[A-Za-z0-9 .\\-+_/&()'!]+$ (typical macOS app display names)."
        )
    return None


def _raise_via_osascript(name: str) -> str:
    """Make an app visible/frontmost via macOS application activation."""
    if platform.system() != "Darwin":
        return f"ERROR: raise_app only works on macOS (detected: {platform.system()})."

    candidates = [name]
    for prefix in ("Apple ",):
        if name.startswith(prefix) and len(name) > len(prefix):
            candidates.append(name[len(prefix):])

    last_error = "(no stderr)"
    for cand in candidates:
        script = f'tell application "{cand}" to activate'
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return f"ERROR: raise_app timed out after {_TIMEOUT_S}s while raising '{cand}'."
        except FileNotFoundError:
            return "ERROR: raise_app could not find 'osascript' (is this macOS?)."
        except Exception as e:
            return f"ERROR: raise_app failed to launch osascript: {e}"

        if proc.returncode == 0:
            return f"{cand} is raised - continue"
        last_error = (proc.stderr or "").strip() or "(no stderr)"

    return (
        f"ERROR: could not raise '{name}'. osascript exit={proc.returncode}: {last_error}\n"
        f"Hint: verify the exact app name (e.g. 'Google Chrome', 'Visual Studio Code'). "
        f"If the app is not running, activate will normally launch it; persistent "
        f"failure usually means the name is wrong."
    )


def handle_raise_app(
    app_name: str,
    agent_mode: str = "remote",
    cancel_key: str | None = None,
) -> str:
    """Activate or prepare a macOS application by name.

    Behaviour depends on ``agent_mode`` (PLAN §5.1):

            * ``"remote"`` — ``osascript activate``.
            * ``"coworker"`` — same visible/frontmost activation path.
    """
    name = (app_name or "").strip()
    err = _validate_name(name)
    if err:
        return err

    return _raise_via_osascript(name)


def handle_bring_app_frontmost(app_name: str, user_approved: bool = False) -> str:
    """Make a named app frontmost; coworker app work treats this as approved."""
    name = (app_name or "").strip()
    err = _validate_name(name)
    if err:
        return err.replace("raise_app", "bring_app_frontmost")
    if not user_approved:
        return (
            "ERROR: bring_app_frontmost requires user_approved=true after the "
            "user explicitly agrees to foreground the app."
        )
    return _raise_via_osascript(name)
