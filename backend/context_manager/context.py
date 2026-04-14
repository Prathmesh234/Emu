"""
context_manager/context.py

Chains PreviousMessage turns per session so each AgentRequest to the model
carries the right conversation history.

Key features:
  - Screenshot management: only latest screenshot kept as image data
  - Action validation: blocks invalid actions at runtime (replaces prompt rules)
  - Plan auto-injection: injects plan.md every N turns to keep model anchored
  - Model-driven compaction: model calls compact_context tool, harness executes
"""

import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from models import AgentRequest, PreviousMessage, MessageRole, ScreenAnnotation, ScreenElement
from prompts import build_system_prompt
from prompts.plan_prompt import PLAN_DIRECTIVE, PLAN_REMINDER
from workspace import build_workspace_context, get_device_details, is_bootstrap_needed, read_bootstrap
from context_manager.action_validator import ActionValidator

# OmniParser toggle
USE_OMNI_PARSER = (
    "--use-omni-parser" in sys.argv
    or os.environ.get("USE_OMNI_PARSER", "").lower() in ("1", "true", "yes")
)

# Prefix used to identify screenshot messages in history
SCREENSHOT_PREFIX = "data:image/"

# Maximum messages before middle-trimming (safety net)
MAX_CHAIN_LENGTH = 300

# Auto-compaction safety net — only fires if model doesn't self-compact.
# Set high: the model should call compact_context before this triggers.
AUTO_COMPACT_THRESHOLD = 300

# Plan auto-injection interval (every N assistant turns)
PLAN_INJECT_INTERVAL = 10


class ContextManager:
    """
    Maintains conversation history per session.

    Typical call order:
    1. add_user_message(session_id, text)           → user types a task
    2. build_request(session_id)                     → send to model
    3. add_assistant_turn(session_id, response_json) → model response
    4. add_screenshot_turn(session_id, base64)       → screenshot from frontend
    5. build_request(session_id)                     → send again
    6. Repeat 3-5
    """

    # Plan reminder injection interval (every N assistant turns, offset from plan inject)
    PLAN_REMINDER_INTERVAL = 15

    def __init__(self):
        self._history: dict[str, list[PreviousMessage]] = {}
        self._step_offset: dict[str, int] = {}
        self._plan_injected: dict[str, bool] = {}
        self.action_validator = ActionValidator()

    def _get(self, session_id: str) -> list[PreviousMessage]:
        """Return existing history or bootstrap a new session with the system prompt."""
        if session_id not in self._history:
            workspace_ctx = build_workspace_context()
            bootstrap_mode = is_bootstrap_needed()
            bootstrap_content = read_bootstrap() if bootstrap_mode else ""
            device_info = get_device_details()
            system_prompt = build_system_prompt(
                workspace_ctx,
                session_id=session_id,
                bootstrap_mode=bootstrap_mode,
                bootstrap_content=bootstrap_content,
                device_details=device_info,
                use_omni_parser=USE_OMNI_PARSER,
            )
            self._history[session_id] = [
                PreviousMessage(role=MessageRole.system, content=system_prompt.strip())
            ]
        return self._history[session_id]

    def add_user_message(self, session_id: str, text: str) -> None:
        """Append a text-only user message.

        On the first real user task (not system feedback like tool results),
        auto-injects the planning directive so the model plans before acting.
        """
        if not text or not text.strip():
            return

        history = self._get(session_id)
        history.append(
            PreviousMessage(role=MessageRole.user, content=text)
        )

        # Inject planning directive on first real user message
        # Skip if: already injected, or message is system feedback (tool results, action results, etc.)
        is_system_feedback = text.startswith("[") and any(
            text.startswith(prefix) for prefix in [
                "[update_plan result]", "[read_plan result]",
                "[compact_context result]", "[shell_exec", "[ACTION REJECTED]",
                "[PLAN CHECKPOINT", "[CONTEXT CONTINUATION]", "[PLANNING REQUIRED]",
                "[PLAN CHECK]",
            ]
        )

        if not self._plan_injected.get(session_id) and not is_system_feedback:
            # Check if there are any assistant turns yet (no = first task)
            has_assistant_turns = any(m.role == MessageRole.assistant for m in history)
            if not has_assistant_turns:
                history.append(
                    PreviousMessage(role=MessageRole.user, content=PLAN_DIRECTIVE)
                )
                self._plan_injected[session_id] = True
                print(f"[plan] Injected planning directive for session {session_id}")

    def add_screenshot_turn(self, session_id: str, base64_screenshot: str) -> None:
        """Append a screenshot as a user message, optionally via OmniParser."""
        if not base64_screenshot.startswith("data:"):
            if base64_screenshot.startswith("/9j"):
                mime = "image/jpeg"
            elif base64_screenshot.startswith("UklGR"):
                mime = "image/webp"
            else:
                mime = "image/png"
            base64_screenshot = f"data:{mime};base64,{base64_screenshot}"

        annotations = None

        if USE_OMNI_PARSER:
            raw_b64 = base64_screenshot.split(",", 1)[1] if "," in base64_screenshot else base64_screenshot
            try:
                from providers.modal.omni_parser.client import parse_screenshot_b64
                result = parse_screenshot_b64(raw_b64, include_annotated=True)

                if result.annotated_image_base64:
                    base64_screenshot = f"data:image/png;base64,{result.annotated_image_base64}"

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
                print(f"[omniparser] {len(elements)} elements detected ({result.latency_ms}ms)")
                for e in elements:
                    tag = e.type.upper()
                    ncx = round(e.center_pixel[0] / img_w, 4)
                    ncy = round(e.center_pixel[1] / img_h, 4)
                    coords = f"center_norm=({ncx},{ncy})"
                    lbl = e.content if e.content else ""
                    click = "  [clickable]" if e.interactable else ""
                    print(f"  [{e.id}] {tag}  label=\"{lbl}\"  {coords}{click}")
            except Exception as e:
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
        """Append the model's full JSON response to the chain."""
        self._get(session_id).append(
            PreviousMessage(role=MessageRole.assistant, content=response_json)
        )

    def add_tool_call_turn(self, session_id: str, tool_calls: list[dict], content: str = "") -> None:
        """Record an assistant message that contains tool calls (no desktop action)."""
        self._get(session_id).append(
            PreviousMessage(
                role=MessageRole.assistant,
                content=content or "",
                tool_calls=tool_calls,
            )
        )

    def add_tool_result_turn(self, session_id: str, tool_call_id: str, tool_name: str, result: str) -> None:
        """Record the result of a tool call."""
        self._get(session_id).append(
            PreviousMessage(
                role=MessageRole.tool,
                content=result,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
            )
        )

    # Placeholder that replaces old screenshots
    SCREENSHOT_PLACEHOLDER = "[A screenshot was taken here and reviewed by you]"

    def _count_assistant_turns(self, session_id: str) -> int:
        """Count assistant turns in current history."""
        return sum(1 for m in self._get(session_id) if m.role == MessageRole.assistant)

    def _should_inject_plan(self, session_id: str) -> bool:
        """Check if it's time to auto-inject plan.md content."""
        turns = self._count_assistant_turns(session_id) + self._step_offset.get(session_id, 0)
        return turns > 0 and turns % PLAN_INJECT_INTERVAL == 0

    def _should_inject_plan_reminder(self, session_id: str) -> bool:
        """Check if it's time for a lightweight plan reminder."""
        turns = self._count_assistant_turns(session_id) + self._step_offset.get(session_id, 0)
        return turns > 0 and turns % self.PLAN_REMINDER_INTERVAL == 0

    def build_request(self, session_id: str) -> AgentRequest:
        """
        Build an AgentRequest from the current history.

        - Only latest screenshot kept as image data
        - Plan auto-injected every PLAN_INJECT_INTERVAL turns
        - Middle-trimmed if chain exceeds MAX_CHAIN_LENGTH
        """
        history = self._get(session_id)

        step_index = (
            self._step_offset.get(session_id, 0)
            + sum(1 for m in history if m.role == MessageRole.assistant)
        )

        # Get original user message
        user_message = ""
        for m in history:
            if m.role == MessageRole.user and not m.content.startswith(SCREENSHOT_PREFIX):
                user_message = m.content
                break

        # Auto-inject plan every N turns
        if self._should_inject_plan(session_id):
            from workspace import read_session_plan
            plan = read_session_plan(session_id)
            if plan:
                plan_msg = (
                    f"[PLAN CHECKPOINT — Step {step_index}]\n"
                    f"Here is your current plan for reference:\n\n{plan}\n\n"
                    f"Continue from the next incomplete step."
                )
                history.append(
                    PreviousMessage(role=MessageRole.user, content=plan_msg)
                )
                print(f"[plan-inject] Auto-injected plan.md at step {step_index}")

        # Lightweight plan reminder (offset from full plan injection)
        elif self._should_inject_plan_reminder(session_id):
            history.append(
                PreviousMessage(role=MessageRole.user, content=PLAN_REMINDER)
            )
            print(f"[plan-remind] Injected plan reminder at step {step_index}")

        # Build trimmed copy: replace all but latest screenshot
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
                if i == last_screenshot_idx and m.annotations and m.annotations.elements:
                    element_text = self._format_annotations(m.annotations)
                    trimmed.append(
                        PreviousMessage(role=MessageRole.user, content=element_text, timestamp=m.timestamp)
                    )

        # Middle-trim safety net
        if len(trimmed) > MAX_CHAIN_LENGTH:
            keep_head = 2
            keep_tail = MAX_CHAIN_LENGTH - keep_head
            trimmed = trimmed[:keep_head] + [
                PreviousMessage(
                    role=MessageRole.user,
                    content=(
                        "[Earlier turns were trimmed. Use read_plan to see your full task plan.]"
                    ),
                )
            ] + trimmed[-keep_tail:]

        return AgentRequest(
            session_id=session_id,
            user_message=user_message,
            base64_screenshot="",
            previous_messages=trimmed,
            step_index=step_index,
        )

    def clear_session(self, session_id: str) -> None:
        """Remove all history for a session."""
        self._history.pop(session_id, None)
        self._step_offset.pop(session_id, None)
        self._plan_injected.pop(session_id, None)
        self.action_validator.clear(session_id)

    @staticmethod
    def _format_annotations(ann: ScreenAnnotation) -> str:
        """Format screen annotations as compact text for the model."""
        w = ann.image_width or 1
        h = ann.image_height or 1
        lines = [f"[SCREEN ELEMENTS] {ann.image_width}x{ann.image_height} — {len(ann.elements)} elements (coords normalized 0-1)"]
        for e in ann.elements:
            x1, y1, x2, y2 = e.bbox_pixel
            cx, cy = e.center_pixel
            nx1, ny1 = round(x1 / w, 4), round(y1 / h, 4)
            nx2, ny2 = round(x2 / w, 4), round(y2 / h, 4)
            ncx, ncy = round(cx / w, 4), round(cy / h, 4)
            lbl = e.content if e.content else ""
            click = "  [clickable]" if e.interactable else ""
            lines.append(f'  [{e.id}] {e.type.upper()}  label="{lbl}"  bbox=({nx1},{ny1},{nx2},{ny2})  center=({ncx},{ncy}){click}')
        return "\n".join(lines)

    SCREEN_ELEMENTS_PREFIX = "[SCREEN ELEMENTS]"

    def get_compact_messages(self, session_id: str) -> list[PreviousMessage]:
        """
        Return pre-filtered messages for the compaction model.
        Strips system prompt, screenshots, element data, and verbose reasoning.
        """
        history = self._get(session_id)
        messages: list[PreviousMessage] = []
        last_was_screenshot_placeholder = False

        for m in history:
            if m.role == MessageRole.system:
                continue
            elif m.role == MessageRole.user and m.content.startswith(SCREENSHOT_PREFIX):
                if not last_was_screenshot_placeholder:
                    messages.append(
                        PreviousMessage(role=m.role, content=self.SCREENSHOT_PLACEHOLDER, timestamp=m.timestamp)
                    )
                    last_was_screenshot_placeholder = True
                continue
            elif m.role == MessageRole.user and m.content.startswith(self.SCREEN_ELEMENTS_PREFIX):
                continue
            elif m.role == MessageRole.assistant:
                last_was_screenshot_placeholder = False
                if m.tool_calls:
                    # Summarize tool calls with arguments for richer compaction
                    tc_parts = []
                    for tc in m.tool_calls:
                        fn = tc.get("function", {})
                        name = fn.get("name", "?")
                        args = fn.get("arguments", "")
                        if isinstance(args, str) and len(args) > 200:
                            args = args[:200] + "..."
                        tc_parts.append(f"{name}({args})" if args else name)
                    messages.append(
                        PreviousMessage(role=m.role, content=f"TOOL_CALLS: {'; '.join(tc_parts)}", timestamp=m.timestamp)
                    )
                else:
                    trimmed = self._trim_assistant_for_compact(m.content)
                    messages.append(
                        PreviousMessage(role=m.role, content=trimmed, timestamp=m.timestamp)
                    )
            elif m.role == MessageRole.tool:
                # Compact tool results — keep enough detail for meaningful summaries
                result_preview = m.content[:1000] + "..." if len(m.content) > 1000 else m.content
                messages.append(
                    PreviousMessage(role=MessageRole.user, content=f"TOOL_RESULT: {result_preview}", timestamp=m.timestamp)
                )
            else:
                last_was_screenshot_placeholder = False
                messages.append(m)

        return messages

    @staticmethod
    def _trim_assistant_for_compact(content: str) -> str:
        """Pre-compress an assistant message for compaction."""
        try:
            data = json.loads(content)
            parts = []
            action = data.get("action", {})
            action_type = action.get("type", "unknown")
            parts.append(f"ACTION: {action_type}")

            if action_type == "shell_exec" and "command" in action:
                parts.append(f"CMD: {action['command']}")
            elif action_type == "type_text" and "text" in action:
                parts.append(f"TEXT: {action['text']}")
            elif action_type == "key_press":
                key = action.get("key", "")
                mods = action.get("modifiers", [])
                combo = "+".join(mods + [key]) if mods else key
                parts.append(f"KEY: {combo}")
            elif action_type == "mouse_move" and "coordinates" in action:
                c = action["coordinates"]
                parts.append(f"TO: ({c.get('x', 0):.3f}, {c.get('y', 0):.3f})")

            if data.get("done"):
                parts.append("DONE=true")
            if data.get("final_message"):
                parts.append(f"MSG: {data['final_message']}")

            reasoning = data.get("reasoning", "")
            if reasoning and len(reasoning) > 300:
                reasoning = reasoning[:300] + "..."
            if reasoning:
                parts.append(f"WHY: {reasoning}")

            return " | ".join(parts)
        except (json.JSONDecodeError, TypeError, AttributeError):
            if len(content) > 500:
                return content[:500] + "..."
            return content

    def reset_with_summary(self, session_id: str, summary: str) -> None:
        """
        Replace the context chain with: system prompt + compacted summary.
        The summary is injected as a continuation directive.
        """
        from workspace import build_workspace_context, get_device_details
        from prompts import build_system_prompt
        from prompts.compact_prompt import CONTINUATION_DIRECTIVE

        workspace_ctx = build_workspace_context()
        device_info = get_device_details()
        system_prompt = build_system_prompt(
            workspace_ctx,
            session_id=session_id,
            bootstrap_mode=False,
            bootstrap_content="",
            device_details=device_info,
            use_omni_parser=USE_OMNI_PARSER,
        )

        # Preserve step count across compactions
        old_history = self._history.get(session_id, [])
        old_steps = sum(1 for m in old_history if m.role == MessageRole.assistant)
        self._step_offset[session_id] = self._step_offset.get(session_id, 0) + old_steps

        total_steps = self._step_offset[session_id]
        user_content = (
            CONTINUATION_DIRECTIVE
            .replace("{session_id}", session_id)
            .replace("{summary}", summary)
            .replace("{step_count}", str(total_steps))
        )

        self._history[session_id] = [
            PreviousMessage(role=MessageRole.system, content=system_prompt.strip()),
            PreviousMessage(role=MessageRole.user, content=user_content),
        ]

    def needs_compaction(self, session_id: str) -> bool:
        """
        Safety-net compaction check. Only fires at a high threshold —
        the model should call compact_context before this triggers.
        """
        return len(self._get(session_id)) > AUTO_COMPACT_THRESHOLD

    def estimate_token_count(self, session_id: str) -> int:
        """Rough token estimate for the current context chain."""
        total = 0
        for m in self._get(session_id):
            if m.content.startswith(SCREENSHOT_PREFIX):
                total += 1000
            else:
                total += len(m.content) // 4
        return total

    def chain_length(self, session_id: str) -> int:
        """Return the number of messages in a session's context chain."""
        return len(self._get(session_id))

    def get_raw_history(self, session_id: str) -> list[PreviousMessage]:
        """Return the full, untruncated conversation history for logging."""
        return list(self._get(session_id))
