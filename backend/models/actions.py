from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError


class ActionType(str, Enum):
    SCREENSHOT              = "screenshot"
    LEFT_CLICK              = "left_click"
    RIGHT_CLICK             = "right_click"
    DOUBLE_CLICK            = "double_click"
    TRIPLE_CLICK            = "triple_click"
    NAVIGATE_AND_CLICK        = "navigate_and_click"
    NAVIGATE_AND_RIGHT_CLICK  = "navigate_and_right_click"
    NAVIGATE_AND_TRIPLE_CLICK = "navigate_and_triple_click"
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

    # Navigate target / move / drag start position
    coordinates: Optional[Coordinates] = Field(
        default=None,
        description="Target screen coordinates (required for navigate_and_click/"
                    "right_click/double_click/triple_click, mouse_move, drag start)"
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


def safe_build_action(raw_action: dict, provider_tag: str = "provider") -> "Action":
    """
    Build an Action from a raw dict, falling back to ActionType.UNKNOWN if
    pydantic validation fails (e.g. malformed coordinates, wrong field type).

    The UNKNOWN action then flows through ActionValidator Rule 5, which tells
    the model the correct JSON format — instead of crashing the request with a
    500 or silently succeeding as done.
    """
    try:
        return Action(**raw_action)
    except (ValidationError, TypeError) as e:
        print(f"[{provider_tag}] INFO: malformed action {raw_action!r} → wrapping as unknown. pydantic: {e}")
        return Action(type=ActionType.UNKNOWN)
