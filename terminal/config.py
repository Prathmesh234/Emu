"""Configuration loading — CLI args, env vars, .emu/.auth_token."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TerminalConfig:
    """Immutable runtime configuration for the terminal client."""

    backend_url: str = "http://127.0.0.1:8000"
    ws_url: str = "ws://127.0.0.1:8000"
    auth_token: str = ""
    screenshot_width: int = 768
    screenshot_quality: int = 60


def _read_auth_token() -> str:
    """Read the auth token from .emu/.auth_token (written by the backend on startup)."""
    candidates = [
        Path.cwd() / ".emu" / ".auth_token",
        Path.home() / ".emu" / ".auth_token",
    ]
    for path in candidates:
        if path.is_file():
            return path.read_text().strip()
    return ""


def load_config(
    backend_url: str = "http://127.0.0.1:8000",
    token_override: str | None = None,
) -> TerminalConfig:
    """Build a TerminalConfig from CLI args and on-disk defaults."""
    token = token_override or _read_auth_token()
    ws_url = backend_url.replace("http://", "ws://").replace("https://", "wss://")

    return TerminalConfig(
        backend_url=backend_url,
        ws_url=ws_url,
        auth_token=token,
    )
