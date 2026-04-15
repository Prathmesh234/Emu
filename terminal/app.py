"""Main Textual application — the TUI shell.

Layout:
  ┌──────────────────────────────────────────────┐
  │  StatusBar (model, chain length, confidence) │
  ├──────────────────────────────────────────────┤
  │                                              │
  │  ConversationView (scrollable)               │
  │    - Screenshot cards                        │
  │    - Reasoning text                          │
  │    - Action cards                            │
  │    - Plan review modals                      │
  │    - Done / error messages                   │
  │                                              │
  ├──────────────────────────────────────────────┤
  │  InputBar (user text input)                  │
  └──────────────────────────────────────────────┘

Keybindings:
  Enter       — send message
  Ctrl+C      — stop current generation / quit
  Ctrl+D      — quit
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer

from terminal.config import TerminalConfig
from terminal.widgets.status_bar import StatusBar
from terminal.widgets.conversation import ConversationView
from terminal.widgets.input_bar import InputBar


class EmuTerminalApp(App):
    """Emu computer-use agent — terminal interface."""

    TITLE = "Emu Terminal"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        ("ctrl+c", "stop_or_quit", "Stop / Quit"),
        ("ctrl+d", "quit", "Quit"),
    ]

    def __init__(self, config: TerminalConfig) -> None:
        super().__init__()
        self._cfg = config

    def compose(self) -> ComposeResult:
        yield StatusBar()
        yield ConversationView()
        yield InputBar()
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize the backend client and agent loop on startup."""
        raise NotImplementedError

    # ── Actions ──────────────────────────────────────────────────────────────

    async def action_stop_or_quit(self) -> None:
        """First press stops generation; second press quits."""
        raise NotImplementedError

    # ── Message handlers ─────────────────────────────────────────────────────

    async def on_input_bar_submitted(self, event) -> None:
        """User pressed Enter in the input bar."""
        raise NotImplementedError
