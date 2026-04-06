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
      2. Micro-movement detection: returning to same move target (within 0.01)
         after already clicking there.
      3. Same action type 3+ times in the last 5 actions → force strategy change.
      4. Scroll amount must be >= 5.
      5. Unknown/plain text action → reject with explicit JSON format hint.
      6. Same click type 3× in a row → force strategy change.
      7. Move+click loop: same coordinates clicked 3+ times → force strategy change.
      8. Absolute coordinate detection: x or y > 1.5 → likely forgot to normalize.
    """

    # Treat positions within this fraction of screen width/height as "same spot"
    COORD_EPSILON = 0.02

    def __init__(self):
        self._history: dict[str, list[str]] = {}
        # Last mouse_move target per session
        self._last_move_coords: dict[str, tuple[float, float]] = {}
        # Ordered list of move-coords recorded at the time of each click
        self._click_coord_history: dict[str, list[tuple[float, float]]] = {}

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

        click_types = {"left_click", "right_click", "double_click", "triple_click"}

        # ── Rule 8: Absolute coordinate detection ────────────────────────────
        # Normalized [0,1] coords can't exceed 1.0 meaningfully.
        # If x or y > 1.5, the model almost certainly sent raw pixel values.
        if action_type == "mouse_move" and (cx > 1.5 or cy > 1.5):
            return False, (
                f"Coordinates ({cx:.1f}, {cy:.1f}) look like absolute pixels, not "
                f"normalized [0,1] ratios. Convert: x_norm = x_px / screen_width, "
                f"y_norm = y_px / screen_height. "
                f"Example: pixel 960 on a 1920-wide screen → 0.5."
            )

        # ── Rule 1: No consecutive mouse_moves without interaction ────────────
        if action_type == "mouse_move" and history and history[-1] == "mouse_move":
            return False, (
                "Cannot move twice without interacting. "
                "The cursor is already positioned — click, type, or scroll."
            )

        # ── Rule 2: Micro-movement — don't return to same spot after clicking ─
        # Fires when the model tries to mouse_move back to the same coordinates
        # it most recently moved to, and the intervening action was a click
        # (i.e., clicking there didn't work, but it wants to click again).
        if action_type == "mouse_move":
            prev = self._last_move_coords.get(session_id)
            last_action = history[-1] if history else None
            if prev and last_action in click_types:
                lx, ly = prev
                if abs(cx - lx) < self.COORD_EPSILON and abs(cy - ly) < self.COORD_EPSILON:
                    return False, (
                        f"You clicked at ({lx:.3f}, {ly:.3f}) but are now moving "
                        f"back to the same spot. Clicking the same position again "
                        f"won't work. Switch strategy: use a keyboard shortcut, "
                        f"scroll to expose the element, or try shell_exec."
                    )
            # Update last known move target (done after validation passes)

        # ── Rule 3: Same action type 3+ times in last 5 actions ──────────────
        # Catches persistent loops regardless of screen_changed flag.
        # Excludes screenshot (the model legitimately takes many screenshots).
        if action_type not in ("screenshot", "unknown") and len(history) >= 4:
            recent = history[-4:]
            same_count = sum(1 for h in recent if h == action_type)
            if same_count >= 3:
                return False, (
                    f"You've used '{action_type}' {same_count + 1}+ times in the "
                    f"last few actions with no visible progress. "
                    f"This approach isn't working. Try a completely different strategy: "
                    f"keyboard shortcut, shell_exec, or a different UI element."
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

        # ── Rule 6: Same click type 3× in a row → force strategy change ──────
        if action_type in click_types and len(history) >= 2:
            if all(h == action_type for h in history[-2:]):
                return False, (
                    f"You've used '{action_type}' 3 times in a row without progress. "
                    f"STOP clicking. Re-read your plan with read_plan, then try a "
                    f"completely different approach: keyboard shortcuts, shell_exec "
                    f"to launch/interact with apps, type_text, or a different element."
                )

        # ── Rule 7: Move+click loop at same coordinates ───────────────────────
        # After each click, record the preceding mouse_move coordinates.
        # If the same spot has been clicked 3+ times → reject.
        if action_type in click_types:
            last_move = self._last_move_coords.get(session_id)
            if last_move:
                click_hist = self._click_coord_history.setdefault(session_id, [])
                click_hist.append(last_move)
                if len(click_hist) > 6:
                    click_hist[:] = click_hist[-6:]

                if len(click_hist) >= 3:
                    lx, ly = click_hist[-3]
                    if all(
                        abs(x - lx) < self.COORD_EPSILON and abs(y - ly) < self.COORD_EPSILON
                        for x, y in click_hist[-2:]
                    ):
                        return False, (
                            f"You've moved to ({lx:.3f}, {ly:.3f}) and clicked there "
                            f"3+ times with no result. Clicking the same element "
                            f"repeatedly will not work. STOP and use a different approach:\n"
                            f"  • Keyboard: Win key to open Start, Tab/Enter to navigate, "
                            f"Alt+Tab to switch apps\n"
                            f"  • Shell: shell_exec with Start-Process, Invoke-Item, or "
                            f"a PowerShell command\n"
                            f"  • Look for a different UI element or interaction method"
                        )

        # ── Record this action and trim history ───────────────────────────────
        if action_type == "mouse_move":
            # Update last-known move target only after all checks pass
            self._last_move_coords[session_id] = (cx, cy)

        history.append(action_type)
        if len(history) > 10:
            history[:] = history[-10:]

        return True, ""

    def clear(self, session_id: str):
        """Reset all state for a session."""
        self._history.pop(session_id, None)
        self._last_move_coords.pop(session_id, None)
        self._click_coord_history.pop(session_id, None)
