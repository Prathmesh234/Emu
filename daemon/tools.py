"""
tools.py — Tool definitions and dispatcher exposed to the LLM (Layer 1 security).

Only four tools are exposed: list_dir, read_file, write_file, finish.
No shell, exec, or network tool exists. The dispatcher enforces path policy
(L2) and per-tick write budget on every call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import policy

MAX_PER_FILE_BYTES = 512 * 1024       # 512 KB per single write
MAX_TOTAL_BYTES_TICK = 2 * 1024 * 1024  # 2 MB total across all writes in one tick
MAX_READ_BYTES = 512 * 1024           # 512 KB per single read


TOOLS: list[dict] = [
    {
        "name": "list_dir",
        "description": (
            "List the entries inside a directory under .emu/. "
            "You should RARELY need this — `sessions/index.json` already tells you "
            "every session id and date, so do NOT call list_dir on `sessions`. "
            "Acceptable uses: `list_dir(\"workspace/memory\")` to see which "
            "daily-log files exist if you are unsure. "
            "Returns a JSON array like "
            "[{\"name\": \"2026-04-19.md\", \"type\": \"file\"}, ...]."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Directory path relative to .emu/. "
                        "Examples: 'workspace/memory', 'sessions/<session_id>/logs'. "
                        "Do NOT pass 'sessions' — use sessions/index.json instead."
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the UTF-8 text content of a file under .emu/. "
            "Returns the file content, or '[error] file does not exist: ...' "
            "if it isn't there (which is a normal, expected outcome — handle "
            "it by skipping that file, not by retrying).\n\n"
            "Common paths you will read:\n"
            "  - 'sessions/index.json'              ← MUST be your FIRST call every tick\n"
            "  - 'workspace/MEMORY.md'\n"
            "  - 'workspace/AGENTS.md'\n"
            "  - 'workspace/memory/2026-04-20.md'   (daily log for a given date)\n"
            "  - 'sessions/<session_id>/plan.md'\n"
            "  - 'sessions/<session_id>/notes.md'\n"
            "  - 'sessions/<session_id>/logs/conversation.json'  (often LARGE — chunk it)\n\n"
            "For large files use start_line and max_lines. The reply will include a "
            "header like '[lines 0-399 of 832 total]' so you know whether to read "
            "the next chunk with start_line=400."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path relative to .emu/. "
                        "Examples: 'sessions/index.json', "
                        "'workspace/memory/2026-04-20.md', "
                        "'sessions/abc-123/logs/conversation.json'."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": (
                        "0-indexed line to start reading from (default 0). "
                        "Use this to chunk through large files like conversation.json."
                    ),
                },
                "max_lines": {
                    "type": "integer",
                    "description": (
                        "Maximum number of lines to return (default: all). "
                        "Recommend 400 for conversation.json, then advance "
                        "start_line by 400 each call until you reach the total."
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write UTF-8 text content to a file under .emu/. "
            "**This FULLY OVERWRITES the file.** If you are editing an existing "
            "file (e.g. appending one new session block to a daily log), you MUST "
            "first `read_file` the current content, build the new full content in "
            "your head, then pass the COMPLETE new content here. Never pass only "
            "the new bits.\n\n"
            "Allowed write targets (everything else is rejected):\n"
            "  - 'workspace/AGENTS.md'\n"
            "  - 'workspace/MEMORY.md'\n"
            "  - 'workspace/USER.md'\n"
            "  - 'workspace/IDENTITY.md'\n"
            "  - 'workspace/memory/YYYY-MM-DD.md'   (filename must match exactly: "
            "zero-padded month + day, .md extension)\n\n"
            "Forbidden: 'workspace/SOUL.md', anything outside the list above. "
            "Returns 'ok' on success or '[policy_error] ...' on rejection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File path relative to .emu/ (must be in the allowlist). "
                        "Daily-log example: 'workspace/memory/2026-04-20.md'. "
                        "Do NOT use today's date for a session whose date in "
                        "sessions/index.json is older — use that session's date."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Full UTF-8 content to write. Replaces the entire file. "
                        "If editing, this must include the prior content you "
                        "want to keep."
                    ),
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Signal that the curation pass is complete and end the tick. "
            "Call this exactly once, after all `write_file` calls are done "
            "(or immediately if nothing needed updating). "
            "Provide a one-paragraph summary of what changed (or 'No changes — "
            "all sessions already captured.' if you wrote nothing)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "One-paragraph summary of changes made this tick. "
                        "Examples: 'Captured session abc-123 into "
                        "workspace/memory/2026-04-20.md; pruned 2 stale rules "
                        "from AGENTS.md.' or 'No changes — all 7 sessions in "
                        "the index were already captured.'"
                    ),
                },
            },
            "required": ["summary"],
        },
    },
]


@dataclass
class DispatchState:
    """Mutable state carried across all tool calls in one tick."""
    bytes_written: int = 0
    written_paths: list[Path] = field(default_factory=list)
    policy_violations: int = 0
    finished: bool = False
    finish_summary: str = ""


def dispatch(name: str, args: dict, state: DispatchState) -> str:
    """
    Dispatch a tool call from the LLM. Returns a string result for the model.
    All I/O is validated through policy.py before touching disk.
    """
    try:
        if name == "list_dir":
            return _list_dir(args, state)
        elif name == "read_file":
            return _read_file(args, state)
        elif name == "write_file":
            return _write_file(args, state)
        elif name == "finish":
            return _finish(args, state)
        else:
            state.policy_violations += 1
            return f"[error] unknown tool: {name!r}"
    except policy.PolicyError as exc:
        state.policy_violations += 1
        return f"[policy_error] {exc}"
    except Exception as exc:
        return f"[error] {type(exc).__name__}: {exc}"


# ── Tool implementations ──────────────────────────────────────────────────────

def _list_dir(args: dict, state: DispatchState) -> str:
    raw_path = args.get("path", "")
    resolved = policy.check_read(raw_path)

    if not resolved.exists():
        return f"[error] path does not exist: {raw_path!r}"
    if not resolved.is_dir():
        return f"[error] path is not a directory: {raw_path!r}"

    entries = [
        {"name": e.name, "type": "dir" if e.is_dir() else "file"}
        for e in resolved.iterdir()
        if not e.name.startswith(".")  # hide dotfiles
    ]
    entries.sort(key=lambda d: d["name"])
    return json.dumps(entries)


def _read_file(args: dict, state: DispatchState) -> str:
    raw_path = args.get("path", "")
    resolved = policy.check_read(raw_path)

    if not resolved.exists():
        return f"[error] file does not exist: {raw_path!r}"
    if not resolved.is_file():
        return f"[error] path is not a file: {raw_path!r}"

    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"[error] file is not valid UTF-8: {raw_path!r}"

    start_line = int(args.get("start_line") or 0)
    max_lines = args.get("max_lines")

    if start_line or max_lines is not None:
        lines = content.splitlines(keepends=True)
        total = len(lines)
        end = start_line + int(max_lines) if max_lines is not None else total
        chunk = "".join(lines[start_line:end])
        if len(chunk.encode("utf-8")) > MAX_READ_BYTES:
            return (
                f"[error] chunk too large. Reduce max_lines "
                f"(requested lines {start_line}-{end} of {total})."
            )
        return f"[lines {start_line}-{min(end, total) - 1} of {total} total]\n{chunk}"

    # Full file — guard against oversized reads
    if len(content.encode("utf-8")) > MAX_READ_BYTES:
        lines_count = content.count("\n") + 1
        return (
            f"[error] file too large to read in full ({resolved.stat().st_size} bytes). "
            f"File has ~{lines_count} lines. Use start_line and max_lines to read in chunks."
        )

    return content


def _write_file(args: dict, state: DispatchState) -> str:
    raw_path = args.get("path", "")
    content = args.get("content", "")

    if not isinstance(content, str):
        state.policy_violations += 1
        return "[policy_error] content must be a string"

    # L2 path check
    resolved = policy.check_write(raw_path)

    # Size caps
    content_bytes = content.encode("utf-8")
    if len(content_bytes) > MAX_PER_FILE_BYTES:
        state.policy_violations += 1
        return (
            f"[policy_error] content too large: {len(content_bytes)} bytes "
            f"exceeds per-file limit of {MAX_PER_FILE_BYTES}. Trim the content."
        )
    if state.bytes_written + len(content_bytes) > MAX_TOTAL_BYTES_TICK:
        state.policy_violations += 1
        return (
            f"[policy_error] tick write budget exceeded: "
            f"{state.bytes_written + len(content_bytes)} bytes total would exceed "
            f"limit of {MAX_TOTAL_BYTES_TICK}."
        )

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")

    state.bytes_written += len(content_bytes)
    state.written_paths.append(resolved)
    return "ok"


def _finish(args: dict, state: DispatchState) -> str:
    summary = args.get("summary", "")
    state.finished = True
    state.finish_summary = summary
    return "done"
