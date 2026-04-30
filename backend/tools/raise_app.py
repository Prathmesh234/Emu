"""
tools/raise_app.py

`raise_app` — backend function tool that brings a named macOS application
to the foreground. Mode-aware (PLAN §5.1):

  * remote / default: existing osascript ``activate`` path. Returns a
    plain status string. Foreground-stealing — fine for remote mode.
  * coworker:        forwards to the emu-cua-driver ``launch_app`` MCP
    tool via ``call_driver_tool``. Hidden background launch — NEVER
    raises a window or steals focus. Returns the raw driver JSON
    (``{pid, bundle_id, name, windows: […]}``) so the model can
    immediately address windows by ``window_id`` per the perception
    contract in ``backend/prompts/coworker_system_prompt.py``.

This is a function tool (called via the API's tool-calling channel),
NOT a desktop action JSON.
"""

from __future__ import annotations

import json
import platform
import subprocess

from .coworker_tools import call_driver_tool


_TIMEOUT_S = 5
_MAX_NAME_LEN = 200


def _validate_name(name: str) -> str | None:
    """Return an ERROR string if invalid, else None."""
    if not name:
        return "ERROR: raise_app requires a non-empty 'app_name'."
    if len(name) > _MAX_NAME_LEN:
        return f"ERROR: raise_app 'app_name' exceeds {_MAX_NAME_LEN} chars."
    if '"' in name or "\\" in name:
        return "ERROR: raise_app 'app_name' must not contain quotes or backslashes."
    return None


def _raise_via_osascript(name: str) -> str:
    """Remote-mode path — unchanged from the original implementation."""
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
        return f"{name} is raised - continue"

    err = (proc.stderr or "").strip() or "(no stderr)"
    return (
        f"ERROR: could not raise '{name}'. osascript exit={proc.returncode}: {err}\n"
        f"Hint: verify the exact app name (e.g. 'Google Chrome', 'Visual Studio Code'). "
        f"If the app is not running, activate will normally launch it; persistent "
        f"failure usually means the name is wrong."
    )


def _raise_via_driver(name: str) -> str:
    """
    Coworker-mode path — hidden background launch via the driver's
    ``launch_app`` MCP tool. Returns the driver's structured JSON on
    success so ``_maybe_update_coworker_target`` can parse ``pid`` and
    ``windows[0].window_id`` for the next perception turn.
    """
    result = call_driver_tool("launch_app", {"name": name})
    if not result.get("ok"):
        return (
            f"ERROR: coworker raise_app failed to launch '{name}': "
            f"{result.get('error', '(no error message)')}"
        )

    parsed = result.get("json")
    if isinstance(parsed, dict):
        # Return the canonical JSON the model can parse for pid/window_id.
        return json.dumps(parsed, ensure_ascii=False)

    # Fallback: driver returned non-JSON output (shouldn't happen for launch_app).
    return result.get("output") or f"{name} launched (no structured output)"


def handle_raise_app(app_name: str, agent_mode: str = "remote") -> str:
    """Activate or hidden-launch a macOS application by name.

    Behaviour depends on ``agent_mode`` (PLAN §5.1):

      * ``"remote"`` — ``osascript activate`` (foreground-stealing).
      * ``"coworker"`` — ``emu-cua-driver call launch_app`` (no foreground
        change; returns ``{pid, bundle_id, name, windows: […]}`` JSON).
    """
    name = (app_name or "").strip()
    err = _validate_name(name)
    if err:
        return err

    if agent_mode == "coworker":
        return _raise_via_driver(name)
    return _raise_via_osascript(name)
