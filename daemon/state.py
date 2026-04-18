"""
state.py — Session index + failure tracking (stateless consolidation).

Design notes:
- There is NO processed_sessions set. The daemon re-examines all sessions
  every tick and relies on its own memory files (MEMORY.md, daily logs,
  AGENTS.md) to decide what's already captured. This matches human-memory
  semantics: learnings can be re-contextualized, edited, merged.

- We maintain a lightweight index at `.emu/sessions/index.json` mapping
  session_id -> date (YYYY-MM-DD). The backend writes a new entry the
  moment a session is created; the daemon reads the index each tick
  without scanning directories. A full rebuild only happens on cold start
  (missing index file).

- state.json at `.emu/global/daemon/state.json` now carries only
  operational fields: consecutive_failures and last_tick_at.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import policy


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    date: str  # "YYYY-MM-DD"


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
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


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


def _read_index() -> dict[str, str]:
    p = _index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_index_atomic(index: dict[str, str]) -> None:
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
    """
    index = _read_index()
    if index.get(session_id) == date:
        return  # already recorded — no write needed
    index[session_id] = date
    _write_index_atomic(index)


def rebuild_session_index() -> dict[str, str]:
    """
    Cold-start / self-heal fallback: scan sessions/ and rewrite the index.
    Only called when the index file is missing (e.g. fresh clone with
    pre-existing sessions) or when you explicitly want to reconcile
    index vs. disk. Normal flow uses record_session_in_index().
    """
    sessions_dir = policy.EMU_ROOT / "sessions"
    index: dict[str, str] = {}
    if sessions_dir.exists():
        for entry in sorted(sessions_dir.iterdir()):
            if entry.is_dir():
                index[entry.name] = _extract_session_date(entry)
    _write_index_atomic(index)
    return index


def list_all_sessions() -> list[SessionInfo]:
    """
    Return every session from the index, newest-date first.
    If the index file is missing, bootstrap it once by scanning — normal
    operation after that is a cheap JSON read, no directory walk.
    """
    if not _index_path().exists():
        rebuild_session_index()
    index = _read_index()

    sessions_dir = policy.EMU_ROOT / "sessions"
    infos = [
        SessionInfo(session_id=sid, path=sessions_dir / sid, date=date)
        for sid, date in index.items()
    ]
    infos.sort(key=lambda s: s.date, reverse=True)
    return infos


def build_input_manifest(sessions: list[SessionInfo]) -> str:
    """Build the initial user message. Lists every session via the index."""
    lines = [
        "## Session index\n",
        f"There are {len(sessions)} session(s) on disk (newest-date first).",
        f"Full index: `sessions/index.json` (read with `read_file` if useful).\n",
        "Before writing, read `workspace/MEMORY.md` and recent daily logs in "
        "`workspace/memory/`. For each session below, decide:",
        "  • already captured in memory → skip",
        "  • needs a new entry → read the session files and write it",
        "  • existing entry should be refined with new context → edit it\n",
    ]
    for s in sessions:
        lines.append(f"- `{s.session_id}` ({s.date}) — path: `sessions/{s.session_id}/`")
    lines.append("")
    lines.append("When all memory updates are done, call `finish` with a summary.")
    return "\n".join(lines)
