import json
import platform
from utilities.connection import ConnectionManager
from context_manager import ContextManager
from workspace import write_session_file, read_session_file, list_session_files
from .handlers import handle_update_plan, handle_read_plan, handle_use_skill, handle_read_memory
from .compaction import handle_compact_context


async def execute_agent_tool(
    session_id: str,
    name: str,
    args: dict,
    manager: ConnectionManager,
    context_manager: ContextManager,
    compact_model,
) -> str:
    """Execute an agent tool by name and return the result string."""
    if name == "update_plan":
        plan_content = args.get("content", "")
        return handle_update_plan(session_id, plan_content)

    elif name == "read_plan":
        return handle_read_plan(session_id)

    elif name == "use_skill":
        skill_name = args.get("skill_name", "")
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "skill_used",
            "skill_name": skill_name,
        })
        return handle_use_skill(skill_name)

    elif name == "read_memory":
        return handle_read_memory(target=args.get("target", "long_term"), date=args.get("date", ""))

    elif name == "write_session_file":
        filename = args.get("filename", "")
        existing = read_session_file(session_id, filename) is not None
        sanitized = filename.strip().replace("/", "").replace("\\", "")
        if not sanitized.endswith(".md"):
            sanitized += ".md"
        file_path = write_session_file(session_id, sanitized, args.get("content", ""))
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "file_written",
            "filename": sanitized,
            "filepath": str(file_path),
            "action": "edited" if existing else "created",
        })
        return f"File '{sanitized}' written successfully."

    elif name == "read_session_file":
        result = read_session_file(session_id, args.get("filename", ""))
        return result if result is not None else f"File '{args.get('filename')}' not found."

    elif name == "list_session_files":
        files = list_session_files(session_id)
        if not files:
            return "No files in current session. (plan.md and notes.md are considered system files)"
        return "Session files: " + ", ".join(files)

    elif name == "compact_context":
        return await handle_compact_context(
            session_id, context_manager, compact_model, manager,
            focus=args.get("focus", ""),
        )

    else:
        args_str = json.dumps(args, ensure_ascii=False)
        return (
            f"ERROR: Unknown function tool '{name}' called with arguments: {args_str}\n\n"
            f"If '{name}' is a desktop action (like shell_exec or mouse_move), "
            f"you MUST return it as a plain JSON text response "
            f"(e.g. {{\"action\": {{\"type\": \"{name}\", ...}}}}), "
            f"NOT as a function tool call. Please try again using the proper format."
        )
