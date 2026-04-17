"""
run.py — Emu Memory Daemon entrypoint.

Invoked every 5 minutes by launchd as: python -m daemon.run

NOTE: For now the daemon runs the single fixed DAEMON_PROMPT. In the future
we may support attached "skills" per Hermes's model (extra prompt fragments
injected into the session). The agent loop is structured so that plugging
in skills later is an additive change — see build_system_prompt() below.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import policy, state, tools
from .llm_client import run_agent_loop, TOOLS
from .prompt import DAEMON_PROMPT

MAX_TURNS = 24
MAX_TOKENS = 120_000
MAX_CONSECUTIVE_FAILURES = 5

# Rotate log files if they exceed 5 MB
LOG_ROTATE_BYTES = 5 * 1024 * 1024


def build_system_prompt() -> str:
    # Hook: if/when skills land, concatenate their bodies here before returning.
    return DAEMON_PROMPT


def _log_tick(log_path: Path, record: dict) -> None:
    _rotate_if_needed(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _rotate_if_needed(path: Path) -> None:
    if path.exists() and path.stat().st_size > LOG_ROTATE_BYTES:
        rotated = path.with_suffix(f".{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.log")
        path.rename(rotated)


def main() -> int:
    logs_dir = policy.EMU_ROOT / "global" / "daemon" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    tick_log = logs_dir / "tick.jsonl"

    # Gate: stop trying after too many consecutive failures
    failures = state.get_consecutive_failures()
    if failures >= MAX_CONSECUTIVE_FAILURES:
        print(
            f"[daemon] {failures} consecutive failures — paused. "
            "Inspect logs at .emu/global/daemon/logs/tick.jsonl and reset "
            "state.json consecutive_failures to 0 to resume.",
            file=sys.stderr,
        )
        return 0

    # Acquire exclusive lock — skip this tick if a previous one is still running
    lock_path = policy.EMU_ROOT / "global" / "daemon" / ".tick.lock"
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("[daemon] previous tick still running; skipping", file=sys.stderr)
        lock_file.close()
        return 0

    try:
        return _run_tick(tick_log)
    except Exception as exc:
        count = state.increment_failures()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": "error",
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "consecutive_failures": count,
        }
        _log_tick(tick_log, record)
        print(f"[daemon] tick failed ({count} consecutive): {exc}", file=sys.stderr)
        return 1
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _run_tick(tick_log: Path) -> int:
    ts_start = datetime.now(timezone.utc)

    unprocessed = state.list_unprocessed_sessions()
    if not unprocessed:
        print("[daemon] no new sessions; idle", file=sys.stderr)
        return 0

    session_ids = [s.session_id for s in unprocessed]
    print(f"[daemon] processing {len(unprocessed)} session(s): {session_ids}", file=sys.stderr)

    result = run_agent_loop(
        system=build_system_prompt(),
        user=state.build_input_manifest(unprocessed),
        tools=TOOLS,
        tool_dispatcher=tools.dispatch,
        max_turns=MAX_TURNS,
        max_total_tokens=MAX_TOKENS,
    )

    # Post-pass: re-validate every path the agent wrote (belt and suspenders)
    post_pass_violations = 0
    for written_path in result.written_paths:
        try:
            policy.check_write(str(written_path.relative_to(policy.EMU_ROOT)))
        except policy.PolicyError as exc:
            post_pass_violations += 1
            print(f"[daemon] POST-PASS VIOLATION: {exc}", file=sys.stderr)

    total_violations = result.policy_violations + post_pass_violations

    # Mark sessions processed only on success
    if result.status in ("ok", "max_turns") and total_violations == 0:
        state.mark_processed(unprocessed, run_id=result.run_id)
    elif total_violations > 0:
        count = state.increment_failures()
        print(
            f"[daemon] {total_violations} policy violation(s) detected — "
            f"sessions NOT marked processed. Consecutive failures: {count}",
            file=sys.stderr,
        )

    files_written = [
        str(p.relative_to(policy.EMU_ROOT)) for p in result.written_paths
    ]
    elapsed_s = (datetime.now(timezone.utc) - ts_start).total_seconds()

    record = {
        "ts":               ts_start.isoformat(),
        "run_id":           result.run_id,
        "sessions_seen":    len(unprocessed),
        "sessions_new":     len(unprocessed),
        "turns":            result.turns,
        "tokens_in":        result.tokens_in,
        "tokens_out":       result.tokens_out,
        "files_written":    files_written,
        "policy_violations": total_violations,
        "elapsed_s":        round(elapsed_s, 2),
        "status":           result.status,
        "summary":          result.finish_summary,
    }
    _log_tick(tick_log, record)

    print(
        f"[daemon] tick done — {len(unprocessed)} session(s), "
        f"{len(files_written)} file(s) written, "
        f"{result.turns} turn(s), "
        f"{result.tokens_in + result.tokens_out} tokens, "
        f"violations={total_violations}, status={result.status}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
