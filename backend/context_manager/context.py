"""
context_manager/context.py

Chains PreviousMessage turns per session so each AgentRequest to Modal
carries the right conversation history. Uses the same models as the rest
of the codebase — no custom dataclasses.

Chain structure (built inside AgentRequest.previous_messages)
─────────────────────────────────────────────────────────────
  [system]    system prompt
  [user]      user message                      ← appended on every call
  [assistant] full AgentResponse JSON            ← appended after each model response
  [user]      next user message
  [assistant] next AgentResponse JSON
  ...repeated for every turn...

The current screenshot is always passed as AgentRequest.base64_screenshot.
"""

from models import AgentRequest, PreviousMessage, MessageRole
from prompts import SYSTEM_PROMPT


class ContextManager:
    """
    Maintains a list of PreviousMessage turns per session.

    Typical call order
    ──────────────────
    1. build_request(session_id, user_message, screenshot)   → send to Modal
    2. add_assistant_turn(session_id, response_json)          → append model reply
    3. Repeat from 1 with the next screenshot
    """

    def __init__(self):
        # session_id -> [PreviousMessage, ...]
        self._history: dict[str, list[PreviousMessage]] = {}

    def _get(self, session_id: str) -> list[PreviousMessage]:
        """Return existing history or bootstrap a new session with the system prompt."""
        if session_id not in self._history:
            self._history[session_id] = [
                PreviousMessage(role=MessageRole.system, content=SYSTEM_PROMPT.strip())
            ]
        return self._history[session_id]

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

    def build_request(
        self,
        session_id: str,
        user_message: str,
        base64_screenshot: str,
    ) -> AgentRequest:
        """
        Build an AgentRequest ready to send to Modal.

        On the FIRST call for a session (history contains only the system prompt),
        the user message is appended to history so subsequent steps can see it.

        Chain after step 0 completes:
          [system] → [user: original message] → [assistant: reasoning + action] → ...

        previous_messages  = everything accumulated so far.
        base64_screenshot  = the latest screenshot (only visual input, not stored in history).
        """
        history = self._get(session_id)

        # Every call adds the user message to the chain
        history.append(PreviousMessage(role=MessageRole.user, content=user_message))

        step_index = max(0, len(history) - 2)  # subtract system prompt + first user msg

        return AgentRequest(
            session_id=session_id,
            user_message=user_message,
            base64_screenshot=base64_screenshot,
            previous_messages=list(history),  # snapshot for this request
            step_index=step_index,
        )

    def clear_session(self, session_id: str) -> None:
        """Remove all history for a session."""
        self._history.pop(session_id, None)
