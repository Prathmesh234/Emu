"""Input bar widget — text entry at the bottom of the screen.

Features:
  - Single-line by default, expands for multiline (Alt+Enter)
  - Slash-command detection (/plan, /compact, /history, /quit, /verbose)
  - Emits a Submitted message when the user presses Enter
"""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Input


class InputBar(Input):
    """User text input with slash-command support."""

    PLACEHOLDER = "Type your task..."

    class Submitted(Message):
        """Fired when the user presses Enter."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(placeholder=self.PLACEHOLDER)

    async def action_submit(self) -> None:
        """Handle Enter key."""
        text = self.value.strip()
        if text:
            self.post_message(self.Submitted(text))
            self.value = ""
