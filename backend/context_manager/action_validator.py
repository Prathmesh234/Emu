"""
context_manager/action_validator.py

Runtime action validation — catches invalid/looping actions before they reach
the frontend.  Fully decoupled from ContextManager; just takes a session_id
and an action dict, returns (is_valid, error_message).
"""


class ActionValidator:
    """
    Stateful per-session validator.  Tracks recent action history and
    rejects patterns that indicate the model is stuck in a loop.

    Rules:
      1. No consecutive mouse_moves without an interaction in between.
      2. Micro-movement: trying to move to the same coordinates (±0.01)
         the cursor was last sent to — signals the cursor didn't move.
      3. Same action type 5+ consecutive times (more than 4×) → force
         strategy change. Excludes screenshot and scroll.
      4. Scroll amount must be >= 5.
      5. Unknown/plain-text action → reject with explicit JSON format hint.
      6. Absolute coordinate detection: x or y > 1.5 → model forgot to
         normalize (raw pixels instead of [0,1] ratios).
    """

    # Positions within this fraction of screen size are treated as "same spot"
    COORD_EPSILON = 0.01

    # Actions that are legitimately repeated many times — don't throttle
    _NO_THROTTLE = {"screenshot", "scroll"}

    def __init__(self):
        self._history: dict[str, list[str]] = {}
        # Last mouse_move target per session (updated only on valid moves)
        self._last_move_coords: dict[str, tuple[float, float]] = {}

    def validate(
        self,
        session_id: str,
        action: dict,
        screen_changed: bool = True,
    ) -> tuple[bool, str]:
        """
        Validate an action against runtime rules.
        Returns (True, "") if valid, (False, error_message) if invalid.
        """
        history = self._history.setdefault(session_id, [])
        action_type = action.get("type", "")

        # Extract coordinates if present
        coords = action.get("coordinates") or {}
        cx = coords.get("x", 0) if isinstance(coords, dict) else 0
        cy = coords.get("y", 0) if isinstance(coords, dict) else 0

        # ── Rule 6: Absolute coordinate detection ────────────────────────────
        # Normalized [0,1] coords should never meaningfully exceed 1.0.
        # x/y > 1.5 almost certainly means the model sent raw pixel values.
        if action_type == "mouse_move" and (cx > 1.5 or cy > 1.5):
            return False, (
                f"Coordinates ({cx:.1f}, {cy:.1f}) look like absolute pixels, not "
                f"normalized [0,1] ratios. Convert them: "
                f"x_norm = x_pixels / screen_width, "
                f"y_norm = y_pixels / screen_height. "
                f"Example: pixel 960 on a 1920-wide screen → 0.5."
            )


        # ── Rule 2: Micro-movement — same coordinates as last move ────────────
        # Fires when the model tries to move the cursor to essentially the
        # same pixel it was already sent to, which is a no-op.
        if action_type == "mouse_move":
            prev = self._last_move_coords.get(session_id)
            if prev:
                lx, ly = prev
                if abs(cx - lx) < self.COORD_EPSILON and abs(cy - ly) < self.COORD_EPSILON:
                    return False, (
                        f"Cursor is already at ({lx:.3f}, {ly:.3f}) — "
                        f"moving there again is a no-op. Just click, or "
                        f"move to a different target."
                    )

        # ── Rule 3: Same action type 5+ consecutive times ─────────────────────
        # "More than 4×" in a row signals the model is stuck on one approach.
        # We check the last 4 history entries: if all 4 match the current
        # action_type, this would be the 5th consecutive identical action.
        if action_type not in self._NO_THROTTLE and len(history) >= 4:
            if all(h == action_type for h in history[-4:]):
                return False, (
                    f"You've performed '{action_type}' 5 times in a row. "
                    f"This approach is not working — switch strategy entirely:\n"
                    f"  • Keyboard: Cmd+Space (Spotlight), Cmd+Tab, Tab/Enter, keyboard shortcuts\n"
                    f"  • Shell: shell_exec with open -a, open, or "
                    f"a shell one-liner\n"
                    f"  • Different element: look for another button, link, or menu"
                )

        # ── Rule 4: Minimum scroll amount ─────────────────────────────────────
        if action_type == "scroll":
            amount = action.get("amount", 0)
            if amount and amount < 5:
                return False, "Minimum scroll amount is 5. Use amount >= 5."

        # ── Rule 5: Reject unknown / plain-text actions ───────────────────────
        if action_type == "unknown":
            return False, (
                "Your response was not a valid JSON action. "
                "Respond with ONLY a raw JSON object — no prose, no markdown fences:\n"
                '  {"action": {"type": "left_click"}, "done": false, "confidence": 0.9}\n'
                "Valid types: mouse_move, left_click, right_click, double_click, "
                "triple_click, type_text, key_press, scroll, drag, shell_exec, "
                "screenshot, wait, done."
            )

        # ── Record action ─────────────────────────────────────────────────────
        if action_type == "mouse_move":
            self._last_move_coords[session_id] = (cx, cy)

        history.append(action_type)
        if len(history) > 10:
            history[:] = history[-10:]

        return True, ""

    def clear(self, session_id: str):
        """Reset all state for a session."""
        self._history.pop(session_id, None)
        self._last_move_coords.pop(session_id, None)
