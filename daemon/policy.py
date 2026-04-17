"""
policy.py — Path resolution and write allowlist enforcement (Layer 2 security).

EMU_ROOT is resolved once at import from the EMU_ROOT env var (or $HOME/.emu).
Every path the LLM provides is realpath'd and checked against EMU_ROOT before
any I/O happens. check_write() is called twice per write: in the tool dispatcher
and again in the post-pass in run.py.
"""

import os
import re
from pathlib import Path


class PolicyError(Exception):
    pass


def _resolve_emu_root() -> Path:
    raw = os.environ.get("EMU_ROOT") or str(Path.home() / ".emu")
    p = Path(raw).expanduser()
    if not p.exists():
        raise RuntimeError(
            f"EMU_ROOT path does not exist: {p!r}. "
            "Set the EMU_ROOT environment variable to the correct .emu directory."
        )
    return p.resolve()


EMU_ROOT: Path = _resolve_emu_root()

WRITE_ALLOWLIST_FILES = frozenset({
    "workspace/AGENTS.md",
    "workspace/MEMORY.md",
    "workspace/USER.md",
    "workspace/IDENTITY.md",
})

WRITE_ALLOWLIST_PREFIXES = (
    "workspace/memory/",
    "global/daemon/",
)

_DAILY_LOG_RE = re.compile(r"^workspace/memory/\d{4}-\d{2}-\d{2}\.md$")

FORBIDDEN_FILES = frozenset({"workspace/SOUL.md"})


def _resolve_inside_emu(raw: str) -> Path:
    if not raw or not raw.strip():
        raise PolicyError("empty path")
    if "\x00" in raw:
        raise PolicyError("null byte in path")
    # Resolve relative to EMU_ROOT; realpath follows all symlinks
    candidate = (EMU_ROOT / raw.lstrip("/")).resolve(strict=False)
    try:
        candidate.relative_to(EMU_ROOT)
    except ValueError:
        raise PolicyError(f"path escapes .emu/: {raw!r}")
    return candidate


def check_read(raw: str) -> Path:
    """Validate a read path. Returns the resolved absolute Path."""
    return _resolve_inside_emu(raw)


def check_write(raw: str) -> Path:
    """
    Validate a write path against the allowlist.
    Raises PolicyError on any violation. Returns the resolved absolute Path.
    """
    resolved = _resolve_inside_emu(raw)
    rel = str(resolved.relative_to(EMU_ROOT))

    if rel in FORBIDDEN_FILES:
        raise PolicyError(f"write to {rel!r} is forbidden")

    if rel in WRITE_ALLOWLIST_FILES:
        return resolved

    if any(rel.startswith(prefix) for prefix in WRITE_ALLOWLIST_PREFIXES):
        if rel.startswith("workspace/memory/") and not _DAILY_LOG_RE.match(rel):
            raise PolicyError(
                f"invalid daily-log filename {rel!r}: must be workspace/memory/YYYY-MM-DD.md"
            )
        return resolved

    raise PolicyError(f"write target not in allowlist: {rel!r}")
