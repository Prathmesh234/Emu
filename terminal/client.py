"""Async HTTP + WebSocket client for the Emu backend.

Talks to the same FastAPI backend that the Electron frontend uses.
All endpoints mirror backend/main.py exactly.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import aiohttp

from terminal.config import TerminalConfig


class EmuClient:
    """Thin async wrapper around the Emu backend REST + WebSocket API."""

    def __init__(self, config: TerminalConfig) -> None:
        self._cfg = config
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open the HTTP session (call once at startup)."""
        headers = {"X-Emu-Token": self._cfg.auth_token}
        self._session = aiohttp.ClientSession(
            base_url=self._cfg.backend_url,
            headers=headers,
        )

    async def close(self) -> None:
        """Tear down HTTP session and any open WebSocket."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()

    # ── REST endpoints ───────────────────────────────────────────────────────

    async def health(self) -> dict:
        """GET /health"""
        raise NotImplementedError

    async def create_session(self) -> str:
        """POST /agent/session → returns session_id."""
        raise NotImplementedError

    async def post_step(
        self,
        session_id: str,
        user_message: str,
        base64_screenshot: str = "",
    ) -> dict:
        """POST /agent/step — send user message + screenshot to the agent loop."""
        raise NotImplementedError

    async def action_complete(
        self,
        session_id: str,
        ipc_channel: str,
        success: bool,
        error: str | None = None,
        output: str | None = None,
    ) -> dict:
        """POST /action/complete — notify backend an action finished."""
        raise NotImplementedError

    async def stop(self, session_id: str) -> dict:
        """POST /agent/stop — interrupt the current agent trajectory."""
        raise NotImplementedError

    async def compact(self, session_id: str) -> dict:
        """POST /agent/compact — trigger context compaction."""
        raise NotImplementedError

    async def get_history(self) -> list[dict]:
        """GET /sessions/history — list past sessions."""
        raise NotImplementedError

    async def get_session_messages(self, session_id: str) -> dict:
        """GET /sessions/{session_id}/messages — full conversation log."""
        raise NotImplementedError

    # ── WebSocket ────────────────────────────────────────────────────────────

    async def connect_ws(self, session_id: str) -> None:
        """Open a WebSocket to /ws/{session_id}?token=..."""
        raise NotImplementedError

    async def ws_messages(self) -> AsyncIterator[dict]:
        """Yield parsed JSON messages from the WebSocket until closed."""
        raise NotImplementedError
        yield  # pragma: no cover — makes this a proper async generator

    async def close_ws(self) -> None:
        """Close the WebSocket connection."""
        raise NotImplementedError
