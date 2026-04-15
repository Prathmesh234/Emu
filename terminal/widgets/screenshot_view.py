"""Screenshot preview widget — inline display of captured screenshots.

Rendering strategy (in priority order):
  1. Sixel graphics   — xterm, mlterm, foot, WezTerm
  2. Kitty protocol   — Kitty, WezTerm
  3. iTerm2 inline    — iTerm2
  4. Block characters — fallback for all terminals (low-res but universal)

For the scaffolding phase this is a placeholder that shows dimensions only.
"""

from __future__ import annotations

from textual.widgets import Static


class ScreenshotView(Static):
    """Inline screenshot preview (or dimensions-only placeholder)."""

    def __init__(self, width: int, height: int) -> None:
        self._img_width = width
        self._img_height = height
        super().__init__(self._render())

    def _render(self) -> str:
        return f"Screenshot captured ({self._img_width}x{self._img_height})"
