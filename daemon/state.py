"""
state.py — Processed-session tracker and input manifest builder.

state.json lives at $EMU_ROOT/global/daemon/state.json and is the daemon's
sole bookkeeping file. Sessions are processed incrementally — once a session
ID appears in processed_sessions it is never re-processed.
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


def _state_path() -> Path:
    return policy.EMU_ROOT / "global" / "daemon" / "state.json"


def _load_state() -> dict:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": 1,
        "processed_sessions": {},
        "last_tick_at": None,
        "consecutive_failures": 0,
    }


def _save_state(data: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _seed_initial_state_if_missing() -> None:
    """
    Enforce the 'incremental only' rule from DESIGN §9: on first tick after
    install, the daemon must NOT backfill the sessions that already exist.
    If state.json does not yet exist, seed it by marking every currently
    present session as already processed (with a synthetic 'seeded' run_id).
    From this point forward, only sessions created AFTER install are visible
    to the daemon.
    """
    if _state_path().exists():
        return

    sessions_dir = policy.EMU_ROOT / "sessions"
    seeded: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat()
    if sessions_dir.exists():
        for entry in sessions_dir.iterdir():
            if entry.is_dir():
                seeded[entry.name] = {"processed_at": now, "run_id": "seeded-at-install"}

    _save_state({
        "version": 1,
        "processed_sessions": seeded,
        "last_tick_at": None,
        "consecutive_failures": 0,
        "seeded_at": now,
    })


def list_unprocessed_sessions() -> list[SessionInfo]:
    """Return sessions in $EMU_ROOT/sessions/ not yet in processed_sessions."""
    _seed_initial_state_if_missing()

    sessions_dir = policy.EMU_ROOT / "sessions"
    if not sessions_dir.exists():
        return []

    data = _load_state()
    processed: set[str] = set(data.get("processed_sessions", {}).keys())

    result: list[SessionInfo] = []
    for entry in sorted(sessions_dir.iterdir()):
        if entry.is_dir() and entry.name not in processed:
            result.append(SessionInfo(session_id=entry.name, path=entry))
    return result


def build_input_manifest(sessions: list[SessionInfo]) -> str:
    """Build the initial user message listing unprocessed sessions."""
    lines = [
        "## Sessions to curate\n",
        f"There are {len(sessions)} unprocessed session(s). "
        "Use list_dir and read_file to inspect them, then write the appropriate "
        "memory files per your instructions.\n",
    ]
    for s in sessions:
        lines.append(f"### Session `{s.session_id}`")
        lines.append(f"Path (relative to .emu/): `sessions/{s.session_id}/`")
        try:
            files = sorted(f.name for f in s.path.iterdir() if f.is_file())
            if files:
                lines.append(f"Files: {', '.join(files)}")
            else:
                lines.append("Files: (empty session)")
        except OSError:
            lines.append("Files: (could not list)")
        lines.append("")

    lines.append(
        "When done updating all memory files, call `finish` with a summary."
    )
    return "\n".join(lines)


def mark_processed(sessions: list[SessionInfo], run_id: str) -> None:
    """Record sessions as processed and update last_tick_at."""
    data = _load_state()
    now = datetime.now(timezone.utc).isoformat()
    for s in sessions:
        data["processed_sessions"][s.session_id] = {
            "processed_at": now,
            "run_id": run_id,
        }
    data["last_tick_at"] = now
    data["consecutive_failures"] = 0
    _save_state(data)


def increment_failures() -> int:
    """Increment failure counter and return the new count."""
    data = _load_state()
    count = data.get("consecutive_failures", 0) + 1
    data["consecutive_failures"] = count
    _save_state(data)
    return count


def get_consecutive_failures() -> int:
    return _load_state().get("consecutive_failures", 0)
