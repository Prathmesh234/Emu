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
            "List the files and subdirectories inside a directory under .emu/. "
            "Pass a path relative to .emu/ (e.g. 'sessions' or 'workspace/memory'). "
            "Returns a JSON array of entry names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to .emu/",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the UTF-8 text content of a file under .emu/. "
            "Pass a path relative to .emu/ (e.g. 'workspace/MEMORY.md'). "
            "For large files, use start_line and max_lines to read in chunks — "
            "the response will include a header showing which lines were returned "
            "and the total line count so you know whether to read more. "
            "Returns the file content as a string, or an error message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to .emu/",
                },
                "start_line": {
                    "type": "integer",
                    "description": "0-indexed line to start reading from (default: 0).",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (default: all).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write UTF-8 text content to a file under .emu/. "
            "Allowed targets (paths relative to .emu/): "
            "workspace/AGENTS.md, workspace/MEMORY.md, workspace/USER.md, "
            "workspace/IDENTITY.md, workspace/memory/YYYY-MM-DD.md. "
            "SOUL.md and all other paths are forbidden. "
            "The file is created or fully overwritten. "
            "Returns 'ok' on success or an error message."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to .emu/ (must be in the allowlist)",
                },
                "content": {
                    "type": "string",
                    "description": "Full UTF-8 content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "finish",
        "description": (
            "Signal that the curation pass is complete. "
            "Call this once all memory files have been updated. "
            "Provide a brief summary of what was changed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-paragraph summary of changes made this tick",
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
