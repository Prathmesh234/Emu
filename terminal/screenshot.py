"""Screenshot capture and encoding.

Replaces the Electron/PowerShell screenshot pipeline with pure Python.
Uses `mss` for fast capture and `Pillow` for resize + WebP encoding.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScreenshotResult:
    """Captured screenshot ready to send to the backend."""

    base64_data: str        # Full data URI: "data:image/webp;base64,..."
    screen_width: int       # Physical screen width in pixels
    screen_height: int      # Physical screen height in pixels
    capture_width: int      # Width after resize (typically 768)
    capture_height: int     # Height after resize


def capture_screenshot(
    max_width: int = 768,
    quality: int = 60,
) -> ScreenshotResult:
    """Capture the full screen, resize, encode as WebP base64.

    Parameters
    ----------
    max_width : int
        Resize the captured image so its width is at most this many pixels.
        Matches the Electron frontend's 768px default.
    quality : int
        WebP encoding quality (0–100).

    Returns
    -------
    ScreenshotResult
        Contains the base64 data URI and screen dimensions.
    """
    raise NotImplementedError
