"""
tools.py — Tool definitions and dispatcher exposed to the LLM (Layer 1 security).

Only four tools are exposed: list_dir, read_file, write_file, finish.
No shell, exec, or network tool exists. The dispatcher enforces path policy
(L2) and per-tick write budget on every call.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import policy

MAX_PER_FILE_BYTES = 512 * 1024       # 512 KB per single write
MAX_TOTAL_BYTES_TICK = 2 * 1024 * 1024  # 2 MB total across all writes in one tick
MAX_READ_BYTES = 512 * 1024           # 512 KB per single read

# ── search_text budgets ───────────────────────────────────────────────────────
# Keep search bounded so a pathological regex can't stall a tick. These are
# per-call caps; the regex itself still runs in-process so a catastrophically
# backtracking pattern against a single large file could hang — we mitigate by
# capping per-file size (MAX_READ_BYTES) and pattern length.
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_FILES = 500
MAX_SEARCH_BYTES = 16 * 1024 * 1024   # 16 MB total scanned per call
MAX_PATTERN_LEN = 500
MAX_CONTEXT_LINES = 3
MAX_LINE_CHARS = 500                  # truncate matched line in output


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
        "name": "search_text",
        "description": (
            "Search file contents under .emu/ for a Python regular expression. "
            "USE THIS instead of reading every daily log one-by-one when you "
            "want to know whether a session id (or any string) is already "
            "captured somewhere — it's the cheapest way to answer 'do I "
            "already have an entry for session XYZ?'.\n\n"
            "Returns a JSON object {\"matches\": [{\"path\", \"line_no\", "
            "\"line\"}, ...], \"files_scanned\": N, \"truncated\": <reason|null>}. "
            "Paths are relative to .emu/. Binary and oversized files (>512KB) "
            "are skipped silently. Dotfiles and dot-directories are skipped.\n\n"
            "Examples:\n"
            "  search_text(pattern=r'### abc-123 —', path='workspace/memory')\n"
            "  search_text(pattern=r'ERROR|failed', path='sessions/abc-123/logs', context_lines=1)\n"
            "  search_text(pattern=r'OpenRouter', case_insensitive=true)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": (
                        f"Python regex pattern. Max {MAX_PATTERN_LEN} chars. "
                        "Invalid regex returns an error — prefer simple "
                        "literals (escape special chars with \\) when you "
                        "just want substring search."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "Directory (recursive) or single file to search, "
                        "relative to .emu/. Omit or pass '' to search the "
                        "entire .emu/ tree. Path is confined to .emu/ — "
                        "anything outside is rejected."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": (
                        f"Cap on returned matches (default 50, hard max "
                        f"{MAX_SEARCH_RESULTS})."
                    ),
                },
                "context_lines": {
                    "type": "integer",
                    "description": (
                        f"Lines of context before/after each match (default "
                        f"0, max {MAX_CONTEXT_LINES}). When > 0 each result "
                        f"gains a 'context' array."
                    ),
                },
                "case_insensitive": {
                    "type": "boolean",
                    "description": "Match case-insensitively (default false).",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "stat_file",
        "description": (
            "Return metadata about a file or directory under .emu/ without "
            "reading its contents. Use this to check whether a file is too "
            "big to read in one call (so you can pre-plan chunking) or to "
            "see when it was last modified. Returns JSON: "
            "{\"type\": 'file'|'dir', \"size_bytes\": N, \"mtime\": "
            "ISO8601, \"line_count\": N (files only, UTF-8 best-effort)}. "
            "Returns '[error] path does not exist: ...' for missing paths — "
            "handle that as a normal signal, not a retry trigger."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory path relative to .emu/. "
                        "Examples: 'sessions/abc-123/logs/conversation.json', "
                        "'workspace/memory'."
                    ),
                },
            },
            "required": ["path"],
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
        elif name == "search_text":
            return _search_text(args, state)
        elif name == "stat_file":
            return _stat_file(args, state)
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


def _search_text(args: dict, state: DispatchState) -> str:
    pattern = args.get("pattern", "")
    raw_path = args.get("path", "") or ""
    case_insensitive = bool(args.get("case_insensitive", False))

    try:
        max_results = min(int(args.get("max_results") or 50), MAX_SEARCH_RESULTS)
    except (TypeError, ValueError):
        return "[error] max_results must be an integer"
    try:
        context_lines = min(max(int(args.get("context_lines") or 0), 0), MAX_CONTEXT_LINES)
    except (TypeError, ValueError):
        return "[error] context_lines must be an integer"

    if not isinstance(pattern, str) or not pattern:
        return "[error] pattern is required (non-empty string)"
    if len(pattern) > MAX_PATTERN_LEN:
        return f"[error] pattern too long (max {MAX_PATTERN_LEN} chars)"

    try:
        flags = re.IGNORECASE if case_insensitive else 0
        rx = re.compile(pattern, flags)
    except re.error as exc:
        return f"[error] invalid regex: {exc}"

    # L2 path check — also handles "" as "search EMU_ROOT itself"
    root = policy.check_read(raw_path) if raw_path else policy.EMU_ROOT
    if not root.exists():
        return f"[error] path does not exist: {raw_path!r}"

    matches: list[dict] = []
    files_scanned = 0
    bytes_scanned = 0
    truncated: str | None = None

    def _iter_candidates(r: Path):
        if r.is_file():
            yield r
            return
        if not r.is_dir():
            return
        # Use rglob + manual filter so we can prune dot-dirs early.
        for entry in sorted(r.rglob("*")):
            rel_parts = entry.relative_to(r).parts
            if any(part.startswith(".") for part in rel_parts):
                continue
            if entry.is_file():
                yield entry

    for fpath in _iter_candidates(root):
        if files_scanned >= MAX_SEARCH_FILES:
            truncated = f"file limit reached ({MAX_SEARCH_FILES})"
            break
        if bytes_scanned >= MAX_SEARCH_BYTES:
            truncated = f"byte budget reached ({MAX_SEARCH_BYTES})"
            break

        # Defense in depth: re-validate every descendant through check_read.
        # If a symlinked file inside .emu points outside, this rejects it.
        try:
            rel = fpath.relative_to(policy.EMU_ROOT)
            policy.check_read(str(rel))
        except (ValueError, policy.PolicyError):
            continue

        try:
            size = fpath.stat().st_size
        except OSError:
            continue
        if size > MAX_READ_BYTES:
            continue  # skip huge files rather than stalling

        try:
            content = fpath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary / unreadable

        files_scanned += 1
        bytes_scanned += size

        lines = content.splitlines()
        for i, line in enumerate(lines):
            if rx.search(line):
                entry: dict = {
                    "path": str(rel),
                    "line_no": i + 1,
                    "line": line[:MAX_LINE_CHARS],
                }
                if context_lines > 0:
                    lo = max(0, i - context_lines)
                    hi = min(len(lines), i + context_lines + 1)
                    entry["context"] = [ln[:MAX_LINE_CHARS] for ln in lines[lo:hi]]
                matches.append(entry)
                if len(matches) >= max_results:
                    truncated = truncated or f"result limit reached ({max_results})"
                    break
        if len(matches) >= max_results:
            break

    return json.dumps({
        "matches": matches,
        "files_scanned": files_scanned,
        "truncated": truncated,
    })


def _stat_file(args: dict, state: DispatchState) -> str:
    raw_path = args.get("path", "")
    resolved = policy.check_read(raw_path)

    if not resolved.exists():
        return f"[error] path does not exist: {raw_path!r}"

    st = resolved.stat()
    info: dict = {
        "path": raw_path,
        "type": "dir" if resolved.is_dir() else "file" if resolved.is_file() else "other",
        "size_bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }
    if resolved.is_file():
        try:
            with resolved.open("rb") as f:
                info["line_count"] = sum(1 for _ in f)
        except OSError:
            pass
    return json.dumps(info)


def _finish(args: dict, state: DispatchState) -> str:
    summary = args.get("summary", "")
    state.finished = True
    state.finish_summary = summary
    return "done"
