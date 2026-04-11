"""Action error helpers — translate raw OS / IPC errors into model-friendly guidance."""

_IPC_TO_ACTION = {
    "mouse:left-click":   "left_click",
    "mouse:right-click":  "right_click",
    "mouse:double-click": "double_click",
    "mouse:triple-click": "triple_click",
    "mouse:move":         "mouse_move",
    "mouse:drag":         "drag",
    "mouse:scroll":       "scroll",
    "keyboard:type":      "type_text",
    "keyboard:key-press": "key_press",
}


def ipc_to_action_label(ipc_channel: str) -> str:
    return _IPC_TO_ACTION.get(ipc_channel, ipc_channel)


def interpret_action_error(error: str, action_label: str) -> str:
    """Convert raw OS/IPC errors into actionable guidance for the model."""
    el = error.lower()

    if any(kw in el for kw in ("permission denied", "operation not permitted",
                                "accessibility", "axerror", "not trusted",
                                "requires permission", "privacy", "sudo")):
        return (
            f"[ACTION FAILED: {action_label}] Permission denied — {error}\n"
            f"This action requires elevated or accessibility permissions. Your options:\n"
            f"  1. Inform the user they need to grant Accessibility access to Emu in:\n"
            f"     System Settings → Privacy & Security → Accessibility.\n"
            f"  2. For filesystem operations use shell_exec with sudo if needed:\n"
            f"     sudo <command>\n"
            f"  3. Choose an approach that doesn't require elevated privileges."
        )

    if any(kw in el for kw in ("not found", "no such file", "cannot find",
                                "does not exist", "path not found",
                                "command not found")):
        return (
            f"[ACTION FAILED: {action_label}] Target not found — {error}\n"
            f"The file, app, or element doesn't exist at the expected location.\n"
            f"Try: use shell_exec to verify the path exists, or search for the "
            f"correct location with ls / find / which."
        )

    if "timed out" in el:
        return (
            f"[ACTION FAILED: {action_label}] Timed out after 30s — the app may be "
            f"unresponsive.\n"
            f"Take a screenshot to assess the current state. If the app is frozen, "
            f"use shell_exec to kill and relaunch it: killall 'AppName'"
        )

    if any(kw in el for kw in ("shell", "process exited", "bash", "zsh", "spawn")):
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
