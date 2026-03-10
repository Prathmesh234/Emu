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

from models import AgentRequest, PreviousMessage, MessageRole, ScreenAnnotation, ScreenElement
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
        Run the screenshot through OmniParser for UI element detection,
        then append it as a user message with annotations attached.

        The annotated (labelled) image replaces the raw screenshot in the chain
        so the model sees element IDs drawn on screen. The structured element
        list is stored in annotations for coordinate-aware reasoning.
        """
        if not base64_screenshot.startswith("data:"):
            base64_screenshot = f"data:image/png;base64,{base64_screenshot}"

        # Strip the data URI prefix for the OmniParser client
        raw_b64 = base64_screenshot.split(",", 1)[1] if "," in base64_screenshot else base64_screenshot

        annotations = None
        try:
            from providers.modal.omni_parser.client import parse_screenshot_b64
            result = parse_screenshot_b64(raw_b64, include_annotated=True)

            # Use the annotated image (with drawn element boxes) instead of raw
            if result.annotated_image_base64:
                base64_screenshot = f"data:image/png;base64,{result.annotated_image_base64}"

            # Build the structured annotation
            elements = [
                ScreenElement(
                    id=e.id, type=e.type, content=e.content,
                    bbox_pixel=e.bbox_pixel, center_pixel=e.center_pixel,
                    interactable=e.interactable,
                )
                for e in result.elements
            ]
            annotations = ScreenAnnotation(
                elements=elements,
                image_width=result.image_width,
                image_height=result.image_height,
                latency_ms=result.latency_ms,
            )
            print(f"[omniparser] {len(elements)} elements detected ({result.latency_ms}ms)")
            for e in elements:
                tag = e.type.upper()
                coords = f"bbox=({e.bbox_pixel[0]},{e.bbox_pixel[1]},{e.bbox_pixel[2]},{e.bbox_pixel[3]})  center=({e.center_pixel[0]},{e.center_pixel[1]})"
                lbl = e.content if e.content else ""
                click = "  [clickable]" if e.interactable else ""
                print(f"  [{e.id}] {tag}  label=\"{lbl}\"  {coords}{click}")
        except Exception as e:
            # OmniParser failure is non-fatal — fall back to raw screenshot
            print(f"[omniparser] Failed, using raw screenshot: {e}")

        self._get(session_id).append(
            PreviousMessage(
                role=MessageRole.user,
                content=base64_screenshot,
                annotations=annotations,
            )
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

        # Build a lightweight copy: replace all but the last screenshot.
        # For the latest screenshot, inject the element list as a follow-up text
        # message so the model sees both the annotated image AND structured data.
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
                # After the latest screenshot, inject the element list as text
                if i == last_screenshot_idx and m.annotations and m.annotations.elements:
                    element_text = self._format_annotations(m.annotations)
                    trimmed.append(
                        PreviousMessage(role=MessageRole.user, content=element_text, timestamp=m.timestamp)
                    )

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

    @staticmethod
    def _format_annotations(ann: ScreenAnnotation) -> str:
        """Format screen annotations as a compact text block for the model."""
        lines = [f"[SCREEN ELEMENTS] {ann.image_width}x{ann.image_height} — {len(ann.elements)} elements detected"]
        for e in ann.elements:
            x1, y1, x2, y2 = e.bbox_pixel
            cx, cy = e.center_pixel
            lbl = e.content if e.content else ""
            click = "  [clickable]" if e.interactable else ""
            lines.append(f'  [{e.id}] {e.type.upper()}  label="{lbl}"  bbox=({x1},{y1},{x2},{y2})  center=({cx},{cy}){click}')
        return "\n".join(lines)

    def get_compact_messages(self, session_id: str) -> list[PreviousMessage]:
        """
        Return the message chain for compaction.

        Same as what the model sees via build_request(), but ALL screenshots
        are replaced with placeholders (no point sending images to a text
        summariser). The system prompt is stripped — it gets re-injected
        after compaction.
        """
        history = self._get(session_id)
        messages: list[PreviousMessage] = []

        for m in history:
            if m.role == MessageRole.system:
                continue
            elif m.role == MessageRole.user and m.content.startswith(SCREENSHOT_PREFIX):
                messages.append(
                    PreviousMessage(role=m.role, content=self.SCREENSHOT_PLACEHOLDER, timestamp=m.timestamp)
                )
            else:
                messages.append(m)

        return messages

    def reset_with_summary(self, session_id: str, summary: str) -> None:
        """
        Replace the context chain with: system prompt + compacted summary.

        The system prompt is rebuilt fresh (picks up current date/time).
        The summary is injected as a user message so the model sees the
        full trajectory context in a compressed form.
        """
        from workspace import build_workspace_context, is_bootstrap_needed, read_bootstrap
        from prompts import build_system_prompt

        workspace_ctx = build_workspace_context()
        bootstrap_mode = is_bootstrap_needed()
        bootstrap_content = read_bootstrap() if bootstrap_mode else ""

        system_prompt = build_system_prompt(
            workspace_ctx,
            session_id=session_id,
            bootstrap_mode=bootstrap_mode,
            bootstrap_content=bootstrap_content,
        )

        self._history[session_id] = [
            PreviousMessage(role=MessageRole.system, content=system_prompt.strip()),
            PreviousMessage(
                role=MessageRole.user,
                content="[COMPACTED SUMMARY]\n" + summary,
            ),
        ]

    def chain_length(self, session_id: str) -> int:
        """Return the number of messages in a session's context chain."""
        return len(self._get(session_id))
