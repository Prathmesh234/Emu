from typing import Optional

from pydantic import BaseModel, Field

from .actions import Action


class AgentResponse(BaseModel):
    """
    Structured response returned by the VLM after processing a single agent step.

    action           : The concrete action to execute on the desktop.
    done             : True when the model considers the task complete.
                       The agent loop should stop and report to the user.
    final_message    : Human-readable summary of what was accomplished.
                       Only populated when done=True.
    confidence       : Model's self-reported confidence in the chosen action
                       (0.0–1.0). Used to trigger fallback / confirmation steps
                       when below a threshold.
    inference_time_ms: Wall-clock time the model took for this step (ms).
                       Useful for performance monitoring and timeout logic.
    model_name       : The identifier of the model that produced this response.
                       Enables multi-model setups where different models handle
                       different step types.
    """

    # Action
    action:    Action = Field(..., description="The action to execute on the desktop")

    # Completion
    done:          bool            = Field(..., description="True when the task is complete")
    final_message: Optional[str]   = Field(
        default=None,
        description="Human-readable completion summary (populated when done=True)"
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

    class Config:
        json_schema_extra = {
            "example": {
                "action": {
                    "type": "left_click",
                    "coordinates": {"x": 24, "y": 1056}
                },
                "done": False,
                "final_message": None,
                "confidence": 0.95,
                "inference_time_ms": 312,
                "model_name": "llava-1.5-13b-hf"
            }
        }
