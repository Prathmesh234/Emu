from enum import Enum
from typing import Literal, Optional, Dict, Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    SCREENSHOT     = "screenshot"
    LEFT_CLICK     = "left_click"
    RIGHT_CLICK    = "right_click"
    DOUBLE_CLICK   = "double_click"
    TRIPLE_CLICK   = "triple_click"
    MOUSE_MOVE     = "mouse_move"
    DRAG           = "drag"
    SCROLL         = "scroll"
    TYPE_TEXT       = "type_text"
    KEY_PRESS       = "key_press"
    SHELL_EXEC     = "shell_exec"
    WAIT           = "wait"
    DONE           = "done"
    UNKNOWN        = "unknown"
    # Agent tools — model-driven context management
    COMPACT_CONTEXT = "compact_context"
    READ_PLAN       = "read_plan"
    UPDATE_PLAN     = "update_plan"
    READ_MEMORY        = "read_memory"
    USE_SKILL          = "use_skill"
    WRITE_SESSION_FILE = "write_session_file"
    READ_SESSION_FILE  = "read_session_file"
    LIST_SESSION_FILES = "list_session_files"

class Coordinates(BaseModel):
    """Normalized screen coordinates in [0, 1] range (resolution-independent)."""
    x: float = Field(..., description="Horizontal position as ratio (0.0 = left edge, 1.0 = right edge)")
    y: float = Field(..., description="Vertical position as ratio (0.0 = top edge, 1.0 = bottom edge)")


class Action(BaseModel):
    """
    A single executable action returned by the model.

    Only the fields relevant to the action type will be populated;
    all others remain None.
    """

    type: ActionType = Field(..., description="The kind of action to execute")

    # Coworker mode target (optional, internal use only)
    coworker_target: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Target app/window for coworker mode execution (internal use)"
    )

    # Click / move / scroll / drag start position
    coordinates: Optional[Coordinates] = Field(
        default=None,
        description="Target screen coordinates (required for mouse_move, drag start)"
    )

    # Drag end position
    end_coordinates: Optional[Coordinates] = Field(
        default=None,
        description="End position for drag (required for DRAG)"
    )

    # Type text
    text: Optional[str] = Field(
        default=None,
        description="String to type (TYPE_TEXT) or plan content (UPDATE_PLAN)"
    )

    # Key press
    key: Optional[str] = Field(
        default=None,
        description="Key identifier, e.g. 'enter', 'tab' (used with KEY_PRESS)"
    )
    modifiers: Optional[list[str]] = Field(
        default=None,
        description="Modifier keys to hold, e.g. ['ctrl', 'shift'] (used with KEY_PRESS)"
    )

    # Scroll
    direction: Optional[Literal["up", "down"]] = Field(
        default=None,
        description="Scroll direction (used with SCROLL)"
    )
    amount: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of scroll notches (used with SCROLL)"
    )

    # Wait
    ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Milliseconds to pause (used with WAIT)"
    )

    # Shell exec
    command: Optional[str] = Field(
        default=None,
        description="Shell command to execute (used with SHELL_EXEC)"
    )

    # Agent tool params
    focus: Optional[str] = Field(
        default=None,
        description="What to prioritize in compaction summary (used with COMPACT_CONTEXT)"
    )


    # Skill invocation
    skill_name: Optional[str] = Field(
        default=None,
        description="Name of the skill to load (used with USE_SKILL)"
    )
