"""
Repair tool-call history before provider requests.

Why this exists:
OpenAI/Azure-compatible providers require every assistant message with
`tool_calls` to be followed by one tool-role output for each function-call id.
If a user stops a coworker step after a tool returns but before the backend
records its output, the next provider request fails with:
`No tool output found for function call ...`.
"""

from __future__ import annotations

from models import MessageRole, PreviousMessage


def repair_orphan_tool_calls(
    history: list[PreviousMessage],
) -> tuple[list[PreviousMessage], int]:
    """Insert synthetic cancelled tool outputs for orphan assistant tool calls."""
    if not history:
        return history, 0

    repaired: list[PreviousMessage] = []
    inserted = 0
    i = 0
    while i < len(history):
        msg = history[i]
        repaired.append(msg)
        if msg.role != MessageRole.assistant or not msg.tool_calls:
            i += 1
            continue

        pending: dict[str, str] = {}
        for tc in msg.tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = tc.get("id")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = fn.get("name") or tc.get("name") or "unknown_tool"
            if tc_id:
                pending[str(tc_id)] = str(name)

        i += 1
        while i < len(history) and history[i].role == MessageRole.tool:
            tool_msg = history[i]
            if tool_msg.tool_call_id:
                pending.pop(tool_msg.tool_call_id, None)
            repaired.append(tool_msg)
            i += 1

        for tc_id, name in pending.items():
            repaired.append(
                PreviousMessage(
                    role=MessageRole.tool,
                    content=(
                        "[TOOL CANCELLED] No tool output was recorded for this "
                        "function call, likely because the user stopped the "
                        "previous step before the tool result was appended."
                    ),
                    tool_call_id=tc_id,
                    tool_name=name,
                )
            )
            inserted += 1

    return repaired, inserted
