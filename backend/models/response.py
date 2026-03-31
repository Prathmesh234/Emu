from typing import Optional

from pydantic import BaseModel, Field

from .actions import Action


class ToolCallInfo(BaseModel):
    """A single tool call returned by the model (OpenAI function calling format)."""
    id:        str = Field(..., description="Unique ID for this tool call")
    name:      str = Field(..., description="Name of the function to call")
    arguments: str = Field(..., description="JSON-encoded arguments string")


class AgentResponse(BaseModel):
    """
    Structured response returned by the VLM after processing a single agent step.

    Two response modes:
      1. Tool calls — model wants to call agent tools (plan, memory, skills, etc.)
         tool_calls is populated, action is None.
      2. Desktop action — model wants to act on the screen (click, type, etc.)
         action is populated, tool_calls is None.
    """

    # Desktop action (mutually exclusive with tool_calls)
    action: Optional[Action] = Field(
        default=None,
        description="Desktop action to execute (None when tool_calls are present)"
    )

    # Agent tool calls (mutually exclusive with action)
    tool_calls: Optional[list[ToolCallInfo]] = Field(
        default=None,
        description="Agent tool calls to execute server-side (None when action is present)"
    )

    # Completion
    done:          bool            = Field(default=False, description="True when the task is complete")
    final_message: Optional[str]   = Field(
        default=None,
        description="Human-readable completion summary (populated when done=True)"
    )

    # Reasoning / Chain-of-thought
    reasoning_content: Optional[str] = Field(
        default=None,
        description="Model's internal reasoning / chain-of-thought text"
    )

    # Quality signals
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Model's confidence in the chosen action (0–1)"
    )

    # Telemetry
    inference_time_ms: int = Field(
        default=0, ge=0,
        description="Wall-clock inference time in milliseconds"
    )
    model_name: str = Field(
        default="",
        description="Identifier of the model that produced this response"
    )
