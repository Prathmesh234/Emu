"""
context_manager/context.py

Chains PreviousMessage turns per session so each AgentRequest to Modal
carries the right conversation history. Uses the same models as the rest
of the codebase — no custom dataclasses.

Chain structure (built inside AgentRequest.previous_messages)
─────────────────────────────────────────────────────────────
  [system]    system prompt
  [user]      "Open TextEdit and type hello world"   ← text task
  [assistant] reasoning + action: screenshot         ← model asks to see screen
  [user]      data:image/png;base64,iVBOR...         ← screenshot from frontend
  [assistant] reasoning + action: left_click(x,y)    ← model acts
  [user]      data:image/png;base64,iVBOR...         ← screenshot after action
  ...repeated...

Screenshots are stored as data URIs in user messages.
modal_client detects these and renders them as multimodal image content.
"""

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from models import AgentRequest, PreviousMessage, MessageRole, ScreenAnnotation, ScreenElement
from prompts import build_system_prompt
from workspace import build_workspace_context, get_device_details, is_bootstrap_needed, read_bootstrap

# When True, screenshots are routed through OmniParser for UI element
# detection and the annotated image replaces the raw one in the chain.
# When False (default), the raw screenshot (with cursor overlay) is sent
# directly to the model — faster, but no structured element list.
USE_OMNI_PARSER = (
    "--use-omni-parser" in sys.argv
    or os.environ.get("USE_OMNI_PARSER", "").lower() in ("1", "true", "yes")
)

# Directory where screenshots are saved (same as frontend uses)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = _BACKEND_DIR / "emulation_screen_shots"

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

            device_info = get_device_details()
            system_prompt = build_system_prompt(
                workspace_ctx,
                session_id=session_id,
                bootstrap_mode=bootstrap_mode,
                bootstrap_content=bootstrap_content,
                device_details=device_info,
            )
            self._history[session_id] = [
                PreviousMessage(role=MessageRole.system, content=system_prompt.strip())
            ]
        return self._history[session_id]

    def add_user_message(self, session_id: str, text: str) -> None:
        """Append a text-only user message (the task instruction)."""
        if not text or not text.strip():
            return  # Skip empty messages
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
            # Detect format from base64 header: JPEG starts with /9j, PNG with iVBOR
            mime = "image/jpeg" if base64_screenshot.startswith("/9j") else "image/png"
            base64_screenshot = f"data:{mime};base64,{base64_screenshot}"

        annotations = None

        if USE_OMNI_PARSER:
            # Strip the data URI prefix for the OmniParser client
            raw_b64 = base64_screenshot.split(",", 1)[1] if "," in base64_screenshot else base64_screenshot

            try:
                from providers.modal.omni_parser.client import parse_screenshot_b64
                result = parse_screenshot_b64(raw_b64, include_annotated=True)

                # Use the annotated image (with drawn element boxes) instead of raw
                if result.annotated_image_base64:
                    base64_screenshot = f"data:image/png;base64,{result.annotated_image_base64}"

                    # Save annotated screenshot to disk
                    try:
                        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        annotated_path = SCREENSHOTS_DIR / f"screenshot_{timestamp}_annotated.png"
                        annotated_bytes = base64.b64decode(result.annotated_image_base64)
                        annotated_path.write_bytes(annotated_bytes)
                        print(f"[omniparser] saved annotated screenshot → {annotated_path.name}")
                    except Exception as save_err:
                        print(f"[omniparser] failed to save annotated screenshot: {save_err}")

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
                img_w = result.image_width or 1
                img_h = result.image_height or 1
                print(f"[omniparser] {len(elements)} elements detected ({result.latency_ms}ms)  [coords normalized to 0-1]")
                for e in elements:
                    tag = e.type.upper()
                    ncx = round(e.center_pixel[0] / img_w, 4)
                    ncy = round(e.center_pixel[1] / img_h, 4)
                    coords = f"center_px=({e.center_pixel[0]},{e.center_pixel[1]})  center_norm=({ncx},{ncy})"
                    lbl = e.content if e.content else ""
                    click = "  [clickable]" if e.interactable else ""
                    print(f"  [{e.id}] {tag}  label=\"{lbl}\"  {coords}{click}")
            except Exception as e:
                # OmniParser failure is non-fatal — fall back to raw screenshot
                print(f"[omniparser] Failed, using raw screenshot: {e}")
        else:
            print("[screenshot] OmniParser skipped — sending direct screenshot to model")

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

        # Middle-trim: if the chain is still too long after screenshot replacement,
        # keep system prompt + first user message + last N turns. This prevents
        # the context from exceeding model limits before auto-compact fires.
        if len(trimmed) > MAX_CHAIN_LENGTH:
            # Keep: [0] system, [1] first user message, then last (MAX-2) messages
            keep_head = 2  # system + first user message
            keep_tail = MAX_CHAIN_LENGTH - keep_head
            trimmed = trimmed[:keep_head] + [
                PreviousMessage(
                    role=MessageRole.user,
                    content=(
                        "[Note: Earlier conversation turns were trimmed to save space. "
                        "Refer to .emu/sessions/" + session_id + "/plan.md for the full task plan.]"
                    ),
                )
            ] + trimmed[-keep_tail:]

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
        """Format screen annotations as a compact text block for the model.

        All coordinates are normalized to [0, 1] range so the model is
        resolution-independent.  Emu denormalizes back to screen pixels
        before executing cliclick/osascript commands on macOS.
        """
        w = ann.image_width or 1   # guard against division by zero
        h = ann.image_height or 1
        lines = [f"[SCREEN ELEMENTS] {ann.image_width}x{ann.image_height} — {len(ann.elements)} elements detected  (coordinates normalized to 0-1)"]
        for e in ann.elements:
            x1, y1, x2, y2 = e.bbox_pixel
            cx, cy = e.center_pixel
            # Normalize to [0, 1]
            nx1, ny1 = round(x1 / w, 4), round(y1 / h, 4)
            nx2, ny2 = round(x2 / w, 4), round(y2 / h, 4)
            ncx, ncy = round(cx / w, 4), round(cy / h, 4)
            lbl = e.content if e.content else ""
            click = "  [clickable]" if e.interactable else ""
            lines.append(f'  [{e.id}] {e.type.upper()}  label="{lbl}"  bbox=({nx1},{ny1},{nx2},{ny2})  center=({ncx},{ncy}){click}')
        return "\n".join(lines)

    # Prefix for screen element annotation blocks injected after screenshots
    SCREEN_ELEMENTS_PREFIX = "[SCREEN ELEMENTS]"

    def get_compact_messages(self, session_id: str) -> list[PreviousMessage]:
        """
        Return the message chain for compaction.

        Same as what the model sees via build_request(), but:
          - ALL screenshots are replaced with placeholders
          - [SCREEN ELEMENTS] blocks (bbox/coordinate data) are stripped
          - The system prompt is removed (re-injected after compaction)
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
            elif m.role == MessageRole.user and m.content.startswith(self.SCREEN_ELEMENTS_PREFIX):
                # Skip screen element annotation blocks — huge bbox data
                # that's useless for text summarisation
                continue
            else:
                messages.append(m)

        return messages

    def reset_with_summary(self, session_id: str, summary: str) -> None:
        """
        Replace the context chain with: system prompt + compacted summary.

        The system prompt is rebuilt fresh (picks up current date/time).
        Bootstrap mode is forced OFF — if we are compacting, we are already
        in an active session, so the first-launch interview must never fire.
        The summary is injected as a user turn framed as a continuation
        directive, followed by an assistant acknowledgment that restates the
        key context so the model has a clear mandate.
        """
        from workspace import build_workspace_context, get_device_details
        from prompts import build_system_prompt

        workspace_ctx = build_workspace_context()
        device_info = get_device_details()

        # Always bootstrap_mode=False: we're mid-session, never first-launch.
        system_prompt = build_system_prompt(
            workspace_ctx,
            session_id=session_id,
            bootstrap_mode=False,
            bootstrap_content="",
            device_details=device_info,
        )

        # Extract key sections from the summary for the assistant ack
        primary_task = ""
        current_step = ""
        remaining_steps = ""
        for line in summary.split("\n"):
            if line.strip().startswith("## PRIMARY TASK"):
                primary_task = "(see summary above)"
            elif line.strip().startswith("## CURRENT STEP"):
                current_step = "(see summary above)"
            elif line.strip().startswith("## REMAINING STEPS"):
                remaining_steps = "(see summary above)"

        # Frame the summary as an explicit continuation directive
        user_content = (
            "[CONTEXT CONTINUATION — READ CAREFULLY]\n\n"
            "The conversation history was compacted to save tokens. "
            "Below is a detailed summary of everything that happened so far.\n\n"
            "YOUR INSTRUCTIONS:\n"
            "1. Read the ENTIRE summary below carefully\n"
            "2. Find ## REMAINING STEPS — those are your next actions\n"
            "3. Continue from ## CURRENT STEP — do NOT restart from the beginning\n"
            "4. Do NOT ask the user to repeat anything\n"
            "5. Do NOT write a new plan.md — it already exists\n"
            "6. If confused about what to do, read .emu/sessions/" + session_id + "/plan.md\n"
            "7. Your next response should be a JSON action continuing the task\n\n"
            "━━━━━━━━━━ COMPACTED CONTEXT BELOW ━━━━━━━━━━\n\n"
            + summary
            + "\n\n━━━━━━━━━━ END OF COMPACTED CONTEXT ━━━━━━━━━━\n\n"
            "REMINDER: Continue from ## REMAINING STEPS. Do NOT start over. "
            "Respond with a JSON action to continue the task."
        )

        self._history[session_id] = [
            PreviousMessage(role=MessageRole.system, content=system_prompt.strip()),
            PreviousMessage(
                role=MessageRole.user,
                content=user_content,
            ),
            PreviousMessage(
                role=MessageRole.assistant,
                content=(
                    '{"reasoning": "Context was compacted. I have read the full '
                    'continuation summary. I understand: (1) the PRIMARY TASK the user '
                    'requested, (2) what steps are COMPLETED, (3) what CURRENT STEP was '
                    'in progress, and (4) what REMAINING STEPS I need to execute next. '
                    'I will NOT start over or ask the user to repeat. I will continue '
                    'from where we left off by taking a screenshot to see the current '
                    'screen state, then proceeding with the remaining steps.", '
                    '"action": {"type": "screenshot"}, "done": false, '
                    '"confidence": 0.95}'
                ),
            ),
        ]

    def chain_length(self, session_id: str) -> int:
        """Return the number of messages in a session's context chain."""
        return len(self._get(session_id))
