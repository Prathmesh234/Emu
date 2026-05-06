"""
context_manager/coworker_validator.py

Runtime validation for coworker-mode function-tool calls and completion
verification. Remote desktop action validation lives in remote_validator.py.
"""


class CoworkerActionValidator:
    """Stateful per-session validator for coworker tool calls/results."""

    _COWORKER_INTERACTIVE_TOOLS = {
        "cua_click",
        "cua_right_click",
        "cua_double_click",
        "cua_press_key",
        "cua_hotkey",
        "cua_type_text",
        "cua_type_text_chars",
        "cua_set_value",
        "cua_scroll",
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

    # Click tools that get hard-blocked after repeated identical failures.
    _CLICK_TOOLS = {"cua_click", "cua_right_click", "cua_double_click"}
    MAX_CONSECUTIVE_CLICK_FAILURES = 3

    def __init__(self):
        self._coworker_pending_verification: dict[str, str] = {}
        # (tool_key, fail_count) tracks consecutive click failures per session.
        self._click_failures: dict[str, tuple[str, int]] = {}
        # (rejection_key, count) tracks repeated pre-dispatch validation loops.
        self._tool_rejections: dict[str, tuple[str, int]] = {}

    def clear(self, session_id: str) -> None:
        """Reset all state for a session."""
        self._coworker_pending_verification.pop(session_id, None)
        self._click_failures.pop(session_id, None)
        self._tool_rejections.pop(session_id, None)

    def _remember_rejection(self, session_id: str, key: str, message: str) -> tuple[bool, str]:
        current_key, count = self._tool_rejections.get(session_id, ("", 0))
        next_count = count + 1 if current_key == key else 1
        self._tool_rejections[session_id] = (key, next_count)
        if next_count >= 3:
            return False, (
                f"{message} This exact invalid tool call has been rejected "
                f"{next_count} times in a row. Stop retrying it: take a fresh "
                "`cua_get_window_state`/`cua_screenshot`, choose one addressing "
                "mode, or report the blocker."
            )
        return False, message

    def _click_key(self, name: str, args: dict | None) -> str:
        """Return the executable click target, ignoring ignored provider defaults."""
        args = args or {}
        window_id = args.get("window_id")
        element_index = args.get("element_index")
        if element_index is not None and window_id is not None:
            return f"{name}:element:{window_id}:{element_index}"

        x = args.get("x")
        y = args.get("y")
        if x is not None and y is not None:
            try:
                x = round(float(x), 1)
                y = round(float(y), 1)
            except (TypeError, ValueError):
                pass
            return f"{name}:pixel:{window_id}:{x}:{y}"

        return f"{name}:invalid"

    def _validate_click_target(self, name: str, args: dict | None) -> tuple[bool, str]:
        """Reject ambiguous click targeting before it can execute the wrong path."""
        args = args or {}
        has_element_target = (
            args.get("element_index") is not None
            and args.get("window_id") is not None
        )
        has_xy = args.get("x") is not None and args.get("y") is not None
        if not has_element_target or not has_xy:
            return True, ""

        try:
            is_zero_default = float(args.get("x")) == 0 and float(args.get("y")) == 0
        except (TypeError, ValueError):
            is_zero_default = False
        if is_zero_default:
            return True, ""

        try:
            is_element_zero = int(args.get("element_index")) == 0
        except (TypeError, ValueError):
            is_element_zero = False
        if is_element_zero:
            return True, ""

        return False, (
            f"`{name}` has an invalid mixed target: provide either "
            "`element_index` + `window_id` OR pixel `x` + `y`, not both. "
            "For a pixel click, omit `element_index` and `action`; for an AX "
            "click, omit `x`, `y`, `modifier`, `count`, and `from_zoom`."
        )

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

        if agent_mode == "coworker" and name in self._CLICK_TOOLS:
            target_ok, target_err = self._validate_click_target(name, args)
            if not target_ok:
                key = self._click_key(name, args)
                return self._remember_rejection(session_id, f"reject:{key}", target_err)

            key = self._click_key(name, args)
            current_key, count = self._click_failures.get(session_id, ("", 0))
            if current_key == key and count >= self.MAX_CONSECUTIVE_CLICK_FAILURES:
                return False, (
                    f"`{name}` has failed {count} times in a row on the same target "
                    f"(element_index={(args or {}).get('element_index')}, "
                    f"x={(args or {}).get('x')}, y={(args or {}).get('y')}). "
                    f"Do NOT retry this click. Change strategy: pick a different "
                    f"element from the AX tree, use a keyboard shortcut, or call "
                    f"`cua_get_window_state` to reassess the UI."
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
                self._tool_rejections.pop(session_id, None)
            return

        if name not in self._COWORKER_INTERACTIVE_TOOLS:
            return

        if name in self._CLICK_TOOLS:
            key = self._click_key(name, args)
            current_key, count = self._click_failures.get(session_id, ("", 0))
            if not ok:
                self._click_failures[session_id] = (key, count + 1 if current_key == key else 1)
            else:
                self._click_failures[session_id] = ("", 0)
                self._tool_rejections.pop(session_id, None)

        if ok:
            self._coworker_pending_verification[session_id] = name

    def validate_done_response(self, session_id: str, final_message: str | None) -> tuple[bool, str]:
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
