"""Status bar widget — persistent single-line header.

Displays:
  - Connection status (backend reachable / unreachable)
  - Active model name
  - Chain length (conversation depth)
  - Current confidence score
  - Agent state (idle / thinking / acting / done)
"""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Single-line status bar docked to the top of the screen."""

    DEFAULT_CSS = """
    StatusBar {
        content-align: left middle;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._model: str = ""
        self._chain_length: int = 0
        self._confidence: float = 0.0
        self._state: str = "idle"

    def on_mount(self) -> None:
        self._render()

    def update_state(
        self,
        *,
        model: str | None = None,
        chain_length: int | None = None,
        confidence: float | None = None,
        state: str | None = None,
    ) -> None:
        """Update one or more status fields and re-render."""
        if model is not None:
            self._model = model
        if chain_length is not None:
            self._chain_length = chain_length
        if confidence is not None:
            self._confidence = confidence
        if state is not None:
            self._state = state
        self._render()

    def _render(self) -> None:
        parts = [
            f"Emu Terminal",
            f"model: {self._model or '---'}",
            f"chain: {self._chain_length}",
            f"conf: {self._confidence:.0%}",
            f"[{self._state}]",
        ]
        self.update(" | ".join(parts))
