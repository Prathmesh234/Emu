"""
backend/workspace/reader.py

Reads .emu/ files and builds context for injection into the system prompt.

Injection tiers:
  FIRMWARE (always injected, every request):
    SOUL.md, AGENTS.md, USER.md, IDENTITY.md, global/preferences.md

  CONDITIONAL (injected at session start, gated):
    MEMORY.md — skip for lightweight tasks; truncate if >2-3k tokens
    memory/YYYY-MM-DD.md — today + yesterday only

  TOOL-ACCESSIBLE (agent reads via shell_exec when needed):
    memory/YYYY-MM-DD.md older than yesterday
    sessions/<id>/*
    Older MEMORY.md chunks (future: vector retrieval)

The .emu/ folder lives at the project root (one level above backend/).
Missing files are silently skipped.
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


# .emu/ is at the project root, one directory above backend/
_BACKEND_DIR   = Path(__file__).resolve().parent.parent
_PROJECT_ROOT  = _BACKEND_DIR.parent
_EMU_DIR       = _PROJECT_ROOT / ".emu"
_WORKSPACE_DIR = _EMU_DIR / "workspace"
_GLOBAL_DIR    = _EMU_DIR / "global"
_SESSIONS_DIR  = _EMU_DIR / "sessions"
_MANIFEST_PATH = _EMU_DIR / "manifest.json"

# ── Tier 1: Firmware (always injected) ──────────────────────────────────────
FIRMWARE_FILES = [
    ("SOUL.md",        _WORKSPACE_DIR / "SOUL.md"),
    ("AGENTS.md",      _WORKSPACE_DIR / "AGENTS.md"),
    ("TOOLS.md",       _WORKSPACE_DIR / "TOOLS.md"),
    ("USER.md",        _WORKSPACE_DIR / "USER.md"),
    ("IDENTITY.md",    _WORKSPACE_DIR / "IDENTITY.md"),
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


def _read_file(filepath: Path) -> Optional[str]:
    """Read a file, return content or None.

    Falls back to cp1252 if UTF-8 decoding fails — handles files that
    may have been created with non-UTF-8 encoding.
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
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
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
        manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
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
    session_dir = _SESSIONS_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "screenshots").mkdir(exist_ok=True)
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


# ── Manifest / Device Details ────────────────────────────────────────────────

def read_manifest() -> Optional[dict]:
    """Read manifest.json and return the parsed dict, or None."""
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def get_device_details() -> dict:
    """Extract platform and device details from manifest.json for system prompt injection."""
    manifest = read_manifest()
    if not manifest:
        return {}
    result = {}
    platform = manifest.get("platform", {})
    if platform:
        result["os_name"] = platform.get("os_name", "macOS")
        result["arch"] = platform.get("arch", "unknown")
    device = manifest.get("device_details", {})
    if device:
        result["screen_width"] = device.get("screen_width")
        result["screen_height"] = device.get("screen_height")
        result["scale_factor"] = device.get("scale_factor")
    return result


# ── Builder ─────────────────────────────────────────────────────────────────

def build_workspace_context() -> str:
    """
    Build the full workspace context string for the system prompt.

    Concatenates:
      1. Firmware files (always)
      2. MEMORY.md (conditional)
      3. Today + yesterday daily logs (conditional)

    Returns empty string if nothing is available.
    """
    firmware = read_firmware()
    memory = read_memory()
    dailies = read_recent_daily_memories()

    if not firmware and not memory and not dailies:
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

    # Conditional — memory
    if memory:
        sections.append("── MEMORY (curated long-term) " + "─" * 46)
        sections.append("")
        sections.append(memory)
        sections.append("")

    # Conditional — recent daily logs
    if dailies:
        sections.append("── RECENT DAILY LOGS " + "─" * 54)
        sections.append("")
        for label, content in dailies.items():
            sections.append(f"┌─ {label} ─┐")
            sections.append(content)
            sections.append("")

    sections.append("═" * 75)
    sections.append("END WORKSPACE CONTEXT")
    sections.append("═" * 75)

    return "\n".join(sections)
