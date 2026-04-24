"""
cleanup.py — Janitor pass for the Emu memory daemon.

Runs once per daemon tick (invoked from run.py, BEFORE the agent loop so
that the agent always sees a tidy workspace). Performs three tasks:

    1) Deletes session folders that have no ``logs/`` subdirectory
       (considered "empty" — nothing for the agent to summarise).
    2) Deletes session folders older than SESSION_MAX_AGE_DAYS days.
    3) Trims ``stderr.log``, ``stdout.log``, ``tick.jsonl``, and any
       other files under ``.emu/global/daemon/logs/`` to the last
       ``MAX_LOG_LINES`` lines.

Safety model (critical — this script deletes files):
    - Every filesystem operation routes through ``_safe_under_root()``,
      which realpath-resolves the target and refuses to touch anything
      outside ``policy.EMU_ROOT``.
    - We use ``os.path.realpath`` (not ``Path.resolve(strict=True)``)
      so symlinks are followed before the containment check — a
      ``.emu/sessions/attack -> /etc`` symlink cannot escape.
    - Any per-item failure is logged and swallowed so the janitor
      can never crash the daemon tick.
    - Index.json updates are written atomically (write temp + rename).

This module is import-safe: importing it does NOT touch the filesystem.
Only ``run_cleanup()`` performs I/O.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Iterable

from . import policy

# ── Config ───────────────────────────────────────────────────────────────
SESSION_MAX_AGE_DAYS = 30
MAX_LOG_LINES = 20

# Filenames under global/daemon/logs/ that should ALWAYS be trimmed even if
# their size is modest. Any other file in that directory is also trimmed
# (captured via glob below) so rotated *.log variants don't grow unchecked.
_ALWAYS_TRIM = ("stderr.log", "stdout.log", "tick.jsonl")


# ── Safety primitives ────────────────────────────────────────────────────
def _safe_under_root(path: Path) -> bool:
    """True iff ``path`` realpath-resolves to a descendant of EMU_ROOT.

    Uses ``os.path.realpath`` so any symlink in the chain is resolved
    *before* the containment check — preventing symlink-escape attacks.
    ``policy.EMU_ROOT`` is itself already realpath'd at import time.
    """
    try:
        resolved = os.path.realpath(str(path))
        root = os.path.realpath(str(policy.EMU_ROOT))
        return resolved == root or resolved.startswith(root + os.sep)
    except OSError:
        return False


def _rm_tree_safe(path: Path) -> bool:
    """Delete ``path`` recursively iff it lies under EMU_ROOT.

    Returns True on success. Never raises.
    """
    if not _safe_under_root(path):
        print(f"[daemon/cleanup] REFUSING to delete outside EMU_ROOT: {path}",
              file=sys.stderr)
        return False
    try:
        if path.is_symlink() or not path.is_dir():
            # Refuse to rmtree a symlink target or non-directory to be safe.
            # A lone symlink inside .emu can still be unlinked individually.
            path.unlink(missing_ok=True)
            return True
        shutil.rmtree(path, ignore_errors=False)
        return True
    except Exception as exc:
        print(f"[daemon/cleanup] failed to delete {path}: {exc}", file=sys.stderr)
        return False


# ── Index.json helpers ───────────────────────────────────────────────────
def _load_index(index_path: Path) -> dict:
    if not index_path.exists():
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[daemon/cleanup] index.json unreadable ({exc}); leaving untouched",
              file=sys.stderr)
        return {}


def _save_index_atomic(index_path: Path, data: dict) -> None:
    if not _safe_under_root(index_path):
        print(f"[daemon/cleanup] REFUSING to write index outside EMU_ROOT: {index_path}",
              file=sys.stderr)
        return
    tmp = index_path.with_suffix(index_path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, index_path)
    except OSError as exc:
        print(f"[daemon/cleanup] failed to write index.json: {exc}", file=sys.stderr)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


# ── Task 1+2: session folder cleanup ─────────────────────────────────────
def _prune_sessions(sessions_dir: Path) -> tuple[int, int]:
    """Delete empty and stale session folders. Returns (empty, stale) counts."""
    if not sessions_dir.is_dir() or not _safe_under_root(sessions_dir):
        return (0, 0)

    index_path = sessions_dir / "index.json"
    index = _load_index(index_path)

    now = time.time()
    max_age_s = SESSION_MAX_AGE_DAYS * 86400
    removed_ids: set[str] = set()
    empty_count = 0
    stale_count = 0

    for entry in sessions_dir.iterdir():
        if not entry.is_dir():
            continue
        # Never touch anything that's a symlink out of the tree.
        if not _safe_under_root(entry):
            continue

        session_id = entry.name
        logs_dir = entry / "logs"

        # Rule 1: no logs subdirectory → empty session
        if not logs_dir.is_dir():
            if _rm_tree_safe(entry):
                removed_ids.add(session_id)
                empty_count += 1
            continue

        # Rule 2: folder mtime older than the cutoff → stale
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if now - mtime > max_age_s:
            if _rm_tree_safe(entry):
                removed_ids.add(session_id)
                stale_count += 1

    # Trim index.json — drop entries for folders we removed, AND drop
    # entries whose folder no longer exists on disk (drift self-heal).
    if index:
        before = len(index)
        index = {
            sid: meta for sid, meta in index.items()
            if sid not in removed_ids and (sessions_dir / sid).is_dir()
        }
        if len(index) != before:
            _save_index_atomic(index_path, index)

    return (empty_count, stale_count)


# ── Task 3: log trimming ─────────────────────────────────────────────────
def _trim_file_to_last_n_lines(path: Path, n: int) -> bool:
    """Keep only the last ``n`` lines of ``path``. Returns True if trimmed."""
    if not _safe_under_root(path):
        print(f"[daemon/cleanup] REFUSING to trim outside EMU_ROOT: {path}",
              file=sys.stderr)
        return False
    if not path.is_file() or path.is_symlink():
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) <= n:
            return False
        tail = lines[-n:]
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(tail)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        print(f"[daemon/cleanup] failed to trim {path}: {exc}", file=sys.stderr)
        return False


def _trim_daemon_logs(logs_dir: Path) -> int:
    """Trim every file in the daemon logs directory. Returns count trimmed."""
    if not logs_dir.is_dir() or not _safe_under_root(logs_dir):
        return 0

    trimmed = 0
    # Collect unique set: always-trim files + anything else already in the dir.
    targets: set[Path] = {logs_dir / name for name in _ALWAYS_TRIM}
    for entry in logs_dir.iterdir():
        if entry.is_file():
            targets.add(entry)

    for path in targets:
        if _trim_file_to_last_n_lines(path, MAX_LOG_LINES):
            trimmed += 1
    return trimmed


# ── Task 4: stray .tmp file sweep ────────────────────────────────────────
# Our atomic-write pattern (write `foo.tmp` → `os.replace` onto `foo`) can
# leak `.tmp` files if the process is killed between those two steps.
# They're harmless but clutter listings a small-model daemon has to scan.
def _sweep_tmp_files(*dirs: Path) -> int:
    removed = 0
    for d in dirs:
        if not d.is_dir() or not _safe_under_root(d):
            continue
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for entry in entries:
            if (
                entry.is_file()
                and not entry.is_symlink()
                and entry.suffix == ".tmp"
                and _safe_under_root(entry)
            ):
                try:
                    entry.unlink()
                    removed += 1
                except OSError as exc:
                    print(f"[daemon/cleanup] failed to unlink {entry}: {exc}",
                          file=sys.stderr)
    return removed


# ── Public entrypoint ────────────────────────────────────────────────────
def run_cleanup() -> dict:
    """Run all janitor tasks. Logs a summary and never raises."""
    summary = {
        "empty_sessions": 0,
        "stale_sessions": 0,
        "logs_trimmed": 0,
        "tmp_files_removed": 0,
    }
    try:
        sessions_dir = policy.EMU_ROOT / "sessions"
        logs_dir = policy.EMU_ROOT / "global" / "daemon" / "logs"

        empty, stale = _prune_sessions(sessions_dir)
        summary["empty_sessions"] = empty
        summary["stale_sessions"] = stale

        summary["logs_trimmed"] = _trim_daemon_logs(logs_dir)
        summary["tmp_files_removed"] = _sweep_tmp_files(sessions_dir, logs_dir)

        if any(summary.values()):
            print(
                f"[daemon/cleanup] empty={summary['empty_sessions']} "
                f"stale={summary['stale_sessions']} "
                f"logs_trimmed={summary['logs_trimmed']} "
                f"tmp_removed={summary['tmp_files_removed']}",
                file=sys.stderr,
            )
    except Exception as exc:  # belt and suspenders — never abort the tick
        print(f"[daemon/cleanup] unexpected error: {exc}", file=sys.stderr)
    return summary


if __name__ == "__main__":
    # Allow running as a one-off: `python -m daemon.cleanup`
    result = run_cleanup()
    print(json.dumps(result, indent=2))
