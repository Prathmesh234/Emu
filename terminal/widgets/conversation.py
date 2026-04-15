"""Conversation view — scrollable container for the agent interaction.

Holds a vertical list of:
  - User messages
  - Screenshot cards
  - Reasoning blocks
  - Action cards
  - Plan review cards
  - Done / error messages

Auto-scrolls to bottom on new content.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from terminal.widgets.action_card import ActionCard
from terminal.widgets.plan_card import PlanCard
from terminal.widgets.screenshot_view import ScreenshotView


class ConversationView(VerticalScroll):
    """Scrollable conversation history."""

    def add_user_message(self, text: str) -> None:
        """Append a user message bubble."""
        raise NotImplementedError

    def add_reasoning(self, text: str) -> None:
        """Append a reasoning/thinking block from the agent."""
        raise NotImplementedError

    def add_action(self, action: dict, confidence: float = 0.0) -> None:
        """Append an ActionCard for a desktop action."""
        raise NotImplementedError

    def add_screenshot(self, width: int, height: int) -> None:
        """Append a screenshot indicator (and optional inline preview)."""
        raise NotImplementedError

    def add_plan(self, content: str) -> None:
        """Append a PlanCard for review."""
        raise NotImplementedError

    def add_done(self, message: str) -> None:
        """Append a task-complete message."""
        raise NotImplementedError

    def add_error(self, message: str) -> None:
        """Append an error message."""
        raise NotImplementedError

    def add_status(self, message: str) -> None:
        """Append an ephemeral status line."""
        raise NotImplementedError
