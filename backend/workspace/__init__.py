"""
backend/workspace/__init__.py

Public API for the workspace reader module.
"""

from .reader import (
    build_workspace_context,
    ensure_session_dir,
    get_device_details,
    get_sessions_dir,
    get_workspace_dir,
    is_bootstrap_needed,
    read_bootstrap,
    read_daily_memory,
    read_firmware,
    read_memory,
    read_recent_daily_memories,
    read_session_plan,
    write_session_plan,
    append_session_notes,
    write_session_file,
    read_session_file,
    list_session_files,
)

__all__ = [
    "build_workspace_context",
    "ensure_session_dir",
    "get_device_details",
    "get_sessions_dir",
    "get_workspace_dir",
    "is_bootstrap_needed",
    "read_bootstrap",
    "read_daily_memory",
    "read_firmware",
    "read_memory",
    "read_recent_daily_memories",
    "read_session_plan",
    "write_session_plan",
    "append_session_notes",
    "write_session_file",
    "read_session_file",
    "list_session_files",
]
