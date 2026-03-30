"""
backend/prompts/system_prompt.py

The system prompt for the desktop automation agent.
Slim, modular — identity + context only. Tool definitions, personality,
and operational rules live in TOOLS.md, SOUL.md, and AGENTS.md respectively
and are injected via the workspace context system.

The prompt is built dynamically:
  - Current date/time and session ID injected every request
  - Device details from manifest.json
  - Vision mode block (OmniParser vs direct) conditionally included
  - Workspace files appended by workspace/reader.py
"""

from datetime import datetime


def build_system_prompt(
    workspace_context: str = "",
    session_id: str = "",
    bootstrap_mode: bool = False,
    bootstrap_content: str = "",
    device_details: dict | None = None,
    use_omni_parser: bool = False,
) -> str:
    """
    Build the full system prompt.

    If bootstrap_mode is True, delegates to build_bootstrap_prompt() instead.
    """
    if bootstrap_mode:
        from .bootstrap_prompt import build_bootstrap_prompt
        return build_bootstrap_prompt(
            session_id=session_id,
            bootstrap_content=bootstrap_content,
            device_details=device_details,
        )

    today = datetime.now().strftime("%A, %B %d, %Y")
    now = datetime.now().strftime("%H:%M")

    # Build device info string
    device_info = ""
    if device_details:
        os_name = device_details.get("os_name", "macOS")
        arch = device_details.get("arch", "")
        sw = device_details.get("screen_width")
        sh = device_details.get("screen_height")
        sf = device_details.get("scale_factor")
        parts = [f"System: {os_name}"]
        if arch:
            parts.append(f"({arch})")
        if sw and sh:
            parts.append(f"| Display: {sw}×{sh}")
            if sf and sf != 1:
                parts.append(f"@{sf}x")
        device_info = " ".join(parts)

    # Select vision block
    vision_block = _OMNIPARSER_BLOCK if use_omni_parser else _DIRECT_SCREENSHOT_BLOCK

    prompt = _BASE_PROMPT.format(
        date=today,
        time=now,
        session_id=session_id or "unknown",
        device_info=device_info or "System: macOS",
        vision_block=vision_block,
    )

    if workspace_context:
        prompt += "\n\n" + workspace_context

    return prompt


SYSTEM_PROMPT = None


def _lazy_system_prompt():
    return build_system_prompt("", device_details=None, use_omni_parser=False)


class _LazyPrompt:
    def __init__(self):
        self._value = None

    def __str__(self):
        if self._value is None:
            self._value = _lazy_system_prompt()
        return self._value

    def strip(self):
        return str(self).strip()


SYSTEM_PROMPT = _LazyPrompt()


# ═══════════════════════════════════════════════════════════════════════════
# BASE PROMPT — lean identity + context anchors
# ═══════════════════════════════════════════════════════════════════════════

_BASE_PROMPT = """\
<identity>
You are Emu, a desktop automation agent on macOS. You observe the screen
via screenshots and execute one action per turn to complete the user's task.

Today: {date} | Time: {time} | Session: {session_id}
{device_info}
Coordinates: normalized [0,1] range — (0,0) top-left, (1,1) bottom-right.
</identity>

<context_rules>
NO TASK YET → done + ask what they need.
TASK DONE → done immediately with a summary of what you did.
[CONTEXT CONTINUATION] → Compacted state snapshot. Read it. Continue from first [TODO] step.

Session dir: .emu/sessions/{session_id}/
Plan file: .emu/sessions/{session_id}/plan.md

Your plan.md is your anchor. When confused, use read_plan to re-orient.
</context_rules>

<action_model>
Mouse navigation and clicking are SEPARATE turns:
  MOUSE_MOVE → moves cursor (only action with coordinates)
  LEFT_CLICK / RIGHT_CLICK / DOUBLE_CLICK → fire at current cursor position
  SCROLL → scrolls at current cursor position
  DRAG → self-contained: start to end in one action

To click something: Turn 1: mouse_move → Turn 2: left_click
To scroll: Turn 1: mouse_move → Turn 2: scroll
To drag: Turn 1: drag (handles start and end)

TYPE_TEXT and KEY_PRESS act on the focused element. No coordinates needed.
</action_model>

{vision_block}
"""


# ═══════════════════════════════════════════════════════════════════════════
# VISION BLOCKS — conditionally injected
# ═══════════════════════════════════════════════════════════════════════════

_OMNIPARSER_BLOCK = """\
<omniparser>
Each screenshot comes with:
  1. ANNOTATED IMAGE — boxes with ID numbers on detected elements
  2. [SCREEN ELEMENTS] text block — structured data for each element

To click a target:
  1. Find the element in the annotated image, note its ID (e.g. [42])
  2. Look up that ID in [SCREEN ELEMENTS]
  3. Use the EXACT center=(x,y) normalized coordinates from that entry

All coordinates in [SCREEN ELEMENTS] are normalized [0,1] ratios.
Always use the exact center values — never estimate.
If no matching element exists, scroll to reveal it or try keyboard.
</omniparser>"""

_DIRECT_SCREENSHOT_BLOCK = """\
<vision>
You receive raw screenshots without annotations. Estimate target coordinates yourself.

Coordinates are normalized [0,1] ratios:
  x=0.0 left | x=0.5 center | x=1.0 right
  y=0.0 top  | y=0.5 center | y=1.0 bottom

Reference points: menu bar y≈0.01, dock y≈0.97, window title y≈0.04.
Aim for the center of elements. If clicks miss, adjust based on where
the cursor appears in the next screenshot, or switch to keyboard/shell.
</vision>"""