import json
import platform
from utilities.connection import ConnectionManager
from context_manager import ContextManager
from workspace import write_session_file, read_session_file, list_session_files
from .handlers import handle_update_plan, handle_read_plan, handle_use_skill, handle_read_memory, handle_create_skill
from .compaction import handle_compact_context
from .shell import handle_shell_exec
from .raise_app import handle_raise_app
from .coworker_tools import (
    COWORKER_DRIVER_TOOL_NAMES,
    call_driver_tool,
    format_driver_result_for_model,
)
from .hermes import (
    handle_invoke_hermes,
    handle_check_hermes,
    handle_cancel_hermes,
    handle_list_hermes_jobs,
)


def _maybe_update_coworker_target(
    context_manager: ContextManager,
    session_id: str,
    tool_name: str,
    args: dict,
    parsed_result: object,
) -> None:
    """
    Track the active (pid, window_id) so per-turn AX perception (PLAN §4.6)
    has something to fetch. Best-effort — never raises.
    """
    try:
        # Explicit (pid, window_id) on any cua_* tool call wins.
        pid_arg = args.get("pid")
        wid_arg = args.get("window_id")
        if pid_arg is not None and wid_arg is not None:
            context_manager.set_coworker_target(session_id, pid_arg, wid_arg)
            return

        # cua_launch_app returns a freshly created window. Result shape from
        # the driver is implementation-defined; probe the common keys.
        if tool_name == "cua_launch_app" and isinstance(parsed_result, dict):
            pid = parsed_result.get("pid")
            wins = parsed_result.get("windows") or []
            wid = None
            if isinstance(wins, list) and wins:
                first = wins[0] if isinstance(wins[0], dict) else None
                if first:
                    wid = first.get("window_id") or first.get("id")
            wid = wid or parsed_result.get("front_window_id") or parsed_result.get("window_id")
            if pid is not None and wid is not None:
                context_manager.set_coworker_target(session_id, pid, wid)
    except Exception:
        # Tracking is opportunistic; never let it break tool dispatch.
        pass


async def execute_agent_tool(
    session_id: str,
    name: str,
    args: dict,
    manager: ConnectionManager,
    context_manager: ContextManager,
    compact_model,
    agent_mode: str = "remote",
) -> str:
    """Execute an agent tool by name and return the result string.

    ``agent_mode`` is passed through to mode-aware handlers (currently
    only ``raise_app``, which uses the driver's hidden ``launch_app``
    in coworker mode — see PLAN §5.1).
    """
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

    elif name == "shell_exec":
        command = args.get("command", "")
        result = handle_shell_exec(command)
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "shell_exec",
            "command": command,
            "result": result[:500],
        })
        return result

    elif name == "raise_app":
        app_name = args.get("app_name", "")
        result = handle_raise_app(app_name, agent_mode=agent_mode)
        # In coworker mode the driver returns structured JSON — mine it for
        # (pid, window_id) so the next perception turn has a target.
        if agent_mode == "coworker" and not result.startswith("ERROR"):
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                parsed = None
            _maybe_update_coworker_target(
                context_manager, session_id, "cua_launch_app", args, parsed
            )
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "raise_app",
            "app_name": app_name,
            "result": result[:200],
        })
        return result

    # ── Coworker-mode driver tools (PLAN §4.5) ────────────────────────────
    # Forward every cua_* call to the local emu-cua-driver Swift CLI. Also
    # accept the friendlier alias ``list_running_apps`` which maps onto the
    # driver's ``list_apps`` tool.
    elif name == "list_running_apps" or name in COWORKER_DRIVER_TOOL_NAMES:
        driver_tool = "list_apps" if name == "list_running_apps" else name[len("cua_"):]
        result = call_driver_tool(driver_tool, args)
        _maybe_update_coworker_target(
            context_manager, session_id, name, args, result.get("json")
        )
        await manager.send(session_id, {
            "type": "tool_event",
            "event": "cua_driver_call",
            "tool": name,
            "ok": bool(result.get("ok")),
            "args": json.dumps(args, ensure_ascii=False)[:300],
        })
        return format_driver_result_for_model(name, result)

    else:
        args_str = json.dumps(args, ensure_ascii=False)

        # Build a concrete example JSON using the args the model sent, so it
        # can literally copy-paste the corrected shape.
        try:
            example_action = {"type": name, **(args if isinstance(args, dict) else {})}
        except Exception:
            example_action = {"type": name}
        example_json = json.dumps({"action": example_action}, ensure_ascii=False)

        return (
            f"ERROR: '{name}' is NOT a function tool — it is a DESKTOP ACTION.\n"
            f"You called it as a function tool with arguments: {args_str}\n"
            f"Nothing was executed.\n\n"
            f"FIX: Stop calling '{name}' as a function tool. Instead, return a plain "
            f"JSON text response (no function/tool call) with this exact shape:\n\n"
            f"  {example_json}\n\n"
            f"Desktop actions that MUST be returned as JSON text (never as tool calls):\n"
            f"  shell_exec, screenshot, mouse_move, navigate_and_click, "
            f"navigate_and_right_click, navigate_and_triple_click, left_click, "
            f"right_click, double_click, triple_click, drag, scroll, type_text, "
            f"key_press, wait, done.\n\n"
            f"Function tools are ONLY: update_plan, read_plan, write_session_file, "
            f"read_session_file, list_session_files, read_memory, use_skill, "
            f"create_skill, compact_context, invoke_hermes, check_hermes, "
            f"cancel_hermes, list_hermes_jobs, raise_app, list_running_apps, "
            f"and (coworker mode only) cua_* driver tools."
        )

