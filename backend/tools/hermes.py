"""
backend/tools/hermes.py

Handler for the `invoke_hermes` agent tool.

Hermes Agent (Nous Research, https://hermes-agent.nousresearch.com) is an
autonomous terminal agent installed locally. It exposes a documented
non-interactive single-query mode:

    hermes chat -q "<prompt>"

This handler runs Hermes headlessly via that command — Emu does NOT have to
focus a terminal window. The full prompt (everything Emu has gathered) is
passed as an argument, and Hermes's stdout is captured and returned to Emu.

The full prompt is also persisted to the session directory as
`hermes_prompt_NN.md` for traceability/debugging.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from utilities.paths import get_emu_path_str
from workspace import write_session_file


HERMES_BIN = "hermes"
DEFAULT_TIMEOUT_S = 600   # 10 minutes — Hermes can be slow on big tasks
MAX_OUTPUT_CHARS = 60_000  # truncate huge stdouts before returning to Emu

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
    # Prepend extras, dropping anything already present to avoid duplicates.
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


async def _run_hermes(prompt: str, timeout_s: int) -> tuple[int, str, str]:
    """Run `hermes chat -q <prompt>` and return (returncode, stdout, stderr).

    stdin is closed (DEVNULL) so Hermes cannot block waiting on an inherited
    stdin if it ever decides to prompt for confirmation. Anything Hermes wants
    to say back — including "need more info" / "please clarify X" — will come
    out on stdout (or stderr) and is returned verbatim to the agent loop.
    """
    hermes_bin = _resolve_hermes_bin() or HERMES_BIN
    proc = await asyncio.create_subprocess_exec(
        hermes_bin,
        "chat",
        "-q",
        prompt,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_augmented_env(),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise

    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


async def handle_invoke_hermes(
    session_id: str,
    goal: str,
    context: str,
    file_paths: list[str] | None = None,
    output_target: str = "",
    constraints: str = "",
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> str:
    """Execute Hermes headlessly and return its stdout to Emu."""
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

    if _resolve_hermes_bin() is None:
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

    # Persist the prompt for traceability.
    from workspace import list_session_files
    existing = [f for f in list_session_files(session_id) if f.startswith("hermes_prompt_")]
    idx = len(existing) + 1
    filename = f"hermes_prompt_{idx:02d}.md"

    prompt_doc = _build_prompt_document(
        goal=goal,
        context=context,
        file_paths=file_paths,
        output_target=output_target,
        constraints=constraints,
    )
    prompt_path: Path = write_session_file(session_id, filename, prompt_doc)

    # Run Hermes headlessly.
    try:
        rc, stdout, stderr = await _run_hermes(prompt_doc, timeout_s)
    except asyncio.TimeoutError:
        return (
            f"ERROR: Hermes did not finish within {timeout_s}s and was killed. "
            f"Prompt was saved to {prompt_path}. Try a smaller, more focused "
            "task or raise the timeout."
        )
    except FileNotFoundError:
        return (
            "ERROR: failed to launch `hermes` — binary disappeared between the "
            "PATH check and exec. Verify the install."
        )

    stdout = _truncate(stdout.strip())
    stderr = _truncate(stderr.strip(), limit=4_000)

    header = (
        f"Hermes finished (exit {rc}). Prompt saved to {prompt_path}.\n"
        f"--- Hermes stdout ---"
    )
    body = stdout if stdout else "(no stdout)"
    err_block = f"\n\n--- Hermes stderr ---\n{stderr}" if stderr else ""

    # Treat Hermes's reply as the tool result. If Hermes asked a clarifying
    # question, requested approval, or reported partial progress, that text
    # is in `body` — the agent loop should read it and respond accordingly
    # (typically: ask the user, gather the missing info, re-invoke with a
    # refined `goal` / `context`).
    guidance = (
        "\n\n--- How to read this ---\n"
        "The text above is exactly what Hermes printed. If it asks a question, "
        "requests approval, or says it needs more information, do NOT silently "
        "retry \u2014 respond to the user with what Hermes is asking, gather the "
        "missing detail, then call invoke_hermes again with a refined `goal` "
        "or expanded `context`. If it announces success and a file path, you "
        "can confirm to the user and move on."
    )

    if rc != 0:
        return (
            f"{header}\n{body}{err_block}{guidance}\n\n"
            f"Hermes exited non-zero ({rc}). Inspect the output above; if it "
            "is recoverable (e.g. a missing dependency Hermes named, or a "
            "clarification request), fix the input and call invoke_hermes "
            "again with a refined prompt."
        )

    return f"{header}\n{body}{err_block}{guidance}"
