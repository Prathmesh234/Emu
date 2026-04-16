"""Coworker action routing and dispatcher."""

from typing import Optional, Dict, Any
from backend.models import Action, ActionType
from backend.coworker.config import get_coworker_mode, CoworkerMode


def should_use_coworker(action: Action) -> bool:
    """
    Determine if an action should be dispatched to coworker mode.
    
    Returns True if:
    - Coworker mode is enabled
    - Action is a desktop action (not screenshot, done, etc.)
    - Action has valid coordinates or keyboard input
    
    Args:
        action: The action to evaluate
        
    Returns:
        bool: True if should route to coworker
    """
    mode = get_coworker_mode()
    
    if mode == CoworkerMode.DISABLED:
        return False
    
    # Non-interactive actions always use regular dispatch
    if action.type in (
        ActionType.SCREENSHOT,
        ActionType.DONE,
        ActionType.UNKNOWN,
        ActionType.WAIT,
    ):
        return False
    
    # Tool-related actions use regular dispatch
    if action.type in (
        ActionType.COMPACT_CONTEXT,
        ActionType.READ_PLAN,
        ActionType.UPDATE_PLAN,
        ActionType.READ_MEMORY,
        ActionType.USE_SKILL,
        ActionType.WRITE_SESSION_FILE,
        ActionType.READ_SESSION_FILE,
        ActionType.LIST_SESSION_FILES,
    ):
        return False
    
    # Interactive actions can use coworker
    return True


def get_coworker_handler(mode: CoworkerMode) -> Optional[str]:
    """
    Get the coworker handler module name for a given mode.
    
    Args:
        mode: The coworker mode
        
    Returns:
        str: Handler module name (e.g., "skylight", "cua_shell")
        or None if invalid
    """
    if mode == CoworkerMode.SKYLIGHT:
        return "skylight"
    elif mode == CoworkerMode.CUA_SHELL:
        return "cua_shell"
    else:
        return None
