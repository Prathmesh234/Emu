"""Desktop action executor — pure Python replacement for Electron IPC.

Translates backend Action payloads into real mouse/keyboard/shell operations
using pyautogui (cross-platform) and subprocess.

Coordinates arrive normalized in [0, 1] and are denormalized to absolute
screen pixels before execution.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionResult:
    """Outcome of executing a single desktop action."""

    ipc_channel: str        # e.g. "mouse:left-click", "keyboard:type"
    success: bool
    error: str | None = None
    output: str | None = None  # stdout for shell_exec


# Maps backend ActionType values to the IPC channel names the backend expects
# in POST /action/complete.  Must stay in sync with backend/main.py.
ACTION_CHANNEL_MAP: dict[str, str] = {
    "screenshot":   "screenshot:capture",
    "left_click":   "mouse:left-click",
    "right_click":  "mouse:right-click",
    "double_click": "mouse:double-click",
    "triple_click": "mouse:triple-click",
    "mouse_move":   "mouse:move",
    "drag":         "mouse:drag",
    "scroll":       "mouse:scroll",
    "type_text":    "keyboard:type",
    "key_press":    "keyboard:key-press",
    "shell_exec":   "shell:exec",
    "wait":         "wait",
    "done":         "done",
}


class ActionExecutor:
    """Execute desktop actions by dispatching to pyautogui / subprocess."""

    def __init__(self) -> None:
        self._screen_width: int = 0
        self._screen_height: int = 0

    def execute(self, action: dict) -> ActionResult:
        """Execute a single action payload from the backend.

        Parameters
        ----------
        action : dict
            Action payload as returned by the backend ``step`` WebSocket
            message.  Must contain at least ``{"type": "<action_type>", ...}``.

        Returns
        -------
        ActionResult
            Success/failure with optional stdout (for shell_exec).
        """
        raise NotImplementedError

    # ── Coordinate helpers ───────────────────────────────────────────────────

    def _denormalize(self, x: float, y: float) -> tuple[int, int]:
        """Convert normalized [0,1] coordinates to absolute screen pixels."""
        raise NotImplementedError

    def _refresh_screen_size(self) -> None:
        """Update cached screen dimensions from pyautogui."""
        raise NotImplementedError

    # ── Per-action handlers ──────────────────────────────────────────────────

    def _handle_left_click(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_right_click(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_double_click(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_triple_click(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_mouse_move(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_drag(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_scroll(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_type_text(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_key_press(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_shell_exec(self, action: dict) -> ActionResult:
        raise NotImplementedError

    def _handle_wait(self, action: dict) -> ActionResult:
        raise NotImplementedError
