"""
backend/skills/loader.py

Discovers, parses, and manages skills from the skills directory tree.

Skill loading follows OpenClaw's precedence model:
  1. .emu/skills/          (user workspace — highest priority)
  2. backend/skills/bundled/ (shipped with Emu — lowest priority)

Each skill lives in its own directory and contains a SKILL.md file with
YAML frontmatter (name, description, requires) and a markdown body with
detailed instructions.

Only name + description are injected into every prompt. The full body
is loaded on demand when the agent triggers a skill via use_skill.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_BUNDLED_DIR = Path(__file__).resolve().parent / "bundled"
_USER_SKILLS_DIR = _PROJECT_ROOT / ".emu" / "skills"


@dataclass
class Skill:
    """A loaded skill definition."""
    name: str
    description: str
    body: str
    source_path: Path
    requires_bins: list[str] = field(default_factory=list)
    requires_env: list[str] = field(default_factory=list)


def _parse_skill_md(filepath: Path) -> Optional[Skill]:
    """
    Parse a SKILL.md file with YAML-like frontmatter.

    Expected format:
      ---
      name: skill-name
      description: "What this skill does and when to use it"
      requires_bins: curl, jq      (optional)
      requires_env: API_KEY         (optional)
      ---
      <markdown body with instructions>
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, OSError):
        return None

    # Split frontmatter from body
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if not match:
        return None

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    # Simple YAML-like parsing (no full YAML dependency)
    fm: dict[str, str] = {}
    for line in frontmatter_text.strip().splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")

    name = fm.get("name", "")
    description = fm.get("description", "")
    if not name or not description:
        return None

    requires_bins = [b.strip() for b in fm.get("requires_bins", "").split(",") if b.strip()]
    requires_env = [e.strip() for e in fm.get("requires_env", "").split(",") if e.strip()]

    return Skill(
        name=name,
        description=description,
        body=body,
        source_path=filepath.parent,
        requires_bins=requires_bins,
        requires_env=requires_env,
    )


def _check_requirements(skill: Skill) -> bool:
    """Check if a skill's binary and env requirements are met."""
    import shutil

    for binary in skill.requires_bins:
        if not shutil.which(binary):
            print(f"[skills] Skipping '{skill.name}': missing binary '{binary}'")
            return False

    for env_var in skill.requires_env:
        if not os.environ.get(env_var):
            print(f"[skills] Skipping '{skill.name}': missing env var '{env_var}'")
            return False

    return True


def _discover_skills_in(directory: Path) -> dict[str, Skill]:
    """
    Walk a directory for skill folders containing SKILL.md.
    Returns {name: Skill} dict.
    """
    skills: dict[str, Skill] = {}
    if not directory.is_dir():
        return skills

    for entry in sorted(directory.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if not skill_file.exists():
            continue
        skill = _parse_skill_md(skill_file)
        if skill and _check_requirements(skill):
            skills[skill.name] = skill

    return skills


# Module-level cache
_loaded_skills: Optional[dict[str, Skill]] = None


def load_skills(force_reload: bool = False) -> list[Skill]:
    """
    Load all eligible skills with precedence:
      1. .emu/skills/           (user overrides)
      2. backend/skills/bundled/ (shipped defaults)

    User skills override bundled skills with the same name.
    Results are cached after first load.
    """
    global _loaded_skills
    if _loaded_skills is not None and not force_reload:
        return list(_loaded_skills.values())

    # Start with bundled (lowest priority)
    merged: dict[str, Skill] = _discover_skills_in(_BUNDLED_DIR)

    # User skills override bundled
    user_skills = _discover_skills_in(_USER_SKILLS_DIR)
    merged.update(user_skills)

    _loaded_skills = merged
    print(f"[skills] Loaded {len(merged)} skills: {', '.join(merged.keys()) or '(none)'}")
    return list(merged.values())


def get_skill_body(name: str) -> Optional[str]:
    """Get the full body of a skill by name (on-demand loading)."""
    if _loaded_skills is None:
        load_skills()
    skill = _loaded_skills.get(name) if _loaded_skills else None
    if skill:
        return skill.body
    return None


def format_skills_for_prompt(skills: Optional[list[Skill]] = None) -> str:
    """
    Format skills metadata for injection into the system prompt.

    Only name + description — keeps token cost low (~25 tokens per skill).
    The full body is loaded on demand via the use_skill agent tool.
    """
    if skills is None:
        skills = load_skills()

    if not skills:
        return ""

    lines = ["<skills>"]
    for s in skills:
        lines.append(f"  <skill>")
        lines.append(f"    <name>{s.name}</name>")
        lines.append(f"    <description>{s.description}</description>")
        lines.append(f"  </skill>")
    lines.append("</skills>")
    return "\n".join(lines)
