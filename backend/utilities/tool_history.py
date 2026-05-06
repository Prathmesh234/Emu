"""
Repair tool-call history before provider requests.

Why this exists:
OpenAI/Azure-compatible providers require every assistant message with
`tool_calls` to be followed by one tool-role output for each function-call id.
If a user stops a coworker step after a tool returns but before the backend
records its output, the next provider request fails with:
`No tool output found for function call ...`.

Compaction/trimming can cause the inverse problem: a preserved tool-role output
can lose the assistant tool call it belonged to, causing:
`No tool call found for function call output ...`.
"""

from __future__ import annotations

from models import MessageRole, PreviousMessage


def repair_orphan_tool_calls(
    history: list[PreviousMessage],
) -> tuple[list[PreviousMessage], int, int]:
    """Return provider-safe history plus counts of inserted and converted items."""
    if not history:
        return history, 0, 0

    repaired: list[PreviousMessage] = []
    inserted = 0
    converted = 0
    i = 0
    while i < len(history):
        msg = history[i]
        if msg.role == MessageRole.tool:
            repaired.append(_tool_result_as_user(msg))
            converted += 1
            i += 1
            continue

        repaired.append(msg)
        if msg.role != MessageRole.assistant or not msg.tool_calls:
            i += 1
            continue

        pending: dict[str, str] = {}
        call_order: list[str] = []
        for tc in msg.tool_calls:
            if not isinstance(tc, dict):
                continue
            tc_id = tc.get("id")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = fn.get("name") or tc.get("name") or "unknown_tool"
            if tc_id:
                tc_id = str(tc_id)
                pending[tc_id] = str(name)
                call_order.append(tc_id)

        i += 1
        grouped_tools: list[PreviousMessage] = []
        while i < len(history) and history[i].role == MessageRole.tool:
            grouped_tools.append(history[i])
            i += 1

        grouped_by_id: dict[str, PreviousMessage] = {}
        extra_tools: list[PreviousMessage] = []
        for tool_msg in grouped_tools:
            tc_id = str(tool_msg.tool_call_id or "")
            if tc_id in pending and tc_id not in grouped_by_id:
                grouped_by_id[tc_id] = tool_msg
            else:
                extra_tools.append(tool_msg)

        for tc_id in call_order:
            if tc_id in grouped_by_id:
                repaired.append(grouped_by_id[tc_id])
                pending.pop(tc_id, None)
            else:
                repaired.append(_cancelled_tool_result(tc_id, pending[tc_id]))
                inserted += 1

        for tool_msg in extra_tools:
            repaired.append(_tool_result_as_user(tool_msg))
            converted += 1

    return repaired, inserted, converted


def _cancelled_tool_result(tool_call_id: str, tool_name: str) -> PreviousMessage:
    return PreviousMessage(
        role=MessageRole.tool,
        content=(
            "[TOOL CANCELLED] No tool output was recorded for this "
            "function call, likely because the user stopped the "
            "previous step before the tool result was appended."
        ),
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )


def _tool_result_as_user(msg: PreviousMessage) -> PreviousMessage:
    tool_name = msg.tool_name or "unknown_tool"
    call_id = msg.tool_call_id or "unknown_call"
    return PreviousMessage(
        role=MessageRole.user,
        content=(
            f"[ORPHAN TOOL RESULT — converted for provider compatibility]\n"
            f"tool={tool_name} call_id={call_id}\n{msg.content}"
        ),
        timestamp=msg.timestamp,
    )
