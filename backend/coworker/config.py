"""Coworker mode configuration and detection."""

import os
from enum import Enum
from typing import Optional


class CoworkerMode(str, Enum):
    """Coworker mode options."""
    SKYLIGHT = "skylight"      # Direct SkyLight.framework bindings
    CUA_SHELL = "cua"          # Shell execution of cua-driver CLI
    DISABLED = "disabled"       # Coworker mode disabled
    AUTO = "auto"              # Auto-detect (try skylight first, fallback to cua)


def detect_coworker_mode() -> CoworkerMode:
    """
    Detect coworker mode from environment variable or system detection.
    
    Environment variable: EMU_COWORKER_MODE
    Valid values: "skylight", "cua", "auto", "disabled"
    
    On macOS with auto mode: Try skylight first, fallback to cua if available
    On non-macOS: Always disabled
    
    Returns:
        CoworkerMode: The detected coworker mode
    """
    import platform
    import sys
    
    raw_mode = os.environ.get("EMU_COWORKER_MODE", "").strip().lower()
    
    # Explicit mode override
    if raw_mode in ("skylight", "cua", "disabled"):
        mode = CoworkerMode(raw_mode)
        print(f"[coworker] Mode: {mode.value} (explicit)")
        return mode
    
    # Auto mode or default
    if raw_mode == "auto" or raw_mode == "":
        # Only macOS supports coworker mode
        if platform.system() != "Darwin":
            print(f"[coworker] Mode: disabled (platform={platform.system()})")
            return CoworkerMode.DISABLED
        
        # On macOS, try to detect which approach is available
        # For now, default to skylight (we'll add cua detection later)
        print(f"[coworker] Mode: skylight (auto-detected on macOS)")
        return CoworkerMode.SKYLIGHT
    
    # Invalid mode
    raise ValueError(
        f"Invalid EMU_COWORKER_MODE={raw_mode}. "
        "Valid options: skylight, cua, auto, disabled"
    )


def is_coworker_enabled() -> bool:
    """Check if coworker mode is enabled."""
    mode = detect_coworker_mode()
    return mode != CoworkerMode.DISABLED


def get_coworker_mode() -> CoworkerMode:
    """Get the current coworker mode."""
    return detect_coworker_mode()
