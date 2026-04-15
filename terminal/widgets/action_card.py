"""Action card widget — renders a single agent action in the conversation.

Displays the action type, coordinates/text/key, and confidence.
Visual style varies by action category:
  - Mouse actions (click, drag, scroll) → green border
  - Keyboard actions (type_text, key_press) → yellow border
  - Shell commands → red border
  - Done → blue border
"""

from __future__ import annotations

from textual.widgets import Static


# Action type → human-readable label
ACTION_LABELS: dict[str, str] = {
    "screenshot":   "Screenshot",
    "left_click":   "Left Click",
    "right_click":  "Right Click",
    "double_click": "Double Click",
    "triple_click": "Triple Click",
    "mouse_move":   "Mouse Move",
    "drag":         "Drag",
    "scroll":       "Scroll",
    "type_text":    "Type Text",
    "key_press":    "Key Press",
    "shell_exec":   "Shell Command",
    "wait":         "Wait",
    "done":         "Done",
}

# Action type → CSS class for border coloring
ACTION_STYLE_CLASS: dict[str, str] = {
    "left_click":   "click",
    "right_click":  "click",
    "double_click": "click",
    "triple_click": "click",
    "mouse_move":   "click",
    "drag":         "click",
    "scroll":       "click",
    "type_text":    "type",
    "key_press":    "type",
    "shell_exec":   "shell",
    "done":         "done",
}


class ActionCard(Static):
    """Renders a single desktop action as a styled card."""

    def __init__(self, action: dict, confidence: float = 0.0) -> None:
        self._action = action
        self._confidence = confidence
        super().__init__(self._render_content())

        style_class = ACTION_STYLE_CLASS.get(action.get("type", ""), "")
        if style_class:
            self.add_class(style_class)

    def _render_content(self) -> str:
        """Build the text content for this action card."""
        action_type = self._action.get("type", "unknown")
        label = ACTION_LABELS.get(action_type, action_type)
        lines = [f"Action: {label}"]

        coords = self._action.get("coordinates")
        if coords:
            lines.append(f"  at ({coords['x']:.3f}, {coords['y']:.3f})")

        end_coords = self._action.get("end_coordinates")
        if end_coords:
            lines.append(f"  to ({end_coords['x']:.3f}, {end_coords['y']:.3f})")

        text = self._action.get("text")
        if text:
            preview = text[:80] + ("..." if len(text) > 80 else "")
            lines.append(f'  text: "{preview}"')

        key = self._action.get("key")
        if key:
            mods = self._action.get("modifiers", [])
            combo = "+".join(mods + [key]) if mods else key
            lines.append(f"  key: {combo}")

        command = self._action.get("command")
        if command:
            preview = command[:100] + ("..." if len(command) > 100 else "")
            lines.append(f"  $ {preview}")

        direction = self._action.get("direction")
        if direction:
            amount = self._action.get("amount", 3)
            lines.append(f"  {direction} x{amount}")

        ms = self._action.get("ms")
        if ms is not None and action_type == "wait":
            lines.append(f"  {ms}ms")

        lines.append(f"  confidence: {self._confidence:.0%}")

        return "\n".join(lines)
