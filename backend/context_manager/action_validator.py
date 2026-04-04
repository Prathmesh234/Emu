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
      2. Micro-movement detection (cursor already at target).
      3. Same action 3× with no screen change → force strategy change.
      4. Scroll amount must be >= 5.
    """

    def __init__(self):
        self._history: dict[str, list[str]] = {}
        self._last_coords: dict[str, tuple[float, float]] = {}

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

        # Rule 1: No consecutive mouse_moves without interaction
        if action_type == "mouse_move" and history and history[-1] == "mouse_move":
            return False, (
                "Cannot move twice without interacting. "
                "The cursor is already positioned — click, type, or scroll."
            )

        # Rule 2: Micro-movement detection
        if action_type == "mouse_move":
            coords = action.get("coordinates", {})
            x, y = coords.get("x", 0), coords.get("y", 0)
            prev = self._last_coords.get(session_id)
            if prev and history and history[-1] == "mouse_move":
                lx, ly = prev
                if abs(x - lx) < 0.01 and abs(y - ly) < 0.01:
                    return False, (
                        "Cursor is already at this position (within 0.01). Just click."
                    )
            self._last_coords[session_id] = (x, y)

        # Rule 3: Same action repeated 3+ times with no screen change
        if (
            len(history) >= 2
            and all(h == action_type for h in history[-2:])
            and not screen_changed
        ):
            return False, (
                f"You've performed '{action_type}' 3 times with no visible change. "
                f"This approach isn't working. Try a completely different strategy: "
                f"keyboard shortcut, shell_exec, or a different element."
            )

        # Rule 4: Minimum scroll amount
        if action_type == "scroll":
            amount = action.get("amount", 0)
            if amount and amount < 5:
                return False, "Minimum scroll amount is 5. Use amount >= 5."

        # Rule 5: Reject unknown/plain text actions
        if action_type == "unknown":
            return False, "Unknown tool call or invalid JSON format. Please choose from the tools available to you."

        # Record and trim history
        history.append(action_type)
        if len(history) > 10:
            history[:] = history[-10:]

        return True, ""

    def clear(self, session_id: str):
        """Reset history for a session."""
        self._history.pop(session_id, None)
        self._last_coords.pop(session_id, None)
