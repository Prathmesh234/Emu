"""
utilities/paths.py

Canonical .emu path resolution.

Every part of the codebase that needs to reference .emu/ (or any path
derived from it) should import from here instead of computing its own.
"""

from pathlib import Path

# ── Project root discovery ────────────────────────────────────────────────────
# backend/ is one level below the project root (which contains .emu/).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent


# ── Cached resolved paths ────────────────────────────────────────────────────
# Resolved once at import time so every caller gets the same value.

def get_project_root() -> Path:
    """Return the absolute project root (parent of ``backend/``)."""
    return _PROJECT_ROOT


def get_emu_path() -> Path:
    """Return the absolute path to the ``.emu`` directory.

    This is the canonical accessor — use it everywhere instead of
    manually joining ``project_root / ".emu"``.
    """
    return _PROJECT_ROOT / ".emu"


def get_emu_path_str() -> str:
    """Return `.emu` as a string path.

    Use this when you need to embed the path in a prompt, log message,
    or any string destined for the shell / the Electron frontend.
    """
    return str(get_emu_path())


def get_project_root_str() -> str:
    """Return the project root as a string."""
    return str(_PROJECT_ROOT)
