from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    SCREENSHOT   = "screenshot"
    LEFT_CLICK   = "left_click"
    RIGHT_CLICK  = "right_click"
    DOUBLE_CLICK = "double_click"
    TRIPLE_CLICK = "triple_click"
    MOUSE_MOVE   = "mouse_move"
    DRAG         = "drag"
    SCROLL       = "scroll"
    TYPE_TEXT    = "type_text"
    KEY_PRESS    = "key_press"
    SHELL_EXEC   = "shell_exec"
    WAIT         = "wait"
    DONE         = "done"


class Coordinates(BaseModel):
    """Normalized screen coordinates in [0, 1] range (resolution-independent)."""
    x: float = Field(..., description="Horizontal position as ratio (0.0 = left edge, 1.0 = right edge)")
    y: float = Field(..., description="Vertical position as ratio (0.0 = top edge, 1.0 = bottom edge)")


class Action(BaseModel):
    """
    A single executable action returned by the model.

    Only the fields relevant to the action type will be populated;
    all others remain None.

    Click / move actions  → coordinates
    Type actions          → text
    Key press actions     → key + modifiers
    Scroll actions        → coordinates + direction + amount
    Wait actions          → ms
    Done actions          → (no extra fields; signals task completion)
    """

    type: ActionType = Field(..., description="The kind of action to execute")

    # Click / move / scroll / drag start position
    coordinates: Optional[Coordinates] = Field(
        default=None,
        description="Target screen coordinates (required for click, move, scroll, drag start)"
    )

    # Drag end position
    end_coordinates: Optional[Coordinates] = Field(
        default=None,
        description="End position for drag (required for DRAG — drag from coordinates to end_coordinates)"
    )

    # Type text
    text: Optional[str] = Field(
        default=None,
        description="String to type (used with TYPE_TEXT)"
    )

    # Key press
    key: Optional[str] = Field(
        default=None,
        description="Key identifier, e.g. 'enter', 'tab', 'escape' (used with KEY_PRESS)"
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
        description="PowerShell command to execute (used with SHELL_EXEC)"
    )
