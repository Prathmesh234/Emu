"""
backend/tools/hermes.py

Handlers for the Hermes Agent toolset:
  - invoke_hermes  → spawn a background Hermes job, return job_id
  - check_hermes   → poll job status / retrieve final output
  - cancel_hermes  → terminate a running job
  - list_hermes_jobs → enumerate all jobs in the current session

Hermes Agent (Nous Research, https://github.com/NousResearch/hermes-agent) is
an autonomous terminal agent installed locally. It exposes a documented
non-interactive single-query mode: `hermes chat -Q -q "<prompt>"`.

Previously this handler ran Hermes synchronously inside the tool call, which
blocked the Emu agent loop for the whole Hermes runtime (up to 10 minutes)
and silently lost output whenever Hermes wrote enough to stderr to fill the
pipe buffer (because `proc.communicate()` deadlocks in that case). The new
design spawns Hermes as a background asyncio job; the model polls the job by
id via `check_hermes`. See `hermes_jobs.py` for the registry implementation.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Optional

from utilities.connection import ConnectionManager
from utilities.paths import get_emu_path_str
from workspace import get_sessions_dir, write_session_file

from . import hermes_jobs
from .hermes_jobs import HermesJob, STUCK_AFTER_S


HERMES_BIN = "hermes"
DEFAULT_TIMEOUT_S = 600   # 10 minutes — Hermes can be slow on big tasks
MAX_OUTPUT_CHARS = 60_000  # truncate huge stdouts before returning to Emu

# Hermes artifacts (task brief + result) live in their own subfolder so they
# don't clutter the top-level session directory and are easy to inspect.
HERMES_SUBDIR = "hermes"

# Per-session lock guarding `_next_brief_filename` so two concurrent
# invoke_hermes calls in the same session never compute the same index and
# clobber each other's task_brief_NN.md.
_brief_locks: dict[str, asyncio.Lock] = {}


def _brief_lock(session_id: str) -> asyncio.Lock:
    lock = _brief_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _brief_locks[session_id] = lock
    return lock

# When Emu is launched as Emu.app from Finder/Spotlight, PATH is the minimal
# /usr/bin:/bin:/usr/sbin:/sbin — the user's shell rc files never run, so any
# binary installed under ~/.hermes/bin or ~/.local/bin is invisible to
# shutil.which / subprocess. Prepend the canonical Hermes install locations
# (and the common user-bin locations) so detection and exec both work.
_HOME = Path.home()
_HERMES_PATH_EXTRAS = [
    str(_HOME / ".hermes" / "bin"),
    str(_HOME / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]


def _augmented_env() -> dict[str, str]:
    """Return os.environ with Hermes install dirs prepended to PATH."""
    env = os.environ.copy()
    existing = env.get("PATH", "")
    existing_parts = existing.split(os.pathsep) if existing else []
    extras = [p for p in _HERMES_PATH_EXTRAS if p and p not in existing_parts]
    if extras:
        env["PATH"] = os.pathsep.join(extras + existing_parts)
    return env


_AUGMENTED_PATH = _augmented_env()["PATH"]


def _resolve_hermes_bin() -> str | None:
    """Locate the hermes binary using the augmented PATH."""
    return shutil.which(HERMES_BIN, path=_AUGMENTED_PATH)


def _build_prompt_document(
    goal: str,
    context: str,
    file_paths: list[str],
    output_target: str,
    constraints: str,
) -> str:
    """Compose the markdown prompt that gets fed to Hermes."""
    parts: list[str] = []
    parts.append("# Task delegated from Emu (desktop agent) to Hermes")
    parts.append("")
    parts.append("Emu has navigated the GUI to gather everything below. You are")
    parts.append("Hermes — execute the task headlessly and produce the requested")
    parts.append("artifact. Verify your work and end with the final file path(s)")
    parts.append("and a short summary of what changed.")
    parts.append("")
    parts.append("## Goal")
    parts.append(goal.strip() or "(no goal provided)")
    parts.append("")

    if output_target.strip():
        parts.append("## Required output")
        parts.append(output_target.strip())
        parts.append("")

    if constraints.strip():
        parts.append("## Constraints")
        parts.append(constraints.strip())
        parts.append("")

    if file_paths:
        parts.append("## Input files")
        parts.append("Read these before doing anything else:")
        for fp in file_paths:
            parts.append(f"- `{fp}`")
        parts.append("")

    if context.strip():
        parts.append("## Full context gathered by Emu")
        parts.append("Treat this as the source of truth. Do NOT ask for")
        parts.append("clarification — work with exactly what is below.")
        parts.append("")
        parts.append(context.strip())
        parts.append("")

    parts.append("## When you are done")
    parts.append("- Save artifacts to disk and print absolute file paths.")
    parts.append("- Print a one-paragraph summary of what you did.")
    parts.append("- If something blocked you, say what and why.")
    return "\n".join(parts)


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    elided = len(text) - limit
    return f"{head}\n\n[... {elided} chars elided ...]\n\n{tail}"


def _install_guidance() -> str:
    """Message returned when the hermes binary cannot be located."""
    manifest_path = f"{get_emu_path_str()}/manifest.json"
    return (
        "Hermes Agent is not installed on this machine.\n\n"
        "Ask the user (in your next final_message): \"Hermes Agent isn't "
        "installed yet — it's a headless terminal agent from Nous Research "
        "that I'd use to do the heavy lifting here. I can install it (~30s) "
        "and then walk you through picking a provider/model and adding an "
        "API key in a fresh session. Want me to go ahead?\"\n\n"
        "If the user says YES:\n"
        "  1. shell_exec → curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash\n"
        f"  2. shell_exec → python3 -c \"import json; p='{manifest_path}'; "
        "d=json.load(open(p)); d['hermes_installed']=True; d['hermes_setup_pending']=True; "
        "json.dump(d,open(p,'w'),indent=2)\"\n"
        "  3. Tell the user the install is done and ask them to start a "
        "NEW session — the next session will auto-detect "
        "hermes_setup_pending and boot straight into setup mode where "
        "I'll open Terminal and run `hermes setup` with you. We'll come "
        "back to the current task after that.\n\n"
        "DO NOT try to run `hermes setup` in the current session yourself "
        "— that wizard is interactive (TTY) and only the dedicated setup "
        "mode is wired to drive it through Terminal.\n\n"
        "If the user says NO, abandon the Hermes plan and either complete "
        "the task yourself via desktop actions or tell the user it can't "
        "be done well without Hermes."
    )


def _next_brief_filename(session_id: str) -> str:
    """Return the next `hermes/task_brief_NN.md` filename for this session.

    Counts existing briefs in `.emu/sessions/<id>/hermes/` so the index keeps
    rising even across backend restarts. Pairs 1:1 with `task_result_NN.md`
    written by `_persist_output` in hermes_jobs.py once the job finishes.
    """
    hermes_dir = get_sessions_dir() / session_id / HERMES_SUBDIR
    if hermes_dir.is_dir():
        existing = [
            f.name for f in hermes_dir.iterdir()
            if f.is_file() and f.name.startswith("task_brief_")
        ]
    else:
        existing = []
    idx = len(existing) + 1
    return f"{HERMES_SUBDIR}/task_brief_{idx:02d}.md"


def _liveness_blurb(job: HermesJob) -> str:
    now = time.time()
    runtime = (job.finished_at or now) - job.started_at
    parts = [f"runtime {runtime:.1f}s"]
    if job.last_output_at:
        idle = now - job.last_output_at
        parts.append(f"last output {idle:.1f}s ago")
        if not job.done_event.is_set() and idle > STUCK_AFTER_S:
            parts.append(
                f"WARNING: no output in {idle:.0f}s — Hermes may be stuck; "
                f"consider cancel_hermes('{job.job_id}')"
            )
    return ", ".join(parts)


def _format_completed_output(job: HermesJob) -> str:
    stdout = _truncate("\n".join(job.stdout_lines).strip())
    stderr = _truncate("\n".join(job.stderr_lines).strip(), limit=4_000)

    output_path_line = (
        f"Full output saved to {job.output_path}.\n" if job.output_path else ""
    )
    header = (
        f"Hermes job {job.job_id} {job.status} (exit {job.rc}). "
        f"Prompt: {job.prompt_path}.\n{output_path_line}"
        f"--- Hermes stdout ---"
    )
    body = stdout if stdout else "(no stdout)"
    err_block = f"\n\n--- Hermes stderr ---\n{stderr}" if stderr else ""

    guidance = (
        "\n\n--- How to read this ---\n"
        "The text above is exactly what Hermes printed. If it asks a question, "
        "requests approval, or says it needs more information, do NOT silently "
        "retry \u2014 respond to the user with what Hermes is asking, gather the "
        "missing detail, then call invoke_hermes again with a refined `goal` "
        "or expanded `context`. If it announces success and a file path, you "
        "can confirm to the user and move on."
    )

    if job.status == "completed":
        return f"{header}\n{body}{err_block}{guidance}"

    if job.status == "timeout":
        return (
            f"{header}\n{body}{err_block}\n\n"
            f"Hermes was killed after exceeding the timeout. The output above "
            f"is whatever it produced before being killed. Consider a smaller "
            "task or a longer timeout."
        )

    if job.status == "cancelled":
        return (
            f"{header}\n{body}{err_block}\n\n"
            "Hermes was cancelled before completion."
        )

    # failed
    err_extra = f" Error: {job.error}." if job.error else ""
    return (
        f"{header}\n{body}{err_block}{guidance}\n\n"
        f"Hermes exited non-zero ({job.rc}).{err_extra} Inspect the output "
        "above; if it is recoverable (e.g. a missing dependency Hermes named, "
        "or a clarification request), fix the input and call invoke_hermes "
        "again with a refined prompt."
    )


# ────────────────────────────────────────────────────────────────────────────
# Tool handlers
# ────────────────────────────────────────────────────────────────────────────

async def handle_invoke_hermes(
    session_id: str,
    goal: str,
    context: str,
    file_paths: list[str] | None = None,
    output_target: str = "",
    constraints: str = "",
    timeout_s: int = DEFAULT_TIMEOUT_S,
    manager: Optional[ConnectionManager] = None,
) -> str:
    """Spawn a Hermes job in the background and return its job_id immediately.

    The agent loop is NOT blocked. The model is expected to either:
      (a) continue with other work and call check_hermes(job_id) later, or
      (b) call check_hermes(job_id, wait_s=N) to block briefly for the result.
    """
    file_paths = file_paths or []

    if not goal.strip():
        return (
            "ERROR: `goal` is required. Describe what Hermes should produce in "
            "one or two sentences (e.g. 'Create a 12-slide PowerPoint about X')."
        )
    if not context.strip() and not file_paths:
        return (
            "ERROR: Hermes will not have access to anything Emu saw on screen. "
            "You MUST pass either `context` (paste every relevant fact, quote, "
            "number, decision, URL you gathered) or `file_paths` (absolute "
            "paths to files Hermes can read), or both. Re-call this tool with "
            "the full context."
        )

    hermes_bin = _resolve_hermes_bin()
    if hermes_bin is None:
        return _install_guidance()

    # Persist the prompt for traceability. Pairs with task_result_NN.md once
    # the job finishes (written by hermes_jobs._persist_output). The lock
    # serializes brief-index allocation per session so concurrent calls
    # never collide on task_brief_NN.md.
    async with _brief_lock(session_id):
        filename = _next_brief_filename(session_id)
        prompt_doc = _build_prompt_document(
            goal=goal,
            context=context,
            file_paths=file_paths,
            output_target=output_target,
            constraints=constraints,
        )
        prompt_path: Path = write_session_file(session_id, filename, prompt_doc)

        job = hermes_jobs.start_job(
            session_id=session_id,
            goal=goal,
            prompt=prompt_doc,
            prompt_path=prompt_path,
            hermes_bin=hermes_bin,
            env=_augmented_env(),
            timeout_s=timeout_s,
            manager=manager,
        )

    return (
        f"Hermes job started: job_id=`{job.job_id}` (timeout {timeout_s}s).\n"
        f"Prompt saved to {prompt_path}.\n\n"
        "Hermes is running in the background — Emu is NOT blocked. Choose one:\n"
        f"  • If you have nothing else to do for the user, call "
        f"`check_hermes(job_id='{job.job_id}', wait_s=60)` to wait up to 60s "
        "for the result. Repeat with longer waits if still running.\n"
        "  • Otherwise, continue helping the user (answer questions, do other "
        f"desktop work) and periodically call `check_hermes('{job.job_id}')` "
        "to see if it finished.\n"
        "  • If the user wants to abort, call "
        f"`cancel_hermes('{job.job_id}')`.\n\n"
        "Tell the user what you delegated to Hermes so they know to expect a "
        "short delay."
    )


async def handle_check_hermes(
    job_id: str,
    wait_s: float = 0.0,
) -> str:
    """Return the current state of a Hermes job; optionally wait briefly."""
    if not job_id:
        return (
            "ERROR: `job_id` is required. Call list_hermes_jobs() to see the "
            "ids of jobs in the current session."
        )

    job = hermes_jobs.get_job(job_id)
    if job is None:
        return (
            f"ERROR: no Hermes job with id '{job_id}'. Call list_hermes_jobs() "
            "to see what's running in this session."
        )

    # Bound the wait so the model can't accidentally hang the loop forever.
    wait_s = max(0.0, min(float(wait_s), 300.0))
    if wait_s > 0 and not job.done_event.is_set():
        await hermes_jobs.wait_for_job(job, wait_s)

    if job.done_event.is_set():
        return _format_completed_output(job)

    # Still running — return a status snapshot plus the most recent stdout
    # lines so the model can see progress without spamming polls.
    tail = "\n".join(job.stdout_lines[-20:]).strip() or "(no stdout yet)"
    return (
        f"Hermes job {job.job_id} status: **{job.status}** "
        f"({_liveness_blurb(job)}).\n"
        f"Goal: {job.goal}\n"
        f"--- recent stdout (last 20 lines) ---\n{tail}\n\n"
        "Hermes is still working. Either continue with other tasks and check "
        "again later, or call check_hermes again with a larger wait_s."
    )


async def handle_cancel_hermes(job_id: str) -> str:
    """Terminate a running Hermes job."""
    if not job_id:
        return "ERROR: `job_id` is required."
    job = hermes_jobs.cancel_job(job_id)
    if job is None:
        return f"ERROR: no Hermes job with id '{job_id}'."
    if job.done_event.is_set():
        return (
            f"Hermes job {job_id} was already finished with status "
            f"'{job.status}' — nothing to cancel."
        )
    return (
        f"Cancellation requested for Hermes job {job_id}. "
        "Call check_hermes shortly to confirm it terminated."
    )


def handle_list_hermes_jobs(session_id: str) -> str:
    """One-line-per-job summary of every Hermes job in this session."""
    jobs = hermes_jobs.list_jobs(session_id)
    if not jobs:
        return "No Hermes jobs have been started in this session."
    rows = []
    for j in jobs:
        runtime = (j.finished_at or time.time()) - j.started_at
        rows.append(
            f"- `{j.job_id}` [{j.status}] runtime={runtime:.1f}s "
            f"goal={j.goal[:80]!r}"
        )
    return "Hermes jobs in this session:\n" + "\n".join(rows)
