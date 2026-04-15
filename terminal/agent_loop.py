"""Core agent orchestration loop.

Mirrors the flow in frontend/pages/Chat.js:
  1. Capture screenshot
  2. POST /agent/step with user message + screenshot
  3. Listen on WebSocket for step/plan_review/done/error messages
  4. Execute desktop actions via ActionExecutor
  5. Capture new screenshot after each action
  6. POST /action/complete to notify backend
  7. Loop until done or user interrupts
"""

from __future__ import annotations

from terminal.client import EmuClient
from terminal.executor import ActionExecutor
from terminal.screenshot import capture_screenshot
from terminal.config import TerminalConfig


class AgentLoop:
    """Drives the observe-act-observe cycle between the terminal UI and the backend."""

    def __init__(
        self,
        client: EmuClient,
        executor: ActionExecutor,
        config: TerminalConfig,
    ) -> None:
        self._client = client
        self._executor = executor
        self._cfg = config
        self._session_id: str | None = None
        self._running: bool = False

    # ── Public API (called by the Textual app) ───────────────────────────────

    async def start_session(self) -> str:
        """Create a new backend session and open the WebSocket."""
        raise NotImplementedError

    async def send_message(self, text: str) -> None:
        """Send a user message and begin the agent loop.

        Steps:
          1. Capture screenshot via screenshot.py
          2. POST /agent/step
          3. Enter _run_loop() to process WebSocket messages
        """
        raise NotImplementedError

    async def stop(self) -> None:
        """Interrupt the current agent trajectory."""
        raise NotImplementedError

    async def compact(self) -> None:
        """Trigger manual context compaction."""
        raise NotImplementedError

    # ── Internal loop ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Process WebSocket messages until done, error, or user interrupt.

        Message types handled:
          - "step"        → display reasoning, execute action, screenshot, notify
          - "plan_review" → display plan, wait for user approval/rejection
          - "done"        → display final message, break
          - "error"       → display error, break
          - "status"      → update status bar
          - "stopped"     → acknowledge stop, break
        """
        raise NotImplementedError

    async def _execute_and_report(self, action: dict) -> None:
        """Execute a single action, capture screenshot, notify backend."""
        raise NotImplementedError
