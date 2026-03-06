"""
context_manager/context.py

Chains PreviousMessage turns per session so each AgentRequest to Modal
carries the right conversation history. Uses the same models as the rest
of the codebase — no custom dataclasses.

Chain structure (built inside AgentRequest.previous_messages)
─────────────────────────────────────────────────────────────
  [system]    system prompt
  [user]      "Open Notepad and type hello world"   ← text task
  [assistant] reasoning + action: screenshot         ← model asks to see screen
  [user]      data:image/png;base64,iVBOR...         ← screenshot from frontend
  [assistant] reasoning + action: left_click(x,y)    ← model acts
  [user]      data:image/png;base64,iVBOR...         ← screenshot after action
  ...repeated...

Screenshots are stored as data URIs in user messages.
modal_client detects these and renders them as multimodal image content.
"""

import json

from models import AgentRequest, PreviousMessage, MessageRole
from prompts import build_system_prompt
from workspace import build_workspace_context, is_bootstrap_needed, read_bootstrap

# Prefix used to identify screenshot messages in history
SCREENSHOT_PREFIX = "data:image/"

# Maximum messages in the context chain before trimming the middle.
# System prompt + first user message + last N turns are always kept.
MAX_CHAIN_LENGTH = 60

# How many consecutive identical action types before injecting a warning.
LOOP_THRESHOLD = 3


class ContextManager:
    """
    Maintains a list of PreviousMessage turns per session.

    Typical call order
    ──────────────────
    1. add_user_message(session_id, text)               → user types a task
    2. build_request(session_id)                         → send to Modal
    3. add_assistant_turn(session_id, response_json)     → model response
    4. add_screenshot_turn(session_id, base64)           → screenshot from frontend
    5. build_request(session_id)                         → send to Modal again
    6. Repeat 3–5 for each step
    """

    def __init__(self):
        # session_id -> [PreviousMessage, ...]
        self._history: dict[str, list[PreviousMessage]] = {}

    def _get(self, session_id: str) -> list[PreviousMessage]:
        """Return existing history or bootstrap a new session with the system prompt."""
        if session_id not in self._history:
            # Build the system prompt dynamically with today's date,
            # session ID, and workspace files from .emu/
            workspace_ctx = build_workspace_context()

            # Check if this is the first launch (bootstrap interview needed)
            bootstrap_mode = is_bootstrap_needed()
            bootstrap_content = read_bootstrap() if bootstrap_mode else ""

            system_prompt = build_system_prompt(
                workspace_ctx,
                session_id=session_id,
                bootstrap_mode=bootstrap_mode,
                bootstrap_content=bootstrap_content,
            )
            self._history[session_id] = [
                PreviousMessage(role=MessageRole.system, content=system_prompt.strip())
            ]
        return self._history[session_id]

    def add_user_message(self, session_id: str, text: str) -> None:
        """Append a text-only user message (the task instruction)."""
        self._get(session_id).append(
            PreviousMessage(role=MessageRole.user, content=text)
        )

    def add_screenshot_turn(self, session_id: str, base64_screenshot: str) -> None:
        """
        Append a screenshot as a user message.
        Stored as a data URI so modal_client can detect and render it as an image.
        """
        if not base64_screenshot.startswith("data:"):
            base64_screenshot = f"data:image/png;base64,{base64_screenshot}"
        self._get(session_id).append(
            PreviousMessage(role=MessageRole.user, content=base64_screenshot)
        )

    def add_assistant_turn(self, session_id: str, response_json: str) -> None:
        """
        Append the model's full JSON response to the chain.
        Call this after Modal responds and the action has been dispatched.
        """
        self._get(session_id).append(
            PreviousMessage(
                role=MessageRole.assistant,
                content=response_json,
            )
        )

    # Placeholder that replaces old screenshots in the request
    SCREENSHOT_PLACEHOLDER = "[A screenshot was taken here and reviewed by you]"

    def build_request(self, session_id: str) -> AgentRequest:
        """
        Build an AgentRequest from the current history.

        Only the LATEST screenshot is kept as image data. All earlier
        screenshots are replaced with a short text placeholder to save
        tokens — the model already saw and acted on them.
        """
        history = self._get(session_id)

        # Count steps: each assistant turn = 1 step
        step_index = sum(1 for m in history if m.role == MessageRole.assistant)

        # Get the original user message (first user turn)
        user_message = ""
        for m in history:
            if m.role == MessageRole.user and not m.content.startswith(SCREENSHOT_PREFIX):
                user_message = m.content
                break

        # Build a lightweight copy: replace all but the last screenshot
        trimmed: list[PreviousMessage] = []
        last_screenshot_idx = -1
        for i, m in enumerate(history):
            if m.role == MessageRole.user and m.content.startswith(SCREENSHOT_PREFIX):
                last_screenshot_idx = i

        for i, m in enumerate(history):
            if (m.role == MessageRole.user
                    and m.content.startswith(SCREENSHOT_PREFIX)
                    and i != last_screenshot_idx):
                trimmed.append(
                    PreviousMessage(role=m.role, content=self.SCREENSHOT_PLACEHOLDER, timestamp=m.timestamp)
                )
            else:
                trimmed.append(m)

        return AgentRequest(
            session_id=session_id,
            user_message=user_message,
            base64_screenshot="",  # no longer passed separately
            previous_messages=trimmed,
            step_index=step_index,
        )

    def clear_session(self, session_id: str) -> None:
        """Remove all history for a session."""
        self._history.pop(session_id, None)
