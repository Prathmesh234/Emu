import re
from pathlib import Path
from typing import Optional
from workspace import read_session_plan, write_session_plan, read_memory, read_daily_memory
from skills import get_skill_body
from utilities.paths import get_emu_path


def handle_read_plan(session_id: str) -> str:
    """Handle the model's read_plan tool call."""
    plan = read_session_plan(session_id)
    if plan:
        return f"[YOUR PLAN]\n{plan}"
    return "No plan.md found for this session. You may need to create one."


def handle_update_plan(session_id: str, content: str) -> str:
    """Handle the model's update_plan tool call."""
    if not content:
        return "No content provided for plan update."
    write_session_plan(session_id, content)
    return "Plan updated successfully."


def handle_read_memory(target: str = "long_term", date: str = "") -> str:
    """Handle the model's read_memory tool call."""
    try:
        if target == "long_term":
            content = read_memory()
            if content:
                return f"[MEMORY.md]\n{content}"
            return "MEMORY.md is empty or does not exist yet."
        elif target == "preferences":
            prefs_path = get_emu_path() / "global" / "preferences.md"
            if prefs_path.exists():
                content = prefs_path.read_text(encoding="utf-8").strip()
                if content:
                    return f"[preferences.md]\n{content}"
            return "preferences.md is empty or does not exist yet."
        elif target == "daily_log":
            content = read_daily_memory(date=date if date else None)
            label = date if date else "today"
            if content:
                return f"[Daily log for {label}]\n{content}"
            return f"No daily log found for {label}."
        else:
            return f"Unknown memory target: {target}. Use long_term, preferences, or daily_log."
    except Exception as e:
        return f"Memory read failed: {e}"


def handle_use_skill(skill_name: str) -> str:
    """Handle the model's use_skill tool call — load full skill body on demand."""
    from skills import load_skills
    available = [s.name for s in load_skills()]
    available_str = ", ".join(available) if available else "(none)"

    if not skill_name or skill_name.strip() in ("", ":", ": "):
        return (
            f"No valid skill name provided. "
            f"Available skills: {available_str}. "
            f"Call use_skill with one of these exact names."
        )
    body = get_skill_body(skill_name)
    if body:
        return f"[SKILL: {skill_name}]\n\n{body}"
    return (
        f"Skill '{skill_name}' not found. "
        f"Available skills: {available_str}. "
        f"Use one of these exact names."
    )


def _slugify_skill_name(raw: str) -> str:
    """Lowercase, hyphen-separated, filesystem-safe skill folder name."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _safe_relative_path(base: Path, candidate: str) -> Optional[Path]:
    """Resolve candidate under base, refusing path traversal or absolute paths."""
    candidate = candidate.strip().lstrip("/\\")
    if not candidate or ".." in candidate.replace("\\", "/").split("/"):
        return None
    target = (base / candidate).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def handle_create_skill(
    name: str,
    description: str,
    instructions: str,
    files: Optional[list[dict]] = None,
    overwrite: bool = False,
) -> str:
    """
    Create a new user skill under .emu/skills/<slug>/.

    The agent calls this to capture a specialized, user-personal workflow
    (e.g. "check my bank balance", "file my weekly expense report") so it
    can be reloaded later via use_skill.

    Args:
        name: Human-readable skill name; will be slugified for the folder.
        description: Frontmatter description — when to use this skill.
        instructions: Markdown body of SKILL.md (the actual procedure).
        files: Optional list of {"path": "scripts/run.py", "content": "..."}
               for scripts/, references/, or assets/ bundled with the skill.
        overwrite: If False (default), refuse to clobber an existing skill
                   with the same slug.
    """
    from skills import load_skills

    if not name or not name.strip():
        return "create_skill failed: 'name' is required."
    if not description or not description.strip():
        return "create_skill failed: 'description' is required (tells the agent when to use it)."
    if not instructions or not instructions.strip():
        return "create_skill failed: 'instructions' (SKILL.md body) is required."

    slug = _slugify_skill_name(name)
    if not slug:
        return f"create_skill failed: '{name}' produces an empty slug. Use letters/numbers."

    skills_root = get_emu_path() / "skills"
    skill_dir = skills_root / slug

    if skill_dir.exists() and not overwrite:
        return (
            f"Skill '{slug}' already exists at {skill_dir}. "
            f"Pass overwrite=true to replace it, or choose a different name."
        )

    try:
        skill_dir.mkdir(parents=True, exist_ok=True)

        # Escape any embedded triple-dashes / quotes in description for safe YAML.
        safe_desc = description.strip().replace('"', '\\"').replace("\n", " ")

        skill_md = (
            "---\n"
            f"name: {slug}\n"
            f'description: "{safe_desc}"\n'
            "---\n\n"
            f"{instructions.strip()}\n"
        )
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

        written_files: list[str] = ["SKILL.md"]
        rejected_files: list[str] = []

        for entry in files or []:
            rel = (entry or {}).get("path", "")
            content = (entry or {}).get("content", "")
            target = _safe_relative_path(skill_dir, rel)
            if target is None:
                rejected_files.append(rel or "(empty path)")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            written_files.append(str(target.relative_to(skill_dir)).replace("\\", "/"))

        # Invalidate cache so the new skill is immediately discoverable.
        load_skills(force_reload=True)

        msg = (
            f"Skill '{slug}' created at {skill_dir}.\n"
            f"Files written: {', '.join(written_files)}.\n"
            f"It is now listed in available skills and can be loaded via use_skill('{slug}')."
        )
        if rejected_files:
            msg += (
                f"\nWARNING: rejected unsafe paths: {', '.join(rejected_files)}. "
                f"Use relative paths under the skill folder (e.g. 'scripts/run.py')."
            )
        return msg
    except (OSError, PermissionError) as e:
        return f"create_skill failed: could not write skill files: {e}"

