from utilities.connection import ConnectionManager
from context_manager import ContextManager


async def handle_compact_context(
    session_id: str,
    context_manager: ContextManager,
    compact_model,
    manager: ConnectionManager,
    focus: str = "",
) -> str:
    """Handle the model's compact_context tool call."""
    chain_len = context_manager.chain_length(session_id)
    if chain_len <= 4:
        return "Context is already short — no compaction needed."

    await manager.send(session_id, {
        "type": "status",
        "message": "Compacting context as requested...",
    })

    try:
        compact_messages = context_manager.get_compact_messages(session_id)
        summary = compact_model(compact_messages)
        old_len = chain_len
        context_manager.reset_with_summary(session_id, summary)
        new_len = context_manager.chain_length(session_id)
        msg = f"Context compacted: {old_len} → {new_len} messages."
        if focus:
            msg += f" Focused on: {focus}"
        print(f"[compact] Model-initiated. {old_len} → {new_len} messages")
        await manager.send(session_id, {"type": "status", "message": msg})
        return msg
    except Exception as e:
        print(f"[compact] Failed: {e}")
        return f"Compaction failed: {e}. Continue without it."


async def auto_compact(
    session_id: str,
    context_manager: ContextManager,
    compact_model,
    manager: ConnectionManager,
) -> None:
    """Safety-net auto-compaction."""
    print(f"[auto-compact] Running...")
    await manager.send(session_id, {"type": "status", "message": "Auto-compacting context..."})
    try:
        compact_messages = context_manager.get_compact_messages(session_id)
        summary = compact_model(compact_messages)
        old_len = context_manager.chain_length(session_id)
        context_manager.reset_with_summary(session_id, summary)
        new_len = context_manager.chain_length(session_id)
        print(f"[auto-compact] Done. {old_len} → {new_len} messages")
        await manager.send(session_id, {"type": "status", "message": f"Compacted: {old_len} → {new_len}"})
    except Exception as e:
        print(f"[auto-compact] Failed (non-fatal): {e}")
