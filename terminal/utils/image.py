"""Image encoding and terminal graphics detection utilities."""

from __future__ import annotations

from enum import Enum


class GraphicsProtocol(str, Enum):
    """Terminal inline graphics protocols, in preference order."""

    SIXEL = "sixel"
    KITTY = "kitty"
    ITERM2 = "iterm2"
    BLOCK = "block"     # Unicode block-character fallback


def detect_terminal_graphics() -> GraphicsProtocol:
    """Detect which inline graphics protocol the current terminal supports.

    Checks (in order):
      1. TERM_PROGRAM / TERM for Sixel, Kitty, iTerm2 support
      2. Falls back to block characters (works everywhere)

    Returns
    -------
    GraphicsProtocol
        The best available protocol.
    """
    raise NotImplementedError


def encode_image_to_data_uri(
    image_bytes: bytes,
    mime_type: str = "image/webp",
) -> str:
    """Encode raw image bytes as a base64 data URI.

    Parameters
    ----------
    image_bytes : bytes
        Raw image file content.
    mime_type : str
        MIME type for the data URI prefix.

    Returns
    -------
    str
        Full data URI string: ``data:<mime>;base64,<encoded>``.
    """
    raise NotImplementedError
