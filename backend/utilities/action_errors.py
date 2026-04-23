"""Action error helpers — translate raw OS / IPC errors into model-friendly guidance."""

_IPC_TO_ACTION = {
    "mouse:left-click":                "left_click",
    "mouse:right-click":               "right_click",
    "mouse:double-click":              "double_click",
    "mouse:triple-click":              "triple_click",
    "mouse:navigate-and-click":        "navigate_and_click",
    "mouse:navigate-and-right-click":  "navigate_and_right_click",
    "mouse:navigate-and-triple-click": "navigate_and_triple_click",
    "mouse:move":                      "mouse_move",
    "mouse:relative-move":             "relative_mouse_move",
    "mouse:drag":                      "drag",
    "mouse:relative-drag":             "relative_drag",
    "mouse:scroll":                    "scroll",
    "mouse:horizontal-scroll":         "horizontal_scroll",
    "mouse:get-position":              "get_mouse_position",
    "keyboard:type":                   "type_text",
    "keyboard:key-press":              "key_press",
}


def ipc_to_action_label(ipc_channel: str) -> str:
    return _IPC_TO_ACTION.get(ipc_channel, ipc_channel)


def interpret_action_error(error: str, action_label: str) -> str:
    """Convert raw OS/IPC errors into actionable guidance for the model."""
    el = error.lower()

    if any(kw in el for kw in ("access is denied", "permission", "privileged",
                                "sudo", "administrator", "elevated", "requires elevation")):
        return (
            f"[ACTION FAILED: {action_label}] Permission denied — {error}\n"
            f"This action requires elevated privileges. Your options:\n"
            f"  1. Inform the user they need to run Emu with appropriate permissions.\n"
            f"  2. Use shell_exec with sudo to request elevation:\n"
            f"     sudo open -a 'AppName'\n"
            f"  3. Choose an approach that doesn't require admin rights."
        )

    if any(kw in el for kw in ("not found", "no such file", "cannot find",
                                "does not exist", "path not found")):
        return (
            f"[ACTION FAILED: {action_label}] Target not found — {error}\n"
            f"The file, app, or element doesn't exist at the expected location.\n"
            f"Try: use shell_exec to verify the path exists, or search for the "
            f"correct location with ls / which / find."
        )

    if "timed out" in el:
        return (
            f"[ACTION FAILED: {action_label}] Timed out after 30s — the app may be "
            f"unresponsive.\n"
            f"Take a screenshot to assess the current state. If the app is frozen, "
            f"use shell_exec to kill and relaunch it: killall 'appname'"
        )

    if any(kw in el for kw in ("zsh", "bash", "shell", "process exited", "ps exited")):
        return (
            f"[ACTION FAILED: {action_label}] Shell process error — {error}\n"
            f"The automation shell encountered an error. Take a screenshot to "
            f"re-orient, then try a simpler action or use shell_exec directly."
        )

    # Generic failure
    return (
        f"[ACTION FAILED: {action_label}] {error}\n"
        f"This action failed at the OS level. Take a screenshot to assess the "
        f"current state, then try a different approach."
    )
