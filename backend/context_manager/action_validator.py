"""
context_manager/action_validator.py

Runtime action validation — catches invalid/looping actions before they reach
the frontend.  Fully decoupled from ContextManager; just takes a session_id
and an action dict, returns (is_valid, error_message).
"""

import re

# Desktop action types that should NEVER appear in a "done" final_message.
# If they do, it means the parser failed to extract the real action from
# truncated / malformed model output.
_DESKTOP_ACTION_TYPES = {
    "left_click", "right_click", "double_click", "triple_click",
    "navigate_and_click", "navigate_and_right_click",
    "navigate_and_triple_click",
    "mouse_move", "drag", "scroll", "type_text", "key_press",
    "screenshot", "wait",
}
_ACTION_PATTERN = re.compile(
    r'(?:^|["\s:,])(' + "|".join(re.escape(a) for a in _DESKTOP_ACTION_TYPES) + r')(?:["\s:,}]|$)'
)

# Actions that require coordinates
_COORD_ACTIONS = {"mouse_move", "drag", "navigate_and_click", "navigate_and_right_click", "navigate_and_triple_click"}
# Click actions (used in Rule 6 for absolute coordinate detection)
_CLICK_ACTIONS = {"left_click", "right_click", "double_click", "triple_click"}

# Max wait duration (30 seconds)
MAX_WAIT_MS = 30_000


class ActionValidator:
    """
    Stateful per-session validator.  Tracks recent action history and
    rejects patterns that indicate the model is stuck in a loop.

    Rules:
      1. Consecutive mouse_moves without an interaction → reject.
      2. Micro-movement: trying to move to the same coordinates (±0.01)
         the cursor was last sent to — signals the cursor didn't move.
      3. Same action type 5+ consecutive times (more than 4×) → force
         strategy change. Excludes screenshot and scroll.
      4. Scroll amount must be >= 5.
      5. Unknown/plain-text action → reject with explicit JSON format hint.
      6. Absolute coordinate detection: x or y > 1.5 → model forgot to
         normalize (raw pixels instead of [0,1] ratios).
      7. Required fields: type_text needs text, key_press needs key,
         scroll needs direction, mouse_move/drag need coordinates,
         drag needs end_coordinates, shell_exec needs command.
      8. Negative / zero-zero coordinates → likely a parsing default.
      9. Wait duration capped at 30s.
     10. Coordinate values must be numbers (reject arrays/strings/nulls).
    """

    # Positions within this fraction of screen size are treated as "same spot"
    COORD_EPSILON = 0.01

    # Actions that are legitimately repeated many times — don't throttle.
    # - screenshot: may be spammed while waiting for UI to settle
    # - scroll: large pages may genuinely need many scrolls
    # - shell_exec: legacy action name kept here for older sessions; it is now
    #   a function tool, not a desktop action.
    # - done: each user request can legitimately end with done, especially in
    #   coworker mode where all real progress happens via function tools.
    _NO_THROTTLE = {"screenshot", "scroll", "shell_exec", "done"}

    # Max consecutive repetitions of the same action type before we force a
    # strategy change. 4 repeats allowed; the 5th is rejected.
    MAX_CONSECUTIVE_REPEATS = 4
    _COWORKER_INTERACTIVE_TOOLS = {
        "cua_click",
        "cua_right_click",
        "cua_double_click",
        "cua_press_key",
        "cua_hotkey",
        "cua_type_text",
        "cua_set_value",
        "cua_drag",
    }

    _COWORKER_PERCEPTION_TOOLS = {
        "cua_get_window_state",
        "cua_screenshot",
        "cua_zoom",
        "cua_list_windows",
        "cua_list_apps",
        "list_running_apps",
        "raise_app",
        "cua_launch_app",
    }

    _BLOCKED_DONE_WORDS = (
        "can't",
        "cannot",
        "couldn't",
        "unable",
        "failed",
        "blocked",
        "limitation",
        "not possible",
        "not safely",
        "need you",
        "please",
    )

    def __init__(self):
        self._history: dict[str, list[str]] = {}
        # Last mouse_move target per session (updated only on valid moves)
        self._last_move_coords: dict[str, tuple[float, float]] = {}
        self._coworker_pending_verification: dict[str, str] = {}

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

        # ── Rule 7: Required fields per action type ──────────────────────────
        if action_type == "type_text":
            text = action.get("text")
            if not text:
                return False, (
                    "type_text requires a non-empty 'text' field. "
                    'Example: {"action": {"type": "type_text", "text": "hello"}, "done": false}'
                )

        if action_type == "key_press":
            key = action.get("key")
            if not key:
                return False, (
                    "key_press requires a 'key' field. "
                    'Example: {"action": {"type": "key_press", "key": "enter"}, "done": false}'
                )

        if action_type == "scroll":
            direction = action.get("direction")
            if direction not in ("up", "down"):
                return False, (
                    "scroll requires a 'direction' field set to 'up' or 'down'. "
                    'Example: {"action": {"type": "scroll", "direction": "down", "amount": 5}, "done": false}'
                )

        if action_type in _COORD_ACTIONS:
            if not coords or not isinstance(coords, dict) or ("x" not in coords or "y" not in coords):
                return False, (
                    f"{action_type} requires 'coordinates' with 'x' and 'y' fields (normalized 0-1). "
                    f'Example: {{"action": {{"type": "{action_type}", "coordinates": {{"x": 0.5, "y": 0.5}}}}, "done": false}}'
                )
            # Rule 10: coordinate values must be scalar numbers
            xv = coords.get("x")
            yv = coords.get("y")
            if not isinstance(xv, (int, float)) or isinstance(xv, bool) \
               or not isinstance(yv, (int, float)) or isinstance(yv, bool):
                return False, (
                    f"'coordinates.x' and 'coordinates.y' must be scalar numbers "
                    f"(got x={xv!r}, y={yv!r}). "
                    f"NEVER pass arrays, strings, or nulls. Use a single normalized value per axis.\n"
                    f'Correct: {{"coordinates": {{"x": 0.5, "y": 0.5}}}}'
                )

        if action_type == "drag":
            end_coords = action.get("end_coordinates") or {}
            if not end_coords or not isinstance(end_coords, dict) or ("x" not in end_coords or "y" not in end_coords):
                return False, (
                    "drag requires 'end_coordinates' with 'x' and 'y' fields. "
                    'Example: {"action": {"type": "drag", "coordinates": {"x": 0.3, "y": 0.3}, '
                    '"end_coordinates": {"x": 0.7, "y": 0.7}}, "done": false}'
                )

        if action_type == "shell_exec":
            return False, (
                "shell_exec is now a FUNCTION TOOL, not a desktop action. "
                "Call it as a tool: "
                '{"name": "shell_exec", "arguments": {"command": "..."}}. '
                "It runs sandboxed inside the .emu directory."
            )

        # ── Rule 8: Negative / zero-zero coordinates ─────────────────────────
        if action_type in _COORD_ACTIONS and coords:
            if cx < 0 or cy < 0:
                return False, (
                    f"Coordinates ({cx}, {cy}) contain negative values. "
                    f"Normalized coordinates must be in [0, 1] range."
                )
            if cx == 0 and cy == 0 and action_type in (
                "mouse_move",
                "navigate_and_click",
                "navigate_and_right_click",
                "navigate_and_triple_click",
            ):
                return False, (
                    "Coordinates (0, 0) is the extreme top-left corner — this is almost "
                    "certainly a default/error. Look at the screenshot and provide real "
                    "target coordinates."
                )

        # ── Rule 6: Absolute coordinate detection ────────────────────────────
        if action_type in (_COORD_ACTIONS | _CLICK_ACTIONS) and coords and (cx > 1.5 or cy > 1.5):
            return False, (
                f"Coordinates ({cx:.1f}, {cy:.1f}) look like absolute pixels, not "
                f"normalized [0,1] ratios. Convert them: "
                f"x_norm = x_pixels / screen_width, "
                f"y_norm = y_pixels / screen_height. "
                f"Example: pixel 960 on a 1920-wide screen → 0.5."
            )


        # ── Rule 2: Micro-movement — same coordinates as last move ────────────
        if action_type == "mouse_move":
            prev = self._last_move_coords.get(session_id)
            if prev:
                lx, ly = prev
                if abs(cx - lx) < self.COORD_EPSILON and abs(cy - ly) < self.COORD_EPSILON:
                    return False, (
                        f"Cursor is already at ({lx:.3f}, {ly:.3f}) — "
                        f"moving there again is a no-op. Pick a different "
                        f"target or use navigate_and_click to click on an element."
                    )

        # ── Rule 11: navigate_and_click at same coordinates as last click ─────
        # Intentionally removed — clicking the same spot twice is legitimate
        # (e.g., cursor placement then selection, waiting for a slow UI,
        # re-trying after a transient failure). The validator was producing
        # false-positive rejection loops.

        # ── Rule 4: Minimum scroll amount ─────────────────────────────────────
        if action_type == "scroll":
            amount = action.get("amount", 0)
            if amount and amount < 5:
                return False, "Minimum scroll amount is 5. Use amount >= 5."

        # ── Rule 9: Wait duration cap ─────────────────────────────────────────
        if action_type == "wait":
            ms = action.get("ms", 1000)
            if ms and ms > MAX_WAIT_MS:
                return False, (
                    f"Wait duration {ms}ms exceeds maximum of {MAX_WAIT_MS}ms (30s). "
                    f"Use a shorter wait or take a screenshot to check if the app is ready."
                )

        # ── Rule 5: Reject unknown / plain-text actions ───────────────────────
        if action_type == "unknown":
            return False, (
                "Your response was not a valid JSON action. "
                "Respond with ONLY a raw JSON object — no prose, no markdown fences.\n\n"
                "For a desktop action:\n"
                '  {"action": {"type": "navigate_and_click", '
                '"coordinates": {"x": 0.5, "y": 0.5}}, "done": false, "confidence": 0.9}\n\n'
                "When you have finished the task and want to reply to the user, "
                "put your answer in final_message:\n"
                '  {"action": {"type": "done"}, "done": true, "confidence": 0.95, '
                '"final_message": "<your full answer to the user goes here>"}\n\n'
                "Valid types: navigate_and_click, navigate_and_right_click, "
                "navigate_and_triple_click, "
                "left_click, right_click, double_click, triple_click, "
                "mouse_move, type_text, key_press, scroll, drag, "
                "screenshot, wait, done."
            )

        # ── Rule 3: Throttle consecutive repeats of same action type ──────────
        # (excludes screenshot, scroll, shell_exec — see _NO_THROTTLE)
        if action_type and action_type not in self._NO_THROTTLE:
            tail = history[-self.MAX_CONSECUTIVE_REPEATS:]
            if (
                len(tail) == self.MAX_CONSECUTIVE_REPEATS
                and all(a == action_type for a in tail)
            ):
                return False, (
                    f"'{action_type}' has been called {self.MAX_CONSECUTIVE_REPEATS} "
                    f"times in a row without progress. Change strategy: take a "
                    f"screenshot to reassess, try a different element, use a "
                    f"keyboard shortcut, or call shell_exec if this is a "
                    f"filesystem/text task."
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
        self._coworker_pending_verification.pop(session_id, None)

    def validate_tool_call(
        self,
        session_id: str,
        name: str,
        args: dict | None,
        agent_mode: str = "remote",
    ) -> tuple[bool, str]:
        """Validate backend function-tool calls before execution."""
        if agent_mode != "coworker" and (
            name == "list_running_apps" or name.startswith("cua_")
        ):
            return False, (
                f"`{name}` is only available in coworker mode. The current "
                "mode is remote, so do not call emu-cua-driver tools. Use "
                "remote desktop action JSON such as screenshot, "
                "navigate_and_click, scroll, type_text, key_press, wait, or "
                "done."
            )
        return True, ""

    def record_tool_result(
        self,
        session_id: str,
        name: str,
        args: dict | None,
        result: str,
        agent_mode: str = "remote",
    ) -> None:
        """Update coworker tool history after a function tool returns."""
        if agent_mode != "coworker":
            return

        ok = result.startswith(f"[{name}]")

        if name in self._COWORKER_PERCEPTION_TOOLS:
            if ok:
                self._coworker_pending_verification.pop(session_id, None)
            return

        if name not in self._COWORKER_INTERACTIVE_TOOLS:
            return

        if ok:
            self._coworker_pending_verification[session_id] = name

    def validate_coworker_done_response(self, session_id: str, final_message: str | None) -> tuple[bool, str]:
        """
        Prevent success-shaped final answers immediately after an unverified
        coworker interaction. Honest blocked/limitation messages are allowed.
        """
        pending = self._coworker_pending_verification.get(session_id)
        if not pending:
            return True, ""

        text = (final_message or "").lower()
        if any(word in text for word in self._BLOCKED_DONE_WORDS):
            return True, ""

        return False, (
            f"The last coworker interaction (`{pending}`) has not been verified "
            "by a successful cua_get_window_state/cua_screenshot/list_windows "
            "call. Do not claim success from a posted click/key alone. Verify "
            "the UI state first; if it did not change, switch strategy or report "
            "the limitation."
        )

    @staticmethod
    def validate_done_response(final_message: str | None) -> tuple[bool, str]:
        """
        Check whether a done response's final_message is actually a
        truncated / malformed desktop action that the JSON parser failed
        to extract.

        Returns (True, "") if the done looks legitimate.
        Returns (False, reason) if it smells like a broken action parse.
        """
        if not final_message:
            return True, ""

        text = final_message.strip()

        # Short fragments that look like JSON keys/values from an action dict
        # e.g. '":"left_click"},"done":false,...'
        if _ACTION_PATTERN.search(text):
            # Extra heuristic: legit final_messages are natural-language
            # summaries. If > 30% of the content is JSON-like punctuation,
            # it's almost certainly a broken parse, not real prose.
            json_chars = sum(1 for c in text if c in '{}[]":,')
            if len(text) > 0 and json_chars / len(text) > 0.25:
                return False, (
                    f"done response appears to contain a truncated desktop action "
                    f"(detected action keyword in final_message). "
                    f"Replacing with screenshot to retry."
                )

        return True, ""
