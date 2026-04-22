"""
tools/shell.py

Guardrailed `shell_exec` tool (backend function tool, NOT a desktop action).

Guardrails:
  1. cwd pinned to the .emu directory (via utilities.paths.get_emu_path).
  2. HOME env rewritten to .emu so `~/foo` lands inside .emu.
  3. Every absolute-path token in the command must resolve inside .emu, with
     a small allowlist for interpreter binaries (/bin, /usr/bin,
     /usr/local/bin, /opt/homebrew/bin). Relative paths resolve against cwd.
  4. Blocklist rejects network tools (curl/wget/ssh/scp/nc/rsync/ftp/telnet),
     privilege escalation (sudo/su), destructive commands (rm -rf, mkfs, dd,
     chmod/chown, kill/pkill/killall, launchctl/systemctl, mount/umount),
     pipe-to-shell (| bash), eval/source.
  5. 30s timeout, 100 KB combined output cap.

Defense-in-depth only: an interpreter call like `python3 -c "..."` can still
embed arbitrary paths in strings. For true FS sandboxing use sandbox-exec.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from utilities.paths import get_emu_path


_TIMEOUT_S = 30
_MAX_OUTPUT_BYTES = 100 * 1024

_BLOCKED_TOKENS = {
    "curl", "wget", "nc", "ncat", "socat",
    "ssh", "scp", "sftp", "rsync", "ftp", "tftp", "telnet",
    "sudo", "su", "doas",
    "mkfs", "dd", "fdisk", "diskutil", "mount", "umount",
    "shutdown", "reboot", "halt", "poweroff",
    "launchctl", "systemctl", "service",
    "kill", "pkill", "killall",
    "chmod", "chown", "chgrp",
    "eval", "source",
}

_BLOCKED_PATTERNS = [
    re.compile(r"\brm\s+-[rfRF]{1,2}\b"),
    re.compile(r"\|\s*(bash|sh|zsh|ksh)\b"),
    re.compile(r"\b(bash|sh|zsh|ksh)\s+<\("),
    re.compile(r">\s*/dev/"),
    re.compile(r"^\s*:\s*\(\s*\)\s*\{"),
]

_ALLOWED_BIN_PREFIXES = (
    "/bin/", "/sbin/", "/usr/bin/", "/usr/sbin/",
    "/usr/local/bin/", "/usr/local/sbin/",
    "/opt/homebrew/bin/", "/opt/homebrew/sbin/",
)


def _reject(reason: str) -> str:
    return (
        f"ERROR: shell_exec refused to run — {reason}\n\n"
        f"shell_exec guardrails:\n"
        f"  • cwd is pinned to .emu; only .emu paths are allowed.\n"
        f"  • Blocked: curl/wget/ssh/scp/nc, sudo/su, rm -rf, chmod/chown,\n"
        f"    kill/pkill/killall, launchctl/systemctl, mount/umount,\n"
        f"    mkfs/dd, pipe-to-shell (| bash), eval/source.\n"
        f"  • 30s timeout, 100 KB output cap.\n"
        f"Rewrite to stay within these rules, or use another tool "
        f"(read_session_file, write_session_file, read_memory, etc.)."
    )


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _paths_in_scope(command: str, emu_dir: Path) -> tuple[bool, str]:
    emu_resolved = emu_dir.resolve()
    for tok in _tokens(command):
        expanded = os.path.expanduser(tok)
        if not expanded.startswith("/"):
            continue
        if any(expanded.startswith(p) for p in _ALLOWED_BIN_PREFIXES):
            continue
        try:
            resolved = Path(expanded).resolve()
        except (OSError, RuntimeError):
            return False, f"could not resolve path '{tok}'"
        try:
            resolved.relative_to(emu_resolved)
        except ValueError:
            return False, (
                f"path '{tok}' is outside the .emu directory "
                f"({emu_resolved}). shell_exec can only touch files under .emu."
            )
    return True, ""


def _violates_blocklist(command: str) -> tuple[bool, str]:
    lowered = command.lower()
    for pat in _BLOCKED_PATTERNS:
        if pat.search(lowered):
            return True, f"command matches blocked pattern ({pat.pattern!r})"
    for t in _tokens(command):
        base = os.path.basename(t).lower()
        if base in _BLOCKED_TOKENS:
            return True, f"command uses blocked program '{base}'"
    return False, ""


def handle_shell_exec(command: str) -> str:
    command = (command or "").strip()
    if not command:
        return "ERROR: shell_exec requires a non-empty 'command'."
    if len(command) > 4000:
        return _reject("command is longer than 4000 chars")

    bad, reason = _violates_blocklist(command)
    if bad:
        return _reject(reason)

    emu_dir = get_emu_path()
    emu_dir.mkdir(parents=True, exist_ok=True)

    ok, reason = _paths_in_scope(command, emu_dir)
    if not ok:
        return _reject(reason)

    safe_env = {
        "PATH": os.environ.get(
            "PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin",
        ),
        "HOME": str(emu_dir),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "en_US.UTF-8"),
        "EMU_DIR": str(emu_dir),
    }

    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", command],
            cwd=str(emu_dir),
            env=safe_env,
            capture_output=True,
            timeout=_TIMEOUT_S,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: shell_exec timed out after {_TIMEOUT_S}s. Command: {command}"
    except Exception as e:
        return f"ERROR: shell_exec failed to launch: {e}"

    out = proc.stdout or ""
    err = proc.stderr or ""
    combined = out + (("\n" + err) if err else "")
    if len(combined) > _MAX_OUTPUT_BYTES:
        combined = combined[:_MAX_OUTPUT_BYTES] + f"\n…[truncated at {_MAX_OUTPUT_BYTES} bytes]"

    header = f"[shell_exec exit={proc.returncode} cwd={emu_dir}]"
    if not combined.strip():
        return f"{header}\n(no output)"
    return f"{header}\n{combined}"
