import json
import platform
from utilities.connection import ConnectionManager
from context_manager import ContextManager
from workspace import write_session_file, read_session_file, list_session_files
from .handlers import handle_update_plan, handle_read_plan, handle_use_skill, handle_read_memory, handle_create_skill
from .compaction import handle_compact_context
from .hermes import (
    handle_invoke_hermes,
    handle_check_hermes,
    handle_cancel_hermes,
    handle_list_hermes_jobs,
)


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

    elif name == "create_skill":
        result = handle_create_skill(
            name=args.get("name", ""),
            description=args.get("description", ""),
            instructions=args.get("instructions", ""),
            files=args.get("files") or [],
            overwrite=bool(args.get("overwrite", False)),
        )
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "skill_created",
            "skill_name": args.get("name", ""),
        })
        return result

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

    elif name == "invoke_hermes":
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "hermes_invoked",
            "goal": args.get("goal", ""),
        })
        return await handle_invoke_hermes(
            session_id=session_id,
            goal=args.get("goal", ""),
            context=args.get("context", ""),
            file_paths=args.get("file_paths") or [],
            output_target=args.get("output_target", ""),
            constraints=args.get("constraints", ""),
            manager=manager,
        )

    elif name == "check_hermes":
        # No WS event — the model polls this repeatedly and we don't want a
        # trace card per poll. The frontend gets `hermes_done` from the job
        # itself when work actually completes.
        return await handle_check_hermes(
            job_id=args.get("job_id", ""),
            wait_s=float(args.get("wait_s", 0) or 0),
        )

    elif name == "cancel_hermes":
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "hermes_done",   # treat cancel like a completion for the UI
            "job_id": args.get("job_id", ""),
            "status": "cancelled",
        })
        return await handle_cancel_hermes(job_id=args.get("job_id", ""))

    elif name == "list_hermes_jobs":
        return handle_list_hermes_jobs(session_id)

    else:
        args_str = json.dumps(args, ensure_ascii=False)
        return (
            f"ERROR: Unknown function tool '{name}' called with arguments: {args_str}\n\n"
            f"If '{name}' is a desktop action (like shell_exec or mouse_move), "
            f"you MUST return it as a plain JSON text response "
            f"(e.g. {{\"action\": {{\"type\": \"{name}\", ...}}}}), "
            f"NOT as a function tool call. Please try again using the proper format."
        )
