"""
state.py — Session index + failure tracking (stateless consolidation).

Design notes:
- The daemon re-examines all sessions every tick. It relies on two cheap
  signals to decide what's new:
    1. `captured_at` on each entry in `sessions/index.json` — an ISO8601
       timestamp set when the session was written into a daily log, or
       None if it's still waiting to be captured.
    2. Existing memory files (MEMORY.md, daily logs, AGENTS.md) for
       in-place refinement of already-captured sessions.
  The captured_at flag is what lets the daemon scale past ~5 sessions
  per day without exhausting its context budget re-deriving "is this
  already captured?" from memory on every tick.

- Capture detection: the agent calls the `mark_captured` tool after
  writing a session's block into a daily log, which flips
  `captured_at` to the current time. This tool is the only LLM-facing
  path that mutates the index. The daily-log heading format
  (`### <session_id> — ...`) is also used by `rebuild_session_index()`
  to backfill captured_at on cold start, so existing memory isn't
  re-processed from scratch.

- We maintain a lightweight index at `.emu/sessions/index.json`:
      { "<session_id>": {"date": "YYYY-MM-DD", "captured_at": <iso|null>} }
  Backward-compat: reads also accept the legacy flat form
      { "<session_id>": "YYYY-MM-DD" }
  which gets migrated to the nested form on the next write.

- The backend writes a new entry the moment a session is created; the
  daemon reads the index each tick without scanning directories. A full
  rebuild only happens on cold start (missing index file).

- state.json at `.emu/global/daemon/state.json` now carries only
  operational fields: consecutive_failures and last_tick_at.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import policy


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    date: str  # "YYYY-MM-DD"
    captured_at: str | None = None  # ISO8601 UTC, or None if not yet captured


# ── state.json (operational bookkeeping only) ────────────────────────────────

def _state_path() -> Path:
    return policy.EMU_ROOT / "global" / "daemon" / "state.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return {
                "version": 2,
                "consecutive_failures": data.get("consecutive_failures", 0),
                "last_tick_at": data.get("last_tick_at"),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {"version": 2, "consecutive_failures": 0, "last_tick_at": None}


def _save_state(data: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: tempfile + rename. A crash mid-write would otherwise
    # leave state.json truncated/corrupt, which permanently wedges the
    # consecutive-failures counter and last_tick_at.
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def mark_tick_complete() -> None:
    data = _load_state()
    data["last_tick_at"] = datetime.now(timezone.utc).isoformat()
    data["consecutive_failures"] = 0
    _save_state(data)


def increment_failures() -> int:
    data = _load_state()
    count = data.get("consecutive_failures", 0) + 1
    data["consecutive_failures"] = count
    _save_state(data)
    return count


def get_consecutive_failures() -> int:
    return _load_state().get("consecutive_failures", 0)


# ── Session index (sessions/index.json) ──────────────────────────────────────

_INDEX_REL = "sessions/index.json"


def _index_path() -> Path:
    return policy.EMU_ROOT / _INDEX_REL


def _extract_session_date(session_dir: Path) -> str:
    """
    Pull YYYY-MM-DD for a session. Preferred source:
    conversation.json's session_date field. Fallback: dir mtime.
    """
    conv = session_dir / "logs" / "conversation.json"
    if conv.exists():
        try:
            data = json.loads(conv.read_text(encoding="utf-8"))
            date = data.get("session_date")
            if isinstance(date, str) and len(date) == 10 and date[4] == "-":
                return date
        except (json.JSONDecodeError, OSError):
            pass
    mtime = datetime.fromtimestamp(session_dir.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime("%Y-%m-%d")


def _read_index() -> dict[str, dict]:
    """
    Read index and normalize to the nested shape:
        {sid: {"date": "YYYY-MM-DD", "captured_at": <iso|null>}}
    Legacy flat shape {sid: "YYYY-MM-DD"} is accepted on read and
    upgraded on the next write.
    """
    p = _index_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    normalized: dict[str, dict] = {}
    for sid, val in raw.items():
        if isinstance(val, str):
            normalized[sid] = {"date": val, "captured_at": None}
        elif isinstance(val, dict) and isinstance(val.get("date"), str):
            captured = val.get("captured_at")
            if not isinstance(captured, str):
                captured = None
            normalized[sid] = {"date": val["date"], "captured_at": captured}
        # Silently skip malformed entries rather than crash the daemon.
    return normalized


def _write_index_atomic(index: dict[str, dict]) -> None:
    """Write index atomically via tempfile + rename (safe vs concurrent reads)."""
    path = _index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def record_session_in_index(session_id: str, date: str) -> None:
    """
    Append (or update) one session in `.emu/sessions/index.json`.
    Called by the backend the moment a session is created so the daemon
    doesn't have to rescan the sessions directory on every tick.

    Preserves any existing `captured_at` on re-records; new sessions
    start with `captured_at = None`.
    """
    index = _read_index()
    existing = index.get(session_id)
    if existing and existing.get("date") == date and "captured_at" in existing:
        # Already in canonical shape with the same date — no-op.
        return
    index[session_id] = {
        "date": date,
        "captured_at": existing.get("captured_at") if existing else None,
    }
    _write_index_atomic(index)


# Match any `### <token> — ...` heading. The token gets validated
# against index membership before being marked captured, so this
# intentionally accepts any non-whitespace sequence (not just UUIDs).
_HEADING_RE = re.compile(r"^###\s+(\S+)\s+—", re.MULTILINE)


def extract_session_ids_from_daily_log(content: str) -> set[str]:
    """Return every session id that appears as a `### <sid> —` heading."""
    return {m.group(1) for m in _HEADING_RE.finditer(content)}


def mark_sessions_captured(
    session_ids: Iterable[str],
    ts: str | None = None,
) -> list[str]:
    """
    Flip `captured_at` on each known session id. Unknown ids are
    ignored. Returns the list of ids that were actually updated.

    Idempotent: re-marking an already-captured session overwrites the
    timestamp with the newer one so we track the most recent refinement.
    """
    ids = [sid for sid in session_ids if sid]
    if not ids:
        return []
    index = _read_index()
    if not index:
        return []
    stamp = ts or datetime.now(timezone.utc).isoformat()
    updated: list[str] = []
    for sid in ids:
        entry = index.get(sid)
        if not entry:
            continue
        entry["captured_at"] = stamp
        updated.append(sid)
    if updated:
        _write_index_atomic(index)
    return updated


def reconcile_captured_from_memory() -> int:
    """
    Scan `workspace/memory/*.md` for `### <sid> —` headings and
    backfill `captured_at` for any index entry that's still uncaptured.
    Used on cold start (from `rebuild_session_index`) so pre-existing
    daily logs don't get re-processed on first tick. Cheap enough to
    also call manually after ad-hoc edits to memory files.

    Returns the number of entries updated.
    """
    index = _read_index()
    if not index:
        return 0

    memory_dir = policy.EMU_ROOT / "workspace" / "memory"
    if not memory_dir.exists():
        return 0

    updates = 0
    for md in sorted(memory_dir.glob("*.md")):
        try:
            content = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        ids = extract_session_ids_from_daily_log(content)
        if not ids:
            continue
        mtime_iso = datetime.fromtimestamp(
            md.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        for sid in ids:
            entry = index.get(sid)
            if entry and entry.get("captured_at") is None:
                entry["captured_at"] = mtime_iso
                updates += 1

    if updates:
        _write_index_atomic(index)
    return updates


def rebuild_session_index() -> dict[str, dict]:
    """
    Cold-start / self-heal fallback: scan sessions/ and rewrite the index.
    Only called when the index file is missing (e.g. fresh clone with
    pre-existing sessions) or when you explicitly want to reconcile
    index vs. disk. Normal flow uses record_session_in_index().

    After rebuild, backfills captured_at from workspace/memory/*.md so
    already-captured sessions don't get re-processed on first tick.
    """
    sessions_dir = policy.EMU_ROOT / "sessions"
    index: dict[str, dict] = {}
    if sessions_dir.exists():
        for entry in sorted(sessions_dir.iterdir()):
            if entry.is_dir():
                index[entry.name] = {
                    "date": _extract_session_date(entry),
                    "captured_at": None,
                }
    _write_index_atomic(index)
    reconcile_captured_from_memory()
    return _read_index()


def list_all_sessions() -> list[SessionInfo]:
    """
    Return every session from the index, newest-date first and with
    uncaptured sessions ahead of captured ones at the same date.
    If the index file is missing, bootstrap it once by scanning — normal
    operation after that is a cheap JSON read, no directory walk.
    """
    if not _index_path().exists():
        rebuild_session_index()
    index = _read_index()

    sessions_dir = policy.EMU_ROOT / "sessions"
    infos = [
        SessionInfo(
            session_id=sid,
            path=sessions_dir / sid,
            date=entry["date"],
            captured_at=entry.get("captured_at"),
        )
        for sid, entry in index.items()
    ]
    # Sort: newer dates first; within a date, uncaptured first so the
    # manifest naturally leads with work that remains.
    infos.sort(key=lambda s: (s.date, s.captured_at is not None), reverse=True)
    return infos


def build_input_manifest(sessions: list[SessionInfo]) -> str:
    """
    Build the initial user message. Splits sessions into uncaptured
    (the tick's focus) and already-captured (skip unless refining),
    keeping the agent's attention on what actually needs to be written.
    """
    uncaptured = [s for s in sessions if s.captured_at is None]
    captured = [s for s in sessions if s.captured_at is not None]

    lines = [
        "## Session index\n",
        f"{len(sessions)} session(s) on disk — "
        f"{len(uncaptured)} uncaptured, {len(captured)} already captured.",
        "Full index: `sessions/index.json` (read with `read_file` if useful).\n",
        "Capture status is tracked in the index via `captured_at`. You do "
        "NOT need to re-derive it by searching memory.",
        "",
        "**Priority:** write an entry for every uncaptured session below. "
        "After each `write_file` to a daily log, call `mark_captured` with "
        "the session ids you just wrote so the next tick skips them.",
        "",
    ]

    if uncaptured:
        lines.append(f"### Uncaptured ({len(uncaptured)}) — newest date first")
        for s in uncaptured:
            lines.append(
                f"- `{s.session_id}` ({s.date}) — path: `sessions/{s.session_id}/`"
            )
        lines.append("")
    else:
        lines.append("### Uncaptured (0) — nothing new to capture this tick.\n")

    if captured:
        lines.append(
            f"### Already captured ({len(captured)}) — SKIP unless you have "
            "budget to refine an entry with new context"
        )
        for s in captured:
            stamp = (s.captured_at or "")[:19]
            lines.append(
                f"- `{s.session_id}` ({s.date}) — captured {stamp}"
            )
        lines.append("")

    lines.append("When all memory updates are done, call `finish` with a summary.")
    return "\n".join(lines)
