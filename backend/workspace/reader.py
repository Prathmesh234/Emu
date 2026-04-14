"""
backend/workspace/reader.py

Reads .emu/ files and builds context for injection into the system prompt.

Injection tiers:
  FIRMWARE (always injected, every request):
    SOUL.md, AGENTS.md, USER.md, IDENTITY.md, global/preferences.md

  CONDITIONAL (injected at session start, gated):
    MEMORY.md — skip for lightweight tasks; truncate if >2-3k tokens

  TOOL-ACCESSIBLE (agent reads via read_memory/shell_exec when needed):
    memory/YYYY-MM-DD.md — all daily logs (not auto-injected)
    sessions/<id>/*
    Older MEMORY.md chunks (future: vector retrieval)

The .emu/ folder lives at the project root (one level above backend/).
Missing files are silently skipped.
"""

import json
import platform
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

from skills import format_skills_for_prompt


# .emu/ is at the project root, one directory above backend/
from utilities.paths import get_emu_path, get_project_root

_PROJECT_ROOT  = get_project_root()
_EMU_DIR       = get_emu_path()
_WORKSPACE_DIR = _EMU_DIR / "workspace"
_GLOBAL_DIR    = _EMU_DIR / "global"
_SESSIONS_DIR  = _EMU_DIR / "sessions"
_MANIFEST_PATH = _EMU_DIR / "manifest.json"

# ── Tier 1: Firmware (always injected) ──────────────────────────────────────
# Ordered for cache efficiency: static files first, user-dependent files last.
# The system prompt + early firmware form a stable prefix that LLMs can cache.
FIRMWARE_FILES = [
    ("SOUL.md",        _WORKSPACE_DIR / "SOUL.md"),
    ("AGENTS.md",      _WORKSPACE_DIR / "AGENTS.md"),
    ("IDENTITY.md",    _WORKSPACE_DIR / "IDENTITY.md"),
    ("USER.md",        _WORKSPACE_DIR / "USER.md"),
    ("preferences.md", _GLOBAL_DIR / "preferences.md"),
]

# ── Tier 2: Conditional (injected when appropriate) ─────────────────────────
MEMORY_FILE = _WORKSPACE_DIR / "MEMORY.md"
MEMORY_TOKEN_LIMIT = 3000  # rough char proxy (~4 chars/token → 12k chars)

# ── Migration: root-level .emu/*.md → .emu/workspace/*.md ──────────────────
# Early versions (or the agent itself) sometimes wrote USER.md / IDENTITY.md
# to .emu/ instead of .emu/workspace/. If the root copy has non-template
# content and the workspace copy is still the default, migrate it over.
_MIGRATABLE_FILES = ["USER.md", "IDENTITY.md"]

def _migrate_root_to_workspace():
    """One-time migration of misplaced root-level .emu/*.md files."""
    for name in _MIGRATABLE_FILES:
        root_file = _EMU_DIR / name
        ws_file = _WORKSPACE_DIR / name
        if not root_file.exists():
            continue
        root_content = _read_file_raw(root_file)
        if not root_content or len(root_content.strip()) < 20:
            continue  # empty or trivial — nothing to migrate
        ws_content = _read_file_raw(ws_file)
        # Only migrate if the workspace copy is shorter (still template)
        if ws_content and len(ws_content.strip()) >= len(root_content.strip()):
            continue
        try:
            ws_file.write_text(root_content, encoding="utf-8")
            print(f"[workspace] migrated .emu/{name} → .emu/workspace/{name}")
        except OSError as e:
            print(f"[workspace] migration failed for {name}: {e}")

def _read_file_raw(filepath: Path) -> Optional[str]:
    """Read file content without stripping, for migration comparison."""
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return filepath.read_text(encoding="cp1252")
        except (FileNotFoundError, PermissionError, OSError):
            return None
    except (FileNotFoundError, PermissionError, OSError):
        return None

# Run migration on module load (idempotent)
_migrate_root_to_workspace()


def get_workspace_dir() -> Path:
    return _WORKSPACE_DIR


def get_sessions_dir() -> Path:
    return _SESSIONS_DIR


def get_device_details() -> dict:
    """Return basic device info for injection into the system prompt."""
    os_name = platform.system()  # 'Windows', 'Darwin', 'Linux'
    if os_name == "Darwin":
        os_name = "macOS"
    return {
        "os_name": os_name,
        "arch": platform.machine(),
    }


def _read_file(filepath: Path) -> Optional[str]:
    """Read a file, return content or None.

    Falls back to cp1252 (Windows default) if UTF-8 decoding fails —
    PowerShell's Set-Content writes ANSI by default.
    """
    try:
        return filepath.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        try:
            return filepath.read_text(encoding="cp1252").strip()
        except (FileNotFoundError, PermissionError, OSError):
            return None
    except (FileNotFoundError, PermissionError, OSError):
        return None


# ── Tier 1: Firmware ────────────────────────────────────────────────────────

def read_firmware() -> dict[str, str]:
    """Read all firmware files. Returns {label: content} for those that exist."""
    result: dict[str, str] = {}
    for label, filepath in FIRMWARE_FILES:
        content = _read_file(filepath)
        if content:
            result[label] = content
    return result


# ── Tier 2: Conditional ────────────────────────────────────────────────────

def read_memory() -> Optional[str]:
    """
    Read MEMORY.md. Returns None if missing or empty.
    Truncates to MEMORY_TOKEN_LIMIT chars if too large.
    """
    content = _read_file(MEMORY_FILE)
    if not content:
        return None
    if len(content) > MEMORY_TOKEN_LIMIT * 4:
        content = content[:MEMORY_TOKEN_LIMIT * 4] + "\n\n[... truncated — MEMORY.md exceeds context budget ...]"
    return content


def read_daily_memory(date: Optional[str] = None) -> Optional[str]:
    """Read a daily memory log by date (YYYY-MM-DD). Defaults to today."""
    import re
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    # Validate date format to prevent path traversal (e.g. "../../.auth_token")
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return None
    filepath = _WORKSPACE_DIR / "memory" / f"{date}.md"
    return _read_file(filepath)


def read_recent_daily_memories() -> dict[str, str]:
    """Read today's and yesterday's daily memory logs."""
    result: dict[str, str] = {}
    today = datetime.now()
    for delta in (0, 1):
        d = (today - timedelta(days=delta)).strftime("%Y-%m-%d")
        content = read_daily_memory(d)
        if content:
            result[f"memory/{d}.md"] = content
    return result


# ── Bootstrap ───────────────────────────────────────────────────────────────

def is_bootstrap_needed() -> bool:
    """Check if the first-launch interview hasn't been completed yet."""
    try:
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8-sig"))
        return not manifest.get("bootstrap_complete", False)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # If manifest is missing or corrupt, assume bootstrap is needed
        return True


def read_bootstrap() -> Optional[str]:
    """Read BOOTSTRAP.md content for injection during bootstrap mode."""
    return _read_file(_WORKSPACE_DIR / "BOOTSTRAP.md")


# ── Session files ───────────────────────────────────────────────────────────

def ensure_session_dir(session_id: str) -> Path:
    """Create and return the session directory: .emu/sessions/<id>/."""
    # Validate session_id format (UUID) to prevent path traversal
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', session_id):
        raise ValueError(f"Invalid session_id format: {session_id}")
    session_dir = _SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def write_session_plan(session_id: str, plan: str) -> Path:
    """Write (or overwrite) the session plan.md."""
    session_dir = ensure_session_dir(session_id)
    plan_path = session_dir / "plan.md"
    plan_path.write_text(plan, encoding="utf-8")
    return plan_path


def read_session_plan(session_id: str) -> Optional[str]:
    """Read a session's plan.md, if it exists."""
    return _read_file(_SESSIONS_DIR / session_id / "plan.md")


def append_session_notes(session_id: str, note: str) -> Path:
    """Append to the session's notes.md."""
    session_dir = ensure_session_dir(session_id)
    notes_path = session_dir / "notes.md"
    with open(notes_path, "a", encoding="utf-8") as f:
        f.write(note + "\n")
    return notes_path


def write_session_file(session_id: str, filename: str, content: str) -> Path:
    """Write an arbitrary file into the session directory."""
    session_dir = ensure_session_dir(session_id)
    file_path = (session_dir / filename).resolve()
    # Prevent path traversal — resolved path must stay within session dir
    if not str(file_path).startswith(str(session_dir.resolve())):
        raise ValueError(f"Path traversal blocked: {filename}")
    file_path.write_text(content, encoding="utf-8")
    return file_path


def read_session_file(session_id: str, filename: str) -> Optional[str]:
    """Read an arbitrary file from the session directory."""
    session_dir = _SESSIONS_DIR / session_id
    file_path = (session_dir / filename).resolve()
    # Prevent path traversal — resolved path must stay within session dir
    if not str(file_path).startswith(str(session_dir.resolve())):
        return None
    return _read_file(file_path)


def list_session_files(session_id: str) -> list[str]:
    """List filenames in a session directory."""
    session_dir = _SESSIONS_DIR / session_id
    if not session_dir.is_dir():
        return []
    return [f.name for f in session_dir.iterdir() if f.is_file()]


# ── Builder ─────────────────────────────────────────────────────────────────

def build_workspace_context() -> str:
    """
    Build the full workspace context string for the system prompt.

    Concatenates:
      1. Firmware files (always)
      2. MEMORY.md (conditional)

    Daily logs are NOT auto-injected — the agent reads them
    on demand via read_memory tool or shell_exec.

    Returns empty string if nothing is available.
    """
    firmware = read_firmware()
    memory = read_memory()

    if not firmware and not memory:
        return ""

    today = datetime.now().strftime("%Y-%m-%d")
    sections: list[str] = []

    sections.append("═" * 75)
    sections.append("WORKSPACE CONTEXT (loaded from .emu/)")
    sections.append("═" * 75)
    sections.append(f"Date: {today}")
    sections.append("")

    # Firmware — always present
    if firmware:
        sections.append("── FIRMWARE (identity layer) " + "─" * 47)
        sections.append("")
        for label, content in firmware.items():
            sections.append(f"┌─ {label} ─┐")
            sections.append(content)
            sections.append("")

    # Skills — always present (names + descriptions only, bodies loaded on demand)
    skills_block = format_skills_for_prompt()
    if skills_block:
        sections.append("── SKILLS (use use_skill to load) " + "─" * 42)
        sections.append("")
        sections.append(skills_block)
        sections.append("")

    # Conditional — memory
    if memory:
        sections.append("── MEMORY (curated long-term) " + "─" * 46)
        sections.append("")
        sections.append(memory)
        sections.append("")

    sections.append("═" * 75)
    sections.append("END WORKSPACE CONTEXT")
    sections.append("═" * 75)

    return "\n".join(sections)
