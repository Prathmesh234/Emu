"""
backend/tools/hermes_jobs.py

Async job registry for `invoke_hermes`.

Hermes Agent (Nous Research) can take many minutes to complete a task. Blocking
the Emu agent loop for that whole window inside a single tool call is bad:
- the FastAPI step request is held open,
- the user sees a frozen UI,
- only one Hermes job can run at a time,
- and `proc.communicate()` deadlocks if Hermes writes more than the OS pipe
  buffer (~64KB) to stderr before exiting, which is almost certainly why Emu
  was "never receiving the final output" today.

This module spawns Hermes as a background asyncio subprocess, drains stdout
and stderr line-by-line into in-memory buffers, and exposes a job_id for the
agent loop to poll via `check_hermes`. Live lines are also pushed over the
session WebSocket as `hermes_progress` events.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from utilities.connection import ConnectionManager
from workspace import write_session_file


# Liveness threshold — used by check_hermes to flag jobs that may be stuck.
STUCK_AFTER_S = 120

JobStatus = str  # "starting" | "running" | "completed" | "failed" | "cancelled" | "timeout"


@dataclass
class HermesJob:
    job_id: str
    session_id: str
    goal: str
    timeout_s: int
    prompt_path: Path
    started_at: float
    status: JobStatus = "starting"
    proc: Optional[asyncio.subprocess.Process] = None
    stdout_lines: list[str] = field(default_factory=list)
    stderr_lines: list[str] = field(default_factory=list)
    last_output_at: float = 0.0
    finished_at: Optional[float] = None
    rc: Optional[int] = None
    output_path: Optional[Path] = None
    error: Optional[str] = None
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None


# session_id -> { job_id -> HermesJob }
_JOBS: dict[str, dict[str, HermesJob]] = {}


def _register(job: HermesJob) -> None:
    _JOBS.setdefault(job.session_id, {})[job.job_id] = job


def get_job(job_id: str) -> Optional[HermesJob]:
    for session_jobs in _JOBS.values():
        if job_id in session_jobs:
            return session_jobs[job_id]
    return None


def list_jobs(session_id: str) -> list[HermesJob]:
    return list(_JOBS.get(session_id, {}).values())


def _new_job_id() -> str:
    return f"hermes-{uuid.uuid4().hex[:8]}"


async def _drain_stream(
    stream: asyncio.StreamReader,
    buf: list[str],
    job: HermesJob,
    stream_name: str,
    manager: Optional[ConnectionManager],
) -> None:
    """Read a subprocess stream line-by-line into `buf`.

    Critical: we MUST drain both stdout and stderr concurrently, otherwise a
    full pipe buffer on one stream blocks the subprocess from exiting and
    `proc.wait()` hangs forever. This is the deadlock that caused the previous
    sync implementation to silently lose Hermes output on long runs.

    We deliberately do NOT await any WebSocket send here — a slow/backed-up
    client would suspend this coroutine, stop draining the pipe, and re-create
    the exact deadlock above. Per-line progress events were dropped for the
    same reason; the model gets recent stdout via `check_hermes` snapshots
    and the frontend gets a single `hermes_done` event when the job ends.
    """
    while True:
        try:
            line = await stream.readline()
        except Exception as exc:  # pragma: no cover — defensive
            buf.append(f"[stream read error: {exc}]")
            return
        if not line:
            return
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        buf.append(text)
        job.last_output_at = time.time()


def _build_output_doc(job: HermesJob) -> str:
    duration = (job.finished_at or time.time()) - job.started_at
    parts = [
        f"# Hermes job {job.job_id}",
        "",
        f"- session: `{job.session_id}`",
        f"- status: **{job.status}**",
        f"- exit code: `{job.rc}`",
        f"- duration: {duration:.1f}s",
        f"- prompt: `{job.prompt_path}`",
        f"- goal: {job.goal}",
        "",
        "## stdout",
        "```",
        "\n".join(job.stdout_lines) if job.stdout_lines else "(empty)",
        "```",
        "",
        "## stderr",
        "```",
        "\n".join(job.stderr_lines) if job.stderr_lines else "(empty)",
        "```",
        "",
    ]
    return "\n".join(parts)


def _persist_output(job: HermesJob) -> None:
    """Write the captured Hermes output next to its task brief.

    Brief lives at `<session>/hermes/task_brief_NN.md`; we mirror the index
    into `<session>/hermes/task_result_NN.md` so each invocation has a paired
    brief+result on disk.
    """
    try:
        # job.prompt_path looks like ".../hermes/task_brief_03.md".
        # Derive the matching result filename and write into the same folder.
        stem = job.prompt_path.stem  # "task_brief_03"
        suffix = stem.replace("task_brief_", "")
        relative = f"{job.prompt_path.parent.name}/task_result_{suffix}.md"
        job.output_path = write_session_file(
            job.session_id, relative, _build_output_doc(job)
        )
    except Exception as exc:
        job.error = f"failed to persist output: {exc}"


async def _run_job(
    job: HermesJob,
    hermes_bin: str,
    prompt: str,
    env: dict[str, str],
    manager: Optional[ConnectionManager],
) -> None:
    """Background task: run Hermes, drain pipes, update job state, notify."""
    try:
        proc = await asyncio.create_subprocess_exec(
            hermes_bin,
            "chat",
            "-Q",          # quiet: suppress banner/spinner/tool previews
            "-q",
            prompt,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        job.status = "failed"
        job.error = f"hermes binary not found at exec time: {exc}"
        job.finished_at = time.time()
        job.done_event.set()
        return
    except Exception as exc:
        job.status = "failed"
        job.error = f"failed to spawn hermes: {exc}"
        job.finished_at = time.time()
        job.done_event.set()
        return

    job.proc = proc
    job.status = "running"
    job.last_output_at = time.time()

    drain_stdout = asyncio.create_task(
        _drain_stream(proc.stdout, job.stdout_lines, job, "stdout", manager)
    )
    drain_stderr = asyncio.create_task(
        _drain_stream(proc.stderr, job.stderr_lines, job, "stderr", manager)
    )

    try:
        await asyncio.wait_for(
            asyncio.gather(drain_stdout, drain_stderr, proc.wait()),
            timeout=job.timeout_s,
        )
        job.rc = proc.returncode if proc.returncode is not None else -1
        job.status = "completed" if job.rc == 0 else "failed"
    except asyncio.TimeoutError:
        job.status = "timeout"
        job.error = f"exceeded timeout of {job.timeout_s}s"
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        job.rc = proc.returncode if proc.returncode is not None else -1
        # Cancel drainers so we don't leak tasks.
        for t in (drain_stdout, drain_stderr):
            if not t.done():
                t.cancel()
    except asyncio.CancelledError:
        job.status = "cancelled"
        job.error = "cancelled"
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        job.rc = proc.returncode if proc.returncode is not None else -1
        for t in (drain_stdout, drain_stderr):
            if not t.done():
                t.cancel()
        # Don't re-raise: we've recorded the cancellation; let the task end
        # cleanly so finalization runs.
    except Exception as exc:
        job.status = "failed"
        job.error = f"unexpected error: {exc}"
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            await proc.wait()
        except Exception:
            pass
        job.rc = proc.returncode if proc.returncode is not None else -1
    finally:
        job.finished_at = time.time()
        _persist_output(job)
        job.done_event.set()
        if manager is not None:
            # Fire-and-forget: never block job finalization on a slow WS client.
            try:
                asyncio.create_task(manager.send(job.session_id, {
                    "type": "tool_event",
                    "event": "hermes_done",
                    "job_id": job.job_id,
                    "goal": job.goal,
                    "status": job.status,
                    "rc": job.rc,
                    "output_path": str(job.output_path) if job.output_path else None,
                }))
            except Exception:
                pass


def start_job(
    session_id: str,
    goal: str,
    prompt: str,
    prompt_path: Path,
    hermes_bin: str,
    env: dict[str, str],
    timeout_s: int,
    manager: Optional[ConnectionManager],
) -> HermesJob:
    """Spawn a background Hermes job and return the registered HermesJob."""
    job = HermesJob(
        job_id=_new_job_id(),
        session_id=session_id,
        goal=goal,
        timeout_s=timeout_s,
        prompt_path=prompt_path,
        started_at=time.time(),
    )
    _register(job)
    job.task = asyncio.create_task(
        _run_job(job, hermes_bin, prompt, env, manager)
    )
    return job


def cancel_job(job_id: str) -> Optional[HermesJob]:
    """Request cancellation. Returns the job (or None if unknown)."""
    job = get_job(job_id)
    if job is None:
        return None
    if job.done_event.is_set():
        return job
    if job.task is not None and not job.task.done():
        job.task.cancel()
    return job


async def wait_for_job(job: HermesJob, wait_s: float) -> bool:
    """Wait up to `wait_s` seconds for a job to finish. Returns True if done."""
    if wait_s <= 0:
        return job.done_event.is_set()
    try:
        await asyncio.wait_for(job.done_event.wait(), timeout=wait_s)
        return True
    except asyncio.TimeoutError:
        return False
